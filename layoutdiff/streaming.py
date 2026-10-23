"""Golden-reference bounded-memory kernels over validated canonical wire files.

Wire is a disposable cache: hex(UTF-8 object key), TAB, canonical JSON record, LF.
Hex preserves Unicode key order and makes keys unambiguous without parsing JSON.
It is never committed. Storage validation must precede creation of this cache.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import os


def wire_row(key, record_bytes):
    return key.encode("utf-8").hex().encode("ascii") + b"\t" + record_bytes + b"\n"


def read_wire(stream):
    previous = b""
    for line in stream:
        key, sep, record = line.rstrip(b"\n").partition(b"\t")
        if not sep or not line.endswith(b"\n") or key <= previous:
            raise ValueError("Invalid or unsorted canonical wire stream")
        previous = key
        yield key, record


def operation(key, before, after):
    name = json.dumps(bytes.fromhex(key.decode()).decode("utf-8"), ensure_ascii=True).encode()
    return b'{"after":' + (after or b"null") + b',"before":' + (before or b"null") + b',"key":' + name + b'}\n'


def merge_python(before, after, output):
    """Exact merge join, O(input bytes), O(maximum record size) memory."""
    with open(before, "rb") as a, open(after, "rb") as b, open(output, "wb") as out:
        left, right = read_wire(a), read_wire(b)
        x, y = next(left, None), next(right, None)
        while x is not None or y is not None:
            if y is None or (x is not None and x[0] < y[0]):
                out.write(operation(x[0], x[1], None)); x = next(left, None)
            elif x is None or y[0] < x[0]:
                out.write(operation(y[0], None, y[1])); y = next(right, None)
            else:
                if x[1] != y[1]:
                    out.write(operation(x[0], x[1], y[1]))
                x, y = next(left, None), next(right, None)


def file_digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def patch_rows(stream):
    previous = b""
    for line in stream:
        parts = line.rstrip(b"\n").split(b"\t")
        if len(parts) != 3 or not line.endswith(b"\n") or parts[0] <= previous:
            raise ValueError("Invalid or unsorted wire patch")
        previous = parts[0]
        yield parts


def apply_python(source, patch, output):
    with open(source, "rb") as src, open(patch, "rb") as delta, open(output, "wb") as out:
        rows, ops = read_wire(src), patch_rows(delta)
        row, op = next(rows, None), next(ops, None)
        while row is not None or op is not None:
            if op is None or row is not None and row[0] < op[0]:
                out.write(row[0] + b"\t" + row[1] + b"\n"); row = next(rows, None)
            else:
                present = row is not None and row[0] == op[0]
                if (row[1] if present else b"null") != op[1]:
                    raise ValueError("Object precondition mismatch")
                if op[2] != b"null":
                    out.write(op[0] + b"\t" + op[2] + b"\n")
                if present:
                    row = next(rows, None)
                op = next(ops, None)


def run_kernel(command, first, second, output, *, backend="auto", count=0):
    from .acceleration import execute
    output = Path(output)
    if output.resolve() in {Path(first).resolve(), Path(second).resolve()}:
        raise ValueError("Output must differ from inputs")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Do not publish partial native or reference output after failure.
    with tempfile.TemporaryDirectory(prefix="ald_kernel_", dir=output.parent) as temp:
        staged = Path(temp) / "result"
        engine = execute(command, first, second, staged, backend=backend, count=count)
        if engine != "native":
            (merge_python if command == "diff" else apply_python)(first, second, staged)
        os.replace(staged, output)
    return engine


def merge(before, after, output, *, backend="auto", count=0):
    return run_kernel("diff", before, after, output, backend=backend, count=count)


def apply(source, patch, output, *, backend="auto", count=0):
    return run_kernel("apply", source, patch, output, backend=backend, count=count)
