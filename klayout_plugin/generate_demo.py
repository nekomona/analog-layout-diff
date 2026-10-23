"""Generate synthetic, reproducible evidence entirely inside a NEW directory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from layoutdiff.history import History, atomic_json
from .codec import db, capture_layout, reconstruct, write_layout
from .review import export_review, review_counts
from .render_diff import render_image


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    layout = db.Layout()
    layout.dbu = 0.001
    top, finger = layout.create_cell("TOP"), layout.create_cell("FINGER")
    m1, m2, m3, m4 = [layout.layer(i, 0) for i in (1, 2, 3, 4)]
    for x in (0, 1600, 3200):
        finger.shapes(m1).insert(db.Box(x, 0, x + 700, 5000))
    for y in (700, 3500):
        finger.shapes(m2).insert(db.Box(-300, y, 4300, y + 700))
    for x in (100, 1700, 3300):
        for y in (900, 3700):
            finger.shapes(m2).insert(db.Box(x, y, x + 300, y + 300))
    top.insert(db.CellInstArray(finger.cell_index(), db.Trans(),
                               db.Vector(6500, 0), db.Vector(0, 8000), 4, 2))
    top.shapes(m1).insert(db.Box(-1500, -2000, 26000, -1000))
    top.shapes(m1).insert(db.Box(-1500, 14500, 26000, 15500))
    old_route = top.shapes(m2).insert(db.Path([db.Point(30000, 0), db.Point(39000, 0),
                                             db.Point(39000, 12000), db.Point(49000, 12000)], 1500))
    old_pad = top.shapes(m3).insert(db.Box(55000, 2000, 66000, 12000))
    before = capture_layout(layout)
    old_route.path = db.Path([db.Point(30000, 0), db.Point(43000, 0),
                              db.Point(43000, 9000), db.Point(50000, 9000)], 1500)
    old_pad.delete()
    top.shapes(m4).insert(db.Box(71000, 2000, 82000, 12000))
    after = capture_layout(layout)
    atomic_json(output / "before.json", before)
    atomic_json(output / "after.json", after)
    write_layout(before, output / "before.gds")
    write_layout(after, output / "after.oas")
    history = History(output / "history")
    history.init()
    first = history.commit(before, "Initial synthetic device array and routing", expected_head=None)
    second = history.commit(after, "Reroute metal, remove old pad, add a new pad", expected_head=first["id"])
    assert history.replay() == after
    restored, top = reconstruct(history.replay())
    assert capture_layout(restored, top.name) == after
    layout, cell, report = export_review(before, after, output / "review")
    image = output / "review" / "review.png"
    render_image(layout, cell, report, image, width=1400, height=720)
    repeated = output / "repeat.png"
    render_image(layout, cell, report, repeated, width=1400, height=720)
    assert repeated.read_bytes() == image.read_bytes()
    repeated.unlink()
    evidence = {"fixture": "synthetic geometry, not a PDK circuit", "commits": [first["id"], second["id"]],
                "counts": review_counts(report), "visible_occurrences": report["visible_occurrences"],
                "exact_native_reconstruction": True, "repeated_png_bytes_equal": True,
                "png_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    atomic_json(output / "verification.json", evidence)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="NEW directory (existing directories refused)")
    generate(parser.parse_args().output)
