"""Explicit, repository-local Git integration; never stage or commit user work."""
import json
import shlex
import subprocess
import sys
from pathlib import Path
from .core import SCHEMA, digest, validate
from .history import read_json, atomic_json


def textconv(value):
    """Deterministic, offline review text. Source JSON remains the stored data."""
    if value.get("schema") == SCHEMA:
        validate(value)
        lines = ["Analog layout snapshot (coordinates in integer DBU)"]
        for key, record in sorted(value["objects"].items()):
            lines.append("\n[" + key + "]")
            for field, data in sorted(record.items()):
                lines.append(field + " = " + json.dumps(data, sort_keys=True, ensure_ascii=True))
        return "\n".join(lines) + "\n"
    if value.get("schema") == SCHEMA + "/commit":
        if digest({k: v for k, v in value.items() if k != "id"}) != value.get("id"):
            raise ValueError("Corrupt layout commit")
        return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    raise ValueError("Not a layout snapshot or layout commit")


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return result.stdout


def setup(repo):
    """Install only diff settings and a root-level snapshot file association."""
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if root != Path(repo).resolve():
        raise ValueError("Pass the repository root explicitly to avoid changing a parent repository")
    driver = Path(__file__).with_name("git_driver.py").resolve()
    command = " ".join(shlex.quote(p) for p in (Path(sys.executable).as_posix(), driver.as_posix()))
    # Use local config only. No global configuration, hooks or staging changes.
    git(root, "config", "--local", "diff.layoutdiff.textconv", command)
    git(root, "config", "--local", "diff.layoutdiff.cachetextconv", "false")
    attrs = root / ".gitattributes"
    content = attrs.read_text(encoding="utf-8") if attrs.exists() else ""
    association = "*.layout.json diff=layoutdiff -merge"
    if association not in content.splitlines():
        with attrs.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(("\n" if content and not content.endswith("\n") else "") + association + "\n")
    return {"repository": str(root), "textconv": command, "attributes": association}


def extract(repo, revision, path, output):
    """Read the original JSON blob, bypassing textconv and shell redirection."""
    if not revision or revision.startswith("-") or ":" in revision:
        raise ValueError("Expected a Git revision, not an option or object path")
    raw = git(repo, "show", "--no-ext-diff", "--no-textconv", revision + ":" + path)
    snapshot = json.loads(raw)
    validate(snapshot)
    atomic_json(output, snapshot)
    return snapshot


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(textconv(read_json(sys.argv[1])), end="")
