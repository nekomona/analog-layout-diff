from layoutdiff.core import canonicalize
from layoutdiff.review import classify
from layoutdiff.gui import display_resource, swatch
import pytest


def test_review_groups_attribute_pair_and_removed_geometry():
    shape = {"kind": "rect", "bBox": [[0, 0], [10, 10]], "props": []}
    moved = {**shape, "bBox": [[20, 0], [30, 10]]}
    old = canonicalize([shape, shape, moved, {"kind": "inst", "name": "I", "xy": [0, 0]}])
    new = canonicalize([shape, {**shape, "props": [["tag", "string", "changed"]]},
                        {"kind": "inst", "name": "I", "xy": [10, 0]},
                        {**moved, "bBox": [[40, 0], [50, 10]]}])
    result = classify(old, new)
    assert result["counts"] == {"untouched": 1, "changed": 1, "moved": 2, "netChanged": 0, "new": 0}
    assert len(result["removed"]) == 0
    assert len(result["attribute_pairs"]) == 2


def test_net_metadata_propagates_to_figures():
    shape = {"kind": "rect", "bBox": [[0, 0], [1, 1]], "net": "VDD"}
    net = {"kind": "net", "name": "VDD", "props": []}
    a = canonicalize([shape, net])
    b = canonicalize([shape, {**net, "props": [["tag", "int", 2]]}])
    result = classify(a, b)
    assert result["counts"]["changed"] == 0
    assert result["counts"]["netChanged"] == 1
    assert result["metadata_changes"] == ["net:VDD"]


def test_style_validation_and_color_icon():
    assert "1 1 1 1 0 0" in display_resource("ALDtest", ["Orange", "Dashed", "3"])
    assert swatch((255, 0, 0)).startswith(b"\x89PNG")
    with pytest.raises(ValueError):
        display_resource("ALDtest", ["bad", "Solid", "3"])


def test_cleanup_refuses_unowned_cells_before_contacting_virtuoso(tmp_path):
    from layoutdiff.gui import GuiWorker
    from layoutdiff.history import atomic_json
    worker = GuiWorker(None, tmp_path)
    token = "a" * 32
    atomic_json(tmp_path / "reviews" / token / "review.json", {
        "token": token, "cell": "designer_source", "library": worker.review_library})
    with pytest.raises(ValueError, match="unrecognized"):
        worker.clean_reviews()
