"""Isolated, synthetic v1 measurements; does not create OA layouts or a new format."""
import argparse
import copy
import difflib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

from layoutdiff.core import canonicalize, diff
from layoutdiff.gitcommit import git, json_bytes, prepare
from layoutdiff.gittools import textconv
from layoutdiff.gitstore import snapshot_path
from layoutdiff.browser import HistoryBrowser

IDENTITY = ["BENCH", "synthetic", "layout"]


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def records(n, template):
    kinds = {}
    for r in template["objects"].values():
        kinds.setdefault(r["kind"], r)
        if r["kind"] == "inst" and r.get("pcell"):
            kinds["pcell"] = r
    result = [copy.deepcopy(kinds["cell"])]
    for i in range(n):
        kind = "rect" if i % 10 < 6 else "path" if i % 10 == 6 else "stdVia" if i % 10 < 9 else "pcell"
        record = copy.deepcopy(kinds.get(kind, kinds["inst"]))
        record["props"] = [["tag", "int", i]] if i % 10 == 0 else []
        record["net"] = None if "net" in record else record.get("net")
        record["group"] = None
        if "pin" in record:
            record["pin"] = None
        if record["kind"] == "inst":
            record["name"] = f"I{i:07d}"
            record["xy"] = [i * 1000, 0]
        elif record["kind"] == "stdVia":
            record["origin"] = [i * 1000, 0]
        elif record["kind"] == "path":
            record["points"] = [[i * 1000, 0], [i * 1000 + 2000, 1000]]
        else:
            record["bBox"] = [[i * 1000, 0], [i * 1000 + 500, 1000]]
        result.append(record)
    return result


def measure(args):
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    os.nice(10)
    # Bound each independent Python process; failed/timeout stages are evidence.
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    data = {"size": args.size, "stage": args.stage}
    if args.stage == "generate":
        template = json.loads(Path(args.template).read_text())
        raw = records(args.size, template)
        start = time.perf_counter()
        before = canonicalize(raw)
        data["canonicalize_s"] = time.perf_counter() - start
        # The stride selects rectangles: 1% of all elements get property edits.
        for i in range(1, len(raw), 100):
            raw[i]["props"] = [["tag", "int", -i]]
        after = canonicalize(raw)
        start = time.perf_counter()
        encoded = json_bytes(before)
        data["serialize_s"] = time.perf_counter() - start
        data["pretty_bytes"] = len(encoded)
        data["minified_v1_bytes"] = len(json.dumps(before, sort_keys=True, separators=(",", ":")).encode())
        data["mean_fields"] = sum(len(r) for r in before["objects"].values()) / len(before["objects"])
        data["record_count"] = len(before["objects"])
        (root / "before.json").write_bytes(encoded)
        (root / "after.json").write_bytes(json_bytes(after))
        repo = root / "repo"
        repo.mkdir(exist_ok=True)
        git(repo, "init")
        git(repo, "config", "user.name", "Scale Benchmark")
        git(repo, "config", "user.email", "scale@example.invalid")
        path = repo / snapshot_path(IDENTITY)
        path.parent.mkdir(parents=True, exist_ok=True)
        for step in range(3):
            before["objects"]["cell:"]["props"] = [["step", "int", step]]
            path.write_bytes(json_bytes(before))
            git(repo, "add", "--", snapshot_path(IDENTITY))
            git(repo, "commit", "-m", f"Benchmark {step}")
        data["git_loose_bytes"] = sum(p.stat().st_size for p in (repo / ".git/objects").rglob("*") if p.is_file())
        start = time.perf_counter()
        git(repo, "gc", "--quiet")
        data["git_gc_s"] = time.perf_counter() - start
        data["git_packed_bytes"] = sum(p.stat().st_size for p in (repo / ".git/objects").rglob("*") if p.is_file())
    else:
        start = time.perf_counter()
        if args.stage == "parse":
            state = json.loads((root / "before.json").read_bytes())
            data["objects"] = len(state["objects"])
        elif args.stage == "history":
            model = HistoryBrowser(None, IDENTITY, root / "repo")
            data["revisions"] = len(model.commits)
        elif args.stage == "prepare":
            after = json.loads((root / "after.json").read_bytes())
            start = time.perf_counter()
            preview = prepare(root / "repo", IDENTITY, after)
            data["operations"] = preview["operations"]
        else:
            before = json.loads((root / "before.json").read_bytes())
            after = json.loads((root / "after.json").read_bytes())
            start = time.perf_counter()
            if args.stage == "diff":
                result = diff(before, after)
                data["operations"] = len(result["operations"])
            else:
                text = "".join(difflib.unified_diff(textconv(before).splitlines(True), textconv(after).splitlines(True)))
                data["patch_bytes"] = len(text.encode())
        data["elapsed_s"] = time.perf_counter() - start
    data["peak_rss_mib"] = rss()
    print(json.dumps(data), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--stage")
    p.add_argument("--size", type=int)
    args = p.parse_args()
    if args.stage:
        measure(args)
        return
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    report = {"python": sys.version, "platform": platform.platform(), "cpu": platform.processor(),
              "cpu_count": os.cpu_count(), "memory_gib": os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3,
              "mode": "synthetic mixed records, warm filesystem, 1% attribute edits; one run per stage", "results": []}
    for n in (1000, 10000, 100000):
        for stage in ("generate", "parse", "diff", "textdiff", "prepare", "history"):
            command = [sys.executable, __file__, "--root", str(root / str(n)), "--template", args.template,
                       "--size", str(n), "--stage", stage]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=180)
                row = json.loads(result.stdout) if result.returncode == 0 else {"size": n, "stage": stage, "error": result.stderr[-1500:]}
            except subprocess.TimeoutExpired:
                row = {"size": n, "stage": stage, "timeout_s": 180}
            report["results"].append(row)
            (root / "report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
