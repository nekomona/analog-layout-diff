"""Review classification without changing snapshot identities or commit semantics."""
from .core import encoded, validate

VISUAL = {"rect", "polygon", "path", "pathSeg", "label", "ellipse", "line", "donut", "arc",
          "inst", "mosaic", "stdVia", "prBoundary", "snapBoundary", "layerBlockage", "areaBlockage", "textDisplay"}
ATTRIBUTES = {"props", "net", "pin", "group", "groupOrder", "routeStatus"}
GROUP_FIELDS = {"group", "groupOrder"}
GROUP_KINDS = {"figGroup", "group"}


def without_group(record):
    return {k: v for k, v in record.items() if k not in GROUP_FIELDS}


def without_connectivity(record):
    result = {k: v for k, v in without_group(record).items() if k not in {"net", "connections"}}
    if result.get("pin"):
        result["pin"] = {k: v for k, v in result["pin"].items() if k not in {"name", "term"}}
    if result.get('mpp'):
        result['mpp'] = {**result['mpp'], 'parts': sorted(
            ({k:v for k,v in part.items() if k not in {'netName','termName'}}
             for part in result['mpp']['parts']), key=encoded)}
    return result


def modification(before, after):
    """Presentation classification. Geometry/ordinary properties take priority."""
    if before is after or encoded(before) == encoded(after):
        return "untouched"
    if before["kind"] in {"net", "term"} and before["kind"] == after["kind"]:
        return "netChanged"
    if encoded(without_group(before)) == encoded(without_group(after)):
        return "untouched"
    if encoded(without_connectivity(before)) == encoded(without_connectivity(after)):
        return "netChanged"
    return "changed"


def classify(before, after):
    validate(before)
    validate(after)
    old, new = before["objects"], after["objects"]
    groups = {}
    remaining = set(old)
    for key in new.keys() & old.keys():
        groups[key] = modification(old[key], new[key])
        remaining.remove(key)
    from .matching import pairs as match_pairs
    pairs, evidence = {}, {}
    unmatched = sorted(new.keys() - groups.keys())
    for key, previous, reason in match_pairs(((k,old[k]) for k in sorted(remaining)),
                                             ((k,new[k]) for k in unmatched)):
        remaining.remove(previous)
        groups[key], pairs[key] = modification(old[previous], new[key]), previous
        evidence[key] = reason
    for key in unmatched:
        groups.setdefault(key, 'new')
    changed = {key for key, value in groups.items() if value == "changed"}
    net_changes = {key for key, value in groups.items() if value == "netChanged"}
    masters = {(r["libName"], r["cellName"], r["viewName"]) for key, r in new.items()
               if key in changed and r["kind"] == "dependency"}
    for key, r in new.items():
        if groups[key] == "new" or r["kind"] not in VISUAL:
            continue
        related = ["net:" + str(r.get("net")), "term:" + str((r.get("pin") or {}).get("term"))]
        if r['kind'] == 'textDisplay' and (r.get('associate') or '').startswith(('net:', 'term:')):
            related.append(r['associate'])
        related += ["net:" + str(c[1]) for c in r.get("connections", [])]
        if r["kind"] in {"inst", "mosaic"} and (
                tuple(r.get(x) for x in ("libName", "cellName", "viewName")) in masters):
            groups[key] = "changed"
        elif groups[key] == "untouched" and any(x in net_changes for x in related):
            groups[key] = "netChanged"
    visual = {k: v for k, v in groups.items() if new[k]["kind"] in VISUAL}
    from .review_groups import group_changes
    return {"groups": visual, "counts": {s: list(visual.values()).count(s) for s in ("untouched", "changed", "netChanged", "new")},
            "group_changes": group_changes(before, after, pairs),
            "removed": sorted(remaining), "attribute_pairs": pairs,
            "pair_evidence": evidence,
            "metadata_changes": [k for k in sorted(new) if new[k]["kind"] not in VISUAL and groups[k] != "untouched"]}
