"""Previewed layout commits using Git's normal commit command and a private index."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter
from layoutdiff.data.core import digest, diff, validate
from layoutdiff.data.history import read_json
from layoutdiff.git.tools import textconv
import difflib


def git(repo, *args, env=None, data=None, check=True, output=None):
    process_env = os.environ.copy()
    process_env["GIT_OPTIONAL_LOCKS"] = "0"
    # The GUI target must never be redirected by inherited Git environment.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        process_env.pop(key, None)
    process_env.update(env or {})
    process_env["GIT_LITERAL_PATHSPECS"] = "1"
    stream = open(output, "wb") if output else None
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], input=data,
                                stdout=stream or subprocess.PIPE, stderr=subprocess.PIPE, env=process_env, timeout=90)
    finally:
        if stream:
            stream.close()
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or "Git command failed")
    return result


def discover(directory):
    result = git(directory, "rev-parse", "--show-toplevel", check=False)
    return Path(result.stdout.decode().strip()).resolve() if result.returncode == 0 else None


def revision(repo):
    branch = git(repo, "symbolic-ref", "--quiet", "HEAD").stdout.decode().strip()
    result = git(repo, "rev-parse", "--verify", "HEAD", check=False)
    head = result.stdout.decode().strip() if result.returncode == 0 else None
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        path = Path(git(repo, "rev-parse", "--git-path", marker).stdout.decode().strip())
        if not path.is_absolute():
            path = repo / path
        if path.exists():
            raise ValueError("Finish the current Git merge/rebase/cherry-pick before committing a layout")
    return {"branch": branch, "head": head}


def history_path(repo, identity):
    return Path(repo) / ".layoutdiff" / "histories" / digest(identity)


def ensure_clean(repo, prefix):
    # --untracked-files=all also catches unexpected files inside our subtree.
    if git(repo, "status", "--porcelain", "--untracked-files=all", "--", prefix).stdout:
        raise ValueError("The managed Git files have staged/uncommitted changes; resolve them before Save & Commit")
    # Do not follow a symlink into another directory (even one inside the repo).
    path = repo
    for part in Path(prefix).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Layout history path cannot contain symlinks")
    if path.is_dir() and any(p.is_symlink() for p in path.rglob("*")):
        raise ValueError("Layout history files cannot be symlinks")


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()


def prepare(repo, identity, snapshot):
    from layoutdiff.data.storage import Snapshot
    if isinstance(snapshot, Snapshot):
        return prepare_v2(repo, identity, snapshot)
    from layoutdiff.git.store import GitSnapshots, blob, head, snapshot_directory
    current_head = head(repo)
    if current_head and git(repo, "log", "--first-parent", "-1", "--format=%H", current_head,
                            "--", snapshot_directory(identity)).stdout:
        # Legacy Python callers must never recreate a conflicting v1 file after migration.
        from layoutdiff.data.storage import from_snapshot
        owner = tempfile.TemporaryDirectory(prefix="ald_preview_")
        converted = from_snapshot(snapshot, Path(owner.name) / "layout")
        converted._capture_owner = owner
        return prepare_v2(repo, identity, converted)
    validate(snapshot)
    repo = Path(repo).resolve()
    if discover(repo) != repo:
        raise ValueError("Select the Git repository root")
    base = revision(repo)
    # Fail before showing a confirmation which cannot create a commit.
    git(repo, "var", "GIT_AUTHOR_IDENT")
    git(repo, "var", "GIT_COMMITTER_IDENT")
    store = GitSnapshots(repo, identity, revision=base["head"])
    prefix = store.path
    ensure_clean(repo, prefix)
    if base["head"]:
        paths = git(repo, "ls-tree", "-r", "--name-only", "-z", base["head"], "--", "layouts").stdout.decode().split("\0")
        if any(p != prefix and p.casefold() == prefix.casefold() for p in paths):
            raise ValueError("Cellview path collides with another layout on case-insensitive filesystems")
    before = store.snapshot(base["head"])
    delta = diff(before, snapshot)
    adopting = blob(repo, base["head"], prefix) is None and bool(before["objects"])
    files = {prefix: json_bytes(snapshot)}
    # Attribute lives in our namespace, avoiding edits to a user's root rules.
    # It prevents Git from silently text-merging conflicting layout snapshots.
    attr_path = "layouts/.gitattributes"
    attrs = blob(repo, base["head"], attr_path) or b""
    rule = b"*.layout.json -merge"
    if rule not in attrs.splitlines():
        ensure_clean(repo, attr_path)
        files[attr_path] = attrs + (b"\n" if attrs and not attrs.endswith(b"\n") else b"") + rule + b"\n"
    kinds = Counter((op["after"] or op["before"])["kind"] for op in delta["operations"])
    counts = Counter("added" if op["before"] is None else "removed" if op["after"] is None else "changed"
                     for op in delta["operations"])
    # Legacy API: render only changed records, never a global text sequence match.
    from layoutdiff.comparison.categories import operation_text
    patch = "".join(operation_text(op) for op in delta["operations"])
    summary = (f"Repository: {repo}\nBranch: {base['branch'].removeprefix('refs/heads/')}\n"
               f"Layout: {' / '.join(identity)}\nBase Git commit: {base['head'] or '(initial commit)'}\n"
               f"Objects: {counts['added']} added, {counts['changed']} changed, {counts['removed']} removed\n"
               f"Kinds: {', '.join(f'{k}: {v}' for k, v in sorted(kinds.items())) or 'none'}\n"
               f"Snapshot file: {prefix}\n"
               + ("Adopt snapshot storage; earlier Git revisions remain available.\n" if adopting else "") +
               "Git stores the snapshot; layout changes are computed from its parent.\n"
               "Cancel keeps the layout saved and creates no Git commit.")
    # IC23.1 hiCreateMLTextField documents an 8191-byte limit. Preserve UTF-8
    # boundaries and expose the complete patch in the native full-file viewer.
    display_patch = patch
    if len(patch.encode("utf-8")) > 7800:
        display_patch = patch.encode("utf-8")[:7600].decode("utf-8", errors="ignore")
        display_patch += "\n[Preview shortened. Use View full diff for all changes.]"
    return {"repo": str(repo), "identity": identity, "base": base,
            "before": before, "snapshot": snapshot, "prefix": prefix, "summary": summary,
            "patch": patch, "display_patch": display_patch, "operations": len(delta["operations"]),
            "write_required": bool(delta["operations"]) or adopting, "adopting": adopting,
            "files": files}


class Prepared(dict):
    """Own preview scratch until confirmation/cancel; full text is lazy."""
    def __getitem__(self, key):
        if key == "patch":
            return "".join(self["changes"].full())
        return super().__getitem__(key)

    def close(self):
        self["changes"].close()
        self["store"].close()
        self["snapshot"].dispose()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def prepare_v2(repo, identity, snapshot, *, backend="auto"):
    from layoutdiff.git.store import GitSnapshots, blob, snapshot_directory, path_identity
    from layoutdiff.data.storage import Snapshot, FILES
    from layoutdiff.comparison.changeindex import ChangeIndex
    repo = Path(repo).resolve()
    if discover(repo) != repo:
        raise ValueError("Select the Git repository root")
    base = revision(repo)
    git(repo, "var", "GIT_AUTHOR_IDENT"); git(repo, "var", "GIT_COMMITTER_IDENT")
    store = GitSnapshots(repo, identity, revision=base["head"])
    changes = None
    try:
        prefix = snapshot_directory(identity)
        for path in (prefix, store.path):
            ensure_clean(repo, path)
        if base["head"]:
            paths = git(repo, "ls-tree", "-r", "--name-only", "-z", base["head"], "--", "layouts").stdout.decode().split("\0")
            for path in paths:
                other = path_identity(path)
                if other and other != list(identity) and [s.casefold() for s in other] == [s.casefold() for s in identity]:
                    raise ValueError("Cellview path collides with another layout on case-insensitive filesystems")
        before = store.open(base["head"])
        changes = ChangeIndex(before, snapshot, backend=backend)
        adopting = blob(repo, base["head"], prefix + "/manifest.json") is None and before.count > 0
        files = {prefix + "/" + name: snapshot.path / name for name in FILES}
        from layoutdiff.virtuoso.omissions import AUDIT, DETAILS, warning
        omissions = getattr(snapshot, 'omissions', None)
        audit_changed = False
        for name, data in ((AUDIT, json_bytes(omissions) if omissions else None),
                           (DETAILS, snapshot.omission_report if omissions else None)):
            previous = (blob(repo, base['head'], prefix + '/' + name) if name == AUDIT else
                (git(repo, 'ls-tree', '-z', base['head'], '--', prefix + '/' + name).stdout or None)
                if base['head'] else None)
            if data is not None:
                files[prefix + '/' + name] = data
                # The summary includes the report hash; avoid loading large reports.
                if name == AUDIT:
                    audit_changed = previous != data
            elif previous is not None:
                files[prefix + '/' + name] = None
                audit_changed = True
        if blob(repo, base["head"], store.path) is not None:
            files[store.path] = None  # Migrate in this same ordinary Git commit.
        attr_path = "layouts/.gitattributes"
        attrs = blob(repo, base["head"], attr_path) or b""
        extra = [r for r in (b"*.layout.json -merge", b"*.jsonl -merge", b"**/*.layout/manifest.json -merge") if r not in attrs.splitlines()]
        if extra:
            ensure_clean(repo, attr_path)
            files[attr_path] = attrs + (b"\n" if attrs and not attrs.endswith(b"\n") else b"") + b"\n".join(extra) + b"\n"
        stat = changes.totals
        summary = (f"Repository: {repo}\nBranch: {base['branch'].removeprefix('refs/heads/')}\n"
            f"Layout: {' / '.join(identity)}\nBase Git commit: {base['head'] or '(initial commit)'}\n"
            f"Changes: {stat['added']}A, {stat['modified']}M, {stat['deleted']}D, {stat['modified_net']} modified net, {stat['moved']} moved / stretched\n"
            f"Snapshot: {prefix} (JSON Lines v2)\nProcessing backend: {changes.backend}\n" +
            ("Migrate this layout to v2 in this commit; historical snapshots remain readable.\n" if adopting else "") +
            "Cancel keeps the layout saved and creates no Git commit.")
        return Prepared(repo=str(repo), identity=list(identity), base=base, before=before, snapshot=snapshot,
            prefix=prefix, summary=summary, changes=changes, store=store, operations=changes.raw_operations,
            display_patch=changes.overview(interactive=False), adopting=adopting,
            write_required=bool(changes.raw_operations) or adopting or audit_changed, files=files,
            omissions=omissions, omission_warning=warning(omissions))
    except BaseException:
        if changes:
            changes.close()
        store.close()
        raise


def cleanup_locks(registry, pid):
    """Supervisor fallback: release only exact-token locks registered by this worker."""
    registry = Path(registry)
    if not registry.exists():
        return
    for record in read_json(registry):
        path = Path(record["path"])
        if record["pid"] == pid and path.name == "index.lock":
            try:
                if not path.is_symlink() and path.read_bytes() == record["token"].encode():
                    staging = record.get("index_staging")
                    if staging:
                        staged = Path(staging)
                        if staged.parent == path.parent and staged.name.startswith("index.ald-"):
                            staged.unlink(missing_ok=True)
                    path.unlink()
            except FileNotFoundError:
                pass


def commit(preview, message, *, scratch=None, registry=None):
    """Commit only this preview; Cancel never calls this function.

    Normal git commit runs hooks and signing with a private index seeded from
    HEAD. The user's index is locked and copied, then only our file entries are
    advanced. Unrelated staged and unstaged work is preserved.
    """
    from layoutdiff.data.history import atomic_json
    if not message.strip():
        raise ValueError("Enter a nonempty commit message")
    if not preview["write_required"]:
        raise ValueError("No layout changes to commit")
    repo, prefix = Path(preview["repo"]), preview["prefix"]
    if revision(repo) != preview["base"]:
        raise ValueError("Git HEAD or branch changed after preview; run Save & Commit again")
    files = preview["files"]
    if isinstance(preview, Prepared):
        from layoutdiff.data.storage import Snapshot
        current = Snapshot(preview["snapshot"].path)
        try:
            current.wire()
            if current.digest != preview["snapshot"].digest:
                raise ValueError("Prepared snapshot changed after preview")
        finally:
            current.close()
        if preview.get('omissions'):
            from layoutdiff.data.streaming import file_digest
            if file_digest(preview['snapshot'].omission_report) != preview['omissions']['reportSha256']:
                raise ValueError('Prepared omission report changed after preview')
    for name in files:
        ensure_clean(repo, name)
    index = Path(git(repo, "rev-parse", "--git-path", "index").stdout.decode().strip())
    if not index.is_absolute():
        index = repo / index
    lock = index.with_name("index.lock")
    index_staging = index.with_name("index.ald-" + uuid.uuid4().hex)
    token = f"layoutdiff:{os.getpid()}:{uuid.uuid4().hex}"
    if registry:
        atomic_json(registry, [{"path": str(lock), "pid": os.getpid(), "token": token,
                               "index_staging": str(index_staging)}])
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, token.encode()); os.close(fd)
    originals = {}
    created_dirs = set()
    committed = False
    backup_temp = None
    try:
        backup_temp = tempfile.TemporaryDirectory(prefix="ald_rollback_", dir=scratch)
        if revision(repo) != preview["base"]:
            raise ValueError("Git changed after preview; run Save & Commit again")
        with tempfile.TemporaryDirectory(prefix="ald_git_", dir=scratch) as temp:
            temp = Path(temp)
            candidate = temp / "commit.index"
            env = {"GIT_INDEX_FILE": str(candidate), "GIT_TERMINAL_PROMPT": "0"}
            git(repo, "read-tree", preview["base"]["head"] or "--empty", env=env)
            # Preserve the user's index independently of the commit index.
            saved_index = temp / "user.index"
            if index.exists():
                shutil.copy2(index, saved_index)
            else:
                git(repo, "read-tree", "--empty", env={**env, "GIT_INDEX_FILE": str(saved_index)})
            for name, data in files.items():
                path = repo / name
                backup = Path(backup_temp.name) / ("original-" + str(len(originals)))
                if path.exists():
                    shutil.copyfile(path, backup)
                    originals[name] = backup
                else:
                    originals[name] = None
                parent = path.parent
                while not parent.exists():
                    created_dirs.add(parent)
                    parent = parent.parent
                path.parent.mkdir(parents=True, exist_ok=True)
                if data is None:
                    path.unlink(missing_ok=True)
                elif isinstance(data, Path):
                    shutil.copyfile(data, path)
                else:
                    path.write_bytes(data)
            git(repo, "add", "--all", "--", *files, env=env)
            messagefile = temp / "message.txt"
            messagefile.write_text(message, encoding="utf-8")
            git(repo, "commit", "--file", str(messagefile), env=env)
            committed = True
            result = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
            # Sync only the committed managed paths to the preserved user index.
            entries = git(repo, "ls-tree", "-r", "-z", result, "--", *files).stdout
            deleted = [name for name, data in files.items() if data is None]
            if deleted:
                git(repo, "update-index", "--force-remove", "--", *deleted, env={**env, "GIT_INDEX_FILE": str(saved_index)})
            git(repo, "update-index", "-z", "--index-info", env={**env, "GIT_INDEX_FILE": str(saved_index)}, data=entries)
            # The scratch environment can reside on another filesystem/drive.
            # Stage alongside index so the final replacement remains atomic.
            with index_staging.open("xb") as stream:
                stream.write(saved_index.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(index_staging, index)
            return {"git_commit": result, "repository": str(repo), "snapshot_path": prefix,
                    "branch": preview["base"]["branch"], "files": list(files), "message": message}
    except Exception as exc:
        # A post-commit hook can hang after Git has advanced HEAD. A timeout or
        # lost response must not restore old files over that completed commit.
        if not committed:
            try:
                current = git(repo, "rev-parse", "--verify", "HEAD", check=False)
                committed = (current.returncode == 0 and
                             current.stdout.decode().strip() != preview["base"]["head"])
            except Exception:
                # The result is unknown: retain the files for explicit recovery.
                committed = True
        if committed:
            raise RuntimeError("Git HEAD advanced or its state could not be verified. Managed files were retained; "
                               "the index may need refresh. Inspect Git status before retrying: " + str(exc)) from exc
        raise
    finally:
        index_staging.unlink(missing_ok=True)
        if not committed:
            for name, original in originals.items():
                path = repo / name
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    shutil.copyfile(original, path)
            for path in sorted(created_dirs, key=lambda p: len(p.parts), reverse=True):
                try:
                    path.rmdir()
                except OSError:
                    pass
        if lock.exists() and lock.read_bytes() == token.encode():
            lock.unlink()
        if backup_temp:
            backup_temp.cleanup()
