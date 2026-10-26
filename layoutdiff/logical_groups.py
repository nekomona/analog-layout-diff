"""Resolve capture-local object references without persisting database handles.

Normal objects keep their existing v1 keys. Groups are content-addressed because
OpenAccess permits duplicate group names. Nested groups resolve bottom-up.
Ambiguous references to identical objects and cycles fail coverage explicitly.
"""
import json
import sqlite3
from .core import encoded, digest
from .storage import NAMED


def pin_key(term, name):
    return '@pin:' + encoded([term, name]).decode('ascii')


def inst_term_key(instance, term):
    return '@instTerm:' + encoded([instance, term]).decode('ascii')


def resolve_records(records):
    db = sqlite3.connect('')
    db.execute('PRAGMA cache_size=-4096')
    db.execute('PRAGMA temp_store=FILE')
    db.execute('CREATE TABLE records(seq INTEGER PRIMARY KEY, token INT, raw BLOB, base TEXT, key TEXT)')
    db.execute('CREATE TABLE refs(token INT PRIMARY KEY, key TEXT, base TEXT)')
    db.execute('CREATE TABLE groups(token INT PRIMARY KEY, raw BLOB, done INT DEFAULT 0)')
    db.execute('CREATE TABLE edges(owner INT, target INT)')
    db.execute('CREATE TABLE counts(base TEXT PRIMARY KEY, n INT)')
    def assign(record):
        kind = record['kind']
        if kind in NAMED:
            return kind + ':' + record.get('name', ''), None
        base = kind + ':' + digest(record)
        old = db.execute('SELECT n FROM counts WHERE base=?', (base,)).fetchone()
        n = old[0] if old else 0
        db.execute('INSERT OR REPLACE INTO counts VALUES (?,?)', (base, n+1))
        return base + ':' + str(n), base
    def ref(token, key, base=None):
        if token is not None:
            old = db.execute('SELECT key,base FROM refs WHERE token=?', (token,)).fetchone()
            if old and old != (key, base):
                raise ValueError('Conflicting capture reference')
            db.execute('INSERT OR IGNORE INTO refs VALUES (?,?,?)', (token, key, base))
    try:
        for seq, r in enumerate(records):
            token = r.pop('_captureId', None)
            if r.get('pin'):
                p = r['pin']
                ref(p.pop('_captureId', None), pin_key(p['term'], p['name']))
            if (r['kind'] == 'group' and '_members' in r) or '_refs' in r:
                if type(token) is not int:
                    raise ValueError('Linked object capture is missing its local reference')
                db.execute('INSERT INTO groups(token,raw) VALUES (?,?)', (token, encoded(r)))
                links = [m[0] for m in r.get('_members') or []]
                links += [link[0] for _, link in r.get('_refs') or [] if link]
                db.executemany('INSERT INTO edges VALUES (?,?)', ((token, target) for target in links))
                continue
            if r['kind'] == 'inst':
                for connection in r['connections']:
                    if len(connection) == 4:
                        ref(connection.pop(), inst_term_key(r['name'], connection[0]))
            key, base = assign(r)
            ref(token, key, base)
            db.execute('INSERT INTO records VALUES (?,?,?,?,?)', (seq, token, encoded(r), base, key))
        db.execute('CREATE INDEX edge_owner ON edges(owner)')
        # Full normal-object multiplicities are known before resolving links.
        while True:
            ready = list(db.execute('SELECT token,raw FROM groups g WHERE done=0 AND NOT EXISTS '
                '(SELECT 1 FROM edges e JOIN groups target ON target.token=e.target '
                'WHERE e.owner=g.token AND target.done=0)'))
            if not ready:
                break
            resolved = []
            for token, raw in ready:
                r = json.loads(raw)
                members, problems = [], []
                def resolve(target, kind):
                    found = db.execute('SELECT key,base FROM refs WHERE token=?', (target,)).fetchone()
                    if not found:
                        problems.append('uncaptured object reference type: ' + str(kind))
                        return None
                    key, base = found
                    if base and db.execute('SELECT n FROM counts WHERE base=?', (base,)).fetchone()[0] > 1:
                        problems.append('ambiguous reference to identical ' + str(kind) + ' objects')
                    return key
                for field, link in r.pop('_refs', None) or []:
                    r[field] = resolve(*link) if link else None
                if '_members' in r:
                    for target, kind, props in r.pop('_members') or []:
                        key = resolve(target, kind)
                        if key is not None:
                            members.append({'target': key, 'props': props or []})
                    if not r['isOrdered']:
                        members.sort(key=encoded)
                    r['members'] = members
                if problems:
                    r['memberReferenceIssues' if r['kind'] == 'group' else 'referenceIssues'] = sorted(set(problems))
                resolved.append((token, r))
            # Resolve a whole dependency level before parents; detect duplicate
            # groups independently of native enumeration order.
            for token, r in sorted(resolved, key=lambda pair: encoded(pair[1])):
                key, base = assign(r)
                ref(token, key, base)
                db.execute('UPDATE groups SET raw=?,done=1 WHERE token=?', (encoded(r), token))
        for token, raw in db.execute('SELECT token,raw FROM groups WHERE done=0'):
            r = json.loads(raw)
            if r['kind'] == 'group':
                r.pop('_members', None)
                r['members'] = []
                r['memberReferenceIssues'] = ['cyclic logical-group references are not supported']
            else:
                for field, _ in r.pop('_refs', []):
                    r[field] = None
                r['referenceIssues'] = ['cyclic object references are not supported']
            db.execute('UPDATE groups SET raw=? WHERE token=?', (encoded(r), token))
        for raw, in db.execute('SELECT raw FROM records ORDER BY seq'):
            yield json.loads(raw)
        for raw, in db.execute('SELECT raw FROM groups'):
            yield json.loads(raw)
    finally:
        db.close()
