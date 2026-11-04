import pytest
import layoutdiff.git.commit as gc
from layoutdiff.data.core import canonicalize
from layoutdiff.git.store import GitSnapshots, snapshot_path

IDENTITY = ["TEST", "top", "layout"]
def snapshot(value):
    return canonicalize([{"kind": "cell", "name": "", "props": [["value", "int", value]]}])

@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repository with spaces"
    root.mkdir()
    gc.git(root, "init")
    gc.git(root, "config", "user.name", "Layout Diff Test")
    gc.git(root, "config", "user.email", "layout-diff@example.invalid")
    return root


def test_initial_preview_cancel_is_read_only(repo):
    preview = gc.prepare(repo, IDENTITY, snapshot(1))
    assert preview["operations"] == 1
    assert "1 added" in preview["summary"]
    assert "value" in preview["patch"]
    assert not (repo / ".layoutdiff").exists()
    assert gc.revision(repo)["head"] is None
    assert not (repo / ".git/index").exists()


@pytest.mark.parametrize("v2", [False, True])
def test_git_snapshots_preserve_unrelated_index_and_worktree(repo, tmp_path, v2):
    (repo / "other.txt").write_text("base")
    gc.git(repo, "add", "other.txt")
    gc.git(repo, "commit", "-m", "unrelated baseline")
    (repo / "other.txt").write_text("staged edit")
    gc.git(repo, "add", "other.txt")
    (repo / "other.txt").write_text("unstaged edit")
    staged = gc.git(repo, "ls-files", "--stage", "--", "other.txt").stdout
    for value in (1, 2):
        source = snapshot(value)
        if v2:
            from layoutdiff.data.storage import from_snapshot
            source = from_snapshot(source, tmp_path / ('snapshot-' + str(value)))
        preview = gc.prepare(repo, IDENTITY, source)
        result = gc.commit(preview, "message with unicode \u6d4b\u8bd5 and $() `quotes`\n\nbody")
        if v2:
            source.close()
        assert result["git_commit"] == gc.revision(repo)["head"]
        assert gc.git(repo, "ls-files", "--stage", "--", "other.txt").stdout == staged
        assert (repo / "other.txt").read_text() == "unstaged edit"
        assert gc.git(repo, "show", "HEAD:other.txt").stdout == b"base"
        store = GitSnapshots(repo, IDENTITY)
        assert store.snapshot(result["git_commit"]) == snapshot(value)
        assert "layout_commit" not in result
        assert not gc.git(repo, "status", "--porcelain", "--", "layouts").stdout
    assert len(GitSnapshots(repo, IDENTITY).revisions()) == 2
    assert not (repo / ".layoutdiff").exists()
    assert gc.prepare(repo, IDENTITY, snapshot(2))["operations"] == 0


def test_changed_head_and_branch_rejected(repo):
    p = gc.prepare(repo, IDENTITY, snapshot(1))
    gc.git(repo, "commit", "--allow-empty", "-m", "concurrent update")
    with pytest.raises(ValueError, match="HEAD"):
        gc.commit(p, "should not commit")
    assert not (repo / ".layoutdiff").exists()


def test_managed_uncommitted_files_are_not_overwritten(repo):
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "first")
    path = repo / snapshot_path(IDENTITY)
    path.write_text("manual work")
    with pytest.raises(ValueError, match="uncommitted"):
        gc.prepare(repo, IDENTITY, snapshot(2))
    assert path.read_text() == "manual work"


def test_empty_message_and_existing_index_lock_do_not_change_repo(repo):
    p = gc.prepare(repo, IDENTITY, snapshot(1))
    with pytest.raises(ValueError, match="message"):
        gc.commit(p, " \n ")
    lock = repo / ".git/index.lock"
    lock.write_text("another writer")
    with pytest.raises(FileExistsError):
        gc.commit(p, "first")
    assert lock.read_text() == "another writer"
    assert not (repo / ".layoutdiff").exists()


def test_failed_commit_restores_files_and_index(repo, monkeypatch):
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "first")
    old_head = gc.revision(repo)
    old_index = (repo / ".git/index").read_bytes()
    old_snapshot = (repo / snapshot_path(IDENTITY)).read_bytes()
    p = gc.prepare(repo, IDENTITY, snapshot(2))
    original = gc.git
    def fail(root, *args, **kwargs):
        if args[0] == "commit":
            raise RuntimeError("commit rejected")
        return original(root, *args, **kwargs)
    monkeypatch.setattr(gc, "git", fail)
    with pytest.raises(RuntimeError, match="rejected"):
        gc.commit(p, "rejected")
    assert (repo / ".git/index").read_bytes() == old_index
    assert gc.revision(repo) == old_head
    assert (repo / snapshot_path(IDENTITY)).read_bytes() == old_snapshot
    assert not (repo / ".git/index.lock").exists()


def test_native_git_hook_rejection_is_honored(repo):
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho blocked-by-test >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match="blocked-by-test"):
        gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "rejected by real hook")
    assert gc.revision(repo)["head"] is None
    assert not (repo / ".layoutdiff").exists()
    assert not (repo / "layouts").exists()
    assert not (repo / ".git/index.lock").exists()


def test_lost_commit_response_does_not_restore_old_layout_over_new_commit(repo, monkeypatch):
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "first")
    preview = gc.prepare(repo, IDENTITY, snapshot(2))
    original = gc.git
    def lose_response(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args[0] == "commit":
            raise RuntimeError("post-commit response lost")
        return result
    monkeypatch.setattr(gc, "git", lose_response)
    with pytest.raises(RuntimeError, match="Managed files were retained"):
        gc.commit(preview, "second")
    store = GitSnapshots(repo, IDENTITY)
    assert store.snapshot(store.head) == snapshot(2)
    assert not (repo / ".git/index.lock").exists()


def test_supervisor_only_releases_its_registered_lock(tmp_path):
    from layoutdiff.data.history import atomic_json
    lock, registry = tmp_path / "index.lock", tmp_path / "locks.json"
    lock.write_text("own-token")
    atomic_json(registry, [{"pid": 123, "path": str(lock), "token": "own-token"}])
    gc.cleanup_locks(registry, 456)
    assert lock.exists()
    lock.write_text("foreign-token")
    gc.cleanup_locks(registry, 123)
    assert lock.exists()
    lock.write_bytes(b"DIRC\x00\xff\xfe")
    gc.cleanup_locks(registry, 123)
    assert lock.read_bytes() == b"DIRC\x00\xff\xfe"
    lock.write_text("own-token")
    gc.cleanup_locks(registry, 123)
    assert not lock.exists()


def test_large_preview_respects_native_field_limit_without_losing_patch(repo):
    large = canonicalize([{"kind": "cell", "name": "", "props": [["text", "string", "\u6d4b\u8bd5" * 10000]]}])
    preview = gc.prepare(repo, IDENTITY, large)
    assert len(preview["display_patch"].encode("utf-8")) < 8191
    assert "View full diff" in preview["display_patch"]
    assert len(preview["patch"]) > len(preview["display_patch"])


def test_ordinary_commits_retain_layout_and_next_diff_base(repo):
    first = gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "layout one")["git_commit"]
    (repo / "notes.txt").write_text("ordinary change")
    gc.git(repo, "add", "notes.txt"); gc.git(repo, "commit", "-m", "documentation only")
    ordinary = gc.revision(repo)["head"]
    store = GitSnapshots(repo, IDENTITY)
    try:
        assert store.snapshot(ordinary) == store.snapshot(first)
        assert store.revisions() == [first]
        assert store.pair(ordinary)[0] == store.pair(ordinary)[1]
    finally:
        store.close()
    preview = gc.prepare(repo, IDENTITY, snapshot(2))
    assert preview["before"] == snapshot(1) and preview["base"]["head"] == ordinary
    result = gc.commit(preview, "layout two")["git_commit"]
    assert gc.git(repo, "show", "-s", "--format=%P", result).stdout.decode().strip() == ordinary
