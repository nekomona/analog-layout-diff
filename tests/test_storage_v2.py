import copy
import json
import random
import pytest
from layoutdiff.data.core import canonicalize, digest, diff
from layoutdiff.data.storage import from_snapshot, write_records, Snapshot, encoded
from layoutdiff.comparison.changeindex import ChangeIndex
from layoutdiff.comparison.categories import CategoryDiff
import layoutdiff.git.commit as gc
from layoutdiff.git.store import GitSnapshots, snapshot_directory, snapshot_path
from layoutdiff.ui.browser import HistoryBrowser
from test_gitcommit import repo, IDENTITY, snapshot


def test_exact_defaults_definitions_duplicates_unicode_and_bytes(tmp_path):
    records = [{"kind": "rect", "props": [], "net": None, "pin": None, "group": None, "bBox": [[1,2],[3,4]]}] * 15
    records += [{"kind": "inst", "name": "器件" + str(i), "params": [["large", "string", "x" * 400]], "physOnly": False} for i in range(3)]
    records += [{"kind": "cell", "name": "", "nested": [False, 0, 0.0, None, [], "", {"symbol": "foo"}]}]
    state = canonicalize(records)
    a, b = from_snapshot(state, tmp_path / "a"), write_records(reversed(records), tmp_path / "b")
    assert a.materialize() == b.materialize() == state
    assert a.digest == digest(state)
    assert a.wire().read_bytes() == b.wire().read_bytes()
    for file in ("manifest.json", "objects.jsonl", "definitions.jsonl"):
        assert (a.path / file).read_bytes() == (b.path / file).read_bytes()
    assert len((a.path / "definitions.jsonl").read_text().splitlines()) == 1
    a.close(); b.close()


def test_missing_null_empty_and_numeric_types_remain_distinct(tmp_path):
    values = [{"kind": "inst", "name": str(i), **fields} for i, fields in enumerate([
        {}, {"props": None}, {"props": []}, {"physOnly": 0}, {"physOnly": False}, {"net": ""}, {"net": None}])]
    value = canonicalize(values)
    result = from_snapshot(value, tmp_path / "s").materialize()
    assert encoded(result) == encoded(value)


def test_forward_reverse_stream_replay_and_corrupt_patch(tmp_path):
    from layoutdiff.data.streampatch import create, apply
    from layoutdiff.data.core import apply_diff
    before = canonicalize([{"kind": "inst", "name": "M", "v": 0}, {"kind": "rect", "x": 2}])
    after = canonicalize([{"kind": "inst", "name": "M", "v": False}, {"kind": "rect", "x": 4}])
    a, b = from_snapshot(before, tmp_path / "a"), from_snapshot(after, tmp_path / "b")
    assert apply_diff(before, diff(before, after)) == after
    create(a, b, tmp_path / "patch", parent="parent")
    assert apply(a, tmp_path / "patch", tmp_path / "forward", parent="parent").materialize() == after
    assert apply(b, tmp_path / "patch", tmp_path / "reverse", parent="parent", reverse=True).materialize() == before
    with pytest.raises(ValueError, match="Parent"):
        apply(a, tmp_path / "patch", tmp_path / "bad")
    path = tmp_path / "patch/operations.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Corrupt"):
        apply(a, tmp_path / "patch", tmp_path / "bad", parent="parent")
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("damage", ["file", "definition", "count", "duplicate", "presence", "key"])
def test_corrupt_data_rejected(tmp_path, damage):
    state = canonicalize([{"kind": "inst", "name": str(i), "params": [["x", "string", "z" * 300]]} for i in range(2)])
    store = from_snapshot(state, tmp_path / "s")
    objects = store.path / "objects.jsonl"
    if damage == "file": objects.write_bytes(objects.read_bytes() + b" ")
    elif damage == "definition": (store.path / "definitions.jsonl").write_bytes(b"")
    elif damage == "count":
        m = store.manifest; m["objectCount"] += 1
        (store.path / "manifest.json").write_bytes(encoded(m))
    else:
        rows = [json.loads(r) for r in objects.read_text().splitlines()]
        if damage == "duplicate": rows.append(rows[0])
        if damage == "presence": rows[0]["defaults"] = ["notDefined"]
        if damage == "key": rows[0]["key"] = "inst:wrong"
        objects.write_bytes(b"".join(encoded(r) + b"\n" for r in rows))
    with pytest.raises((ValueError, KeyError)):
        Snapshot(store.path).wire()


def test_stream_diff_and_disk_categories_match_golden(tmp_path):
    rng = random.Random(417)
    for step in range(12):
        before = canonicalize([{"kind": "rect", "layerName": "MET1", "bBox": [[i,0],[i+1,1]], "props": []} for i in range(70)])
        records = copy.deepcopy(list(before["objects"].values()))
        for r in rng.sample(records, 20): r["props"] = [["x", "int", step]]
        records += records[:3]
        after = canonicalize(records[2:])
        a, b = from_snapshot(before, tmp_path / f"a{step}"), from_snapshot(after, tmp_path / f"b{step}")
        changes = ChangeIndex(a, b)
        expected = diff(before, after)["operations"]
        assert list(changes.operations()) == expected
        reference = CategoryDiff(expected)
        assert changes.rows == reference.rows
        assert changes.page(0, 0) == reference.page(0, 0)
        assert "".join(changes.full()) == "".join(reference.full())
        changes.close(); a.close(); b.close()


def test_v2_migration_lazy_history_and_git_isolation(repo, tmp_path):
    old = gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "v1")
    current = from_snapshot(snapshot(1), tmp_path / "current")
    (repo / "unrelated").write_text("staged")
    gc.git(repo, "add", "unrelated")
    staged = gc.git(repo, "ls-files", "--stage", "unrelated").stdout
    preview = gc.prepare(repo, IDENTITY, current)
    assert preview["adopting"] and not preview["operations"]
    committed = gc.commit(preview, "Explicit v2 migration")
    preview.close()
    assert not (repo / snapshot_path(IDENTITY)).exists()
    assert (repo / snapshot_directory(IDENTITY) / "objects.jsonl").exists()
    assert gc.git(repo, "ls-files", "--stage", "unrelated").stdout == staged
    model = HistoryBrowser(None, IDENTITY, repo)
    assert len(model.commits) == 2 and not model.store._states
    assert model.rows(lazy=True)[0][-3:] == ["...", "...", "..."]
    assert model.pair(committed["git_commit"]) == (snapshot(1), snapshot(1))
    assert model.pair(old["git_commit"])[1] == snapshot(1)
    assert model.detail(committed["git_commit"])["counts"] == {"added": 0, "modified": 0, "deleted": 0, "modified_net": 0, "moved": 0}
    model.close(); current.close()
    p = gc.prepare(repo, IDENTITY, snapshot(2))
    assert isinstance(p, gc.Prepared)
    gc.commit(p, "Legacy API retains v2 format")
    p.close()
    assert not (repo / snapshot_path(IDENTITY)).exists()


def test_sequential_stream_history_from_empty(tmp_path):
    from layoutdiff.data.streampatch import create, apply
    from layoutdiff.data.core import empty_snapshot
    previous = from_snapshot(empty_snapshot(), tmp_path / "initial")
    parent = None
    for step in range(8):
        state = canonicalize([{"kind": "cell", "name": "", "step": step}] +
            [{"kind": "rect", "bBox": [[i, 0], [i+1, step+1]], "props": []} for i in range(step, 25)] +
            [{"kind": "rect", "x": 1}] * (step % 4))
        current = from_snapshot(state, tmp_path / f"s{step}")
        create(previous, current, tmp_path / f"p{step}", parent=parent, backend="python")
        result = apply(previous, tmp_path / f"p{step}", tmp_path / f"r{step}", parent=parent, backend="python")
        assert encoded(result.materialize()) == encoded(state)
        previous.close(); current.close()
        previous, parent = result, str(step)
    previous.close()


def test_v2_failure_rolls_back_deleted_v1_and_preserves_index(repo, tmp_path, monkeypatch):
    gc.commit(gc.prepare(repo, IDENTITY, snapshot(1)), "v1")
    old_index = (repo / ".git/index").read_bytes()
    current = from_snapshot(snapshot(2), tmp_path / "current")
    preview = gc.prepare(repo, IDENTITY, current)
    original = gc.git
    def reject(root, *args, **kwargs):
        if args[0] == "commit": raise RuntimeError("rejected")
        return original(root, *args, **kwargs)
    monkeypatch.setattr(gc, "git", reject)
    with pytest.raises(RuntimeError, match="rejected"): gc.commit(preview, "v2")
    assert json.loads((repo / snapshot_path(IDENTITY)).read_bytes()) == snapshot(1)
    assert not (repo / snapshot_directory(IDENTITY)).exists()
    assert (repo / ".git/index").read_bytes() == old_index
    preview.close(); current.close()


def test_patch_accepts_two_large_records_without_weakening_snapshot_limit(tmp_path, monkeypatch):
    import layoutdiff.data.storage as storage
    from layoutdiff.data.streampatch import create, apply
    monkeypatch.setattr(storage, "MAX_LINE", 32768)
    a = write_records([{"kind": "inst", "name": "I", "payload": "a" * 20000}], tmp_path / "a")
    b = write_records([{"kind": "inst", "name": "I", "payload": "b" * 20000}], tmp_path / "b")
    create(a, b, tmp_path / "patch", backend="python")
    assert (tmp_path / "patch/operations.jsonl").stat().st_size > storage.MAX_LINE
    rebuilt = apply(a, tmp_path / "patch", tmp_path / "rebuilt", backend="python")
    assert rebuilt.digest == b.digest
    with pytest.raises(ValueError, match="limit"):
        write_records([{"kind": "inst", "name": "I", "payload": "x" * 40000}], tmp_path / "oversize")
    a.close(); b.close(); rebuilt.close()
