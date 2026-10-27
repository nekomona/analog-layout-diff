"""Explicit, audited supported-only projection. Never used by strict captures.

The SQLite graph bounds memory independently of design size. Dependent records
are omitted conservatively; surviving figures are detached from omitted figure
groups. Re-resolving capture tokens repairs content-addressed links after that
change. Malformed storage and essential cell metadata still fail closed.
"""
from collections import Counter
import json
from .core import encoded, digest
from .storage import spool, write_records, NAMED
from .support import GroupCheck, record_issues, checked_records, UnsupportedContentError
from .logical_groups import pin_key, inst_term_key, resolve_records
from .oa_content import LINK_FIELDS, references
from .streaming import file_digest

AUDIT = 'omissions.json'
DETAILS = 'omissions.jsonl'


def warning(audit):
    if not audit:
        return ''
    return (f"INCOMPLETE CHECKPOINT: {audit['omitted']} element(s) omitted; "
            f"{audit['detached']} figure(s) detached from omitted groups. "
            "Rollback/restore to this checkpoint will lose the ignored elements. "
            "The saved source layout is unchanged by committing.")


def project(source, destination, report):
    db = spool('')
    groups = GroupCheck()
    db.executescript('''
        CREATE TABLE objects(id INTEGER PRIMARY KEY, key TEXT UNIQUE, raw BLOB, kind TEXT, parent TEXT);
        CREATE TABLE targets(key TEXT PRIMARY KEY, owner INT, token INTEGER UNIQUE);
        CREATE TABLE edges(owner INT, target TEXT);
        CREATE TABLE recipe_nets(owner INT, target TEXT);
        CREATE TABLE rejected(id INT PRIMARY KEY, reasons BLOB);
    ''')
    def reject(oid, reasons):
        db.execute('INSERT OR IGNORE INTO rejected VALUES (?,?)', (oid, encoded(reasons)))
    def token(key):
        found = db.execute('SELECT token FROM targets WHERE key=?', (key,)).fetchone()
        if not found:
            raise ValueError('Projection has a dangling reference: ' + key)
        return found[0]
    try:
        for oid, (key, r) in enumerate(source.records(), 1):
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?)',
                       (oid, key, encoded(r), r['kind'], r.get('group')))
            groups.add(key, r)
            problems = record_issues(r)
            if problems:
                reject(oid, problems)
            links = references(r)
            if r.get('mppOwner'):
                links.append('@mpp:' + r['mppOwner'])
            if r.get('mpp'):
                # ROD recipes can retain a name after its OA net was deleted.
                # Native replay already removes the resulting empty net. Keep
                # dependency edges only for nets that actually exist in source;
                # an existing but unsupported net must still propagate omission.
                db.executemany('INSERT INTO recipe_nets VALUES (?,?)',
                    ((oid, 'net:' + p['netName']) for p in r['mpp']['parts'] if p.get('netName')))
            if r['kind'] == 'group':
                links += [m['target'] for m in r.get('members') or []]
            if r.get('net'):
                links.append('net:' + r['net'])
            if r.get('pin'):
                links.append('term:' + r['pin']['term'])
                if r['pin'].get('primary') is False:
                    links.append(pin_key(r['pin']['term'], r['pin']['name']))
            if r['kind'] == 'inst':
                links += ['net:' + c[1] for c in r.get('connections') or [] if c[1]]
            db.executemany('INSERT INTO edges VALUES (?,?)', ((oid, link) for link in links))
        # Object IDs and synthetic pin/instTerm tokens occupy disjoint ranges.
        db.execute('INSERT INTO targets SELECT key,id,id FROM objects')
        alias_id = db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]
        for oid, raw in db.execute('SELECT id,raw FROM objects'):
            r = json.loads(raw)
            aliases = []
            if r.get('mpp'):
                aliases.append('@mpp:' + r['mpp']['name'])
            if r.get('pin') and r['pin'].get('primary', True):
                aliases.append(pin_key(r['pin']['term'], r['pin']['name']))
            if r['kind'] == 'inst':
                aliases += [inst_term_key(r['name'], c[0]) for c in r.get('connections') or []]
            for alias in aliases:
                alias_id += 1
                db.execute('INSERT INTO targets VALUES (?,?,?)', (alias, oid, alias_id))
        for key, reasons in groups.issues():
            row = db.execute('SELECT id FROM objects WHERE key=?', (key,)).fetchone()
            if row:
                reject(row[0], reasons)
        for oid, raw in db.execute('SELECT id,raw FROM objects WHERE kind IN (?,?,?,?)', tuple(LINK_FIELDS)):
            r = json.loads(raw)
            for field in LINK_FIELDS[r['kind']]:
                path = r.get(field + 'Property')
                if not isinstance(path, list) or not path:
                    continue
                target = r.get(field)
                row = db.execute('SELECT o.raw FROM targets t JOIN objects o ON o.id=t.owner WHERE t.key=?',
                                 (target,)).fetchone()
                if not row:
                    continue  # Missing targets are rejected below.
                root = json.loads(row[0])
                props = root.get('props') or []
                if target.startswith('@pin:'):
                    props = root['pin'].get('props') or []
                elif target.startswith('@instTerm:'):
                    name = json.loads(target.partition(':')[2])[1]
                    props = next(c[2] for c in root['connections'] if c[0] == name)
                for name in path:
                    found = next((p for p in props if p[0] == name), None)
                    if found is None:
                        reject(oid, ['missing textDisplay property reference'])
                        break
                    props = found[2] if found[1] == 'hierProp' else []
        for kind in ('snapBoundary', 'sitePattern'):
            if db.execute('SELECT COUNT(*) FROM objects WHERE kind=?', (kind,)).fetchone()[0] > 1:
                for oid, in db.execute('SELECT id FROM objects WHERE kind=?', (kind,)):
                    reject(oid, ['multiple ' + kind + ' records in one cellview'])
        db.execute('INSERT INTO edges SELECT r.owner,r.target FROM recipe_nets r '
                   'JOIN targets t ON t.key=r.target')
        # If a figure is omitted, its enclosing group is not a faithful group.
        # Keep other geometry and detach it, instead of deleting all members.
        db.execute("INSERT INTO edges SELECT g.id,m.key FROM objects g JOIN objects m "
                   "ON g.key='figGroup:'||m.parent WHERE g.kind='figGroup'")
        # MPP reconstruction must be atomic: omitting any generated member
        # otherwise regenerates geometry that the checkpoint says was omitted.
        db.execute("INSERT INTO edges SELECT t.owner,o.key FROM edges e JOIN objects o ON o.id=e.owner "
                   "JOIN targets t ON t.key=e.target WHERE e.target LIKE '@mpp:%'")
        db.execute('CREATE INDEX edges_target ON edges(target)')
        db.execute('CREATE INDEX edges_owner ON edges(owner)')
        db.execute('CREATE INDEX targets_owner ON targets(owner)')
        for oid, in db.execute('SELECT DISTINCT e.owner FROM edges e LEFT JOIN targets t '
                              'ON e.target=t.key WHERE t.key IS NULL'):
            reject(oid, ['missing referenced object'])
        # Propagate omissions breadth-first, without repeated full-design scans.
        db.execute('CREATE TABLE pending(id INT PRIMARY KEY)')
        db.execute('INSERT INTO pending SELECT id FROM rejected')
        db.execute('CREATE TABLE detached(id INT PRIMARY KEY)')
        db.execute('CREATE TABLE projected(id INT PRIMARY KEY, base TEXT)')
        db.execute('CREATE INDEX projected_base ON projected(base)')
        for oid, key, kind in db.execute('SELECT id,key,kind FROM objects'):
            if kind not in NAMED:
                db.execute('INSERT INTO projected VALUES (?,?)', (oid, key.rsplit(':', 1)[0]))
        while True:
            while True:
                row = db.execute('SELECT id FROM pending LIMIT 1').fetchone()
                if row is None:
                    break
                oid = row[0]
                db.execute('DELETE FROM pending WHERE id=?', (oid,))
                for owner, in db.execute('SELECT DISTINCT e.owner FROM edges e JOIN targets t ON t.key=e.target '
                                        'WHERE t.owner=? AND e.owner NOT IN (SELECT id FROM rejected)', (oid,)):
                    reject(owner, ['depends on an omitted element'])
                    db.execute('INSERT OR IGNORE INTO pending VALUES (?)', (owner,))
            # Detachment can make formerly distinct anonymous figures identical.
            # Omit ambiguous dependents instead of choosing an arbitrary member.
            for oid, raw in db.execute('SELECT m.id,m.raw FROM objects m WHERE m.parent IS NOT NULL '
                    'AND m.id NOT IN (SELECT id FROM rejected) AND m.id NOT IN (SELECT id FROM detached) '
                    "AND NOT EXISTS (SELECT 1 FROM objects g WHERE g.key='figGroup:'||m.parent "
                    'AND g.id NOT IN (SELECT id FROM rejected))'):
                db.execute('INSERT INTO detached VALUES (?)', (oid,))
                r = json.loads(raw); r['group'] = None; r.pop('groupOrder', None)
                if r['kind'] in NAMED:
                    continue
                base = r['kind'] + ':' + digest(r)
                db.execute('UPDATE projected SET base=? WHERE id=?', (base, oid))
                if db.execute('SELECT COUNT(*) FROM projected WHERE base=? AND id NOT IN (SELECT id FROM rejected)',
                              (base,)).fetchone()[0] > 1:
                    for owner, in db.execute('SELECT DISTINCT e.owner FROM edges e JOIN targets t ON e.target=t.key '
                            'JOIN projected p ON p.id=t.owner WHERE p.base=? AND e.owner NOT IN (SELECT id FROM rejected)', (base,)):
                        reject(owner, ['ambiguous reference after figure-group detachment'])
                        db.execute('INSERT OR IGNORE INTO pending VALUES (?)', (owner,))
            if not db.execute('SELECT 1 FROM pending LIMIT 1').fetchone():
                break
        counts, omitted, detached = Counter(), 0, 0
        with report.open('wb') as output:
            for key, raw, reasons in db.execute('SELECT o.key,o.raw,r.reasons FROM objects o '
                                               'JOIN rejected r ON o.id=r.id ORDER BY o.key'):
                reasons = json.loads(reasons)
                counts.update(reasons); omitted += 1
                output.write(encoded(dict(element=key, issues=reasons, action='omit', record=json.loads(raw))) + b'\n')
            for key, raw, parent in db.execute('SELECT key,raw,parent FROM objects WHERE parent IS NOT NULL '
                    'AND id NOT IN (SELECT id FROM rejected) ORDER BY key'):
                if not db.execute("SELECT 1 FROM objects WHERE key=? AND id NOT IN (SELECT id FROM rejected)",
                                  ('figGroup:' + parent,)).fetchone():
                    detached += 1
                    output.write(encoded(dict(element=key, issues=['membership in omitted or missing figure group'],
                                              action='detach-group', record=json.loads(raw))) + b'\n')
        if db.execute("SELECT 1 FROM objects JOIN rejected USING(id) WHERE kind='cell'").fetchone():
            raise UnsupportedContentError(counts, report)
        def records():
            for oid, key, raw in db.execute('SELECT id,key,raw FROM objects WHERE id NOT IN (SELECT id FROM rejected) ORDER BY id'):
                r = json.loads(raw)
                r['_captureId'] = oid
                if r.get('group') and not db.execute('SELECT 1 FROM objects WHERE key=? AND id NOT IN (SELECT id FROM rejected)',
                                                    ('figGroup:' + r['group'],)).fetchone():
                    r['group'] = None
                    r.pop('groupOrder', None)
                if r.get('pin') and r['pin'].get('primary', True):
                    r['pin']['_captureId'] = token(pin_key(r['pin']['term'], r['pin']['name']))
                if r['kind'] == 'inst':
                    for con in r.get('connections') or []:
                        con.append(token(inst_term_key(r['name'], con[0])))
                if r['kind'] == 'group':
                    r['_members'] = [[token(m['target']), 'object', m.get('props') or []] for m in r.pop('members')]
                if r['kind'] in LINK_FIELDS:
                    r['_refs'] = [[f, [token(r[f]), 'object'] if r[f] else None] for f in LINK_FIELDS[r['kind']]]
                    for f in LINK_FIELDS[r['kind']]:
                        del r[f]
                yield r
        # Check again after relinking: ambiguous identities introduced by
        # detaching groups must never silently enter a commit.
        result = write_records(checked_records(resolve_records(records()), report.with_suffix('.validation.jsonl')), destination)
        result.source_digest = source.digest
        result.omissions = (dict(schema='analog-layout-diff/omissions/1', sourceSha256=source.digest,
            snapshotSha256=result.digest, omitted=omitted, detached=detached,
            counts=dict(sorted(counts.items())), reportSha256=file_digest(report)) if omitted or detached else None)
        result.omission_report = report
        return result
    finally:
        groups.close()
        db.close()
