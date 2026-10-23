import copy
import json
from pathlib import Path
import pytest
from layoutdiff.core import canonicalize, diff, apply_diff, empty_snapshot
from layoutdiff.dependencies import compare_dependencies, native_snapshot
from layoutdiff.gittools import git, setup, extract, textconv
from layoutdiff.hash_views import fingerprint
from layoutdiff.history import atomic_json, History
from layoutdiff.virtuoso import VirtuosoAdapter, coverage


def dep(hash_value="a" * 64):
    return {"kind": "dependency", "name": '["LIB","child","layout"]',
            "libName": "LIB", "cellName": "child", "viewName": "layout", "pcell": False,
            "fingerprint": {"status": "ok", "method": "saved-oa-sha256-v1", "sha256": hash_value},
            "dirty": False, "dirtyCounter": None}


def test_child_only_changes_replay_and_reverse_without_native_changes():
    a, b = canonicalize([dep()]), canonicalize([dep("b" * 64)])
    delta = diff(a, b)
    assert len(delta["operations"]) == 1
    assert delta["operations"][0]["key"].startswith("dependency:")
    assert apply_diff(a, delta) == b
    assert apply_diff(b, delta, reverse=True) == a
    assert native_snapshot(a) == native_snapshot(b)
    assert not coverage(b)
    assert len(compare_dependencies(a, b)) == 1


def test_missing_dirty_unknown_and_new_dependencies_warn():
    a = canonicalize([dep()])
    assert not compare_dependencies(a, a)
    assert compare_dependencies(a, empty_snapshot())
    assert compare_dependencies(empty_snapshot(), a)
    for changes in [{"dirty": True, "dirtyCounter": "4"}, {"fingerprint": {"status": "unresolved"}}]:
        b = canonicalize([{**dep(), **changes}])
        assert compare_dependencies(b, b)
        assert compare_dependencies(a, b)


def test_legacy_history_is_unchanged():
    root = Path(__file__).parent / 'fixtures' / 'legacy_history'
    result = History(root / "example-history").replay()
    assert result == json.loads((root / "example-latest.json").read_text())
    assert native_snapshot(result) == result


def test_dependency_service_failure_is_a_warning(tmp_path):
    adapter = VirtuosoAdapter(None, tmp_path)
    def fail(**kwargs):
        raise ConnectionError("test disconnected")
    adapter.hierarchy.read = fail
    with pytest.warns(UserWarning, match="unavailable"):
        issues = adapter.check_dependencies(canonicalize([dep()]))
    assert len(issues) == 1
    assert adapter.check_dependencies(empty_snapshot()) == []


def test_saved_oa_fingerprint_ignores_locks_but_detects_content(tmp_path):
    (tmp_path / "layout.oa").write_bytes(b"first database")
    before = fingerprint(tmp_path)
    (tmp_path / "layout.oa.cdslck").write_text("transient lock")
    assert fingerprint(tmp_path) == before
    (tmp_path / "layout.oa").write_bytes(b"second database")
    assert fingerprint(tmp_path)["sha256"] != before["sha256"]
    assert fingerprint(tmp_path / "absent")["status"] == "unavailable"


def test_git_diff_log_extract_and_configuration_are_repository_local(tmp_path):
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Layout Diff Test")
    git(repo, "config", "user.email", "layout-diff@example.invalid")
    attrs = repo / ".gitattributes"
    attrs.write_text("*.txt text\n")
    setup(repo)
    setup(repo)
    assert attrs.read_text().count("*.layout.json") == 1
    assert attrs.read_text().startswith("*.txt text\n")
    a, b = canonicalize([dep()]), canonicalize([dep("b" * 64)])
    atomic_json(repo / "top.layout.json", a)
    git(repo, "add", ".gitattributes", "top.layout.json")
    git(repo, "commit", "-m", "initial snapshot")
    atomic_json(repo / "top.layout.json", b)
    worktree_diff = git(repo, "diff", "--textconv").decode()
    assert "sha256" in worktree_diff and "a" * 64 in worktree_diff and "b" * 64 in worktree_diff
    git(repo, "add", "top.layout.json")
    staged_diff = git(repo, "diff", "--cached", "--textconv").decode()
    assert "sha256" in staged_diff
    git(repo, "commit", "-m", "child-only edit")
    log = git(repo, "log", "-p", "--textconv", "--", "top.layout.json").decode()
    assert "child-only edit" in log and "fingerprint =" in log
    restored = extract(repo, "HEAD~1", "top.layout.json", tmp_path / "old.json")
    assert restored == a
    assert json.loads(git(repo, "show", "HEAD:top.layout.json")) == b
    child = repo / "subfolder"
    child.mkdir()
    with pytest.raises(ValueError, match="root"):
        setup(child)
    with pytest.raises(ValueError):
        extract(repo, "--help", "top.layout.json", tmp_path / "bad.json")


def test_git_driver_rejects_tampering():
    a = canonicalize([dep()])
    bad = copy.deepcopy(a)
    bad["objects"]["wrong key"] = bad["objects"].pop(next(iter(bad["objects"])))
    with pytest.raises(ValueError):
        textconv(bad)
    commit = diff(empty_snapshot(), a)
    commit["message"] = "altered"
    with pytest.raises(ValueError, match="Corrupt"):
        textconv(commit)


def test_cli_replay_live_check_failure_does_not_block(tmp_path, monkeypatch):
    import sys
    import types
    from layoutdiff.cli import main
    history = History(tmp_path / "history")
    history.init()
    snapshot = canonicalize([dep()])
    history.commit(snapshot)
    class Disconnected:
        @classmethod
        def from_env(cls):
            raise ConnectionError("test bridge unavailable")
    monkeypatch.setitem(sys.modules, "virtuoso_bridge", types.SimpleNamespace(VirtuosoClient=Disconnected))
    output = tmp_path / "replayed.json"
    with pytest.warns(UserWarning, match="unavailable"):
        assert main(["replay", str(history.path), str(output), "--check-dependencies"]) == 0
    assert json.loads(output.read_text()) == snapshot
    assert json.loads(output.with_suffix(".warnings.json").read_text())
