"""Disposable work bundles with native GUI leases.

SKILL writes RELEASED only after all windows/forms and OA opens referencing a
bundle are gone. The supervisor can reap these without calling the bridge,
including after the main worker stops. No user paths are recursively removed.
"""
from pathlib import Path
import json
import shutil
import tempfile
import uuid
from .history import atomic_json


def new_session():
    return Path(tempfile.mkdtemp(prefix="ald-session-"))


def reap(session, *, parent_dead=False):
    session = Path(session)
    if not session.name.startswith("ald-session-"):
        raise ValueError("Not an owned temporary session")
    pending = []
    for folder in (session / "work").glob("*"):
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            record = json.loads((folder / "lease.json").read_text())
        except (FileNotFoundError, ValueError):
            if parent_dead:
                shutil.rmtree(folder)
                continue
            pending.append(str(folder)); continue
        if record.get("token") != folder.name or record.get("path") != str(folder):
            raise ValueError("Unrecognized temporary work bundle")
        if parent_dead or not record.get('armed', True) or (folder / "RELEASED").exists():
            shutil.rmtree(folder)
        else:
            pending.append(str(folder))
    return pending


def allocate(session):
    token = uuid.uuid4().hex
    path = Path(session) / "work" / token
    path.mkdir(parents=True, mode=0o700)
    atomic_json(path / "lease.json", {"token": token, "path": str(path), "armed": False})
    return token, path
