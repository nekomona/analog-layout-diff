"""Linux stress checks in fresh processes; reads existing benchmark inputs only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from layoutdiff.storage import Snapshot, write_records
from layoutdiff.changeindex import ChangeIndex
from layoutdiff.streaming import merge, file_digest
from layoutdiff.streampatch import create, apply


def check(case, source):
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ald_stress_") as temp:
        root = Path(temp)
        empty = write_records([], root / "empty")
        if case == "large-record":
            # A long route checks per-record expansion and complete detail export.
            large = write_records([{"kind": "path", "layerName": "MET1", "purpose": "drawing",
                "width": 5, "points": [[i, i % 7] for i in range(100000)], "props": []}], root / "large")
        else:
            large = Snapshot(source)
        a, b = (large, empty) if case == "all-delete" else (empty, large)
        changes = ChangeIndex(a, b, backend="auto")
        assert changes.raw_operations == large.count
        assert sum(sum(row[1:]) for row in changes.rows) == large.count
        merge(a.wire(), b.wire(), root / "python-ops", backend="python", count=large.count)
        assert file_digest(changes.operations_path) == file_digest(root / "python-ops")
        export_hash, export_bytes = hashlib.sha256(), 0
        for text in changes.full():
            raw = text.encode(); export_bytes += len(raw); export_hash.update(raw)
        page_start = time.perf_counter()
        for index, row in enumerate(changes.rows):
            page = changes.page(index, (sum(row[1:])-1) // 10)
            assert page["count"] == sum(row[1:])
        pages_s = time.perf_counter() - page_start
        create(a, b, root / "patch", backend="auto")
        rebuilt = apply(a, root / "patch", root / "rebuilt", backend="auto")
        assert rebuilt.digest == b.digest
        reverse = apply(b, root / "patch", root / "reverse", backend="auto", reverse=True)
        assert reverse.digest == a.digest
        result = {"case": case, "records": large.count, "backend": changes.backend,
            "exact_python_operations": True, "forward_reverse_equal": True,
            "full_export_bytes": export_bytes, "full_export_sha256": export_hash.hexdigest(),
            "last_category_pages_s": pages_s, "elapsed_s": time.perf_counter() - start,
            "peak_python_rss_mib": int(next(line.split()[1] for line in
                Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:'))) / 1024}
        changes.close(); empty.close(); large.close(); rebuilt.close(); reverse.close()
        return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("source"); p.add_argument("--case")
    args = p.parse_args()
    if args.case:
        print(json.dumps(check(args.case, args.source)))
    else:
        results = []
        for case in ("all-add", "all-delete", "large-record"):
            r = subprocess.run([sys.executable, __file__, args.source, "--case", case],
                               capture_output=True, text=True, timeout=240)
            if r.returncode:
                raise RuntimeError(r.stderr)
            results.append(json.loads(r.stdout))
        print(json.dumps({"memory": "Python worker VmHWM after exec; excludes native child", "cases": results}, indent=2))
