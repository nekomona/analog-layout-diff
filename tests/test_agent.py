"""Agent analysis uses real Git conflicts without modifying Git's authority."""
import copy
import json
from pathlib import Path
import pytest

from layoutdiff.agent.service import AgentService
from layoutdiff.agent import repository as repos
from layoutdiff.data.core import canonicalize, digest
from layoutdiff.data.history import atomic_json, read_json
from layoutdiff.data.storage import from_snapshot
from layoutdiff.git.active_merge import index_entries, cell_paths
from layoutdiff.git.commit import git
from layoutdiff.git.store import snapshot_path
from test_repository_merge import branches, snap, write
from test_active_merge import conflicted

IDENTITY = ['TEST', 'a', 'layout']


@pytest.fixture
def service(tmp_path):
    value = AgentService(tmp_path / 'agent')
    yield value
    value.close()


def test_diff_reports_stretch_once_and_preserves_secondary_connectivity(service, tmp_path):
    repo, _, _ = branches(tmp_path)
    before = snap(10)
    records = list(before['objects'].values())
    rect = next(r for r in records if r['kind'] == 'rect')
    rect['bBox'][1][0] += 30
    rect['net'] = 'N'
    after = canonicalize(records)
    atomic_json(repo / snapshot_path(IDENTITY), after)
    result = service.diff({'repository': str(repo), 'cellview': IDENTITY})
    assert result['raw_operations'] == 2
    assert result['counts']['moved'] == 1
    assert result['total'] == 1
    row, = result['items']
    assert row['status'] == 'moved' and row['correspondence']['inferred']
    assert 'geometry' in row['facets'] and 'connectivity' in row['facets']
    assert row['fields']['net']['before'] == {'present': False}
    assert row['fields']['net']['after'] == {'present': True, 'value': 'N'}
    # Cached details remain bound to the original inputs after an unrelated edit.
    write(repo, 'a', 999)
    repeated = service.diff({'analysis_id': result['analysis_id'], 'layer': 'M1'})
    assert repeated['items'] == result['items']
    assert not service.diff({'analysis_id': result['analysis_id'], 'region': [500,500,600,600]})['items']


@pytest.mark.parametrize('v2', [False, True])
def test_explain_external_merge_reads_parents_and_preserves_index_and_markers(service, tmp_path, v2):
    repo, ours, theirs = conflicted(tmp_path, v2)
    (repo / 'other.txt').write_text('staged')
    git(repo, 'add', 'other.txt')
    (repo / 'other.txt').write_text('unstaged')
    index = (repo / '.git/index').read_bytes()
    files = {str(p.relative_to(repo)): p.read_bytes() for p in (repo / 'layouts').rglob('*') if p.is_file()}
    result = service.merge_explain({'repository': str(repo)})
    assert result['active_merge'] and result['supported']
    assert result['head'] == ours and result['incoming'] == [theirs]
    assert result['ordinary_conflicts'] == ['notes.txt']
    cell = next(c for c in result['cells'] if c['cellview'] == IDENTITY)
    assert cell['unresolved'] == 1
    unit, = cell['units']
    assert unit['evidence'] and unit['reasons']
    assert 'target' in unit['choices'] and 'incoming' in unit['choices']
    assert {r['stage'] for r in cell['index_conflicts']} >= {2, 3}
    assert (repo / '.git/index').read_bytes() == index
    assert files == {str(p.relative_to(repo)): p.read_bytes() for p in (repo / 'layouts').rglob('*') if p.is_file()}
    assert not git(repo, 'worktree', 'list', '--porcelain').stdout.count(b'worktree ') > 1


def test_explain_preserves_already_staged_cell(service, tmp_path):
    repo, _, _ = conflicted(tmp_path)
    git(repo, 'checkout', '--theirs', '--', snapshot_path(IDENTITY))
    git(repo, 'add', snapshot_path(IDENTITY))
    staged = index_entries(repo, cell_paths(IDENTITY))
    result = service.merge_explain({'repository': str(repo), 'cellview': IDENTITY})
    assert result['cells'][0]['status'] == 'not_unmerged'
    assert staged == index_entries(repo, cell_paths(IDENTITY))


@pytest.mark.parametrize('v2', [False, True])
def test_merge_preview_accept_write_leaves_git_index_and_other_files(service, tmp_path, v2):
    repo, ours, theirs = conflicted(tmp_path, v2)
    initial_index = (repo / '.git/index').read_bytes()
    initial = repos.work_hashes(repo, cell_paths(IDENTITY))
    explanation = service.merge_explain({'repository': str(repo), 'cellview': IDENTITY})['cells'][0]
    decisions = {u['id']: 'incoming' for u in explanation['units'] if u['status'] == 'unresolved'}
    args = {'plan_id': explanation['plan_id'], 'generation': 0, 'decisions': decisions}
    preview = service.merge_apply(args)
    assert preview['unresolved'] == 0 and preview['validation'] == 'logical'
    assert repos.work_hashes(repo, cell_paths(IDENTITY)) == initial
    accepted = service.merge_apply({**args, 'mode': 'accept'})
    assert accepted['generation'] == 1
    with pytest.raises(ValueError, match='Stale'):
        service.merge_apply(args)
    with pytest.raises(ValueError, match='Native validation'):
        service.merge_apply({'plan_id': args['plan_id'], 'generation': 1, 'mode': 'write'})
    result = service.merge_apply({'plan_id': args['plan_id'], 'generation': 1, 'mode': 'write', 'native_validation': False})
    assert not result['staged'] and result['git_commit'] is None
    assert repos.worktree_snapshot(repo, IDENTITY)[0] == snap(20)
    assert (repo / '.git/index').read_bytes() == initial_index
    assert repos.commit_id(repo, 'HEAD') == ours and repos.commit_id(repo, 'MERGE_HEAD') == theirs
    assert (repo / 'notes.txt').read_text().startswith('<<<<<<<')


def test_plan_ref_and_managed_file_staleness_blocks_writes(service, tmp_path):
    repo, _, _ = branches(tmp_path)
    plan = service.merge_plan({'repository': str(repo), 'cellview': IDENTITY, 'theirs': 'incoming'})
    write(repo, 'a', 333)
    with pytest.raises(ValueError, match='changed'):
        service.merge_apply({'plan_id': plan['plan_id'], 'generation': 0, 'mode': 'write', 'native_validation': False})
    assert read_json(repo / snapshot_path(IDENTITY)) == snap(333)


def test_invalid_batch_does_not_accept_a_partial_decision(service, tmp_path):
    repo, _, _ = branches(tmp_path)
    plan = service.merge_plan({'repository': str(repo), 'cellview': IDENTITY, 'theirs': 'incoming'})
    args = {'plan_id': plan['plan_id'], 'generation': 0, 'mode': 'accept',
            'decisions': {plan['units'][0]['id']: 'incoming', 'missing': 'target'}}
    with pytest.raises(ValueError, match='Unknown merge decision'):
        service.merge_apply(args)
    assert service.merge_plan({'plan_id': plan['plan_id']})['generation'] == 0


def test_protocol_pages_replay_and_interrupted_request(service):
    calls = []
    service.dispatch = lambda op, p: calls.append((op, p)) or {'text': 'quote " slash \\ and unicode \u4e2d\n' * 400}
    ident = 'request_1'
    (service.requests / (ident + '.request')).write_text('diff\n{}')
    assert service.poll() == 1
    assert service.poll() == 0 and len(calls) == 1
    count = int((service.requests / (ident + '.done')).read_text())
    chunks = [(service.requests / f'{ident}.page.{n}').read_text() for n in range(count)]
    assert count > 1 and all(len(c) <= 2048 for c in chunks)
    assert json.loads(''.join(chunks))['result']['text'].startswith('quote " slash')
    (service.requests / 'crashed.request').write_text('export\n{}')
    (service.requests / 'crashed.running').write_text('old-worker')
    service.recover()
    assert read_json(service.requests / 'crashed.result.json')['status'] == 'unknown'
    assert service.poll() == 0


def test_export_requires_expected_dirty_files_and_detects_source_change(service, tmp_path):
    repo, _, _ = branches(tmp_path)
    class Adapter:
        def capture_store(self, *args, **kw):
            return from_snapshot(snap(45), tmp_path / ('capture-' + str(len(list(tmp_path.glob('capture-*'))))))
    service.adapter = Adapter()
    service.source_state = lambda identity: [True, 3]
    write(repo, 'a', 30)
    with pytest.raises(ValueError, match='local changes'):
        service.export({'repository': str(repo), 'cellview': IDENTITY})
    analysis = service.diff({'repository': str(repo), 'cellview': IDENTITY})
    old_index = (repo / '.git/index').read_bytes()
    out = service.export({'repository': str(repo), 'cellview': IDENTITY, 'expected_worktree': analysis['worktree_digest']})
    assert out['source_state'] == [True, 3]
    assert (repo / '.git/index').read_bytes() == old_index
    assert read_json(repo / snapshot_path(IDENTITY)) == snap(45)
    iterator = iter(([True, 4], [True, 5]))
    service.source_state = lambda identity: next(iterator)
    with pytest.raises(ValueError, match='changed during capture'):
        service.export({'repository': str(repo), 'cellview': IDENTITY, 'expected_worktree': out['worktree_digest']})
    assert read_json(repo / snapshot_path(IDENTITY)) == snap(45)


def test_write_failure_rolls_back_and_preserves_index(service, tmp_path, monkeypatch):
    repo, _, _ = branches(tmp_path)
    before, index = (repo / snapshot_path(IDENTITY)).read_bytes(), (repo / '.git/index').read_bytes()
    replace = repos.os.replace
    def fail(source, destination):
        if Path(destination) == repo / 'layouts/.gitattributes':
            raise OSError('injected publication failure')
        return replace(source, destination)
    monkeypatch.setattr(repos.os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        repos.write_snapshot(repo, IDENTITY, snap(99), repos.guard(repo, IDENTITY), tmp_path / 'write')
    assert (repo / snapshot_path(IDENTITY)).read_bytes() == before
    assert (repo / '.git/index').read_bytes() == index
    assert not (repo / '.git/index.lock').exists()


def test_no_active_merge_and_unknown_operation(service, tmp_path):
    repo, _, _ = branches(tmp_path)
    assert not service.merge_explain({'repository': str(repo)})['active_merge']
    with pytest.raises(ValueError, match='Unknown operation'):
        service.dispatch('eval', {'code': 'anything'})
    with pytest.raises(ValueError):
        service.diff({'repository': str(repo), 'cellview': IDENTITY, 'offset': -1})


def test_plan_pages_reuse_analysis_and_refresh_external_decisions(service, tmp_path):
    from layoutdiff.data.merge_session import MergeSession
    repo, _, _ = branches(tmp_path)
    args = {'repository': str(repo), 'cellview': IDENTITY, 'theirs': 'incoming'}
    plan = service.merge_plan(args)
    ident = plan['plan_id']
    original = service.plans[ident]
    assert service.merge_plan(args) == plan
    assert service.plans[ident] == original
    external = MergeSession(service.root / 'plans' / ident)
    external.decide_many({plan['units'][0]['id']: 'incoming'}, 0)
    refreshed = service.merge_plan({'plan_id': ident})
    assert refreshed['generation'] == 1 and refreshed['unresolved'] == 0
    assert service.plans[ident][0] is not original[0]
