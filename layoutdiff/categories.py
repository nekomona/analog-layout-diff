"""Presentation-only categories over exact v1 operations. Never changes storage."""
from collections import Counter, defaultdict
import difflib
import json
from .core import encoded
from .review import VISUAL, modification

PAGE_SIZE = 10
COUNT_FIELDS = ('added', 'modified', 'deleted', 'modified_net', 'moved')


def snapshot_changes(before, after):
    """GUI projection of already validated snapshots; no new canonicalization."""
    a, b = before["objects"], after["objects"]
    return [{"key": key, "before": a.get(key), "after": b.get(key)}
            for key in sorted(a.keys() | b.keys()) if encoded(a.get(key)) != encoded(b.get(key))]


def category(record):
    kind = record["kind"]
    if record.get('mpp'):
        return str(record.get('layerName') or 'Unknown layer') + ' MPPs'
    if record.get('mppOwner'):
        return str(record.get('layerName') or 'Unknown layer') + ' MPP subshapes'
    if kind in {"inst", "mosaic", "dependency"}:
        master = record.get("libName", "?") + "/" + record.get("cellName", "?")
        if record.get("viewName", "layout") != "layout":
            master += "/" + record["viewName"]
        suffix = ("pcell" if record.get("pcell") else "cell") if kind == "inst" else kind
        return master + " " + suffix
    if kind == "stdVia":
        return str(record.get("viaDef") or "Unknown via definition") + " vias"
    if kind == 'layerBlockage':
        return str(record.get('layer') or 'Unknown layer') + ' blockages'
    if kind in VISUAL - {"inst", "mosaic", "stdVia", "prBoundary", "snapBoundary", "areaBlockage"}:
        layer = str(record.get("layerName") or "Unknown layer")
        purpose = record.get("purpose")
        if purpose and purpose != "drawing":
            layer += "/" + purpose
        return layer + (" text displays" if kind == 'textDisplay' else " labels" if kind == "label" else " shapes")
    return {"cell": "Cellview properties", "net": "Connectivity / nets", "term": "Connectivity / terminals",
            "figGroup": "Figure groups", "group": "Logical groups", "prBoundary": "Placement boundary",
            "snapBoundary": "Snap boundary", "sitePattern": "Placement site pattern", "areaBlockage": "Placement blockages",
            "unsupported": "Unsupported content"}.get(kind, kind)


def status(op):
    if op['before'] is None:
        return 'added'
    if op['after'] is None:
        return 'deleted'
    return {'netChanged': 'modified_net', 'moved': 'moved'}.get(modification(op['before'], op['after']), 'modified')


def operation_category(op):
    label = category(op['after'] or op['before'])
    if op['before'] and op['after']:
        if category(op['before']) != label:
            label = category(op['before']) + ' -> ' + label
        if status(op) == 'modified_net':
            label = 'Modified net / ' + label
        elif status(op) == 'moved':
            label = 'Moved / stretched / ' + label
        elif modification(op['before'], op['after']) == 'untouched':
            label = 'Group membership / ' + label
    return label


def display_operations(operations):
    """Shared, conservative display pairing; exact stored operations survive."""
    from .matching import pairs
    deleted = {op['key']: op['before'] for op in operations if op['after'] is None}
    added = {op['key']: op for op in operations if op['before'] is None}
    consumed, paired = set(), {}
    for key, old, evidence in pairs(deleted.items(), ((k,op['after']) for k,op in added.items())):
        consumed.add(old)
        paired[key] = {**added[key], 'before': deleted[old], 'before_key': old, 'match': evidence}
    return [paired.get(op["key"], op) for op in operations if op["key"] not in consumed]


def operation_text(op):
    before, after = op["before"], op["after"]
    a = json.dumps(before, sort_keys=True, indent=2, ensure_ascii=True).splitlines(True) if before is not None else []
    b = json.dumps(after, sort_keys=True, indent=2, ensure_ascii=True).splitlines(True) if after is not None else []
    # Keep line boundaries between objects even if the JSON has no final newline.
    if a:
        a[-1] += "\n"
    if b:
        b[-1] += "\n"
    evidence = f"Matched by {op['match']} (derived correspondence).\n" if op.get('match') else ''
    return (f"\n@@ {status(op).upper()} {op['key']} @@\n" + evidence +
            "".join(difflib.unified_diff(a, b, fromfile=op.get("before_key", op["key"]),
                                         tofile=op["key"], n=max(len(a), len(b)))))


def operation_excerpt(op, limit=580):
    """Bound UI formatting work, including very long point arrays.

    Full text matching/pretty-printing belongs only to an explicit export.
    Reserve space for both sides so a long old value cannot hide the new one.
    """
    encoder = json.JSONEncoder(sort_keys=True, indent=2, ensure_ascii=True)
    evidence = f"Matched by {op['match']}.\n" if op.get('match') else ''
    header = (f"\n@@ {status(op).upper()} {op['key']} @@\n" + evidence).encode("utf-8")
    pieces = [header[:limit]]
    values = [(name, op[name]) for name in ("before", "after") if op[name] is not None]
    budget = max(0, (limit - len(pieces[0])) // len(values))
    shortened = len(header) > limit
    for name, value in values:
        raw = bytearray((name + ":\n").encode()[:budget])
        for fragment in encoder.iterencode(value):
            part = fragment.encode()
            available = budget - len(raw)
            raw.extend(part[:available])
            if len(part) > available:
                shortened = True
                break
        pieces.append(bytes(raw))
    text = b"".join(pieces).decode("utf-8", errors="ignore")
    if shortened:
        text += "\n[Record shortened; Open full diff contains all fields.]\n"
    return text


class CategoryDiff:
    def __init__(self, operations):
        groups = defaultdict(list)
        self.raw_operations = len(operations)
        for op in display_operations(operations):
            label = operation_category(op)
            groups[label].append(op)
        self.groups = [(label, groups[label]) for label in sorted(groups)]
        self.totals = Counter(dict.fromkeys(COUNT_FIELDS, 0))
        self.rows = []
        for label, ops in self.groups:
            counts = Counter(status(op) for op in ops)
            self.totals.update(counts)
            self.rows.append([label, *(counts[k] for k in COUNT_FIELDS)])

    def overview(self, *, interactive=True):
        return ("Layout changes by category (A added, M modified, D deleted, MN modified net, MS moved / stretched)\n\n" +
                "\n".join(f"{label}: {a}A, {m}M, {d}D, {mn}MN, {ms}MS" for label, a, m, d, mn, ms in self.rows) +
                ("\nNo element changes." if not self.rows else "") +
                ("\n\nSelect a category for paged details. Open full diff includes every changed field." if interactive else
                   "\n\nView full diff shows every changed field. Saved snapshots retain all details.") +
                "\nMN counts connectivity-only changes. MS counts position/size edits; M excludes both."
                "\nPosition/size edits combined with other property, layer or orientation changes stay M."
                "\nMoves/stretches use conservative geometric matching; ambiguous pairs remain A/D."
                "\nMosaics count as array objects. Dependencies and metadata have separate rows.")

    def page(self, index, page):
        label, ops = self.groups[index]
        pages = max(1, (len(ops) + PAGE_SIZE - 1) // PAGE_SIZE)
        if page < 0 or page >= pages:
            raise ValueError("Category page is out of range")
        start = page * PAGE_SIZE
        text = f"{label}\nChanges {start + 1}-{min(start + PAGE_SIZE, len(ops))} of {len(ops)} | Page {page + 1}/{pages}\n"
        for op in ops[start:start + PAGE_SIZE]:
            text += operation_excerpt(op)
        return {"title": label, "text": text, "page": page, "pages": pages, "count": len(ops)}

    def full(self, index=None):
        yield self.overview() + "\n"
        for label, ops in self.groups if index is None else [self.groups[index]]:
            yield "\n### " + label + "\n"
            for op in ops:
                yield operation_text(op)
