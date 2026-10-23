"""Deterministic headless PNG helper, using KLayout's actual LayoutView renderer.

python -m klayout_plugin.render_diff before.gds after.oas review.png
The PNG includes an explicit legend; removed objects/old changed positions are
red hollow ghosts. No native desktop window or live design is touched.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from layoutdiff.core import empty_snapshot
from layoutdiff.history import read_json
from .api import view_api
from .codec import read_layout, validate_klayout
from .review import build_review, configure_view, load_style, review_counts


def load_snapshot(path, top=None):
    if str(path) == "EMPTY":
        return empty_snapshot()
    if Path(path).suffix.lower() == ".json":
        if top is not None:
            raise ValueError("--top only applies to stream input; JSON already selects its top")
        snapshot = read_json(path)
        validate_klayout(snapshot)
        return snapshot
    return read_layout(path, top)


def render_image(layout, cell, report, path, *, style=None, width=1200, height=800):
    """Byte-repeatable for identical input/style/KLayout/Pillow versions.

    Database geometry is rendered by KLayout, and Pillow adds a fixed bitmap-font
    legend. No timestamps, random IDs, external fonts, or source paths are drawn.
    """
    if not 400 <= width <= 8192 or not 250 <= height <= 8192:
        raise ValueError("Image dimensions must be 400..8192 by 250..8192")
    lay = view_api()
    from PIL import Image, ImageDraw, ImageFont

    path, style = Path(path), style or load_style()
    if path.suffix.lower() != ".png":
        raise ValueError("Image output must end in .png")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve exclusively: never overwrite an input/source or an older artifact.
    with path.open("xb"):
        pass
    fd, raw = tempfile.mkstemp(suffix=".png", prefix=".layoutdiff-render-", dir=path.parent)
    os.close(fd)
    try:
        view = lay.LayoutView()
        cv = view.show_layout(layout.dup(), False)
        view.cellview(cv).cell = view.cellview(cv).layout().cell(cell.name)
        configure_view(view, report, style, cellview=cv)
        box = cell.dbbox()
        if box.empty() or box.width() == 0 or box.height() == 0:
            from .codec import db
            box = db.DBox(-1, -1, 1, 1)
        padding = max(box.width(), box.height()) * 0.06
        view.zoom_box(box.enlarged(padding))
        header = 100
        view.save_image(raw, width, height - header)
        output = Image.new("RGB", (width, height), style["background"])
        with Image.open(raw) as scene:
            output.paste(scene.convert("RGB"), (0, header))
        draw, font = ImageDraw.Draw(output), ImageFont.load_default()
        fg = "#1d2433" if sum(int(style["background"][i:i+2], 16) for i in (1, 3, 5)) > 360 else "#eeeeee"
        draw.text((16, 9), "ANALOG LAYOUT DIFF | after + before ghosts", fill=fg, font=font)
        counts = review_counts(report)
        for index, category in enumerate(("unchanged", "changed", "added", "removed")):
            x = 16 + index * ((width - 32) // 4)
            color = style[category]["color"]
            draw.rectangle((x, 33, x + 12, 45), outline=color,
                           fill=color if style[category]["fill"] else None, width=2)
            draw.text((x + 18, 33), f"{category}: {counts[category]}", fill=fg, font=font)
        mode = "unique-pair inference" if report["pairing"] != "exact-only" else "exact objects only"
        draw.text((16, 56), f"Changed: {mode}. Red: removals AND old changed positions.", fill=fg, font=font)
        draw.text((16, 76), f"Metadata changes: {counts['metadata']} | counts are stored objects; arrays expand in view", fill=fg, font=font)
        output.save(path, format="PNG", optimize=False, compress_level=9)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        Path(raw).unlink(missing_ok=True)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="GDS/OAS, KLayout snapshot JSON, or EMPTY")
    parser.add_argument("after", help="GDS/OAS or KLayout snapshot JSON")
    parser.add_argument("output", help="NEW PNG path (existing files are refused)")
    parser.add_argument("--before-top")
    parser.add_argument("--after-top")
    parser.add_argument("--style", help="JSON with background and category color/fill/width/line_style")
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--limit", type=int, default=250000)
    parser.add_argument("--exact-only", action="store_true", help="Disable changed-pair inference")
    args = parser.parse_args(argv)
    try:
        before = load_snapshot(args.before, args.before_top)
        after = load_snapshot(args.after, args.after_top)
        layout, cell, report = build_review(before, after, pair_changes=not args.exact_only, limit=args.limit)
        render_image(layout, cell, report, args.output, style=load_style(args.style), width=args.width, height=args.height)
        print(str(Path(args.output).resolve()))
        print(review_counts(report))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"layout-diff: {exc}\n")


if __name__ == "__main__":
    main()
