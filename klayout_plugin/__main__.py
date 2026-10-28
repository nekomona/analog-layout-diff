"""Isolated KLayout command line integration; no Virtuoso bridge needed."""
from __future__ import annotations

import argparse
from pathlib import Path

from layoutdiff.data.core import empty_snapshot
from layoutdiff.data.history import History, read_json
from .codec import read_layout, write_layout
from .render_diff import load_snapshot, render_image
from .review import export_review, load_style, review_counts


def _new_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        import json
        json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create empty history")
    init.add_argument("history")
    capture = sub.add_parser("capture", help="Read GDS/OAS to canonical JSON")
    capture.add_argument("input")
    capture.add_argument("output")
    capture.add_argument("--top")
    commit = sub.add_parser("commit", help="Append stream/JSON state to existing history")
    commit.add_argument("history")
    commit.add_argument("input")
    commit.add_argument("--top")
    commit.add_argument("-m", "--message", required=True)
    for name in ["log", "replay", "restore"]:
        parser = sub.add_parser(name)
        parser.add_argument("history")
        if name != "log":
            parser.add_argument("output")
            parser.add_argument("--at", help="Full reachable commit SHA256; defaults to HEAD")
    review = sub.add_parser("review", help="Create review.oas, layers, JSON and PNG in NEW directory")
    review.add_argument("output")
    source = review.add_mutually_exclusive_group(required=True)
    source.add_argument("--history")
    source.add_argument("--before", help="GDS/OAS/JSON or EMPTY; requires --after")
    review.add_argument("--after")
    review.add_argument("--before-top")
    review.add_argument("--after-top")
    review.add_argument("--at")
    review.add_argument("--style")
    review.add_argument("--exact-only", action="store_true")
    review.add_argument("--limit", type=int, default=250000)
    args = p.parse_args(argv)
    try:
        if args.command == "init":
            History(args.history).init()
            print("Initialized " + str(Path(args.history).resolve()))
        elif args.command == "capture":
            _new_json(args.output, read_layout(args.input, args.top))
            print(str(Path(args.output).resolve()))
        elif args.command == "commit":
            history = History(args.history)
            head = read_json(history.path / "HEAD")  # Read BEFORE capture for writer-race protection.
            snapshot = load_snapshot(args.input, args.top)
            if snapshot == empty_snapshot():
                raise ValueError("Commit requires a KLayout snapshot, not EMPTY")
            value = history.commit(snapshot, args.message, expected_head=head)
            print(value["id"] if value else "No changes")
        elif args.command == "log":
            history = History(args.history)
            history.replay()  # Verify hashes/preconditions before showing a trusted log.
            for c in reversed(history.chain()):
                print(c["id"] + " " + c["message"])
        elif args.command in {"replay", "restore"}:
            history = History(args.history)
            if args.at and not any(c["id"] == args.at for c in history.chain()):
                raise ValueError("Revision is not reachable from HEAD")
            snapshot = history.replay(args.at)
            if args.command == "replay":
                _new_json(args.output, snapshot)
            else:
                write_layout(snapshot, args.output)
            print(str(Path(args.output).resolve()))
        elif args.command == "review":
            if args.history:
                if args.after or args.before_top or args.after_top:
                    raise ValueError("--after and top options cannot be combined with --history")
                history = History(args.history)
                chain = history.chain()
                selected = next((c for c in chain if c["id"] == args.at), None) if args.at else (chain[-1] if chain else None)
                if selected is None:
                    raise ValueError("History empty or selected revision not reachable from HEAD")
                after = history.replay(selected["id"])
                before = history.replay(selected["parent"]) if selected["parent"] else empty_snapshot()
            else:
                if not args.after or args.at:
                    raise ValueError("--before requires --after; --at requires --history")
                before = load_snapshot(args.before, args.before_top)
                after = load_snapshot(args.after, args.after_top)
            style = load_style(args.style)
            layout, cell, report = export_review(before, after, args.output, style=style,
                                                  pair_changes=not args.exact_only, limit=args.limit)
            render_image(layout, cell, report, Path(args.output) / "review.png", style=style)
            print(str(Path(args.output).resolve()))
            print(review_counts(report))
    except (ValueError, RuntimeError, OSError) as exc:
        p.exit(2, f"layout-diff: {exc}\n")


if __name__ == "__main__":
    main()
