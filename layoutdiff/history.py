"""Append-only single-parent history with atomic HEAD and exclusive writers."""
import contextlib
import json
import os
import re
import uuid
from pathlib import Path
from .core import empty_snapshot, diff, apply_diff


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, indent=2, ensure_ascii=True, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class History:
    def __init__(self, path):
        self.path = Path(path)

    def init(self):
        self.path.mkdir(parents=True, exist_ok=True)
        if list(self.path.iterdir()):
            raise ValueError("History directory must be empty")
        (self.path / "commits").mkdir()
        atomic_json(self.path / "empty.json", empty_snapshot())
        atomic_json(self.path / "HEAD", None)

    @contextlib.contextmanager
    def lock(self):
        lock = self.path / ".lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError("History is locked by another writer; inspect .lock before recovery") from None
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def chain(self, head=None):
        current = read_json(self.path / "HEAD") if head is None else head
        result, seen = [], set()
        while current:
            if not isinstance(current, str) or not re.fullmatch(r"[0-9a-f]{64}", current) or current in seen:
                raise ValueError("Invalid or cyclic history link")
            seen.add(current)
            commit = read_json(self.path / "commits" / (current + ".json"))
            if commit.get("id") != current:
                raise ValueError("Commit filename/id mismatch")
            result.append(commit)
            current = commit["parent"]
        return list(reversed(result))

    def replay(self, head=None):
        state, parent = read_json(self.path / "empty.json"), None
        if state != empty_snapshot():
            raise ValueError("Initial empty snapshot is corrupt")
        for commit in self.chain(head):
            state = apply_diff(state, commit, parent=parent)
            parent = commit["id"]
        return state

    def commit(self, snapshot, message="", *, expected_head=None):
        with self.lock():
            head = read_json(self.path / "HEAD")
            if head != expected_head:
                raise ValueError("History changed since capture; retry against current HEAD")
            old = self.replay()
            commit = diff(old, snapshot, parent=head, message=message)
            if not commit["operations"]:
                return None
            apply_diff(old, commit, parent=head)
            atomic_json(self.path / "commits" / (commit["id"] + ".json"), commit)
            atomic_json(self.path / "HEAD", commit["id"])
            return commit
