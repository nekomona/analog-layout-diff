"""Optional native kernels; Python remains the golden reference and fallback."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import warnings

THRESHOLD = 50000
PROTOCOL = "layoutdiff-native/1 wire/1 diff apply"
_verified = {}
_warned = set()
_last = {"selected": "python", "reason": "not requested"}


def executable():
    configured = os.environ.get("ALD_NATIVE_TOOL")
    return Path(configured) if configured else Path(sys.prefix) / ("Scripts/layoutdiff-native.exe" if os.name == "nt" else "bin/layoutdiff-native")


def verify(path):
    stat = path.stat()
    stamp = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if stamp in _verified:
        return
    report = json.loads(path.with_suffix(path.suffix + ".json").read_text())
    expected = Path(__file__).with_name("native_source.sha256").read_text().strip()
    if report["source_sha256"] != expected or report["binary_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError("Native source/binary provenance mismatch; rebuild the accelerator")
    if subprocess.check_output([str(path), "--version"], text=True, timeout=5).strip() != PROTOCOL:
        raise ValueError("Unsupported native protocol")
    from .streaming import wire_row, merge_python, apply_python
    from .core import encoded
    before = {"inst:ASCII": {"kind": "inst", "name": "ASCII", "v": -0.0},
              "inst:汉😀\t\"": {"kind": "inst", "name": "汉😀\t\"", "v": 10**30},
              "rect:old": {"kind": "rect", "value": True}}
    after = {"inst:ASCII": {"kind": "inst", "name": "ASCII", "v": 0},
             "inst:汉😀\t\"": before["inst:汉😀\t\""], "rect:new": {"kind": "rect", "v": [None, 1e-7]}}
    with tempfile.TemporaryDirectory(prefix="ald_native_check_") as temp:
        root = Path(temp)
        for name, records in (("before", before), ("after", after)):
            (root / name).write_bytes(b"".join(wire_row(k, encoded(v)) for k, v in sorted(records.items())))
        merge_python(root / "before", root / "after", root / "reference")
        subprocess.run([str(path), "diff", str(root / "before"), str(root / "after"), str(root / "actual")], check=True, capture_output=True, timeout=5)
        if (root / "actual").read_bytes() != (root / "reference").read_bytes():
            raise ValueError("Native diff self-test differs from Python reference")
        patch = []
        for line in (root / "reference").read_bytes().splitlines():
            op = json.loads(line)
            patch.append(op["key"].encode().hex().encode() + b"\t" + encoded(op["before"]) + b"\t" + encoded(op["after"]) + b"\n")
        (root / "patch").write_bytes(b"".join(patch))
        apply_python(root / "before", root / "patch", root / "reference")
        subprocess.run([str(path), "apply", str(root / "before"), str(root / "patch"), str(root / "actual")], check=True, capture_output=True, timeout=5)
        if (root / "actual").read_bytes() != (root / "reference").read_bytes():
            raise ValueError("Native apply self-test differs from Python reference")
    _verified[stamp] = True


def execute(command, first, second, output, *, backend, count):
    mode = os.environ.get("ALD_BACKEND", "auto") if backend == "auto" else backend
    if mode not in {"auto", "python", "native"}:
        raise ValueError("Backend must be auto, python or native")
    path = executable()
    large = count >= THRESHOLD or max(Path(first).stat().st_size, Path(second).stat().st_size) >= 32 * 1024**2
    if mode == "python" or mode == "auto" and not large:
        _last.update(selected="python", reason="forced" if mode == "python" else "below size threshold")
        return "python"
    try:
        verify(path)
        result = subprocess.run([str(path), command, str(first), str(second), str(output)], capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[:1000])
        _last.update(selected="native", reason="forced" if mode == "native" else "large design")
        return "native"
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        _last.update(selected="python", reason=str(exc))
        if mode == "native":
            raise RuntimeError("Native backend unavailable/failed: " + str(exc)) from exc
        if path.exists() and str(exc) not in _warned:
            warnings.warn("Native layout backend failed; using Python: " + str(exc), RuntimeWarning)
            _warned.add(str(exc))
        return "python"


def info():
    path = executable()
    try:
        verify(path)
        availability = "verified"
    except Exception as exc:
        availability = str(exc)
    return {"mode": os.environ.get("ALD_BACKEND", "auto"), "tool": str(path), "availability": availability,
            "threshold_objects": THRESHOLD, "threshold_wire_bytes": 32 * 1024**2, "last": dict(_last)}
