import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
import pytest
from layoutdiff.data.core import canonicalize
from layoutdiff.data.storage import from_snapshot
from layoutdiff.virtuoso.omissions import project, AUDIT, DETAILS
from layoutdiff.virtuoso.support import coverage, checked_records, UnsupportedContentError
from layoutdiff.virtuoso.adapter import normalize
from layoutdiff.ui.worker import GuiWorker
import layoutdiff.git.commit as gc
from layoutdiff.git.store import GitSnapshots, path_identity
from test_oa_content import records as linked_records


def simple():
    return [dict(kind='cell', name='', props=[]),
            dict(kind='rect', layerName='MET1', purpose='drawing', bBox=[[0,0],[100,100]], props=[]),
            dict(kind='unsupported', category='futureObjects', detail='unknown v1', props=[])]


def candidate(tmp_path, records):
    folder = tmp_path / uuid.uuid4().hex
    folder.mkdir()
    full = from_snapshot(canonicalize(list(records)), folder/'full')
    try:
        return project(full, folder/'supported', folder/'report.jsonl')
    finally:
        full.close()


def test_projection_omits_unknown_and_keeps_strict_default(tmp_path):
    source = simple()
    with pytest.raises(UnsupportedContentError):
        list(checked_records(iter(source), tmp_path/'strict.jsonl'))
    out = candidate(tmp_path, source)
    assert out.materialize() == canonicalize(source[:2])
    assert not coverage(out.materialize())
    assert out.omissions['omitted'] == 1
    assert json.loads(out.omission_report.read_text())['record'] == source[-1]
    assert out.source_digest != out.digest
    out.close()


def test_projection_preserves_supported_linked_records_exactly(tmp_path):
    source = normalize(linked_records())
    out = candidate(tmp_path, source['objects'].values())
    assert out.materialize() == source
    assert out.omissions is None
    out.close()


def test_projection_propagates_omission_to_linked_objects_and_groups(tmp_path):
    raw = linked_records()
    raw[1]['props'] = [['unsupported', 'futureType', 1]]
    source = normalize(raw)
    out = candidate(tmp_path, source['objects'].values())
    assert not coverage(out.materialize())
    assert out.omissions['omitted'] == 3  # rectangle, its blockage, containing logical group
    assert {r['kind'] for _, r in out.records()} == {'cell','textDisplay','snapBoundary','sitePattern'}
    out.close()


def test_omitted_figure_group_detaches_and_rekeys_surviving_links(tmp_path):
    raw = linked_records()
    raw[1].update(group='G', groupOrder=0)
    raw += [dict(kind='figGroup', name='G', type='unsupported', props=[], ordered=True, memberCount=1, _captureId=8)]
    out = candidate(tmp_path, normalize(raw)['objects'].values())
    assert not coverage(out.materialize())
    assert out.omissions['omitted'] == 1 and out.omissions['detached'] == 1
    kept = dict(out.records())
    key, rect = next((k,r) for k,r in kept.items() if r['kind']=='rect')
    assert rect['group'] is None and 'groupOrder' not in rect
    blockage = next(r for r in kept.values() if r['kind']=='layerBlockage')
    assert blockage['parent'] == key  # changed anonymous ID propagated
    assert next(r for r in kept.values() if r['kind']=='group')['members']
    out.close()


def test_omitted_member_drops_ordered_group_preserving_other_geometry(tmp_path):
    raw = simple()
    raw[1].update(group='G', groupOrder=0)
    raw[2].update(group='G', groupOrder=1)
    raw += [dict(kind='figGroup', name='G', type='none', ordered=True, memberCount=2, props=[])]
    out = candidate(tmp_path, raw)
    assert out.omissions['omitted'] == 2 and out.omissions['detached'] == 1
    assert not coverage(out.materialize())
    out.close()


def test_detachment_collision_omits_ambiguous_dependents(tmp_path):
    raw = linked_records()
    duplicate = copy.deepcopy(raw[1]); duplicate['_captureId'] = 9; duplicate['group'] = None
    raw[1]['group'] = 'G'
    raw += [duplicate, dict(kind='figGroup', name='G', type='futureGroup', props=[], _captureId=8)]
    out = candidate(tmp_path, normalize(raw)['objects'].values())
    assert not coverage(out.materialize())
    assert sum(r['kind']=='rect' for _,r in out.records()) == 2
    assert out.omissions['omitted'] == 3  # figure group, blockage, logical group
    assert 'ambiguous reference after figure-group detachment' in out.omissions['counts']
    out.close()


def test_source_fingerprint_tracks_unknown_only_changes(tmp_path):
    raw = simple()
    a = candidate(tmp_path, raw)
    raw[-1]['detail'] = 'unknown v2'
    b = candidate(tmp_path, raw)
    assert a.digest == b.digest and a.source_digest != b.source_digest
    assert a.omissions != b.omissions
    a.close(); b.close()


def test_missing_property_reference_and_bus_dependencies_are_omitted(tmp_path):
    raw = linked_records()
    raw[5]['associateProperty'] = ['missing']
    source = normalize(raw)
    out = candidate(tmp_path, source['objects'].values())
    assert not coverage(out.materialize())
    assert out.omissions['omitted'] == 2  # display plus logical group
    out.close()
    raw = simple()
    raw[1]['net'] = 'BUS<1:0>'
    raw.append(dict(kind='net', name='BUS<1:0>', numBits=2, props=[]))
    out = candidate(tmp_path, raw)
    assert out.materialize() == canonicalize(raw[:1])
    assert out.omissions['omitted'] == 3
    out.close()


def test_omitted_primary_pin_does_not_promote_secondary_figure(tmp_path):
    raw = simple()[:2]
    raw += [dict(kind='net', name='N', numBits=1, props=[]),
            dict(kind='term', name='T', net='N', props=[])]
    primary = raw[1]
    primary.update(net='N', pin=dict(term='T', name='P', primary=True, props=[]))
    secondary = copy.deepcopy(primary)
    secondary['bBox'] = [[200,0],[300,100]]
    secondary['pin']['primary'] = False
    primary['props'] = [['bad', 'futureType', 1]]
    raw.append(secondary)
    out = candidate(tmp_path, raw)
    assert out.omissions['omitted'] == 2
    assert not any(r.get('pin') for _, r in out.records())
    assert not coverage(out.materialize())
    out.close()


def test_malformed_storage_not_treated_as_unsupported(tmp_path):
    with pytest.raises(ValueError, match='Duplicate named'):
        candidate(tmp_path, [simple()[0], simple()[0]])
    raw = simple(); raw[0]['props'] = [['bad', 'futureType', 1]]
    with pytest.raises(UnsupportedContentError):
        candidate(tmp_path, raw)


@pytest.fixture
def worker(tmp_path):
    repo = tmp_path/'repo'; repo.mkdir()
    gc.git(repo, 'init')
    gc.git(repo, 'config', 'user.name', 'Omission Test')
    gc.git(repo, 'config', 'user.email', 'omission@example.invalid')
    w = GuiWorker(None, tmp_path/'worker')
    w.source = simple(); w.calls = []
    def execute(expr):
        w.calls.append(expr)
        return 't'
    w.execute = execute
    w.git_repository = lambda: repo
    w.adapter = SimpleNamespace(capture_store=lambda *a, **kw: candidate(tmp_path, copy.deepcopy(w.source)))
    w.identity = ['TEST', 'unknown', 'layout']
    yield w
    w.close()


def start(worker):
    preview = worker.quick_preview(worker.identity)
    return worker.quick_commit(preview['token'], 'Test unknown elements')


def second(worker):
    first = start(worker)
    return worker.quick_omit_continue(first['token'])


@pytest.mark.parametrize('stage', [0,1,2])
def test_reject_at_any_stage_leaves_git_and_saved_source_unchanged(worker, stage):
    original = copy.deepcopy(worker.source)
    if stage == 0:
        result = worker.quick_preview(worker.identity)
    elif stage == 1:
        result = start(worker)
    else:
        result = second(worker)
    worker._dispatch(['quick-cancel', result['token']])
    assert not worker.previews and worker.source == original
    assert gc.revision(worker.git_repository())['head'] is None
    assert not (worker.git_repository()/'layouts').exists()


def test_only_second_confirmation_commits_and_audits(worker):
    first = start(worker)
    assert first['confirmation'] == 1
    assert gc.revision(worker.git_repository())['head'] is None
    with pytest.raises(ValueError, match='expired'):
        worker.quick_omit_confirm(first['token'])
    last = worker.quick_omit_continue(first['token'])
    assert last['confirmation'] == 2 and first['token'] != last['token']
    assert gc.revision(worker.git_repository())['head'] is None
    with pytest.raises(ValueError, match='expired'):
        worker.quick_omit_continue(first['token'])
    commit = worker.quick_omit_confirm(last['token'])
    assert not worker.previews
    with pytest.raises(ValueError, match='expired'):
        worker.quick_omit_confirm(last['token'])
    store = GitSnapshots(worker.git_repository(), worker.identity)
    assert store.snapshot(commit['git_commit']) == canonicalize(worker.source[:2])
    assert store.omissions(commit['git_commit'])['omitted'] == 1
    assert 'explicitly confirmed twice' in commit['message']
    for name in (AUDIT, DETAILS):
        assert path_identity(store.v2+'/'+name) == worker.identity
    store.close()


@pytest.mark.parametrize('change', ['unknown','known','git','unsaved','failure'])
def test_confirmation_revalidates_and_cleans_up(worker, change):
    last = second(worker)
    if change == 'unknown': worker.source[-1]['detail'] = 'new unknown'
    if change == 'known': worker.source[1]['bBox'][1][0] += 1
    if change == 'git':
        gc.git(worker.git_repository(), 'commit', '--allow-empty', '-m', 'other')
    if change == 'unsaved': worker.execute = lambda expr: 'nil'
    if change == 'failure':
        def fail(*a, **kw): raise RuntimeError('capture failed')
        worker.adapter.capture_store = fail
    before = gc.revision(worker.git_repository())['head']
    with pytest.raises((ValueError, RuntimeError)):
        worker.quick_omit_confirm(last['token'])
    assert not worker.previews
    assert gc.revision(worker.git_repository())['head'] == before


def test_supported_commit_skips_prompts_and_removes_old_omission_audit(worker):
    last = second(worker)
    worker.quick_omit_confirm(last['token'])
    worker.source.pop()
    preview = worker.quick_preview(worker.identity)
    result = worker.quick_commit(preview['token'], 'Complete checkpoint')
    store = GitSnapshots(worker.git_repository(), worker.identity)
    assert store.omissions(result['git_commit']) is None
    assert not (worker.git_repository()/store.v2/DETAILS).exists()
    store.close()


def test_unknown_only_change_still_produces_audited_commit(worker):
    last = second(worker); worker.quick_omit_confirm(last['token'])
    unchanged = worker.quick_preview(worker.identity)
    assert unchanged['no_changes']
    worker.source[-1]['detail'] = 'unknown v2'
    last = second(worker)
    result = worker.quick_omit_confirm(last['token'])
    from layoutdiff.ui.browser import HistoryBrowser, RepositoryBrowser
    browser = HistoryBrowser(None, worker.identity, worker.git_repository())
    detail = browser.detail(result['git_commit'])
    assert all(n == 0 for n in detail['counts'].values())
    assert 'INCOMPLETE CHECKPOINT' in detail['summary']
    repository = RepositoryBrowser(worker.git_repository())
    repository.history()
    assert repository.cells(result['git_commit']) == [worker.identity]
    browser.close()
