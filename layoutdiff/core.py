"""Exact JSON snapshots and checked, reversible object operations.

Database handles never serve as persisted identities. Named objects use natural
keys; anonymous figures use content hashes and occurrence indexes (a multiset).
A move of an anonymous figure is deliberately represented as delete + add.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter

SCHEMA = "analog-layout-diff/1"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def empty_snapshot():
    return {"schema": SCHEMA, "objects": {}}


def canonicalize(records):
    objects, counts = {}, Counter()
    for record in sorted(copy.deepcopy(records), key=encoded):
        kind = record["kind"]
        if kind in {"cell", "net", "term", "inst", "mosaic", "figGroup", "dependency"}:
            key = kind + ":" + record.get("name", "")
        else:
            base = kind + ":" + digest(record)
            key = base + ":" + str(counts[base])
            counts[base] += 1
        if key in objects:
            raise ValueError("Duplicate named object: " + key)
        objects[key] = record
    return {"schema": SCHEMA, "objects": objects}


def validate(snapshot):
    if snapshot.get("schema") != SCHEMA or not isinstance(snapshot.get("objects"), dict):
        raise ValueError("Unsupported or invalid snapshot schema")
    if set(snapshot) != {"schema", "objects"}:
        raise ValueError("Unknown snapshot fields")
    encoded(snapshot)  # Reject NaN, infinities and non-JSON values.
    if canonicalize(list(snapshot["objects"].values())) != snapshot:
        raise ValueError("Noncanonical or corrupt object keys")


def diff(before, after, *, parent=None, message=""):
    validate(before)
    validate(after)
    ops = []
    a, b = before["objects"], after["objects"]
    for key in sorted(a.keys() | b.keys()):
        if encoded(a.get(key)) != encoded(b.get(key)):
            ops.append({"key": key, "before": a.get(key), "after": b.get(key)})
    body = {"schema": SCHEMA + "/commit", "parent": parent,
            "base": digest(before), "result": digest(after), "message": message,
            "operations": ops}
    return {**body, "id": digest(body)}


def apply_diff(snapshot, commit, *, parent=None, reverse=False):
    """Validate all preconditions before returning a new snapshot; no mutation."""
    validate(snapshot)
    body = {k: v for k, v in commit.items() if k != "id"}
    if commit.get("schema") != SCHEMA + "/commit" or digest(body) != commit.get("id"):
        raise ValueError("Corrupt commit or unsupported schema")
    if commit["parent"] != parent:
        raise ValueError("Parent commit mismatch")
    old, new = ("after", "before") if reverse else ("before", "after")
    source, target = ("result", "base") if reverse else ("base", "result")
    if digest(snapshot) != commit[source]:
        raise ValueError("Base snapshot mismatch")
    result = copy.deepcopy(snapshot)
    seen = set()
    for op in commit["operations"]:
        key = op["key"]
        if key in seen or encoded(result["objects"].get(key)) != encoded(op[old]):
            raise ValueError("Object precondition mismatch: " + key)
        seen.add(key)
        if op[new] is None:
            result["objects"].pop(key, None)
        else:
            result["objects"][key] = copy.deepcopy(op[new])
    validate(result)
    if digest(result) != commit[target]:
        raise ValueError("Result digest mismatch")
    return result
