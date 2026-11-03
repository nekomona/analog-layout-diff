import copy
from pathlib import Path
import pytest
from layoutdiff.data.core import canonicalize
from layoutdiff.eda.virtuoso.adapter import coverage, render, VirtuosoAdapter, normalize


def test_known_unsupported_data_blocks_reconstruction():
    snap = canonicalize([{"kind": "unsupported", "category": "routes", "count": 3}])
    assert coverage(snap)
    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError("Must reject before touching Virtuoso")
    adapter = VirtuosoAdapter(NoCalls(), Path(__file__).parent / ".artifacts")
    with pytest.raises(ValueError, match="faithfully"):
        adapter.reconstruct(snap, "LAYOUT_DIFF_TEST", "never_created")


def test_unknown_geometry_and_off_grid_are_blockers():
    assert coverage(canonicalize([{"kind": "dot", "props": []}]))
    assert coverage(canonicalize([{"kind": "rect", "bBox": ["@off-grid", "1.1"], "props": []}]))


def test_transport_tags_do_not_corrupt_literal_property_lists():
    record = {"kind": "cell", "name": "", "props": [
        ["literal", "ILList", ["@list", ["@float", "123"]]],
        ["float", "float", ["@float", "1.23456789012345"]]]}
    props = dict((n, v) for n, _, v in normalize([record])["objects"]["cell:"]["props"])
    assert props == {"literal": ["@float", "123"], "float": 1.23456789012345}


def path_segment(begin="custom", end="chamfer", **fields):
    return {"kind": "pathSeg", "layerName": "MET1", "purpose": "drawing",
            "beginPt": [0, 0], "endPt": [4000, 4000], "width": 600,
            "beginStyle": begin, "endStyle": end, "beginExt": 200, "endExt": 400,
            "topology": "straight", "props": [], **fields}


@pytest.mark.parametrize("styles", [("custom", "chamfer"), ("variable", "custom"), ("custom", "custom")])
def test_custom_path_segment_dimensions_reach_native_constructor(styles):
    r = path_segment(*styles, customExtensions=[150, 250, 200, 300, 350, 400])
    meta = {"kind": "cell", "name": "", "dbu": 1000, "units": "micron", "cellType": "maskLayout", "props": []}
    snapshot = canonicalize([meta, r])
    assert not coverage(snapshot)
    code = "\n".join(render(snapshot))
    end_extension = '0.0' if styles[1] == 'chamfer' else '0.4'
    assert f'list(0.2 {end_extension} list(0.15 0.25 0.2 0.3 0.35 0.4))' in code
    # Both point coordinates and custom dimensions retain API units on diagonals.
    assert 'list(4.0 4.0) 0.6' in code


def test_chamfer_needs_no_custom_dimensions_and_legacy_ordinary_records_stay_valid():
    for styles in [("chamfer", "chamfer"), ("chamfer", "truncate"), ("variable", "extend")]:
        assert not coverage(canonicalize([path_segment(*styles)]))


@pytest.mark.parametrize("extensions", [None, [], [1, 2, 3], [0, 0, False, 0, 0, 0], [0, 0, 1.5, 0, 0, 0]])
def test_incomplete_custom_snapshots_require_recapture(extensions):
    assert "recapture" in " ".join(coverage(canonicalize([path_segment(customExtensions=extensions)])))


@pytest.mark.parametrize("filename", ["reader.il", "hierarchy.il", "gui.il", "browser.il", "runtime.il"])
def test_reader_has_balanced_parentheses(filename):
    # SKILL's loader can silently repair an unterminated procedure; reject it locally.
    owner = 'eda/virtuoso' if filename in {'reader.il', 'hierarchy.il'} else 'ui'
    source = Path(__file__).parents[1].joinpath('layoutdiff', owner, 'skill', filename).read_text()
    depth, string, escape, comment = 0, False, False, False
    for ch in source:
        if comment:
            comment = ch != "\n"
        elif string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                string = False
        elif ch == ';':
            comment = True
        elif ch == '"':
            string = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            assert depth >= 0
    assert depth == 0 and not string
