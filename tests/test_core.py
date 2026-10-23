import copy
import random
import pytest
from layoutdiff.core import canonicalize, diff, apply_diff, empty_snapshot, digest
from layoutdiff.sexpr import loads, dumps


def test_seeded_histories_and_reverse():
    for seed in range(40):
        rng = random.Random(seed)
        records, state, head = [], empty_snapshot(), None
        commits = []
        for step in range(30):
            if records and rng.random() < .45:
                records.pop(rng.randrange(len(records)))
            else:
                records.append({"kind": "rect", "xy": [rng.randrange(4), rng.randrange(4)]})
            next_state = canonicalize(records)
            commit = diff(state, next_state, parent=head)
            assert apply_diff(state, commit, parent=head) == next_state
            assert apply_diff(next_state, commit, parent=head, reverse=True) == state
            commits.append(commit)
            state, head = next_state, commit["id"]
        replay, head = empty_snapshot(), None
        for commit in commits:
            replay = apply_diff(replay, commit, parent=head)
            head = commit["id"]
        assert replay == state


def test_multiplicity_and_order_independence():
    a = {"kind": "rect", "box": [[0, 0], [1, 1]]}
    b = {"kind": "label", "text": '01 "quoted" \\ \n'}
    assert canonicalize([a, b, a]) == canonicalize([a, a, b])
    snap = canonicalize([a, a])
    assert len(snap["objects"]) == 2
    assert len(diff(snap, canonicalize([a]))["operations"]) == 1


def test_tampering_wrong_base_parent_and_atomicity():
    start = empty_snapshot()
    target = canonicalize([{"kind": "net", "name": "OUT", "sigType": "analog"}])
    commit = diff(start, target)
    original = copy.deepcopy(start)
    for bad in [dict(commit, result="bad"), dict(commit, parent="wrong")]:
        with pytest.raises(ValueError):
            apply_diff(start, bad)
    with pytest.raises(ValueError, match="Base"):
        apply_diff(target, commit)
    with pytest.raises(ValueError, match="Parent"):
        apply_diff(start, commit, parent="wrong")
    altered = copy.deepcopy(commit)
    altered["operations"][0]["before"] = {"kind": "net", "name": "fake"}
    altered["id"] = digest({k: v for k, v in altered.items() if k != "id"})
    with pytest.raises(ValueError, match="precondition"):
        apply_diff(start, altered)
    assert start == original


def test_named_changes_are_single_replacements():
    a = canonicalize([{"kind": "inst", "name": "I0", "xy": [0, 0]}])
    b = canonicalize([{"kind": "inst", "name": "I0", "xy": [1, 0]}])
    assert len(diff(a, b)["operations"]) == 1


def test_data_parser_types_escaping_and_truncation():
    assert loads('(nil t "123" 123 1.5 ("x\\n\\\"\\\\"))') == [None, True, "123", 123, 1.5, ['x\n"\\']]
    for text in ['(1 (2)', '(1) (2)', ')']:
        with pytest.raises(ValueError):
            loads(text)
    assert dumps('a"\\\n') == '"a\\\"\\\\\\n"'


def test_nonfinite_and_duplicate_named_objects_rejected():
    with pytest.raises(ValueError):
        canonicalize([{"kind": "rect", "x": float("nan")}])
    with pytest.raises(ValueError):
        canonicalize([{"kind": "net", "name": "x"}] * 2)
