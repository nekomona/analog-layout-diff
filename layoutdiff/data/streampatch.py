"""Checked forward/reverse replay of a streamed patch, without a full object map."""
import json
from pathlib import Path
import tempfile
import shutil
from layoutdiff.data.core import encoded
from layoutdiff.data.storage import Snapshot, write_records, strict_json, json_lines
import layoutdiff.data.storage as storage
from layoutdiff.data.streaming import merge, file_digest, read_wire, apply as apply_kernel

PATCH_SCHEMA = "analog-layout-diff/2/patch"


def create(before, after, destination, *, parent=None, backend="auto"):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ald_patch_", dir=destination.parent) as temp:
        stage = Path(temp) / "patch"
        stage.mkdir()
        engine = merge(before.wire(), after.wire(), stage / "operations.jsonl", backend=backend, count=max(before.count, after.count))
        manifest = {"schema": PATCH_SCHEMA, "parent": parent, "base": before.digest,
                    "result": after.digest, "operationsSha256": file_digest(stage / "operations.jsonl")}
        (stage / "manifest.json").write_bytes(encoded(manifest) + b"\n")
        stage.rename(destination)
    return {**manifest, "backend": engine}


def apply(source, patch, destination, *, parent=None, reverse=False, backend="auto"):
    patch, destination = Path(patch), Path(destination)
    manifest = strict_json((patch / "manifest.json").read_bytes())
    if set(manifest) != {"schema", "parent", "base", "result", "operationsSha256"} or manifest["schema"] != PATCH_SCHEMA:
        raise ValueError("Invalid streamed patch manifest")
    if manifest["parent"] != parent:
        raise ValueError("Parent mismatch")
    if file_digest(patch / "operations.jsonl") != manifest["operationsSha256"]:
        raise ValueError("Corrupt patch operations")
    source.wire()
    expected_source, expected_target = (manifest["result"], manifest["base"]) if reverse else (manifest["base"], manifest["result"])
    if source.digest != expected_source:
        raise ValueError("Base snapshot mismatch")
    old, new = ("after", "before") if reverse else ("before", "after")
    def operations():
        previous = b""
        # A replacement contains two maximum-sized records plus its key.
        for op in json_lines(patch / "operations.jsonl", max_line=3 * storage.MAX_LINE):
                if set(op) != {"key", "before", "after"} or op["before"] is None and op["after"] is None:
                    raise ValueError("Invalid operation")
                if any(value is not None and not isinstance(value, dict) for value in (op["before"], op["after"])):
                    raise ValueError("Operation records must be objects")
                key = op["key"].encode("utf-8").hex().encode()
                if key <= previous:
                    raise ValueError("Duplicate or unsorted operation")
                previous = key
                yield key, op
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ald_apply_", dir=destination.parent) as temp:
        temp = Path(temp)
        wire_patch, result = temp / "patch.wire", temp / "result.wire"
        with wire_patch.open("wb") as stream:
            for key, op in operations():
                stream.write(key + b"\t" + encoded(op[old]) + b"\t" + encoded(op[new]) + b"\n")
        engine = apply_kernel(source.wire(), wire_patch, result, backend=backend, count=source.count)
        with result.open("rb") as stream:
            value = write_records((strict_json(raw) for _, raw in read_wire(stream)), temp / "layout")
        if value.digest != expected_target or file_digest(value.wire()) != file_digest(result):
            raise ValueError("Result digest mismatch")
        value.close()
        value.path.rename(destination)
    value = Snapshot(destination)
    value.backend = engine
    return value
