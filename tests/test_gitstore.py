import json
import random
import pytest
from layoutdiff import gitcommit as gc
from layoutdiff import gitstore as gs
from layoutdiff.core import canonicalize, empty_snapshot, diff, apply_diff
from layoutdiff.browser import HistoryBrowser
from layoutdiff.history import History, atomic_json
from test_gitcommit import repo, IDENTITY, snapshot


def test_ordinary_git_commits_multiple_cells_and_worktree_isolation(repo):
    a = gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "First")
    other = ["TEST", "second", "layout"]
    for identity in (IDENTITY, other):
        path = repo / gs.snapshot_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gc.json_bytes(snapshot(2)))
    gc.git(repo, "add", "layouts")
    gc.git(repo, "commit", "-m", "Two cells through ordinary Git")
    changed = gs.head(repo)
    gc.git(repo, "commit", "--allow-empty", "-m", "Unrelated commit")
    (repo / gs.snapshot_path(IDENTITY)).write_text("uncommitted invalid JSON")
    index = (repo / ".git/index").read_bytes()
    model = HistoryBrowser(None, IDENTITY, repo)
    assert [c["id"] for c in model.commits] == [changed, a["git_commit"]]
    assert model.pair(changed) == (snapshot(1), snapshot(2))
    assert len(model.detail(changed)["files"]) == 2
    assert model.rows()[0][-4:] == [0, 1, 0, 0]
    assert gs.sources(repo) == [other, IDENTITY]
    assert (repo / ".git/index").read_bytes() == index


def test_legacy_git_migration_reads_blobs_without_custom_chain(repo):
    folder = gc.history_path(repo, IDENTITY)
    history = History(folder)
    history.init()
    atomic_json(folder / "source.json", IDENTITY)
    for value in (1, 2):
        old = history.commit(snapshot(value), f"Legacy {value}", expected_head=json.loads((folder / "HEAD").read_text()))
        atomic_json(folder / "latest.layout.json", snapshot(value))
        gc.git(repo, "add", ".layoutdiff")
        gc.git(repo, "commit", "-m", f"Legacy {value}")
    legacy_head = gs.head(repo)
    legacy_bytes = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    p = gc.prepare(repo, IDENTITY, snapshot(2))
    assert p["adopting"] and p["operations"] == 0 and p["write_required"]
    adopted = gc.commit(p, "Adopt Git snapshots")
    assert all(name.startswith("layouts/") for name in adopted["files"])
    assert {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == legacy_bytes
    # A missing local custom chain cannot affect Git-backed browsing.
    (folder / "commits" / (old["id"] + ".json")).unlink()
    model = HistoryBrowser(None, IDENTITY, repo)
    assert len(model.commits) == 3
    assert model.pair(legacy_head) == (snapshot(1), snapshot(2))
    assert model.rows()[0][-4:] == [0, 0, 0, 0]
    assert not gc.prepare(repo, IDENTITY, snapshot(2))["write_required"]
    # A later deletion must not resurrect the archived latest snapshot.
    gc.git(repo, "rm", "--", gs.snapshot_path(IDENTITY))
    gc.git(repo, "commit", "-m", "Delete snapshot")
    model = HistoryBrowser(None, IDENTITY, repo)
    assert model.pair(gs.head(repo)) == (snapshot(2), empty_snapshot())
    assert model.rows()[0][-4:] == [0, 0, 1, 0]
    assert IDENTITY in gs.sources(repo)


def test_paths_roundtrip_special_names_and_case_collisions(repo):
    for identity in (["../TEST", "a/b %:*", "布局"], ["CON", "..", "layout."], IDENTITY):
        path = gs.snapshot_path(identity)
        assert gs.path_identity(path) == identity
        assert len(path.split("/")) == 4
        gc.commit(gc.prepare(repo, identity, snapshot(1)), "Special identity")
        assert GitSnapshot(repo, identity) == snapshot(1)
    with pytest.raises(ValueError, match="case-insensitive"):
        gc.prepare(repo, ["test", "top", "layout"], snapshot(2))


def GitSnapshot(repo, identity):
    store = gs.GitSnapshots(repo, identity)
    return store.snapshot(store.head)


def test_shared_attributes_stale_preview_and_no_automatic_merge(repo):
    p = gc.prepare(repo, IDENTITY, snapshot(1))
    attrs = repo / "layouts/.gitattributes"
    attrs.parent.mkdir()
    attrs.write_text("user work\n")
    with pytest.raises(ValueError, match="uncommitted"):
        gc.commit(p, "Must not overwrite attributes")
    assert attrs.read_text() == "user work\n"
    attrs.unlink()
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "First")
    attr = gc.git(repo, "check-attr", "merge", "--", gs.snapshot_path(IDENTITY)).stdout
    assert b"unset" in attr


def test_random_git_versions_replay_derived_diffs_from_empty(repo):
    rng = random.Random(731)
    expected = []
    for step in range(12):
        records = [{"kind": "cell", "name": "", "props": [["step", "int", step]]}]
        records += [{"kind": "rect", "bBox": [[x, 0], [x + 2, rng.randrange(1, 40)]]}
                    for x in rng.sample(range(30), rng.randrange(1, 10))]
        value = canonicalize(records)
        gc.commit(gc.prepare(repo, IDENTITY, value), f"Random {step}")
        expected.append(value)
    store = gs.GitSnapshots(repo, IDENTITY)
    state, parent = empty_snapshot(), None
    for rev, expected_state in zip(reversed(store.revisions()), expected):
        before, after = store.pair(rev)
        patch = diff(before, after, parent=parent)
        state = apply_diff(state, patch, parent=parent)
        assert state == expected_state
        parent = patch["id"]
    assert not (repo / ".layoutdiff").exists()


def test_first_parent_comparison_for_external_merge(repo):
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "Initial")
    branch = gc.revision(repo)["branch"]
    gc.git(repo, "checkout", "-b", "side")
    (repo / "notes").write_text("other branch")
    gc.git(repo, "add", "notes")
    gc.git(repo, "commit", "-m", "Side notes")
    gc.git(repo, "checkout", branch.removeprefix("refs/heads/"))
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(2)), "Main layout")
    gc.git(repo, "merge", "--no-ff", "side", "-m", "External merge")
    store = gs.GitSnapshots(repo, IDENTITY)
    assert store.pair(store.head) == (snapshot(2), snapshot(2))
    assert len(store.revisions()) == 2
