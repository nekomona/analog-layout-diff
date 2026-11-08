"""Structured projections of the same correspondence and decisions as the UI."""
from collections import Counter

from layoutdiff.data.core import digest, encoded
from layoutdiff.comparison.categories import display_operations, snapshot_changes, status
from layoutdiff.comparison.geometry_changes import POSITION, SIZE
from layoutdiff.comparison.matching import bounds


def value_summary(value, limit=1200):
    raw = encoded(value)
    if len(raw) <= limit:
        return value
    return {"truncated": True, "sha256": digest(value), "bytes": len(raw),
            "preview": raw[:limit].decode("ascii")}


def fields(before, after):
    """Presence is explicit: an absent attribute is different from JSON null."""
    before, after = before or {}, after or {}
    result = {}
    for name in sorted(before.keys() | after.keys()):
        if name in before and name in after and encoded(before[name]) == encoded(after[name]):
            continue
        result[name] = {side: {"present": name in record,
                              **({"value": value_summary(record[name])} if name in record else {})}
                        for side, record in (("before", before), ("after", after))}
    return result


def change(op, *, records=False):
    before, after = op["before"], op["after"]
    r = after or before
    changed = fields(before, after)
    facets = []
    for label, names in (("geometry", POSITION | SIZE | {"params", "mpp", "orient"}),
                         ("connectivity", {"net", "pin", "connections"}),
                         ("group_membership", {"group", "groupOrder", "members"}),
                         ("properties", {"props"})):
        if changed.keys() & names:
            facets.append(label)
    if r["kind"] in {"net", "term"} and "connectivity" not in facets:
        facets.append("connectivity")
    result = {"key": op["key"], "before_key": op.get("before_key", op["key"]),
              "status": status(op), "kind": r["kind"],
              "layer": r.get("layerName", r.get("layer")), "purpose": r.get("purpose"),
              "fields": changed, "facets": facets,
              "correspondence": {"inferred": bool(op.get("match")), "evidence": op.get("match")},
              "bounds": {"before": bounds(before or {}), "after": bounds(after or {})}}
    if records:
        result["records"] = {"before": value_summary(before, 4000), "after": value_summary(after, 4000)}
    return result


def matches(op, *, layer=None, region=None):
    records = [r for r in (op["before"], op["after"]) if r]
    if layer is not None and not any(r.get("layerName", r.get("layer")) == layer for r in records):
        return False
    if region is not None:
        x0, y0, x1, y1 = region
        return any(b and b[0] <= x1 and b[2] >= x0 and b[1] <= y1 and b[3] >= y0
                   for b in (bounds(r) for r in records))
    return True


def unit_summary(plan, ident, resolved, *, details=False):
    unit = plan.units[ident]
    choices = ["base", "target", "incoming"]
    if unit["combined"] is not None:
        choices.append("combined")
    try:
        plan.candidate(ident, "both")
        choices.append("both")
    except ValueError:
        pass
    result = {"id": ident, "category": unit["category"],
              "status": "resolved" if ident in resolved else "unresolved" if unit["reasons"] else "automatic",
              "reasons": unit["reasons"], "evidence": unit["evidence"], "choices": choices,
              "objects": {side: len(rows) for side, rows in unit["alternatives"].items()},
              "explanation": "; ".join(unit["reasons"]) or "Compatible changes can be combined automatically."}
    result["changes"] = {}
    for side in ("target", "incoming"):
        # These maps have logical handles; they are not canonical snapshots.
        ops = snapshot_changes({"objects": unit["alternatives"]["base"]},
                               {"objects": unit["alternatives"][side]})
        paired = display_operations(ops)
        result["changes"][side] = {"counts": dict(Counter(status(op) for op in paired)),
            "items": [change(op) for op in paired[:10 if details else 2]],
            "total": len(paired), "truncated": len(paired) > (10 if details else 2)}
    return result
