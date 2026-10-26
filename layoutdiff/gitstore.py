"""Read canonical cellview snapshots from Git trees, including legacy Git payloads.

Git is the history authority. Semantic operations are derived, never persisted
as a second commit graph. Reads are pinned to immutable commits and ignore the
index/worktree. Legacy latest.layout.json blobs remain readable in old commits.
"""
from pathlib import Path
import json
import re
import tempfile
import shutil
from collections import OrderedDict
from urllib.parse import quote, unquote
from .core import digest, empty_snapshot, validate
from .gitcommit import git
from .storage import Snapshot, from_snapshot, strict_json, FILES


def check_identity(identity):
    if len(identity) != 3 or not all(isinstance(v, str) and v and "\0" not in v for v in identity):
        raise ValueError("Expected a library, cell and view identity")


def component(name):
    value = quote(name, safe="")
    # Encode special filesystem names; normal design names remain readable.
    if (name in {".", ".."} or name.endswith(".") or
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)):
        value = "".join(f"%{b:02X}" for b in name.encode("utf-8"))
    return value


def snapshot_path(identity):
    check_identity(identity)
    return "layouts/" + "/".join(component(v) for v in identity) + ".layout.json"


def snapshot_directory(identity):
    return snapshot_path(identity).removesuffix(".json")


def path_identity(path):
    parts = path.split("/")
    if len(parts) == 5 and parts[-1] in (*FILES, 'omissions.json', 'omissions.jsonl') and parts[-2].endswith(".layout"):
        return path_identity("/".join(parts[:-1]) + ".json")
    if len(parts) != 4 or parts[0] != "layouts" or not parts[-1].endswith(".layout.json"):
        return None
    result = [unquote(v) for v in [*parts[1:3], parts[3][:-len(".layout.json")]]]
    return result if snapshot_path(result) == path else None


def head(repo):
    result = git(repo, "rev-parse", "--verify", "HEAD", check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def blob(repo, revision, path):
    """Return a regular file's bytes, or None if absent; other failures propagate."""
    if revision is None:
        return None
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("Expected a full Git commit ID")
    entry = git(repo, "ls-tree", "-z", revision, "--", path).stdout
    if not entry:
        return None
    mode, kind, oid = entry.split(b"\t", 1)[0].split()
    if mode not in (b"100644", b"100755") or kind != b"blob":
        raise ValueError("Layout storage must contain regular files: " + path)
    return git(repo, "cat-file", "blob", oid.decode()).stdout


def blob_file(repo, revision, path, destination):
    if revision is None:
        return False
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("Expected a full Git commit ID")
    entry = git(repo, "ls-tree", "-z", revision, "--", path).stdout
    if not entry:
        return False
    mode, kind, oid = entry.split(b"\t", 1)[0].split()
    if mode not in (b"100644", b"100755") or kind != b"blob":
        raise ValueError("Layout storage must contain regular files: " + path)
    git(repo, "cat-file", "blob", oid.decode(), output=destination)
    return True


class GitSnapshots:
    def __init__(self, repo, identity, *, revision=None):
        self.repo, self.identity = Path(repo).resolve(), list(identity)
        self.path = snapshot_path(identity)
        self.v2 = snapshot_directory(identity)
        self.legacy = ".layoutdiff/histories/" + digest(identity)
        self.head = revision if revision is not None else head(repo)
        self._states, self._metadata = OrderedDict(), {}
        self._temp = tempfile.TemporaryDirectory(prefix="ald_gitblobs_")
        self._log = None

    def close(self):
        for state in self._states.values():
            state.close()
        self._states.clear()
        self._temp.cleanup()

    def open(self, revision):
        if revision in self._states:
            self._states.move_to_end(revision)
            return self._states[revision]
        folder = Path(self._temp.name) / (revision or "empty")
        folder.mkdir()
        target = folder / "layout"
        target.mkdir()
        try:
            has_v2 = blob_file(self.repo, revision, self.v2 + "/manifest.json", target / "manifest.json")
            if has_v2:
                for name in FILES[1:]:
                    if not blob_file(self.repo, revision, self.v2 + "/" + name, target / name):
                        raise ValueError("Incomplete v2 snapshot")
                state = Snapshot(target)
                old = blob(self.repo, revision, self.path)
                if old is not None:
                    value = strict_json(old); validate(value)
                    state.wire()
                    if digest(value) != state.digest:
                        raise ValueError("Conflicting coexisting v1/v2 snapshots")
            else:
                if revision and git(self.repo, "ls-tree", "-r", "--name-only", revision, "--", self.v2).stdout:
                    raise ValueError("Incomplete v2 snapshot: missing manifest")
                introduced_v2 = revision and git(self.repo, "log", "--first-parent", "-1", "--format=%H", revision, "--", self.v2).stdout
                raw = None if introduced_v2 else blob(self.repo, revision, self.path)
                if raw is None and not introduced_v2 and revision:
                    introduced = git(self.repo, "log", "--first-parent", "-1", "--format=%H", revision, "--", self.path).stdout
                    if not introduced:
                        raw = blob(self.repo, revision, self.legacy + "/latest.layout.json")
                        if raw is not None:
                            source = blob(self.repo, revision, self.legacy + "/source.json")
                            if source is None or strict_json(source) != self.identity:
                                raise ValueError("Legacy Git layout identity mismatch")
                target.rmdir()
                state = from_snapshot(strict_json(raw) if raw is not None else empty_snapshot(), target)
            self._states[revision] = state
            while len(self._states) > 3:
                _, old = self._states.popitem(last=False)
                old.close()
                shutil.rmtree(old.path.parent)
            return state
        except BaseException:
            shutil.rmtree(folder)
            raise

    def snapshot(self, revision):
        return self.open(revision).materialize()

    def metadata(self, revision):
        if revision not in self._metadata:
            raw = git(self.repo, "show", "-s", "--format=%H%x00%P%x00%an%x00%aI%x00%B", revision).stdout
            sha, parents, author, date, message = raw.decode("utf-8", errors="replace").split("\0", 4)
            self._metadata[revision] = {"sha": sha, "parents": parents.split(), "author": author,
                                        "date": date, "message": message.rstrip("\n")}
        return self._metadata[revision]

    def omissions(self, revision):
        from .omissions import AUDIT
        raw = blob(self.repo, revision, self.v2 + '/' + AUDIT)
        if raw is None:
            return None
        audit = strict_json(raw)
        if (audit.get('schema') != 'analog-layout-diff/omissions/1' or
                audit.get('snapshotSha256') != self.open(revision).digest or
                any(type(audit.get(k)) is not int or audit[k] < 0 for k in ('omitted', 'detached'))):
            raise ValueError('Invalid or mismatched layout omission audit')
        return audit

    def pair(self, revision):
        parents = self.metadata(revision)["parents"]
        return self.snapshot(parents[0] if parents else None), self.snapshot(revision)

    def pair_stores(self, revision):
        parents = self.metadata(revision)["parents"]
        return self.open(parents[0] if parents else None), self.open(revision)

    def revisions(self):
        if not self.head:
            return []
        if self._log is None:
            raw = git(self.repo, "log", "--first-parent", "-z", "--format=%H%x00%P%x00%an%x00%aI%x00%B", self.head, "--",
                      self.path, self.v2, self.legacy + "/latest.layout.json").stdout.decode("utf-8", errors="replace").split("\0")
            self._log = []
            for i in range(0, len(raw) - 1, 5):
                sha, parents, author, date, message = raw[i:i + 5]
                self._log.append(sha)
                self._metadata[sha] = {"sha": sha, "parents": parents.split(), "author": author,
                    "date": date, "message": message.rstrip("\n")}
        return self._log


def sources(repo):
    """Include deleted cellviews so their earlier commits remain browseable."""
    revision = head(repo)
    if not revision:
        return []
    data = git(repo, "log", "--first-parent", "--format=", "--name-only", "-z", revision,
               "--", "layouts", ".layoutdiff/histories").stdout.decode("utf-8")
    result = set()
    for path in set(data.split("\0")):
        path = path.lstrip("\n")
        identity = path_identity(path)
        if identity:
            result.add(tuple(identity))
        elif re.fullmatch(r"\.layoutdiff/histories/[0-9a-f]{64}/source.json", path):
            # Legacy source files were immutable; fetch from their newest change
            # if later commits removed the archival directory.
            revs = git(repo, "log", "--first-parent", "--diff-filter=AM", "-1", "--format=%H",
                       revision, "--", path).stdout.decode().splitlines()
            raw = blob(repo, revs[0], path) if revs else None
            if raw:
                identity = json.loads(raw)
                check_identity(identity)
                if path == ".layoutdiff/histories/" + digest(identity) + "/source.json":
                    result.add(tuple(identity))
    return [list(v) for v in sorted(result)]
