import copy
import random
import pytest
from layoutdiff.data.core import canonicalize, empty_snapshot, digest
from layoutdiff.data.merge import MergePlan, merge_record
from layoutdiff.data.merge_session import MergeSession


def rect(x=0, **extra):
    return {'kind': 'rect', 'layerName': 'MET1', 'purpose': 'drawing',
            'bBox': [[x, 0], [x+100, 100]], 'props': [], **extra}


def snap(*records):
    return canonicalize([{'kind': 'cell', 'name': '', 'dbu': 1000, 'units': 'micron',
                          'technology': 'TEST_TECH', 'props': []}, *records])


def test_one_branch_change_and_unchanged_preserve_exact_states():
    base = snap(rect(), rect(800))
    target = snap(rect(20), rect(800))
    for t, i in ((target, base), (base, target), (base, base)):
        p = MergePlan(base, t, i)
        assert not p.unresolved()
        assert p.result() == (target if t != i else base)


def test_two_moves_require_explicit_inferred_identity_choice():
    b, t, i = snap(rect()), snap(rect(20)), snap(rect(40))
    p = MergePlan(b, t, i)
    assert len(p.unresolved()) == 1
    ident = p.unresolved()[0]
    assert p.units[ident]['evidence']
    assert p.result({ident: 'target'}) == t
    assert p.result({ident: 'incoming'}) == i
    assert p.result({ident: 'base'}) == b
    assert p.result({ident: 'both'}) == snap(rect(20), rect(40))


def test_named_independent_properties_combine_but_geometry_is_atomic():
    b = {'kind': 'inst', 'name': 'I0', 'origin': [0, 0], 'orient': 'R0', 'props': []}
    t = {**b, 'props': [['a', 'int', 1]]}
    i = {**b, 'props': [['b', 'int', 2]]}
    r, reasons = merge_record(b, t, i)
    assert not reasons and r['props'] == [['a', 'int', 1], ['b', 'int', 2]]
    assert merge_record(b, {**b, 'origin': [10, 0]}, {**b, 'orient': 'R90'})[1]
    assert merge_record(b, None, t)[1] == ['delete/modify']


def test_property_deletion_missing_null_and_type_conflicts():
    b = {'kind': 'net', 'name': 'N', 'props': [['x', 'int', 1]], 'sigType': None}
    t = {**b, 'props': []}
    i = {**b, 'sigType': 'signal'}
    assert merge_record(b, t, i) == ({**i, 'props': []}, [])
    assert merge_record(b, {**b, 'props': [['x', 'int', 2]]},
                        {**b, 'props': [['x', 'string', '2']]})[1]


def test_concurrent_identical_additions_are_not_silently_deduplicated():
    p = MergePlan(snap(), snap(rect()), snap(rect()))
    ident, = p.unresolved()
    assert p.result({ident: 'both'}) == snap(rect(), rect())
    assert p.result({ident: 'target'}) == snap(rect())


def test_coordinate_system_change_cannot_mix_other_branch_geometry():
    b = snap(rect())
    t = copy.deepcopy(b); t['objects']['cell:']['dbu'] = 2000; t = canonicalize(list(t['objects'].values()))
    i = snap(rect(20))
    p = MergePlan(b, t, i)
    ident, = p.unresolved()
    assert p.result({ident: 'target'}) == t
    assert p.result({ident: 'incoming'}) == i


def test_random_one_sided_edits_reconstruct_exactly():
    rng = random.Random(137)
    for _ in range(30):
        records = [rect(i*400) for i in range(12)]
        base = snap(*records)
        del records[rng.randrange(len(records))]
        records.append(rect(rng.randrange(10000, 20000)))
        target = snap(*records)
        p = MergePlan(base, target, base)
        assert not p.unresolved() and p.result() == target


def test_durable_decisions_undo_redo_stale_requests_and_tampering(tmp_path):
    path = tmp_path/'merge'
    s = MergeSession.create(path, snap(rect()), snap(rect(20)), snap(rect(40)))
    ident, = s.unresolved()
    before = s.snapshot
    candidate = s.preview(ident, 'incoming', 0)
    assert s.snapshot == before and s.unresolved()
    s.decide(ident, 'incoming', 0, validated_digest=digest(candidate))
    assert not s.unresolved() and s.snapshot == candidate
    loaded = MergeSession(path)
    assert loaded.snapshot == candidate and loaded.generation == 1
    with pytest.raises(ValueError, match='Stale'):
        loaded.decide(ident, 'target', 0)
    loaded.undo(1)
    assert loaded.snapshot == before and loaded.unresolved()
    loaded.undo(2, redo=True)
    assert MergeSession(path).snapshot == candidate
    (path/'events'/(loaded.head+'.json')).write_text('{}')
    with pytest.raises(ValueError, match='Corrupt'):
        MergeSession(path)


def test_orphan_event_is_not_a_committed_decision(tmp_path):
    s = MergeSession.create(tmp_path/'s', snap(rect()), snap(rect(20)), snap(rect(40)))
    (s.path/'events'/('a'*64+'.json')).write_text('{not json}')
    assert MergeSession(s.path).generation == 0


def test_manual_edit_and_undo_are_recorded_without_losing_other_geometry(tmp_path):
    s = MergeSession.create(tmp_path/'s', snap(rect()), snap(rect(20)), snap(rect(40)))
    ident, = s.unresolved()
    s.accept_edits(snap(rect(30), rect(800)), ident, 0)
    assert not s.unresolved() and s.snapshot == snap(rect(30), rect(800))
    with pytest.raises(ValueError, match='overlaps custom'):
        s.preview(ident, 'target', 1)
    s.undo(1)
    assert s.snapshot == snap(rect())
    s.undo(2, redo=True)
    assert MergeSession(s.path).snapshot == snap(rect(30), rect(800))


def test_two_workers_cannot_overwrite_each_others_decisions(tmp_path):
    first = MergeSession.create(tmp_path/'s', snap(rect()), snap(rect(20)), snap(rect(40)))
    second = MergeSession(first.path)
    ident, = first.unresolved()
    first.decide(ident, 'target', 0)
    with pytest.raises(ValueError, match='Stale'):
        second.decide(ident, 'incoming', 0)
    assert MergeSession(first.path).snapshot == snap(rect(20))


def test_abandoned_preview_does_not_create_journal_events(tmp_path):
    s = MergeSession.create(tmp_path/'s', snap(rect()), snap(rect(20)), snap(rect(40)))
    ident, = s.unresolved()
    s.preview(ident, 'target', 0)
    assert not list((s.path/'events').iterdir())
    assert MergeSession(s.path).unresolved() == [ident]
