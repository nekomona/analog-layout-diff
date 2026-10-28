"""Independent Linux processes; same synthetic snapshots as the recorded v1 baseline."""
import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
from layoutdiff.data.storage import Snapshot, from_snapshot, strict_json, write_records
from layoutdiff.comparison.changeindex import ChangeIndex
from layoutdiff.git.commit import git, prepare_v2, commit
from layoutdiff.git.store import snapshot_directory
from layoutdiff.ui.browser import HistoryBrowser
from layoutdiff.data.streaming import read_wire, merge

IDENTITY = ["BENCH", "synthetic", "layout"]


def stage(root, size, name, backend):
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    folder = root / str(size)
    a, b = Snapshot(folder / "before"), Snapshot(folder / "after")
    start = time.perf_counter()
    result = {"size": size, "stage": name, "requested_backend": backend}
    if name == "validate":
        a.wire(); b.wire()
    elif name in {"diff_cold", "diff_warm"}:
        if name == "diff_warm":
            a.wire(); b.wire(); start = time.perf_counter()
        changes = ChangeIndex(a, b, backend=backend)
        result.update(operations=changes.raw_operations, backend=changes.backend, categories=changes.rows)
        page_start = time.perf_counter()
        changes.page(0, 0)
        result["page_s"] = time.perf_counter() - page_start
        changes.close()
    elif name == "kernel":
        a.wire(); b.wire(); start = time.perf_counter()
        result["backend"] = merge(a.wire(), b.wire(), folder / "kernel-ops.jsonl", backend=backend, count=size)
    elif name == "prepare":
        preview = prepare_v2(folder / "repo", IDENTITY, b, backend=backend)
        result.update(operations=preview["operations"], backend=preview["changes"].backend)
        preview.close()
    elif name == "history":
        model = HistoryBrowser(None, IDENTITY, folder / "repo")
        rows = model.rows(lazy=True)
        result.update(revisions=len(rows), decoded_snapshots=len(model.store._states))
        model.close()
    elif name == "encode_stream":
        wire = a.wire()
        start = time.perf_counter()
        import tempfile
        with tempfile.TemporaryDirectory() as temp, wire.open("rb") as stream:
            value = write_records((strict_json(raw) for _, raw in read_wire(stream)), Path(temp) / "layout")
            assert value.digest == a.digest
    # /proc VmHWM starts at exec; ru_maxrss can retain the fork parent's pre-exec peak.
    hwm = next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines() if line.startswith("VmHWM:"))
    result.update(elapsed_s=time.perf_counter() - start, peak_rss_mib=int(hwm) / 1024)
    print(json.dumps(result), flush=True)


def build(root, baseline):
    for size in (1000, 10000, 100000):
        folder = root / str(size)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("before", "after"):
            if not (folder / name).exists():
                value = strict_json((baseline / str(size) / (name + ".json")).read_bytes())
                store = from_snapshot(value, folder / name)
                assert store.materialize() == value
                del value
        repo = folder / "repo"
        if repo.exists():
            continue
        repo.mkdir()
        git(repo, "init"); git(repo, "config", "user.name", "Scale Benchmark")
        git(repo, "config", "user.email", "scale@example.invalid")
        trees = []
        for name in ("before", "after"):
            preview = prepare_v2(repo, IDENTITY, Snapshot(folder / name), backend="python")
            commit(preview, "Benchmark " + name)
            preview.close()
            trees.append(git(repo, "rev-parse", "HEAD^{tree}").stdout.decode().strip())
        parent = None
        for i in range(100):
            tree = trees[(i + 1) % 2]  # Final revision is before, for preparation.
            parent = git(repo, "commit-tree", tree, *(["-p", parent] if parent else []),
                "-m", "Benchmark history " + str(i)).stdout.decode().strip()
        git(repo, "update-ref", "HEAD", parent)
        git(repo, "read-tree", "--reset", "-u", parent)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True); p.add_argument("--baseline")
    p.add_argument("--stage"); p.add_argument("--size", type=int)
    p.add_argument("--backend", default="python"); p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--built", action="store_true")
    args = p.parse_args()
    root = Path(args.root)
    if args.stage:
        stage(root, args.size, args.stage, args.backend); return
    if not args.built:
        build(root, Path(args.baseline))
        os.execv(sys.executable, [sys.executable, *sys.argv, "--built"])
    report = {"backend": args.backend, "repeat": args.repeat, "filesystem": "warm; new process/cold codec cache each stage", "sizes": {}, "runs": []}
    for size in (1000, 10000, 100000):
        report["sizes"][size] = sum(p.stat().st_size for p in (root / str(size) / "before").iterdir())
        for name in ("validate", "diff_cold", "diff_warm", "kernel", "prepare", "history", "encode_stream"):
            for run in range(args.repeat):
                result = subprocess.run([sys.executable, __file__, "--root", str(root), "--size", str(size),
                    "--stage", name, "--backend", args.backend], capture_output=True, text=True, timeout=180)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                row = json.loads(result.stdout); row["run"] = run
                report["runs"].append(row)
                (root / (args.backend + ".json")).write_text(json.dumps(report, indent=2))
                print(json.dumps(row), flush=True)


if __name__ == "__main__": main()
