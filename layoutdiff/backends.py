"""Contract for SKILL, direct OA Python/C++, or offline snapshot readers.

An OpenAccess binding should translate persistent objects into the documented
record schema and pass those records through canonicalize(). It must not use
process-local OA handles as keys. No OA vendor module is imported by the core.
"""
from typing import Protocol
from .core import validate
from .history import read_json


class SnapshotReader(Protocol):
    def capture(self, library: str, cell: str, view: str = "layout") -> dict: ...


class JsonReader:
    """Adapter for snapshots emitted by an external OA extraction process."""
    def __init__(self, path):
        self.path = path

    def capture(self, library="", cell="", view="layout"):
        snapshot = read_json(self.path)
        validate(snapshot)
        return snapshot
