import argparse
import json
from collections import Counter
from pathlib import Path
from layoutdiff.data.core import diff, apply_diff, digest
from layoutdiff.data.history import History, read_json, atomic_json


def live_dependency_check(snapshot, report):
    from layoutdiff.eda.virtuoso.dependencies import emit_warnings
    try:
        from virtuoso_bridge import VirtuosoClient
        from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter
        adapter = VirtuosoAdapter(VirtuosoClient.from_env(), Path(report).parent / "artifacts")
        issues = adapter.check_dependencies(snapshot, emit=False)
    except Exception as exc:
        issues = [{"key": "hierarchy", "reason": "live dependency check unavailable: " + str(exc)}]
    emit_warnings(issues)
    atomic_json(report, issues)
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description="Single-parent Virtuoso layout snapshots and diffs")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backend-info", help="Show native accelerator verification and automatic selection policy")
    for command in ("encode-v2", "decode-v2"):
        p = sub.add_parser(command)
        p.add_argument("input"); p.add_argument("output")
    p = sub.add_parser("migrate-v2", help="Commit an exact v1-to-v2 migration without rewriting history")
    p.add_argument("repository"); p.add_argument("library"); p.add_argument("cell")
    p.add_argument("--view", default="layout"); p.add_argument("-m", "--message", default="Migrate layout snapshot to JSON Lines v2")
    p = sub.add_parser("diff-stream", help="Bounded-memory diff of two v2 directories")
    p.add_argument("before"); p.add_argument("after"); p.add_argument("output")
    p.add_argument("--parent"); p.add_argument("--backend", choices=("auto", "python", "native"), default="auto")
    p = sub.add_parser("apply-stream", help="Checked bounded-memory forward/reverse replay")
    p.add_argument("snapshot"); p.add_argument("patch"); p.add_argument("output")
    p.add_argument("--parent"); p.add_argument("--reverse", action="store_true")
    p.add_argument("--backend", choices=("auto", "python", "native"), default="auto")
    sub.add_parser("gui-serve", help="Ask the installed Virtuoso plugin to launch its host-local worker")
    sub.add_parser("gui-stop", help="Ask the installed Virtuoso plugin to stop its owned runtime")
    sub.add_parser("gui-clean", help="Queue closed temporary-review cleanup in the Virtuoso worker")
    p = sub.add_parser("init", help="Create an empty append-only history")
    p.add_argument("history")
    p = sub.add_parser("capture", help="Read a cellview without modifying or saving it")
    p.add_argument("library"); p.add_argument("cell"); p.add_argument("output")
    p.add_argument("--view", default="layout")
    p.add_argument("--format", choices=("v1", "v2"), default="v1")
    p = sub.add_parser("diff", help="Compare two snapshots")
    p.add_argument("before"); p.add_argument("after"); p.add_argument("output")
    p = sub.add_parser("apply", help="Check and apply an operation file offline")
    p.add_argument("snapshot"); p.add_argument("commit"); p.add_argument("output")
    p.add_argument("--parent", default=None)
    p.add_argument("--reverse", action="store_true")
    p = sub.add_parser("commit", help="Append a captured JSON snapshot")
    p.add_argument("history"); p.add_argument("snapshot"); p.add_argument("-m", "--message", default="")
    p = sub.add_parser("record", help="Capture a live view and append it to history")
    p.add_argument("history"); p.add_argument("library"); p.add_argument("cell")
    p.add_argument("--view", default="layout"); p.add_argument("-m", "--message", default="")
    for command in ("log", "replay"):
        p = sub.add_parser(command)
        p.add_argument("history")
        if command == "replay":
            p.add_argument("output"); p.add_argument("--at", default=None, help="Full commit ID")
            p.add_argument("--check-dependencies", action="store_true", help="Warn about live master drift; does not block replay")
    p = sub.add_parser("check-dependencies", help="Compare recorded master fingerprints to the current Virtuoso libraries")
    p.add_argument("snapshot")
    p.add_argument("--report", default="dependency-warnings.json")
    p = sub.add_parser("git-setup", help="Configure a repository-local semantic diff driver for *.layout.json")
    p.add_argument("repository", help="Explicit Git repository root")
    p = sub.add_parser("git-extract", help="Export a canonical snapshot from a Git revision for restore")
    p.add_argument("repository"); p.add_argument("revision"); p.add_argument("path"); p.add_argument("output")
    p = sub.add_parser("restore", help="Reconstruct into a fresh cell in the test library")
    p.add_argument("snapshot"); p.add_argument("cell")
    p.add_argument("--library", default="LAYOUT_DIFF_TEST")
    p.add_argument("--allow-library", default="LAYOUT_DIFF_TEST", help="Explicit writable destination library")
    p = sub.add_parser("coverage", help="List reconstruction blockers and object counts")
    p.add_argument("snapshot")
    p = sub.add_parser("xor", help="Compare two exported GDS files, including text")
    p.add_argument("left"); p.add_argument("right")
    p.add_argument("--left-top"); p.add_argument("--right-top")
    args = parser.parse_args(argv)
    if args.command == "backend-info":
        from layoutdiff.data.acceleration import info
        print(json.dumps(info(), indent=2))
    elif args.command in {"encode-v2", "decode-v2"}:
        from layoutdiff.data.storage import from_snapshot, load
        if args.command == "encode-v2":
            print(from_snapshot(load(args.input), args.output).digest)
        else:
            atomic_json(args.output, load(args.input))
    elif args.command == "migrate-v2":
        from layoutdiff.git.store import GitSnapshots
        from layoutdiff.git.commit import prepare_v2, commit
        store = GitSnapshots(args.repository, [args.library, args.cell, args.view])
        try:
            value = store.open(store.head)
            if not value.count:
                raise ValueError("No existing layout snapshot to migrate")
            preview = prepare_v2(args.repository, store.identity, value)
            try:
                print(json.dumps(commit(preview, args.message) if preview["write_required"] else {"unchanged": True}))
            finally:
                preview.close()
        finally:
            store.close()
    elif args.command == "diff-stream":
        from layoutdiff.data.storage import Snapshot
        from layoutdiff.data.streampatch import create
        print(json.dumps(create(Snapshot(args.before), Snapshot(args.after), args.output, parent=args.parent, backend=args.backend)))
    elif args.command == "apply-stream":
        from layoutdiff.data.storage import Snapshot
        from layoutdiff.data.streampatch import apply
        print(apply(Snapshot(args.snapshot), args.patch, args.output, parent=args.parent, reverse=args.reverse, backend=args.backend).digest)
    elif args.command in {"gui-serve", "gui-stop", "gui-clean"}:
        from virtuoso_bridge import VirtuosoClient
        from layoutdiff.eda.virtuoso.adapter import checked
        client = VirtuosoClient.from_env()
        if checked(client.execute_skill("boundp('ALDRuntimeMenu)")) != "t":
            raise ValueError("Load the installed startup.il in Virtuoso CIW first; see docs/runtime/README.md")
        expression = {"gui-serve": "ALDRuntimeStart()", "gui-stop": "ALDRuntimeStop()",
                      "gui-clean": 'ALDGUIEnqueue(list("cleanup"))'}[args.command]
        checked(client.execute_skill(expression))
        print("Requested through Virtuoso; see CIW > Layout Diff > Runtime for status")
    elif args.command == "init":
        History(args.history).init()
        print("Initialized", args.history)
    elif args.command in {"capture", "record", "restore"}:
        from virtuoso_bridge import VirtuosoClient
        from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, coverage
        artifacts = Path(args.history) / "captures" if args.command == "record" else Path(getattr(args, "snapshot", getattr(args, "output", "."))).resolve().parent / "artifacts"
        adapter = VirtuosoAdapter(VirtuosoClient.from_env(), artifacts,
                                  writable_library=getattr(args, "allow_library", "LAYOUT_DIFF_TEST"))
        if args.command == "restore":
            from layoutdiff.data.storage import load
            snapshot = load(args.snapshot)
            actual = adapter.reconstruct(snapshot, args.library, args.cell)
            atomic_json(artifacts / "restored.layout.json", actual)
            print("Reconstructed; top-level content verified", args.library, args.cell, digest(actual))
            print("Dependency warnings:", len(adapter.last_dependency_warnings))
        else:
            if args.command == "capture" and args.format == "v2":
                import shutil
                value = adapter.capture_store(args.library, args.cell, args.view, temporary=True)
                try:
                    shutil.copytree(value.path, args.output)
                    print(json.dumps({"digest": value.digest, "objects": value.count, "format": "v2"}))
                finally:
                    value.dispose()
                return 0
            history = History(args.history) if args.command == "record" else None
            head = read_json(history.path / "HEAD") if history else None
            snapshot = adapter.capture(args.library, args.cell, args.view)
            issues = coverage(snapshot)
            if history:
                if issues:
                    atomic_json(artifacts / "incomplete.json", snapshot)
                    raise ValueError("Capture has unsupported data; history not updated:\n" + "\n".join(issues))
                result = history.commit(snapshot, args.message, expected_head=head)
                print(result["id"] if result else "No changes")
            else:
                atomic_json(args.output, snapshot)
                print(json.dumps({"digest": digest(snapshot), "objects": len(snapshot["objects"]), "coverage_issues": issues}, indent=2))
    elif args.command == "diff":
        result = diff(read_json(args.before), read_json(args.after))
        atomic_json(args.output, result)
        print(f"{len(result['operations'])} operations; {result['id']}")
    elif args.command == "apply":
        atomic_json(args.output, apply_diff(read_json(args.snapshot), read_json(args.commit), parent=args.parent, reverse=args.reverse))
    elif args.command == "commit":
        from layoutdiff.eda.virtuoso.adapter import coverage
        history = History(args.history)
        head = read_json(history.path / "HEAD")
        snapshot = read_json(args.snapshot)
        issues = coverage(snapshot)
        if issues:
            raise ValueError("Unsupported snapshot cannot enter reconstructable history:\n" + "\n".join(issues))
        result = history.commit(snapshot, args.message, expected_head=head)
        print(result["id"] if result else "No changes")
    elif args.command == "replay":
        result = History(args.history).replay(args.at)
        atomic_json(args.output, result)
        print(digest(result))
        if args.check_dependencies:
            live_dependency_check(result, Path(args.output).with_suffix(".warnings.json"))
    elif args.command == "check-dependencies":
        issues = live_dependency_check(read_json(args.snapshot), args.report)
        print(f"{len(issues)} dependency warnings (nonblocking)")
    elif args.command == "git-setup":
        from layoutdiff.git.tools import setup
        print(json.dumps(setup(args.repository), indent=2))
    elif args.command == "git-extract":
        from layoutdiff.git.tools import extract
        print(digest(extract(args.repository, args.revision, args.path, args.output)))
    elif args.command == "log":
        history = History(args.history)
        history.replay()  # Do not present an unverified chain as valid.
        for commit in history.chain():
            counts = Counter("add" if o["before"] is None else "delete" if o["after"] is None else "replace" for o in commit["operations"])
            print(commit["id"][:12], dict(counts), commit["message"])
    elif args.command == "coverage":
        from layoutdiff.eda.virtuoso.adapter import coverage
        snapshot = read_json(args.snapshot)
        print(json.dumps({"kinds": dict(Counter(x["kind"] for x in snapshot["objects"].values())), "issues": coverage(snapshot)}, indent=2))
    elif args.command == "xor":
        from layoutdiff.eda.virtuoso.geometry import compare_gds
        result = compare_gds(args.left, args.right, left_top=args.left_top, right_top=args.right_top)
        print(json.dumps(result, indent=2))
        return 0 if result["equal"] else 1
    return 0
