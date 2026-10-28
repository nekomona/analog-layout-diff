import copy
import pytest
from layoutdiff.comparison.categories import CategoryDiff, category, snapshot_changes
from layoutdiff.data.core import canonicalize, diff


def rect(x=0, **kwargs):
    return {"kind": "rect", "layerName": "MET1", "purpose": "drawing", "bBox": [[x, 0], [x+1, 1]],
            "props": [], **kwargs}


def test_categories_preserve_storage_and_pair_moves_and_attribute_edits():
    before = canonicalize([rect(0), rect(3), rect(5)])
    after = canonicalize([rect(0, props=[["note", "string", "changed"]]), rect(3), rect(8)])
    saved = copy.deepcopy([before, after])
    operations = diff(before, after)["operations"]
    result = CategoryDiff(operations)
    assert result.rows == [["MET1 shapes", 0, 1, 0, 0, 0], ["Moved / stretched / MET1 shapes", 0, 0, 0, 0, 1]]
    assert result.raw_operations == 4
    assert [before, after] == saved
    assert snapshot_changes(before, after) == operations
    full = "".join(result.full())
    assert '"note"' in full and '"changed"' in full and '"bBox"' in full


def test_duplicates_pair_once_without_hiding_multiplicity():
    before = canonicalize([rect()] * 3)
    after = canonicalize([rect(props=[["p", "int", 1]])] * 2)
    result = CategoryDiff(diff(before, after)["operations"])
    assert result.rows == [["MET1 shapes", 0, 2, 1, 0, 0]]


def test_vias_pcells_cells_mosaics_connectivity_and_metadata():
    records = [
        {"kind": "stdVia", "viaDef": "MET2_MET1"},
        {"kind": "inst", "name": "M", "libName": "EXAMPLE_TECH", "cellName": "example_nmos", "pcell": True},
        {"kind": "inst", "name": "I", "libName": "LIB", "cellName": "CHILD"},
        {"kind": "mosaic", "name": "A", "libName": "LIB", "cellName": "CHILD", "rows": 20, "columns": 10},
        {"kind": "dependency", "name": "dep", "libName": "LIB", "cellName": "CHILD"},
        {"kind": "cell", "name": ""}, {"kind": "net", "name": "VDD"},
        rect(purpose="pin"), {"kind": "label", "layerName": "MET1"}]
    values = [category(r) for r in records]
    assert values == ["MET2_MET1 vias", "EXAMPLE_TECH/example_nmos pcell", "LIB/CHILD cell", "LIB/CHILD mosaic",
                      "LIB/CHILD dependency", "Cellview properties", "Connectivity / nets", "MET1/pin shapes", "MET1 labels"]
    changed = {**records[2], "cellName": "OTHER"}
    result = CategoryDiff([{"key": "inst:I", "before": records[2], "after": changed}])
    assert result.rows == [["LIB/CHILD cell -> LIB/OTHER cell", 0, 1, 0, 0, 0]]


def test_page_bounds_and_complete_export_with_large_properties():
    ops = [{"key": f"inst:I{i:03d}", "before": None,
            "after": {"kind": "inst", "name": f"I{i:03d}", "libName": "LIB", "cellName": "CELL",
                      "props": [["long", "string", "x" * 2000 + f"END{i:03d}"]]}} for i in range(23)]
    result = CategoryDiff(ops)
    assert result.rows == [["LIB/CELL cell", 23, 0, 0, 0, 0]]
    first, last = result.page(0, 0), result.page(0, 2)
    assert first["pages"] == 3 and len(first["text"].encode()) < 7600
    assert "inst:I009" in first["text"] and "inst:I010" not in first["text"]
    assert "inst:I022" in last["text"]
    assert "END022" in "".join(result.full(0))
    with pytest.raises(ValueError):
        result.page(0, 3)


def test_100k_initial_elements_reduce_to_one_category():
    ops = [{"key": f"shape:{i}", "before": None, "after": rect(i)} for i in range(100000)]
    result = CategoryDiff(ops)
    assert result.rows == [["MET1 shapes", 100000, 0, 0, 0, 0]]
    assert result.page(0, 9999)["pages"] == 10000
    assert "shape:99999" in result.page(0, 9999)["text"]


def test_large_route_preview_does_not_iterate_entire_geometry():
    from layoutdiff.comparison.categories import operation_excerpt
    class BoundedPoints(list):
        def __iter__(self):
            for i in range(100000):
                assert i < 100, "Preview traversed geometry beyond its display budget"
                yield [i, i]
    record = {"kind": "path", "points": BoundedPoints([1])}
    text = operation_excerpt({"key": "path:long", "before": record, "after": record})
    assert "before:" in text and "after:" in text and "shortened" in text
    assert len(text.encode()) < 700
