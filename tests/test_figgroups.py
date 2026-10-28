import copy
import json
import pytest
from layoutdiff.data.core import canonicalize, diff, apply_diff, empty_snapshot
from layoutdiff.virtuoso.adapter import coverage, render, VirtuosoAdapter
from layoutdiff.virtuoso.support import checked_records, UnsupportedContentError
from layoutdiff.data.storage import write_records
from layoutdiff.comparison.review import classify


def fixture():
    return [
        {"kind": "cell", "name": "", "dbu": 1000, "units": "micron", "cellType": "maskLayout", "props": []},
        {"kind": "figGroup", "name": "outer", "ordered": True, "type": "none", "origin": [2000, 3000], "orient": "R90", "memberCount": 3},
        {"kind": "figGroup", "name": "inner", "ordered": True, "type": "none", "origin": [0, 0], "orient": "R0", "memberCount": 1, "group": "outer", "groupOrder": 1},
        *[{"kind": "rect", "layerName": "MET1", "purpose": "drawing", "bBox": [[0, 0], [1000, 1000]], "group": "outer", "groupOrder": n} for n in (2, 0)],
        {"kind": "rect", "layerName": "MET2", "purpose": "drawing", "bBox": [[0, 0], [1000, 1000]], "group": "inner", "groupOrder": 0},
    ]


def test_ordered_nested_groups_survive_storage_diff_and_deferred_attachment(tmp_path):
    records = fixture()
    snapshot = canonicalize(records)
    assert not coverage(snapshot)
    assert write_records(checked_records(iter(records), tmp_path / 'issues.jsonl'), tmp_path / 'v2').materialize() == snapshot
    assert not (tmp_path / 'issues.jsonl').exists()
    newer = copy.deepcopy(records)
    newer[3]['groupOrder'], newer[4]['groupOrder'] = 0, 2
    newer[3]['bBox'][0][0] = 500  # distinguish previously identical members
    after = canonicalize(newer)
    patch = diff(snapshot, after)
    assert apply_diff(snapshot, patch) == after
    assert apply_diff(after, patch, reverse=True) == snapshot
    code = render(snapshot)
    assert 'dbCreateFigGroup(cv "outer" t list(2.0 3.0) "R90")' in '\n'.join(code)
    attachments = [c for c in code if 'dbAddFigToFigGroup' in c]
    assert code.index(attachments[0]) > max(i for i, c in enumerate(code) if c.startswith('o='))
    expected = [k for k, r in sorted(snapshot['objects'].items(), key=lambda kv: (kv[1].get('group', ''), kv[1].get('groupOrder', 0))) if r.get('group')]
    assert all('figures["' + key + '"]' in cmd for key, cmd in zip(expected, attachments))


@pytest.mark.parametrize('fault', ['missing_count', 'missing_order', 'duplicate_order', 'missing_member', 'missing_group', 'negative_order', 'boolean_order', 'special_type'])
def test_incomplete_ordered_groups_fail_before_reconstruction(tmp_path, fault):
    records = fixture()
    if fault == 'missing_count': del records[1]['memberCount']
    elif fault == 'missing_order': del records[3]['groupOrder']
    elif fault == 'duplicate_order': records[3]['groupOrder'] = 0
    elif fault == 'missing_member': records.pop()
    elif fault == 'missing_group': records[3]['group'] = 'absent'
    elif fault == 'negative_order': records[3]['groupOrder'] = -1
    elif fault == 'boolean_order': records[3]['groupOrder'] = True
    else: records[1]['type'] = 'modgen'
    snap = canonicalize(records)
    assert coverage(snap)
    with pytest.raises(UnsupportedContentError):
        write_records(checked_records(iter(records), tmp_path / 'issues.jsonl'), tmp_path / 'rejected')
    assert not (tmp_path / 'rejected').exists()
    class NoCalls:
        def __getattr__(self, name): raise AssertionError(name)
    with pytest.raises(ValueError, match='faithfully'):
        VirtuosoAdapter(NoCalls(), tmp_path).reconstruct(snap, 'LAYOUT_DIFF_TEST', 'never_created')


def test_legacy_unordered_group_and_empty_ordered_group_remain_supported():
    records = fixture()[:2]
    records[1]['memberCount'] = 0
    assert not coverage(canonicalize(records))
    records[1]['ordered'] = None
    del records[1]['memberCount']
    assert not coverage(canonicalize(records))


def test_group_reordering_highlights_only_group_boundaries():
    records = fixture()
    records[3]['bBox'][0][0] = 500
    before = canonicalize(records)
    records[3]['groupOrder'], records[4]['groupOrder'] = 0, 2
    changes = classify(before, canonicalize(records))
    assert changes['counts'] == {'untouched': 3, 'changed': 0, 'moved': 0, 'netChanged': 0, 'new': 0}
    assert any(g['status'] == 'changed' for g in changes['group_changes'])
    assert not changes['removed']


def test_all_categories_and_every_element_are_reported_without_partial_store(tmp_path):
    records = [{'kind': 'unsupported', 'category': f'category-{i}', 'props': []} for i in range(25)]
    records += [records[0]] * 40
    records += [{'kind': 'net', 'name': 'bus', 'numBits': 8}]
    records += [{'kind': 'rect', 'props': [['hier', 'hierProp', [['child', 'opaque', 0]]]],
                 'pin': {'props': [['pin', 'opaquePin', 0]]}}]
    records += [{'kind': 'inst', 'name': 'I0', 'connections': [['P', 'N', [['p', 'opaqueTerm', 0]]]]}]
    seen = []
    def source():
        for r in records:
            seen.append(r)
            yield r
    report = tmp_path / 'issues.jsonl'
    with pytest.raises(UnsupportedContentError) as exc:
        write_records(checked_records(source(), report), tmp_path / 'rejected')
    assert len(seen) == len(records)
    assert len(exc.value.counts) == 29
    assert exc.value.counts['unsupported collection: category-0'] == 41
    assert 'category-24' in str(exc.value) and 'opaqueTerm' in str(exc.value)
    details = [json.loads(line) for line in report.read_text().splitlines()]
    assert len(details) == len(records)
    assert len({row['element'] for row in details}) == len(records)
    assert not (tmp_path / 'rejected').exists()


def test_reconstruction_errors_do_not_truncate_after_twelve_objects(tmp_path):
    snap = canonicalize([{'kind': 'unsupported', 'category': f'category-{i:02}'} for i in range(20)])
    with pytest.raises(ValueError) as exc:
        VirtuosoAdapter(None, tmp_path).reconstruct(snap, 'LAYOUT_DIFF_TEST', 'unused')
    assert all(f'category-{i:02}' in str(exc.value) for i in range(20))


@pytest.mark.parametrize("categories", [90, 200])
def test_gui_coverage_report_is_not_truncated_to_six_kilobytes(tmp_path, categories):
    from types import SimpleNamespace
    from layoutdiff.ui.worker import GuiWorker
    from layoutdiff.virtuoso.sexpr import dumps as sk
    counts = {f'unsupported category {i:03} with a long diagnostic description': 1 for i in range(categories)}
    report = tmp_path / 'all.jsonl'
    report.write_text('{}\n')
    failure = UnsupportedContentError(counts, report)
    client = SimpleNamespace(layoutdiff_local_files=True, layoutdiff_scratch=lambda name: '/tmp/' + name,
        upload_file=lambda *args: SimpleNamespace(status='success', output='t'))
    worker = GuiWorker(client, tmp_path / 'worker')
    sent = []
    def execute(code):
        sent.append(code)
        return '(("quick-preview" "lib" "cell" "layout"))' if code.startswith('ALDGUIPoll') else 't'
    def fail(request): raise failure
    worker.execute, worker.dispatch = execute, fail
    assert worker.poll() == 1
    shown = next(code for code in sent if code.startswith('ALDGUIUnsupported'))
    if categories == 90:
        assert len(shown) > 6000 and all(reason in shown for reason in counts)
    else:
        summary = report.with_suffix('.summary.txt').read_text()
        assert all(reason in summary for reason in counts)
        assert '/transport/all.summary.txt' in shown and 'ald-session-' in shown
    audit = json.loads(next((worker.root / 'requests').glob('*.json')).read_text())
    assert audit['unsupported_counts'] == counts and 'notification_error' not in audit


def test_unsupported_group_members_do_not_mask_the_underlying_category(tmp_path):
    records = fixture()[:2]
    records[1]['memberCount'] = 1
    records.append({'kind': 'unsupported', 'category': 'routes', 'group': 'outer', 'groupOrder': 0})
    with pytest.raises(UnsupportedContentError) as exc:
        list(checked_records(iter(records), tmp_path / 'issues.jsonl'))
    assert exc.value.counts == {'unsupported collection: routes': 1}
