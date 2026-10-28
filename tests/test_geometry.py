import klayout.db as kdb
from layoutdiff.virtuoso.geometry import compare_gds


def make(path, dx=0, text="a"):
    layout = kdb.Layout()
    layout.dbu = .001
    child = layout.create_cell("child")
    li = layout.layer(81, 0)
    child.shapes(li).insert(kdb.Box(0, 0, 100 + dx, 100))
    top = layout.create_cell("top")
    top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(1000, 0)))
    top.shapes(li).insert(kdb.Text(text, kdb.Trans()))
    layout.write(str(path))


def test_geometry_xor_detects_one_dbu_and_text_only_changes(tmp_path):
    a, b = tmp_path / "a.gds", tmp_path / "b.gds"
    make(a)
    make(b)
    assert compare_gds(a, b)["equal"]
    make(b, dx=1)
    assert not compare_gds(a, b)["equal"]
    assert compare_gds(a, b)["layers"][0]["xor_area_dbu2"] == 100
    make(b, text="different")
    report = compare_gds(a, b)
    assert not report["equal"]
    assert report["layers"][0]["xor_empty"]
