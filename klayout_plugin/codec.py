"""Canonical, hierarchical KLayout database snapshots, without OA claims."""
from __future__ import annotations

import math
from pathlib import Path

from .api import db

from layoutdiff.core import canonicalize, encoded, validate

BACKEND = "klayout-static/1"


def _value(value):
    """Typed JSON for KLayout property names/values (including nested values)."""
    if value is None:
        return ["null", None]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float) and math.isfinite(value):
        return ["float", value]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, (list, tuple)):
        return ["list", [_value(v) for v in value]]
    if isinstance(value, dict):
        return ["dict", sorted([[_value(k), _value(v)] for k, v in value.items()], key=encoded)]
    raise ValueError(f"Unsupported KLayout property value: {type(value).__name__}")


def _unvalue(value):
    tag, data = value
    if tag == "null" and data is None:
        return None
    if tag in {"bool", "int", "float", "str"}:
        return data
    if tag == "bytes":
        return bytes.fromhex(data)
    if tag == "list":
        return [_unvalue(v) for v in data]
    if tag == "dict":
        return {_unvalue(k): _unvalue(v) for k, v in data}
    raise ValueError("Invalid typed property value")


def _props(obj):
    return sorted([[_value(k), _value(v)] for k, v in obj.properties().items()], key=encoded)


def _restore_props(obj, props):
    obj.set_properties({_unvalue(k): _unvalue(v) for k, v in props})


def _point(p):
    return [p.x, p.y]


def transform_record(t):
    return {"mag": t.mag, "angle": t.angle, "mirror": t.is_mirror(), "xy": _point(t.disp)}


def transform_from(record):
    return db.ICplxTrans(record["mag"], record["angle"], record["mirror"], *record["xy"])


def shape_record(shape):
    if shape.is_box():
        b = shape.box
        return {"type": "box", "box": [b.left, b.bottom, b.right, b.top]}
    if shape.is_path():
        p = shape.path
        return {"type": "path", "points": [_point(v) for v in p.each_point()],
                "width": p.width, "begin": p.bgn_ext, "end": p.end_ext, "round": p.round}
    if shape.is_text():
        t = shape.text
        return {"type": "text", "string": t.string,
                "rot": t.trans.rot, "xy": _point(t.trans.disp),
                "size": t.size, "font": t.font, "halign": int(t.halign), "valign": int(t.valign)}
    if shape.is_polygon() or shape.is_simple_polygon():
        p = shape.polygon
        return {"type": "polygon", "hull": [_point(v) for v in p.each_point_hull()],
                "holes": [[_point(v) for v in p.each_point_hole(i)] for i in range(p.holes())]}
    raise ValueError("Unsupported KLayout shape (edge/user object); capture refused")


def shape_from(record):
    kind = record["type"]
    if kind == "box":
        return db.Box(*record["box"])
    if kind == "polygon":
        p = db.Polygon([db.Point(*v) for v in record["hull"]])
        for hole in record["holes"]:
            p.insert_hole([db.Point(*v) for v in hole])
        return p
    if kind == "path":
        return db.Path([db.Point(*v) for v in record["points"]], record["width"],
                       record["begin"], record["end"], record["round"])
    if kind == "text":
        t = db.Text(record["string"], db.Trans(record["rot"] % 4, record["rot"] >= 4, *record["xy"]))
        t.size, t.font = record["size"], record["font"]
        t.halign = { -1: db.Text.NoHAlign, 0: db.Text.HAlignLeft,
                     1: db.Text.HAlignCenter, 2: db.Text.HAlignRight}[record["halign"]]
        t.valign = { -1: db.Text.NoVAlign, 0: db.Text.VAlignTop,
                     1: db.Text.VAlignCenter, 2: db.Text.VAlignBottom}[record["valign"]]
        return t
    raise ValueError("Unknown KLayout shape type: " + str(kind))


def _top(layout, top):
    if top is None:
        tops = list(layout.top_cells())
        if len(tops) != 1:
            raise ValueError("Select one top cell explicitly; database has " + str(len(tops)))
        return tops[0]
    cell = layout.cell(top)
    if cell is None:
        raise ValueError("Top cell does not exist: " + str(top))
    return cell


def capture_layout(layout, top=None):
    """Read a selected cell and all reachable cells; never modify the layout.

    PCells and library cells enter as evaluated static cells. No generators,
    library links, technology, netlist, or editor metadata are reconstructed.
    """
    root = _top(layout, top)
    cells, visiting = {}, set()

    def visit(cell):
        if cell.cell_index() in visiting:
            raise ValueError("Recursive cell hierarchy cannot be captured")
        if cell.name in cells:
            return
        visiting.add(cell.cell_index())
        for inst in cell.each_inst():
            visit(layout.cell(inst.cell_index))
        visiting.remove(cell.cell_index())
        cells[cell.name] = cell

    visit(root)
    records, used_layers = [], set()
    for name, cell in sorted(cells.items()):
        records.append({"kind": "cell", "name": name, "backend": BACKEND,
                        "properties": _props(cell)})
        for li in layout.layer_indexes():
            shapes = cell.shapes(li)
            if shapes.is_empty():
                continue
            info = layout.get_info(li)
            if info.layer < 0 or info.datatype < 0:
                raise ValueError("Stream capture requires numeric layer/datatype pairs")
            layer = (info.layer, info.datatype, info.name)
            used_layers.add(layer)
            for shape in shapes.each():
                records.append({"kind": "klayout_shape", "cell": name, "layer": list(layer),
                                "geometry": shape_record(shape), "properties": _props(shape)})
        for inst in cell.each_inst():
            records.append({"kind": "klayout_instance", "cell": name,
                            "master": layout.cell(inst.cell_index).name,
                            "transform": transform_record(inst.cplx_trans),
                            "array": {"regular": inst.is_regular_array(), "a": _point(inst.a),
                                      "b": _point(inst.b), "na": inst.na, "nb": inst.nb},
                            "properties": _props(inst)})
    records.append({"kind": "klayout_meta", "backend": BACKEND, "top": root.name,
                    "dbu_um": layout.dbu, "properties": _props(layout),
                    "layers": [list(v) for v in sorted(used_layers)]})
    snapshot = canonicalize(records)
    validate_klayout(snapshot)
    return snapshot


def read_layout(path, top=None):
    path = Path(path)
    if path.suffix.lower() not in {".gds", ".gds2", ".gdsii", ".oas", ".oasis"}:
        raise ValueError("Expected a GDS or OASIS layout file")
    layout = db.Layout()
    layout.read(str(path))
    return capture_layout(layout, top)


def validate_klayout(snapshot):
    validate(snapshot)
    objs = list(snapshot["objects"].values())
    metas = [o for o in objs if o["kind"] == "klayout_meta"]
    if len(metas) != 1 or metas[0].get("backend") != BACKEND:
        raise ValueError("Expected a klayout-static/1 snapshot (not a Virtuoso/OA snapshot)")
    meta = metas[0]
    if not isinstance(meta["dbu_um"], (int, float)) or not math.isfinite(meta["dbu_um"]) or meta["dbu_um"] <= 0:
        raise ValueError("Invalid database unit")
    cells = {o["name"] for o in objs if o["kind"] == "cell" and o.get("backend") == BACKEND}
    if meta["top"] not in cells:
        raise ValueError("Missing top cell")
    children = {name: [] for name in cells}
    for o in objs:
        if o["kind"] not in {"cell", "klayout_shape", "klayout_instance", "klayout_meta"}:
            raise ValueError("Unsupported record in KLayout snapshot: " + o["kind"])
        if o["kind"] == "cell" and o.get("backend") != BACKEND:
            raise ValueError("Mixed database backends")
        if o["kind"] in {"klayout_shape", "klayout_instance"} and o["cell"] not in cells:
            raise ValueError("Object references missing cell")
        if o["kind"] == "klayout_shape":
            if o["layer"] not in meta["layers"]:
                raise ValueError("Shape references missing layer")
            shape_from(o["geometry"])
        if o["kind"] == "klayout_instance":
            if o["master"] not in cells:
                raise ValueError("Instance references missing master")
            children[o["cell"]].append(o["master"])
            a = o["array"]
            if a["regular"] and (a["na"] < 1 or a["nb"] < 1):
                raise ValueError("Invalid array count")
            if o["transform"]["mag"] <= 0:
                raise ValueError("Invalid instance magnification")
    done, stack = set(), set()

    def visit(name):
        if name in stack:
            raise ValueError("Recursive cell hierarchy")
        if name in done:
            return
        stack.add(name)
        for child in children[name]:
            visit(child)
        stack.remove(name)
        done.add(name)
    visit(meta["top"])
    if done != cells:
        raise ValueError("Snapshot contains cells unreachable from selected top")
    return meta


def reconstruct(snapshot):
    """Construct a fresh in-memory static layout; source files are never opened."""
    meta = validate_klayout(snapshot)
    layout = db.Layout()
    layout.dbu = meta["dbu_um"]
    _restore_props(layout, meta["properties"])
    records = list(snapshot["objects"].values())
    cells = {}
    for o in records:
        if o["kind"] == "cell":
            cell = layout.create_cell(o["name"])
            _restore_props(cell, o["properties"])
            cells[o["name"]] = cell
    layers = {tuple(v): layout.layer(db.LayerInfo(v[0], v[1], v[2])) for v in meta["layers"]}
    for o in records:
        if o["kind"] == "klayout_shape":
            shape = cells[o["cell"]].shapes(layers[tuple(o["layer"])]).insert(shape_from(o["geometry"]))
            _restore_props(shape, o["properties"])
        elif o["kind"] == "klayout_instance":
            args = [cells[o["master"]].cell_index(), transform_from(o["transform"])]
            a = o["array"]
            if a["regular"]:
                args += [db.Vector(*a["a"]), db.Vector(*a["b"]), a["na"], a["nb"]]
            inst = cells[o["cell"]].insert(db.CellInstArray(*args))
            _restore_props(inst, o["properties"])
    # The exact native modeled state must round-trip before publishing anything.
    if encoded(capture_layout(layout, meta["top"])) != encoded(snapshot):
        raise ValueError("KLayout normalized fields during reconstruction; exact replay refused")
    return layout, cells[meta["top"]]


def write_layout(snapshot, path):
    """Publish a new file exclusively. Stream formats can normalize representation.

    The JSON snapshot is the authoritative exact archive; GDS can fracture hole
    polygons and has narrower property support. Use OAS for a richer export.
    """
    path = Path(path)
    if path.exists():
        raise FileExistsError("Destination exists: " + str(path))
    if path.suffix.lower() not in {".gds", ".oas"}:
        raise ValueError("Output must end in .gds or .oas")
    layout, _ = reconstruct(snapshot)
    options = db.SaveLayoutOptions()
    options.set_format_from_filename(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive placeholder prevents accidental overwrite, including a race.
    with path.open("xb"):
        pass
    try:
        layout.write(str(path), options)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
