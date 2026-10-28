import json
from pathlib import Path
import subprocess
import pytest
import layoutdiff.data.acceleration as acc
from layoutdiff.data.streaming import merge, wire_row
from layoutdiff.data.core import encoded


def inputs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"")
    b.write_bytes(wire_row("inst:I", encoded({"kind": "inst", "name": "I"})))
    return a, b


def test_missing_optional_backend_and_python_override(tmp_path, monkeypatch):
    a, b = inputs(tmp_path)
    monkeypatch.setenv("ALD_NATIVE_TOOL", str(tmp_path / "missing"))
    assert merge(a, b, tmp_path / "out", count=100000) == "python"
    assert json.loads((tmp_path / "out").read_text())["key"] == "inst:I"
    with pytest.raises(RuntimeError, match="Native backend"):
        merge(a, b, tmp_path / "out", backend="native")
    monkeypatch.setenv("ALD_BACKEND", "python")
    assert merge(a, b, tmp_path / "out", count=100000) == "python"


def test_failed_accelerator_discards_partial_output_before_fallback(tmp_path, monkeypatch):
    a, b = inputs(tmp_path)
    fake = tmp_path / "native"
    fake.write_bytes(b"test-only placeholder")
    monkeypatch.setenv("ALD_NATIVE_TOOL", str(fake))
    monkeypatch.setattr(acc, "verify", lambda path: None)
    def fail(command, **kwargs):
        Path(command[-1]).write_text("partial invalid native output")
        return subprocess.CompletedProcess(command, 2, b"", b"injected failure")
    monkeypatch.setattr(acc.subprocess, "run", fail)
    with pytest.warns(RuntimeWarning, match="using Python"):
        assert merge(a, b, tmp_path / "out", count=100000) == "python"
    assert json.loads((tmp_path / "out").read_text())["after"] == {"kind": "inst", "name": "I"}


def test_reject_input_output_alias_without_modifying_input(tmp_path):
    a, b = inputs(tmp_path)
    original = b.read_bytes()
    with pytest.raises(ValueError, match="differ"):
        merge(a, b, b, backend="python")
    assert b.read_bytes() == original


def test_small_inputs_do_not_launch_native(tmp_path, monkeypatch):
    a, b = inputs(tmp_path)
    monkeypatch.delenv("ALD_BACKEND", raising=False)
    def forbidden(path): raise AssertionError("Small input should use Python")
    monkeypatch.setattr(acc, "verify", forbidden)
    assert merge(a, b, tmp_path / "out") == "python"
