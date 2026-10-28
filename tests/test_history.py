import pytest
from layoutdiff.data.history import History, read_json
from layoutdiff.data.core import canonicalize


def test_append_replay_noop_and_concurrent_writer(tmp_path):
    h = History(tmp_path / "log")
    h.init()
    first = canonicalize([{"kind": "rect", "x": 1}])
    second = canonicalize([{"kind": "rect", "x": 2}])
    c1 = h.commit(first)
    assert h.replay() == first
    assert h.commit(first, expected_head=c1["id"]) is None
    with pytest.raises(ValueError, match="changed"):
        h.commit(second)
    with h.lock():
        with pytest.raises(RuntimeError, match="locked"):
            h.commit(second, expected_head=c1["id"])
    c2 = h.commit(second, expected_head=c1["id"])
    assert h.replay() == second
    assert h.replay(c1["id"]) == first
    assert len(h.chain()) == 2
    assert read_json(h.path / "HEAD") == c2["id"]


def test_corrupt_commit_and_initial_state_rejected(tmp_path):
    h = History(tmp_path / "log")
    h.init()
    commit = h.commit(canonicalize([{"kind": "rect", "x": 1}]))
    (h.path / "commits" / (commit["id"] + ".json")).write_text('{}')
    with pytest.raises(ValueError):
        h.replay()
