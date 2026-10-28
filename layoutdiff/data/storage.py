"""Version 2 deterministic JSON Lines codec. Python is the semantic reference.

All spools/indexes are disposable SQLite files outside Git, with bounded caches.
No histories or identities are stored in them. core.py remains the v1 oracle.
"""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import copy

from layoutdiff.data.core import SCHEMA, encoded, digest, validate, empty_snapshot
from layoutdiff.data.streaming import file_digest, wire_row

FORMAT = "analog-layout-diff/2"
NAMED = {"cell", "net", "term", "inst", "mosaic", "figGroup", "dependency"}
# Explicit presence list preserves missing vs null/empty/false exactly.
DEFAULTS = {"props": [], "net": None, "pin": None, "group": None,
            "viewName": "layout", "orient": "R0", "physOnly": False}
FILES = ("manifest.json", "objects.jsonl", "definitions.jsonl")
MAX_LINE = 16 * 1024 * 1024


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON field: " + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("Nonfinite JSON number: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def json_lines(path, *, max_line=None):
    limit = MAX_LINE if max_line is None else max_line
    with open(path, "rb") as stream:
        while True:
            line = stream.readline(limit + 1)
            if not line:
                return
            if len(line) > limit or not line.endswith(b"\n"):
                raise ValueError("Oversize or unterminated JSONL record")
            value = strict_json(line)
            if line != encoded(value) + b"\n":
                raise ValueError("Noncanonical JSONL encoding")
            yield value


def spool(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA cache_size=-4096")
    db.execute("PRAGMA temp_store=FILE")
    db.execute("PRAGMA journal_mode=OFF")
    return db


def logical_hasher():
    result = hashlib.sha256()
    result.update(b'{"objects":{')
    return result


def hash_record(h, key, raw, count):
    if count:
        h.update(b",")
    h.update(encoded(key)); h.update(b":"); h.update(raw)


def hash_end(h):
    h.update(b'},"schema":"analog-layout-diff/1"}')
    return h.hexdigest()


def definition(field, value):
    raw = encoded({"field": field, "value": value})
    return "sha256:" + hashlib.sha256(b"ald-definition-1\0" + raw).hexdigest(), raw


def write_records(records, destination, *, compact=True):
    """Externally sort arbitrary capture order, assign v1 keys, write atomically.

    New destinations only. A failed conversion leaves no partial layout folder.
    No complete snapshot or content-key counter table is held in RAM.
    """
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ald_encode_", dir=destination.parent) as temp:
        temp = Path(temp)
        target = temp / "layout"
        target.mkdir()
        db = spool(temp / "sort.sqlite")
        try:
            db.execute("CREATE TABLE objects(key TEXT PRIMARY KEY, raw BLOB NOT NULL) WITHOUT ROWID")
            db.execute("CREATE TABLE multiplicity(base TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID")
            db.execute("CREATE TABLE defs(ref TEXT PRIMARY KEY, raw BLOB NOT NULL, n INTEGER NOT NULL) WITHOUT ROWID")
            for record in records:
                raw = encoded(record)
                if len(raw) > MAX_LINE - 2048:
                    raise ValueError("Record exceeds the 16 MiB format limit")
                kind = record["kind"]
                if not isinstance(kind, str) or not kind:
                    raise ValueError("Invalid record kind")
                if kind in NAMED:
                    key = kind + ":" + record.get("name", "")
                else:
                    base = kind + ":" + hashlib.sha256(raw).hexdigest()
                    old = db.execute("SELECT n FROM multiplicity WHERE base=?", (base,)).fetchone()
                    n = old[0] if old else 0
                    db.execute("INSERT OR REPLACE INTO multiplicity VALUES (?,?)", (base, n + 1))
                    key = base + ":" + str(n)
                try:
                    db.execute("INSERT INTO objects VALUES (?,?)", (key, raw))
                except sqlite3.IntegrityError as exc:
                    raise ValueError("Duplicate named object: " + key) from exc
                if compact:
                    for field in ("params", "props"):
                        if field in record and len(encoded(record[field])) >= 192:
                            ref, value = definition(field, record[field])
                            db.execute("INSERT INTO defs VALUES (?,?,1) ON CONFLICT(ref) DO UPDATE SET n=n+1", (ref, value))
            db.commit()
            # Only repeated large blocks are worth the indirection.
            db.execute("DELETE FROM defs WHERE n<2")
            with (target / "definitions.jsonl").open("wb") as stream:
                for ref, raw in db.execute("SELECT ref,raw FROM defs ORDER BY ref"):
                    stream.write(encoded({"id": ref, **strict_json(raw)}) + b"\n")
            h, count = logical_hasher(), 0
            with (target / "objects.jsonl").open("wb") as stream:
                for key, raw in db.execute("SELECT key,raw FROM objects ORDER BY key"):
                    hash_record(h, key, raw, count); count += 1
                    record = strict_json(raw)
                    refs = {}
                    if compact:
                        for field in ("params", "props"):
                            if field in record and len(encoded(record[field])) >= 192:
                                ref, _ = definition(field, record[field])
                                if db.execute("SELECT 1 FROM defs WHERE ref=?", (ref,)).fetchone():
                                    refs[field] = ref
                                    del record[field]
                    omitted = sorted(k for k, v in DEFAULTS.items() if k in record and encoded(record[k]) == encoded(v)) if compact else []
                    packed = {k: v for k, v in record.items() if k not in omitted}
                    # Keep the smaller representation; presence is explicit.
                    row = {"key": key, "record": packed, **({"defaults": omitted} if omitted else {}), **({"refs": refs} if refs else {})}
                    plain = {"key": key, "record": record, **({"refs": refs} if refs else {})}
                    if len(encoded(plain)) < len(encoded(row)):
                        row = plain
                    line = encoded(row) + b"\n"
                    if len(line) > MAX_LINE:
                        raise ValueError("Object envelope exceeds the 16 MiB format limit")
                    stream.write(line)
            manifest = {"schema": FORMAT, "codec": 1, "objectCount": count,
                        "semanticSha256": hash_end(h), "files": {name: file_digest(target / name)
                        for name in ("objects.jsonl", "definitions.jsonl")}}
            (target / "manifest.json").write_bytes(encoded(manifest) + b"\n")
            target.rename(destination)
        finally:
            db.close()
    return Snapshot(destination)


def from_snapshot(snapshot, destination, *, compact=True):
    validate(snapshot)
    return write_records(snapshot["objects"].values(), destination, compact=compact)


class Snapshot:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink() or any((self.path / f).is_symlink() for f in FILES):
            raise ValueError("Snapshot files cannot be symlinks")
        self.manifest = strict_json((self.path / "manifest.json").read_bytes())
        m = self.manifest
        if (set(m) != {"schema", "codec", "objectCount", "semanticSha256", "files"} or
            m["schema"] != FORMAT or type(m["codec"]) is not int or m["codec"] != 1 or
            type(m["objectCount"]) is not int or m["objectCount"] < 0 or
            set(m["files"]) != {"objects.jsonl", "definitions.jsonl"}):
            raise ValueError("Unsupported or malformed v2 manifest")
        self._cache = None
        self._wire = None

    @property
    def count(self):
        return self.manifest["objectCount"]

    @property
    def digest(self):
        return self.manifest["semanticSha256"]

    def records(self):
        for key, record, raw in self._records():
            yield key, record

    def _records(self):
        """Fully verify while streaming; consumers must exhaust the iterator."""
        with tempfile.TemporaryDirectory(prefix="ald_defs_") as temp:
            db = spool(Path(temp) / "defs.sqlite")
            try:
                db.execute("CREATE TABLE defs(id TEXT PRIMARY KEY, field TEXT, raw BLOB, used INTEGER DEFAULT 0) WITHOUT ROWID")
                previous = ""
                for row in json_lines(self.path / "definitions.jsonl"):
                    if set(row) != {"id", "field", "value"} or row["field"] not in {"params", "props"}:
                        raise ValueError("Invalid definition")
                    ref, raw = definition(row["field"], row["value"])
                    if row["id"] != ref or ref <= previous:
                        raise ValueError("Definition hash/order mismatch")
                    previous = ref
                    db.execute("INSERT INTO defs(id,field,raw) VALUES (?,?,?)", (ref, row["field"], encoded(row["value"])))
                previous, group, group_count, maximum = "", None, 0, -1
                h, count, cache = logical_hasher(), 0, OrderedDict()
                for row in json_lines(self.path / "objects.jsonl"):
                    if not {"key", "record"} <= set(row) <= {"key", "record", "refs", "defaults"}:
                        raise ValueError("Invalid object envelope")
                    key, record = row["key"], row["record"]
                    if not isinstance(key, str) or key <= previous or not isinstance(record, dict):
                        raise ValueError("Duplicate or unsorted object key")
                    previous = key
                    omitted = row.get("defaults", [])
                    if not isinstance(omitted, list) or omitted != sorted(set(omitted)):
                        raise ValueError("Invalid default presence list")
                    for field in omitted:
                        if field not in DEFAULTS or field in record:
                            raise ValueError("Conflicting default field")
                        record[field] = copy.deepcopy(DEFAULTS[field])
                    refs = row.get("refs", {})
                    if not isinstance(refs, dict):
                        raise ValueError("Invalid references")
                    for field, ref in refs.items():
                        if field not in {"params", "props"} or field in record:
                            raise ValueError("Conflicting definition reference")
                        if ref not in cache:
                            found = db.execute("SELECT field,raw FROM defs WHERE id=?", (ref,)).fetchone()
                            if not found or found[0] != field:
                                raise ValueError("Missing or wrong-type definition")
                            cache[ref] = (field, found[1])
                            db.execute("UPDATE defs SET used=1 WHERE id=?", (ref,))
                            while len(cache) > 1 and (len(cache) > 32 or sum(len(v[1]) for v in cache.values()) > 4 * 1024 * 1024):
                                cache.popitem(last=False)
                        if cache[ref][0] != field:
                            raise ValueError("Wrong-type definition")
                        record[field] = strict_json(cache[ref][1])
                    raw = encoded(record)
                    if len(raw) > MAX_LINE - 2048:
                        raise ValueError("Expanded record exceeds the 16 MiB format limit")
                    kind = record.get("kind")
                    if kind in NAMED:
                        if key != kind + ":" + record.get("name", ""):
                            raise ValueError("Noncanonical named key")
                        base, n = None, -1
                    else:
                        base = str(kind) + ":" + hashlib.sha256(raw).hexdigest()
                        suffix = key[len(base) + 1:]
                        if not isinstance(kind, str) or not key.startswith(base + ":") or not suffix.isascii() or not suffix.isdigit() or str(int(suffix)) != suffix:
                            raise ValueError("Noncanonical anonymous key")
                        n = int(suffix)
                    if base != group:
                        if group is not None and maximum != group_count - 1:
                            raise ValueError("Noncontiguous duplicate occurrences")
                        group, group_count, maximum = base, 0, -1
                    if base is not None:
                        group_count += 1; maximum = max(maximum, n)
                    hash_record(h, key, raw, count); count += 1
                    yield key, record, raw
                if group is not None and maximum != group_count - 1:
                    raise ValueError("Noncontiguous duplicate occurrences")
                if count != self.count or hash_end(h) != self.digest:
                    raise ValueError("Snapshot count or semantic hash mismatch")
                if db.execute("SELECT 1 FROM defs WHERE used=0 LIMIT 1").fetchone():
                    raise ValueError("Unreferenced definition")
                for name, expected in self.manifest["files"].items():
                    if file_digest(self.path / name) != expected:
                        raise ValueError("Snapshot file hash mismatch")
            finally:
                db.close()

    def wire(self):
        if self._wire is None:
            self._cache = tempfile.TemporaryDirectory(prefix="ald_wire_")
            target = Path(self._cache.name) / "canonical.wire"
            try:
                with target.open("wb") as stream:
                    for key, record, raw in self._records():
                        stream.write(wire_row(key, raw))
            except BaseException:
                self.close()
                raise
            self._wire = target
        return self._wire

    def materialize(self):
        return {"schema": SCHEMA, "objects": dict(self.records())}

    def close(self):
        if self._cache:
            self._cache.cleanup()
        self._cache = self._wire = None

    def dispose(self):
        self.close()
        owner = getattr(self, "_capture_owner", None)
        if owner:
            owner.cleanup()
            self._capture_owner = None

    def __del__(self):
        try:
            self.dispose()
        except Exception:
            pass


def load(path):
    path = Path(path)
    if path.is_dir():
        return Snapshot(path).materialize()
    state = strict_json(path.read_bytes())
    validate(state)
    return state
