"""Read-only remote helper: hash saved OA files, returning metadata only.

Invoked as a script on the filesystem host; uses only the Python standard library.
Lock files and transient files are intentionally excluded. A concurrent write
invalidates the hint instead of presenting a mixed read as a stable fingerprint.
"""
import hashlib
import json
import sys
from pathlib import Path


def fingerprint(directory):
    try:
        files = sorted(Path(directory).glob("*.oa"))
        if not files:
            return {"status": "unavailable"}
        before = [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files]
        hashes = []
        for p in files:
            h = hashlib.sha256()
            with p.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            hashes.append([p.name, h.hexdigest()])
        after_files = sorted(Path(directory).glob("*.oa"))
        after = [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in after_files]
        if before != after:
            return {"status": "unstable"}
        payload = json.dumps(hashes, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return {"status": "ok", "method": "saved-oa-sha256-v1",
                "sha256": hashlib.sha256(payload).hexdigest()}
    except (OSError, TypeError, ValueError):
        return {"status": "unavailable"}


if __name__ == "__main__":
    paths = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps({p: fingerprint(p) for p in paths}, sort_keys=True))
