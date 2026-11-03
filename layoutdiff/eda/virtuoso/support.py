"""Complete reconstruction coverage with disk-backed group relationship checks."""
from collections import Counter
import json
import sqlite3

SUPPORTED = {"cell", "rect", "polygon", "path", "pathSeg", "label", "ellipse", "line", "donut", "arc",
             "net", "term", "inst", "mosaic", "stdVia", "figGroup", "group", "prBoundary", "dependency",
             "layerBlockage", "areaBlockage", "snapBoundary", "sitePattern", "textDisplay"}


def record_issues(r):
    issues = []
    kind = r["kind"]
    from layoutdiff.eda.virtuoso.oa_content import issues as oa_issues
    issues.extend(oa_issues(r))
    from layoutdiff.eda.virtuoso.mpp import issues as mpp_issues
    issues.extend(mpp_issues(r))
    if kind not in SUPPORTED:
        issues.append("unsupported collection: " + str(r.get('category', kind)) if kind == "unsupported"
                      else "unsupported object type: " + kind)
    if kind == "pathSeg":
        styles = {r.get("beginStyle"), r.get("endStyle")}
        if not styles <= {"truncate", "extend", "variable", "chamfer", "custom"}:
            issues.append("unknown pathSeg end style")
        if "custom" in styles:
            extensions = r.get("customExtensions")
            if (not isinstance(extensions, list) or len(extensions) != 6 or
                    any(type(value) is not int for value in extensions)):
                issues.append("custom pathSeg needs six integer-DBU customExtensions; recapture this layout")
    if kind == "net" and r.get("numBits", 1) != 1:
        issues.append("bus net")
    if kind == "mosaic" and (r.get("mosaicType") != "simple" or len(r.get("tileArray") or []) != 1):
        issues.append("non-simple mosaic")
    if kind == "figGroup":
        if r.get("type") != "none":
            issues.append("unsupported figGroup type: " + str(r.get("type")))
        if r.get("ordered") and (type(r.get("memberCount")) is not int or r["memberCount"] < 0):
            issues.append("ordered figGroup needs memberCount and member order; recapture this layout")
    if "groupOrder" in r and (not r.get("group") or type(r["groupOrder"]) is not int or r["groupOrder"] < 0):
        issues.append("invalid figure groupOrder")
    if kind == 'group':
        if not isinstance(r.get('name'), str) or not isinstance(r.get('defName'), str):
            issues.append('logical group name or definition missing')
        if (any(r.get(flag) is not None and type(r[flag]) is not bool
                for flag in ('isSet', 'isCollection', 'isOrdered', 'isUniqueName')) or
                bool(r.get('isSet')) == bool(r.get('isCollection'))):
            issues.append('invalid logical group flags')
        if r.get('deleteWhen') not in {'deleteNever', 'deleteFirst', 'deleteLast'}:
            issues.append('unsupported logical group deletion policy')
        if not isinstance(r.get('members'), list):
            issues.append('logical group memberships missing; recapture this layout')
        issues.extend(r.get('memberReferenceIssues', []))

    def check_props(props, location):
        for name, typ, value in props or []:
            if typ == "hierProp":
                check_props(value, location + "/" + name)
            elif typ not in {"string", "int", "float", "boolean", "ILList", "time"}:
                issues.append(f"unsupported {location} type: {typ}")
    check_props(r.get("props"), "property")
    check_props((r.get("pin") or {}).get("props"), "pin property")
    if kind == 'group':
        for member in r.get('members') or []:
            check_props(member.get('props'), 'group member property')
            if member.get('target') == 'cell:':
                issues.append('cellView cannot be a logical group member')
    if kind in {"inst", "mosaic"}:
        check_props(r.get("params"), "parameter")
    for _, _, props in r.get("connections") or []:
        check_props(props, "instTerm property")
    serialized = json.dumps(r)
    if '"@off-grid"' in serialized or '"@unsupported-db-reference"' in serialized:
        issues.append("unrepresentable value")
    return sorted(set(issues))


class GroupCheck:
    """Avoid a Python set for every member of a 100K-element ordered group."""
    def __init__(self):
        self.db = None

    def add(self, key, r):
        if r["kind"] != "figGroup" and not r.get("group"):
            return
        if self.db is None:
            self.db = sqlite3.connect("")  # Private on-disk DB deleted by close().
            self.db.execute("PRAGMA cache_size=-2048")
            self.db.execute("PRAGMA temp_store=FILE")
            self.db.execute("CREATE TABLE groups(name TEXT PRIMARY KEY, key TEXT, ordered INT, expected INT)")
            self.db.execute("CREATE TABLE members(parent TEXT, ordinal INT)")
        if r["kind"] == "figGroup":
            expected = r.get("memberCount")
            self.db.execute("INSERT OR REPLACE INTO groups VALUES (?,?,?,?)",
                (r["name"], key, bool(r.get("ordered")), expected if type(expected) is int else None))
        if r.get("group"):
            rank = r.get("groupOrder")
            self.db.execute("INSERT INTO members VALUES (?,?)",
                (r["group"], rank if type(rank) is int and rank >= 0 else None))

    def issues(self):
        if self.db is None:
            return
        self.db.execute("CREATE INDEX members_parent ON members(parent)")
        for name, key, ordered, expected, count, ranked, distinct, low, high in self.db.execute(
            "SELECT g.name,g.key,g.ordered,g.expected,COUNT(m.parent),COUNT(m.ordinal),"
            "COUNT(DISTINCT m.ordinal),MIN(m.ordinal),MAX(m.ordinal) "
            "FROM groups g LEFT JOIN members m ON g.name=m.parent GROUP BY g.name"):
            if ordered and expected is not None and (count != expected or ranked != count or
                    distinct != count or (count and (low != 0 or high != count - 1))):
                yield key, ["incomplete or duplicate ordered figGroup membership; recapture this layout"]
            elif not ordered and ranked:
                yield key, ["groupOrder belongs to an unordered figGroup"]
        for name, in self.db.execute("SELECT DISTINCT parent FROM members WHERE parent NOT IN (SELECT name FROM groups)"):
            yield "figGroup:" + name, ["missing figure group"]

    def close(self):
        if self.db is not None:
            self.db.close()


def coverage(snapshot):
    issues = []
    groups = GroupCheck()
    try:
        masters = Counter(r['mpp']['name'] for r in snapshot['objects'].values() if isinstance(r.get('mpp'),dict))
        for key,r in snapshot['objects'].items():
            if r.get('mppOwner') and masters[r['mppOwner']] != 1:
                issues.append('missing or duplicate MPP master: ' + key)
        if any(n != 1 for n in masters.values()):
            issues.append('duplicate MPP master names')
        for key, r in snapshot["objects"].items():
            issues.extend(reason + ": " + key for reason in record_issues(r))
            groups.add(key, r)
        for key, reasons in groups.issues():
            issues.extend(reason + ": " + key for reason in reasons)
        from layoutdiff.eda.virtuoso.logical_groups import pin_key, inst_term_key
        targets = set(snapshot['objects'])
        for r in snapshot['objects'].values():
            if r.get('pin'):
                targets.add(pin_key(r['pin']['term'], r['pin']['name']))
            if r['kind'] == 'inst':
                targets.update(inst_term_key(r['name'], con[0]) for con in r.get('connections') or [])
        property_roots = dict(snapshot['objects'])
        for r in snapshot['objects'].values():
            if r.get('pin'):
                property_roots[pin_key(r['pin']['term'], r['pin']['name'])] = r['pin']
            if r['kind'] == 'inst':
                for name, _, props in r.get('connections') or []:
                    property_roots[inst_term_key(r['name'], name)] = {'props': props}
        for key, r in snapshot['objects'].items():
            from layoutdiff.eda.virtuoso.oa_content import references
            for target in references(r):
                if target not in targets:
                    issues.append('missing object reference: ' + key + ' -> ' + target)
            for field in ('associate', 'owner', 'parent'):
                path = r.get(field + 'Property')
                if isinstance(path, list) and path:
                    props = property_roots.get(r.get(field), {}).get('props') or []
                    for name in path:
                        found = next((p for p in props if p[0] == name), None)
                        if found is None:
                            issues.append('missing textDisplay property reference: ' + key)
                            break
                        props = found[2] if found[1] == 'hierProp' else []
            if r['kind'] == 'group':
                for member in r.get('members') or []:
                    if member.get('target') not in targets:
                        issues.append('missing logical group member: ' + key)
        from layoutdiff.eda.virtuoso.oa_content import replay_items
        from graphlib import CycleError
        try:
            replay_items(snapshot)
        except CycleError:
            issues.append('cyclic object references are not supported')
        for kind in ('sitePattern', 'snapBoundary'):
            if sum(r['kind'] == kind for r in snapshot['objects'].values()) > 1:
                issues.append('multiple ' + kind + ' records in one cellview')
        return sorted(set(issues))
    finally:
        groups.close()


class UnsupportedContentError(ValueError):
    def __init__(self, counts, report):
        self.counts, self.report = dict(counts), report
        super().__init__("Cannot commit unsupported layout content (complete scan):\n" +
            "\n".join(f"- {reason}: {count} element(s)" for reason, count in sorted(counts.items())) +
            "\nFull element details: " + str(report))


def checked_records(records, report):
    """Consume the entire capture before rejecting; do not publish partial data."""
    counts = Counter()
    groups = GroupCheck()
    try:
        with report.open("w", encoding="utf-8") as stream:
            def log(key, issues, record=None):
                counts.update(issues)
                stream.write(json.dumps({"element": key, "issues": issues, "record": record},
                                        ensure_ascii=True) + "\n")
            for line, record in enumerate(records, 1):
                key = record["kind"] + ":" + str(record.get("name", "capture-line-" + str(line)))
                groups.add(key, record)
                issues = record_issues(record)
                if issues:
                    log(key, issues, record)
                else:
                    yield record
            for key, issues in groups.issues():
                log(key, issues)
        if counts:
            raise UnsupportedContentError(counts, report)
        report.unlink()
    finally:
        groups.close()
