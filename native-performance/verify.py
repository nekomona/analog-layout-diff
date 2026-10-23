"""Differential tests against Python; invoke after installing the Python package."""
import copy
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time
from layoutdiff.core import canonicalize, diff, encoded
from layoutdiff.storage import from_snapshot
from layoutdiff.changeindex import ChangeIndex
from layoutdiff.streampatch import create, apply
from layoutdiff.streaming import merge, wire_row, merge_python, apply_python
from layoutdiff.acceleration import info, executable

start = time.perf_counter()
assert info()["availability"] == "verified", info()
rng = random.Random(99141)
with tempfile.TemporaryDirectory(prefix="ald_native_regression_") as temp:
    root = Path(temp)
    for seed in range(40):
        records = [{"kind": "cell", "name": "", "v": seed}]
        records += [{"kind": "inst", "name": name, "libName": "L", "cellName": "C", "props": [["v", "ILList", [1e-7, -0.0, 1e20, 2**80, True, None, "汉😀"]]]}
                    for name in ["A", 'quote"back\\tab\t', "汉😀", "\x00\x7f"]]
        records += [{"kind": "rect", "layerName": "M1", "bBox": [[i,0],[i+1,1]], "props": []} for i in range(rng.randrange(5, 150))]
        before = canonicalize(records)
        changed = copy.deepcopy(records)
        for record in rng.sample(changed, min(10, len(changed))): record["extra"] = rng.choice([None, 0, False, 1.0, [], "x"])
        changed = changed[1:] + changed[-3:]
        after = canonicalize(changed)
        a, b = from_snapshot(before, root / f"a{seed}"), from_snapshot(after, root / f"b{seed}")
        py, native = ChangeIndex(a, b, backend="python"), ChangeIndex(a, b, backend="native")
        assert py.operations_path.read_bytes() == native.operations_path.read_bytes()
        assert list(native.operations()) == diff(before, after)["operations"]
        assert native.rows == py.rows and "".join(native.full()) == "".join(py.full())
        create(a, b, root / f"patch{seed}", parent="parent", backend="native")
        assert encoded(apply(a, root / f"patch{seed}", root / f"forward{seed}", parent="parent", backend="native").materialize()) == encoded(after)
        assert encoded(apply(b, root / f"patch{seed}", root / f"reverse{seed}", parent="parent", backend="native", reverse=True).materialize()) == encoded(before)
        py.close(); native.close(); a.close(); b.close()
    # Large automatic selection and an all-add stream, without native schema parsing.
    (root / "empty").write_bytes(b"")
    with (root / "large").open("wb") as stream:
        for i in range(100000):
            key = f"inst:I{i:06d}"
            stream.write(wire_row(key, encoded({"kind": "inst", "name": key[5:], "value": i})))
    assert merge(root / "empty", root / "large", root / "large-native", count=100000) == "native"
    merge_python(root / "empty", root / "large", root / "large-python")
    assert (root / "large-native").read_bytes() == (root / "large-python").read_bytes()
    saved = os.environ.get("ALD_NATIVE_TOOL")
    os.environ["ALD_NATIVE_TOOL"] = str(root / "not-installed")
    assert merge(root / "empty", root / "large", root / "fallback", count=100000) == "python"
    assert (root / "fallback").read_bytes() == (root / "large-python").read_bytes()
    try:
        merge(root / "empty", root / "large", root / "forced", backend="native")
        raise AssertionError("Forced native must fail when unavailable")
    except RuntimeError: pass
    if saved is None: del os.environ["ALD_NATIVE_TOOL"]
    else: os.environ["ALD_NATIVE_TOOL"] = saved
    (root / "bad").write_bytes(b"ff\t{}\n00\t{}\n")
    (root / "protected").write_text("existing output")
    try:
        merge(root / "bad", root / "empty", root / "protected", backend="native")
        raise AssertionError("Unsorted input accepted")
    except RuntimeError: pass
    assert (root / "protected").read_text() == "existing output"
print(json.dumps({"random_pairs": 40, "forward_reverse_checks": 80, "exact_python_parity": True,
    "unicode_numbers_and_duplicates": True, "automatic_100k_selection": "native", "fallback_equal": True,
    "forced_missing_rejected": True, "failed_output_not_published": True, "seconds": time.perf_counter() - start,
    "backend": info()}, indent=2))
