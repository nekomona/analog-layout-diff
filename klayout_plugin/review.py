"""Conservative object review and a disposable colored layout."""
from __future__ import annotations

import copy
import re
from collections import defaultdict
from pathlib import Path

from layoutdiff.data.core import diff, digest, empty_snapshot
from layoutdiff.data.history import atomic_json, read_json
from .api import view_api
from .codec import db, shape_from, transform_from, validate_klayout

CATEGORIES = ("unchanged", "changed", "added", "removed")
DEFAULT_STYLE = {
    "background": "#ffffff",
    "unchanged": {"color": "#8b95a5", "fill": True, "line_style": 0, "width": 1},
    "changed": {"color": "#e38b16", "fill": True, "line_style": 0, "width": 2},
    "added": {"color": "#169b62", "fill": True, "line_style": 0, "width": 2},
    "removed": {"color": "#d13c4b", "fill": False, "line_style": 1, "width": 2},
}


def load_style(path=None):
    style = copy.deepcopy(DEFAULT_STYLE)
    updates = read_json(path) if path else {}
    if not isinstance(updates, dict) or set(updates) - set(style):
        raise ValueError("Unknown review style fields")
    for key, value in updates.items():
        if key == "background":
            style[key] = value
        else:
            if not isinstance(value, dict) or set(value) - set(style[key]):
                raise ValueError("Unknown category style fields")
            style[key].update(value)
    for color in [style["background"]] + [style[k]["color"] for k in CATEGORIES]:
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Colors must be #RRGGBB")
    for key in CATEGORIES:
        s = style[key]
        if type(s["fill"]) is not bool or type(s["width"]) is not int or not 1 <= s["width"] <= 8:
            raise ValueError("Style fill must be boolean and width must be 1..8")
        if type(s["line_style"]) is not int or not 0 <= s["line_style"] <= 7:
            raise ValueError("Built-in line_style must be 0..7")
    return style


def _geometry(record):
    return record["kind"] in {"klayout_shape", "klayout_instance"}


def _bucket(record):
    if record["kind"] == "klayout_shape":
        return (record["kind"], record["cell"], tuple(record["layer"]), record["geometry"]["type"])
    return (record["kind"], record["cell"], record["master"])


def classify(before, after, *, pair_changes=True):
    """Exact common content; optional unique-pair inference for anonymous edits.

    Pair ONLY a single unmatched before and after object in a same-cell,
    same-layer/type bucket (instances: same cell/master). This is a display hint,
    not recovered identity. Ambiguous multiple edits remain removed and added.
    The original history operations are never rewritten.
    """
    if before != empty_snapshot():
        validate_klayout(before)
    validate_klayout(after)
    a, b = before["objects"], after["objects"]
    common = {k for k in a.keys() & b.keys() if a[k] == b[k] and _geometry(a[k])}
    unchanged = sorted(common)
    removed = {k for k in a if _geometry(a[k]) and k not in common}
    added = {k for k in b if _geometry(b[k]) and k not in common}
    changed = []
    if pair_changes:
        old_groups, new_groups = defaultdict(list), defaultdict(list)
        for key in sorted(removed):
            old_groups[_bucket(a[key])].append(key)
        for key in sorted(added):
            new_groups[_bucket(b[key])].append(key)
        for bucket in sorted(old_groups.keys() & new_groups.keys()):
            old, new = old_groups[bucket], new_groups[bucket]
            if len(old) == len(new) == 1:
                changed.append({"before": old[0], "after": new[0], "basis": "unique-compatible-pair"})
                removed.remove(old[0])
                added.remove(new[0])
    metadata = [o for o in diff(before, after)["operations"]
                if not _geometry(o["after"] or o["before"])]
    return {"schema": "analog-layout-diff/klayout-review/1",
            "before": digest(before), "after": digest(after),
            "unchanged": unchanged, "changed": changed, "added": sorted(added),
            "removed": sorted(removed), "metadata": metadata,
            "pairing": "unique-compatible-pair" if pair_changes else "exact-only"}


def review_counts(report):
    return {key: len(report[key]) for key in (*CATEGORIES, "metadata")}


def _statuses(report, side):
    result = {k: "unchanged" for k in report["unchanged"]}
    result.update({k: "added" for k in report["added"]} if side == "after" else
                  {k: "removed" for k in report["removed"]})
    result.update({c[side]: "changed" for c in report["changed"]})
    return result


def _occurrences(snapshot, statuses, side, *, limit):
    """Yield native geometry, transform, review category and original L/D.

    A changed/added/removed instance colors its descendants. Before-side changed
    geometry is a removed-position ghost. A changed child propagates to every
    unchanged reference, so child-only edits cannot disappear from review.
    """
    if snapshot == empty_snapshot():
        return
    meta = validate_klayout(snapshot)
    objects = snapshot["objects"]
    by_cell = defaultdict(list)
    for key, o in objects.items():
        if _geometry(o):
            by_cell[o["cell"]].append((key, o))
    for records in by_cell.values():
        records.sort()
    budget = 0

    def visit(cell, trans, inherited=None):
        nonlocal budget
        for key, record in by_cell[cell]:
            budget += 1
            if budget > limit:
                raise ValueError(f"Review expansion exceeds {limit} objects; choose a smaller top or increase --limit")
            own = statuses[key]
            status = inherited or own
            if record["kind"] == "klayout_shape":
                # Before contributes ghosts only; exact objects come from after.
                if side == "before" and status == "unchanged":
                    continue
                yield (shape_from(record["geometry"]),
                       "removed" if side == "before" else status,
                       tuple(record["layer"]), trans, key)
            else:
                a = record["array"]
                inst = db.CellInstArray(0, transform_from(record["transform"]))
                if a["regular"]:
                    inst = db.CellInstArray(0, transform_from(record["transform"]),
                                           db.Vector(*a["a"]), db.Vector(*a["b"]), a["na"], a["nb"])
                for local in inst.each_cplx_trans():
                    budget += 1
                    if budget > limit:
                        raise ValueError("Review array expansion exceeds object limit")
                    yield from visit(record["master"], trans * local,
                                     status if status != "unchanged" else None)
    yield from visit(meta["top"], db.ICplxTrans())


def build_review(before, after, *, pair_changes=True, limit=250000):
    """Build a NEW layout containing after geometry and red before-only ghosts.

    Each (category, original layer/datatype/name) gets a distinct review layer.
    Source layer information remains in its name and review.json layer mapping.
    This disposable visual layout is never a reconstruction or a source edit.
    """
    report = classify(before, after, pair_changes=pair_changes)
    meta = validate_klayout(after)
    if before != empty_snapshot() and validate_klayout(before)["dbu_um"] != meta["dbu_um"]:
        raise ValueError("Review requires equal database units; normalize units explicitly first")
    layout = db.Layout()
    layout.dbu = meta["dbu_um"]
    layout.set_property("layoutdiff.review", True)
    cell = layout.create_cell("LAYOUT_DIFF_REVIEW")
    mapping, leaves, occurrences = {}, {}, {k: 0 for k in CATEGORIES}
    for side, snapshot in [("after", after), ("before", before)]:
        for geometry, category, layer, trans, key in _occurrences(snapshot, _statuses(report, side), side, limit=limit):
            identity = (category, layer)
            if identity not in mapping:
                number = 1000 + len(mapping)
                name = f"{category.upper()} | {layer[0]}/{layer[1]} {layer[2]}".rstrip()
                mapping[identity] = (layout.layer(db.LayerInfo(number, 0, name)), number, name)
            # Keep the native shape under its original complex transform.
            # Flattening a scaled path changes integer width rounding, and a
            # flattened Text cannot retain arbitrary rotation. Shared one-shape
            # leaves let KLayout render both exactly as in the source hierarchy.
            leaf_key = (key, category)
            if leaf_key not in leaves:
                leaf = layout.create_cell("OBJECT_" + str(len(leaves)))
                leaf.shapes(mapping[identity][0]).insert(geometry)
                leaves[leaf_key] = leaf
            cell.insert(db.CellInstArray(leaves[leaf_key].cell_index(), trans))
            occurrences[category] += 1
    report["layers"] = [{"category": cat, "original": list(layer), "layer": val[1],
                         "datatype": 0, "name": val[2]}
                        for (cat, layer), val in sorted(mapping.items(), key=lambda item: item[1][1])]
    report["visible_occurrences"] = occurrences
    report["note"] = ("After geometry plus before-side ghosts. Changed pairs are inference; "
                      "ghosts include old changed geometry. Counts are database objects, not XOR areas.")
    return layout, cell, report


def configure_view(view, report, style=None, *, cellview=0):
    """Apply only local view settings; never modify global KLayout preferences."""
    style = style or load_style()
    lay = view_api()
    view.clear_layers()
    for item in report["layers"]:
        settings = style[item["category"]]
        node = lay.LayerPropertiesNode()
        node.source = f"{item['layer']}/{item['datatype']}@{cellview + 1}"
        node.name = item["name"]
        node.fill_color = node.frame_color = int(settings["color"][1:], 16)
        node.dither_pattern = 0 if settings["fill"] else 1
        node.line_style, node.width = settings["line_style"], settings["width"]
        node.visible = True
        view.insert_layer(view.end_layers(), node)
    view.set_config("background-color", style["background"])
    view.set_config("grid-visible", "false")
    view.set_config("text-visible", "true")
    view.set_config("text-font", "0")
    view.set_config("default-text-size", "0.15")
    view.max_hier_levels = 2


def review_commit(history, revision=None, **kwargs):
    """Verify replayed revisions before comparing a selected commit to its parent."""
    chain = history.chain()
    if not chain:
        raise ValueError("History is empty")
    selected = chain[-1] if revision is None else next((c for c in chain if c["id"] == revision), None)
    if selected is None:
        raise ValueError("Revision is not reachable from HEAD; use a full commit ID")
    after = history.replay(selected["id"])
    before = history.replay(selected["parent"]) if selected["parent"] else empty_snapshot()
    return build_review(before, after, **kwargs)


def export_review(before, after, output_dir, *, style=None, pair_changes=True, limit=250000):
    """Publish a fresh directory; refuse existing output, including source paths."""
    layout, cell, report = build_review(before, after, pair_changes=pair_changes, limit=limit)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=False)
    layout.write(str(path / "review.oas"))
    atomic_json(path / "review.json", report)
    atomic_json(path / "style.json", style or load_style())
    # The same LayoutView layer settings work in desktop KLayout and in headless.
    lay = view_api()
    view = lay.LayoutView()
    # LayoutView assumes ownership; give it a copy so the caller keeps its DB.
    cv = view.show_layout(layout.dup(), False)
    view.cellview(cv).cell = view.cellview(cv).layout().cell(cell.name)
    configure_view(view, report, style, cellview=cv)
    view.save_layer_props(str(path / "review.lyp"))
    return layout, cell, report
