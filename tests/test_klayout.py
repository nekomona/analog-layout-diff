"""Real KLayout database, stream, history, review, and renderer regressions."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from layoutdiff.data.core import apply_diff, canonicalize, diff, digest, empty_snapshot
from layoutdiff.data.history import History, read_json
from layoutdiff.eda.klayout.codec import (db, capture_layout, read_layout, reconstruct,
                                   validate_klayout, write_layout)
from layoutdiff.eda.klayout.review import (DEFAULT_STYLE, build_review, classify, export_review,
                                    load_style, review_commit, review_counts)
from layoutdiff.eda.klayout.render_diff import render_image


def database():
    layout = db.Layout()
    layout.dbu = 0.002
    layout.set_properties({"author": "fixture", 9: [1, 2.5, "3", None]})
    top, child, empty = [layout.create_cell(n) for n in ["TOP", "DEVICE", "EMPTY"]]
    top.set_properties({"nested": {"value": [4, "four"]}})
    m1, m2 = layout.layer(db.LayerInfo(1, 0, "M1")), layout.layer(db.LayerInfo(2, 1, "M2"))
    for _ in range(2):
        top.shapes(m1).insert(db.Box(-100, -200, 700, 500))
    poly = db.Polygon([db.Point(0, 0), db.Point(2000, 0), db.Point(2000, 1500), db.Point(0, 1500)])
    poly.insert_hole([db.Point(200, 200), db.Point(600, 200), db.Point(600, 600), db.Point(200, 600)])
    shape = child.shapes(m2).insert(poly)
    shape.set_properties({7: "pin-label", "list": [1, 2, "x"]})
    child.shapes(m1).insert(db.Path([db.Point(0, 0), db.Point(150, 900), db.Point(1000, 900)], 80, 50, 75, True))
    for rot in range(8):
        text = db.Text(f"D{rot}", db.Trans(rot % 4, rot >= 4, rot * 200, 2000))
        text.size, text.font = 160, 0
        text.halign, text.valign = db.Text.HAlignCenter, db.Text.VAlignBottom
        child.shapes(m1).insert(text)
    inst = top.insert(db.CellInstArray(child.cell_index(), db.ICplxTrans(1.5, 30, True, 4000, 2000),
                                      db.Vector(4000, 0), db.Vector(500, 6000), 2, 3))
    inst.set_properties({"device": "array"})
    top.insert(db.CellInstArray(empty.cell_index(), db.Trans()))
    return layout


def simple(*boxes, layer=1):
    layout = db.Layout()
    cell = layout.create_cell("TOP")
    for box in boxes:
        cell.shapes(layout.layer(layer, 0)).insert(db.Box(*box))
    return capture_layout(layout)


def regions(layout, cell):
    return {(layout.get_info(li).layer, layout.get_info(li).datatype): db.Region(cell.begin_shapes_rec(li))
            for li in layout.layer_indexes()}


def test_native_exact_roundtrip_and_duplicates():
    original = database()
    snapshot = capture_layout(original)
    recovered, top = reconstruct(snapshot)
    assert capture_layout(recovered) == snapshot
    assert len([r for r in snapshot["objects"].values() if r["kind"] == "cell"]) == 3
    duplicates = [r for r in snapshot["objects"].values()
                  if r["kind"] == "klayout_shape" and r["geometry"]["type"] == "box"]
    assert len(duplicates) == 2
    old_regions, new_regions = regions(original, original.cell("TOP")), regions(recovered, top)
    assert old_regions.keys() == new_regions.keys()
    assert all((old_regions[key] ^ new_regions[key]).is_empty() for key in old_regions)


@pytest.mark.parametrize("extension", ["gds", "oas"])
def test_stream_input_replay_reconstruction(tmp_path, extension):
    source = tmp_path / ("source." + extension)
    database().write(str(source))
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    snapshot = read_layout(source)
    layout, top = reconstruct(snapshot)
    assert capture_layout(layout, top.name) == snapshot
    restored = tmp_path / ("restored." + extension)
    write_layout(snapshot, restored)
    again = read_layout(restored)
    native, native_top = reconstruct(again)
    a, b = regions(layout, top), regions(native, native_top)
    assert all((a[k] ^ b[k]).is_empty() for k in a)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    with pytest.raises(FileExistsError):
        write_layout(snapshot, source)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_deterministic_order_and_multitop(tmp_path):
    a = simple((0, 0, 20, 20), (60, 60, 100, 100))
    b = simple((60, 60, 100, 100), (0, 0, 20, 20))
    assert digest(a) == digest(b)
    layout = database()
    layout.create_cell("OTHER")
    with pytest.raises(ValueError, match="Select one top"):
        capture_layout(layout)
    assert capture_layout(layout, "TOP") == capture_layout(database())
    with pytest.raises(ValueError, match="does not exist"):
        capture_layout(layout, "missing")


def test_fail_closed_on_other_backend_bad_units_and_unreachable():
    snapshot = simple((0, 0, 20, 20))
    with pytest.raises(ValueError, match="not a Virtuoso"):
        validate_klayout(canonicalize([{"kind": "cell", "name": "", "dbu": 1000}]))
    records = list(snapshot["objects"].values())
    records.append({"kind": "cell", "name": "orphan", "backend": "klayout-static/1", "properties": []})
    with pytest.raises(ValueError, match="unreachable"):
        validate_klayout(canonicalize(records))
    records = copy.deepcopy(list(snapshot["objects"].values()))
    next(v for v in records if v["kind"] == "klayout_meta")["dbu_um"] = 0
    with pytest.raises(ValueError, match="database unit"):
        validate_klayout(canonicalize(records))


def test_history_every_revision_reverse_and_tamper(tmp_path):
    snapshots = [simple((0, 0, 20, 20)), simple((5, 0, 25, 20)), simple()]
    history = History(tmp_path / "history")
    history.init()
    state, parent = empty_snapshot(), None
    for index, snapshot in enumerate(snapshots):
        c = history.commit(snapshot, f"revision {index}", expected_head=parent)
        assert history.replay(c["id"]) == snapshot
        assert apply_diff(snapshot, c, parent=parent, reverse=True) == state
        recovered, top = reconstruct(snapshot)
        assert capture_layout(recovered, top.name) == snapshot
        state, parent = snapshot, c["id"]
    assert history.commit(state, "unchanged", expected_head=parent) is None
    with pytest.raises(ValueError, match="changed since capture"):
        history.commit(snapshots[0], "stale", expected_head=None)
    commit_path = history.path / "commits" / (parent + ".json")
    corrupt = read_json(commit_path)
    corrupt["message"] = "tampered"
    commit_path.write_text(json.dumps(corrupt), encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt commit"):
        history.replay()


def test_classifier_unique_pair_ambiguous_edits_and_duplicate_counts():
    before = simple((0, 0, 20, 20), (40, 0, 60, 20))
    after = simple((0, 0, 20, 20), (45, 0, 65, 20))
    r = classify(before, after)
    assert review_counts(r) == {"unchanged": 1, "changed": 1, "added": 0, "removed": 0, "metadata": 0}
    exact = classify(before, after, pair_changes=False)
    assert len(exact["added"]) == len(exact["removed"]) == 1
    ambiguous = classify(before, simple((10, 0, 30, 20), (50, 0, 70, 20)))
    assert not ambiguous["changed"]
    assert len(ambiguous["added"]) == len(ambiguous["removed"]) == 2
    duplicates = classify(simple((0, 0, 20, 20), (0, 0, 20, 20)), simple((0, 0, 20, 20)))
    assert len(duplicates["unchanged"]) == len(duplicates["removed"]) == 1


def test_changed_instance_and_child_changes_expand_to_all_references():
    layout = db.Layout()
    top, child = layout.create_cell("TOP"), layout.create_cell("DEVICE")
    layer = layout.layer(1, 0)
    shape = child.shapes(layer).insert(db.Box(0, 0, 200, 200))
    inst = top.insert(db.CellInstArray(child.cell_index(), db.Trans(), db.Vector(400, 0), db.Vector(0, 0), 3, 1))
    before = capture_layout(layout)
    shape.box = db.Box(0, 0, 250, 200)
    after = capture_layout(layout)
    _, _, report = build_review(before, after)
    assert report["visible_occurrences"] == {"unchanged": 0, "changed": 3, "added": 0, "removed": 3}
    inst.cplx_trans = db.ICplxTrans(1, 45, False, 2000, 1000)
    moved = capture_layout(layout)
    _, _, report = build_review(after, moved)
    assert report["visible_occurrences"]["changed"] == 3
    assert report["visible_occurrences"]["removed"] == 3
    with pytest.raises(ValueError, match="limit|exceeds"):
        build_review(before, moved, limit=2)


def test_removal_only_and_metadata_change(tmp_path):
    before = simple((0, 0, 1000, 500))
    after = simple()
    _, cell, report = build_review(before, after)
    assert not cell.bbox().empty()
    assert report["visible_occurrences"]["removed"] == 1
    assert report["visible_occurrences"]["added"] == 0
    layout = database()
    before = capture_layout(layout)
    layout.cell("TOP").set_property("version", 2)
    after = capture_layout(layout)
    _, _, report = build_review(before, after)
    assert len(report["metadata"]) == 1
    assert report["visible_occurrences"]["removed"] == 0


def test_style_validation_and_dbu_mismatch(tmp_path):
    config = tmp_path / "style.json"
    config.write_text('{"added":{"color":"#0055bb","fill":false}}')
    style = load_style(config)
    assert style["added"]["color"] == "#0055bb"
    assert not style["added"]["fill"]
    assert DEFAULT_STYLE["added"]["color"] == "#169b62"
    config.write_text('{"removed":{"width":0}}')
    with pytest.raises(ValueError, match="width"):
        load_style(config)
    before = simple((0, 0, 10, 10))
    layout, _ = reconstruct(before)
    layout.dbu *= 2
    with pytest.raises(ValueError, match="equal database units"):
        build_review(before, capture_layout(layout))


def visual_pair():
    before_layout = db.Layout()
    cell = before_layout.create_cell("TOP")
    cell.shapes(before_layout.layer(1, 0)).insert(db.Box(0, 0, 1600, 1000))
    changed = cell.shapes(before_layout.layer(2, 0)).insert(db.Box(2100, 0, 3500, 1000))
    removed = cell.shapes(before_layout.layer(3, 0)).insert(db.Box(4200, 0, 5600, 1000))
    before = capture_layout(before_layout)
    changed.box = db.Box(2400, 300, 3800, 1300)
    removed.delete()
    cell.shapes(before_layout.layer(4, 0)).insert(db.Box(6000, 0, 7400, 1000))
    return before, capture_layout(before_layout)


def test_rendered_images_real_geometry_color_and_byte_determinism(tmp_path):
    before, after = visual_pair()
    layout, cell, report = build_review(before, after)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    render_image(layout, cell, report, a, width=900, height=500)
    render_image(layout, cell, report, b, width=900, height=500)
    assert a.read_bytes() == b.read_bytes()
    with Image.open(a) as image:
        assert image.size == (900, 500)
        pixels = image.crop((0, 100, 900, 500)).convert("RGB")
        colors = set(pixels.get_flattened_data() if hasattr(pixels, "get_flattened_data") else pixels.getdata())
        for category in ["unchanged", "changed", "added", "removed"]:
            color = DEFAULT_STYLE[category]["color"]
            expected = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
            assert expected in colors, category
    with pytest.raises(FileExistsError):
        render_image(layout, cell, report, a)


def test_review_export_layer_mapping_and_history_first_commit(tmp_path):
    before, after = visual_pair()
    path = tmp_path / "review"
    layout, cell, report = export_review(before, after, path)
    assert layout.cell("LAYOUT_DIFF_REVIEW").name == cell.name  # Still alive after LayoutView destruction.
    assert (path / "review.lyp").is_file()
    assert read_json(path / "review.json") == report
    loaded = db.Layout(); loaded.read(str(path / "review.oas"))
    assert loaded.property("layoutdiff.review")
    assert len(list(loaded.layer_indexes())) == len(report["layers"])
    with pytest.raises(FileExistsError):
        export_review(before, after, path)
    history = History(tmp_path / "history"); history.init()
    commit = history.commit(after, "initial", expected_head=None)
    _, _, report = review_commit(history, commit["id"])
    assert report["before"] == digest(empty_snapshot())
    assert not report["removed"]


def test_review_hierarchy_transforms_match_native_regions():
    original = database()
    review, cell, report = build_review(empty_snapshot(), capture_layout(original))
    expected = regions(original, original.cell("TOP"))
    for item in report["layers"]:
        assert item["category"] == "added"
        actual = db.Region(cell.begin_shapes_rec(review.find_layer(item["layer"], 0)))
        assert (actual ^ expected[tuple(item["original"][:2])]).is_empty()


@pytest.mark.parametrize('cli_module', ['layoutdiff.eda.klayout', 'klayout_plugin'])
def test_cli_full_flow_and_snapshot_helper(tmp_path, cli_module):
    root = Path(__file__).resolve().parents[1]
    input_file, after_file = tmp_path / "before.oas", tmp_path / "after.oas"
    before, after = visual_pair()
    write_layout(before, input_file); write_layout(after, after_file)
    history = tmp_path / "history"

    def run(*args, module=cli_module):
        result = subprocess.run([sys.executable, "-m", module, *map(str, args)], cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    run("init", history)
    first = run("commit", history, input_file, "-m", "first").strip()
    second = run("commit", history, after_file, "-m", "second").strip()
    assert first in run("log", history) and second in run("log", history)
    run("replay", history, tmp_path / "first.json", "--at", first)
    run("restore", history, tmp_path / "restored.oas", "--at", second)
    assert read_layout(tmp_path / "restored.oas") == read_layout(after_file)
    run("review", tmp_path / "review", "--history", history)
    assert (tmp_path / "review" / "review.png").is_file()
    run(tmp_path / "first.json", after_file, tmp_path / "helper.png", "--width", 800, "--height", 400,
        module=cli_module + ".render_diff")
    assert (tmp_path / "helper.png").is_file()


def test_gui_macro_xml_and_python_compile():
    import ast
    import xml.etree.ElementTree as ET
    root = Path(__file__).resolve().parents[1] / 'layoutdiff/eda/klayout'
    macro = ET.parse(root / "analog_layout_diff.lym").getroot()
    assert macro.findtext("interpreter") == "python"
    ast.parse(macro.findtext("text"))
    ast.parse((root / "gui.py").read_text(encoding="utf-8"))


@pytest.mark.parametrize('module', ['layoutdiff.eda.klayout.generate_demo', 'klayout_plugin.generate_demo'])
def test_demo_entrypoints_generate_verified_snapshots(tmp_path, module):
    output = tmp_path / 'demo'
    result = subprocess.run([sys.executable, '-m', module, str(output)],
                            cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_json(output / 'verification.json')
    assert report['exact_native_reconstruction'] and report['repeated_png_bytes_equal']
    assert (output / 'review/review.png').is_file()
