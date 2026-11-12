"""Headless persistence, native subprocess boundaries and omission consent."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from layoutdiff.agent.service import AgentService
from layoutdiff.agent import repository as repos
from layoutdiff.data.core import digest
from layoutdiff.data.history import atomic_json
from layoutdiff.data.storage import from_snapshot
from layoutdiff.eda.virtuoso.batch import BatchAdapter
from layoutdiff.eda.virtuoso.sexpr import dumps as sk
from layoutdiff.git.commit import git
from layoutdiff.git.store import snapshot_directory
from test_repository_merge import branches, snap, write

IDENTITY = ['TEST', 'a', 'layout']


def test_pinned_diff_pages_survive_process_lifetime_and_detect_corruption(tmp_path):
    repo, _, _ = branches(tmp_path)
    write(repo, 'a', 50)
    root = tmp_path / 'agent'
    service = AgentService(root, durable_diffs=True)
    page = service.diff({'repository': str(repo), 'cellview': IDENTITY, 'limit': 1})
    service.close()
    write(repo, 'a', 90)
    service = AgentService(root, durable_diffs=True)
    try:
        resumed = service.diff({'analysis_id': page['analysis_id'], 'limit': 1})
        assert resumed['items'] == page['items'] and resumed['digests'] == page['digests']
        assert Path(resumed['exact_operations']).is_file()
    finally:
        service.close()
    manifest = Path(page['inputs']) / 'after/objects.jsonl'
    manifest.write_text('{}\n')
    service = AgentService(root, durable_diffs=True)
    try:
        with pytest.raises(ValueError):
            service.diff({'analysis_id': page['analysis_id']})
    finally:
        service.close()


def test_batch_subprocess_clears_display_and_requires_completion(tmp_path, monkeypatch):
    monkeypatch.setenv('DISPLAY', 'unusable-display')
    monkeypatch.setenv('CDS_NOGRAPH_DISPLAY', 'also-unusable')
    fake = tmp_path / 'fake.py'
    record = {'kind': 'cell', 'name': '', 'dbu': 1000, 'technology': 'TEST', 'props': []}
    def sexpr(value):
        return '(' + ' '.join(map(sexpr, value)) + ')' if isinstance(value, list) else sk(value)
    transport = sexpr([[k, v] for k, v in record.items()]) + '\n'
    fake.write_text('import os,sys\nfrom pathlib import Path\n'
        'assert "DISPLAY" not in os.environ and "CDS_NOGRAPH_DISPLAY" not in os.environ\n'
        'assert "-nograph" in sys.argv and "-nocdsinit" in sys.argv\n'
        'folder=Path(sys.argv[-1]).parent\n'
        f'(folder/"capture.sexpr").write_text({transport!r})\n'
        '(folder/"hierarchy.sexpr").write_text("")\n'
        '(folder/"complete").write_text("ok")\n')
    original = subprocess.Popen
    def execute(command, **kwargs):
        return original([sys.executable, str(fake), *command[1:]], **kwargs)
    monkeypatch.setattr('layoutdiff.eda.virtuoso.batch.subprocess.Popen', execute)
    adapter = BatchAdapter('fake-virtuoso', tmp_path, tmp_path / 'jobs')
    value = adapter.capture('TEST', 'a')
    assert value['objects']['cell:']['technology'] == 'TEST'
    fake.write_text('pass\n')
    with pytest.raises(RuntimeError, match='process.log'):
        adapter.capture('TEST', 'a')
    fake.write_text('import time\ntime.sleep(10)\n')
    adapter.timeout = .1
    with pytest.raises(RuntimeError, match='timed out'):
        adapter.capture('TEST', 'a')


def test_incomplete_export_requires_digest_bound_consent_and_retains_report(tmp_path):
    from layoutdiff.eda.virtuoso.omissions import project
    repo, _, _ = branches(tmp_path)
    class Adapter:
        def capture_store(self, *args, **options):
            assert options['allow_unsupported'] is True
            folder = tmp_path / ('capture-' + str(len(list(tmp_path.glob('capture-*')))))
            full = from_snapshot(snap(35), folder / 'full')
            try:
                result = project(full, folder / 'supported', folder / 'report.jsonl')
            finally:
                full.close()
            # An independently captured diagnostic record can be omitted.
            raw = b'{"synthetic":"unsupported native record"}\n'
            result.omission_report.write_bytes(raw)
            result.omissions = dict(schema='analog-layout-diff/omissions/1', sourceSha256='synthetic',
                snapshotSha256=result.digest, omitted=1, detached=0, counts={'newKind': 1},
                reportSha256=hashlib.sha256(raw).hexdigest())
            return result
    service = AgentService(tmp_path / 'agent', adapter=Adapter())
    before_index = (repo / '.git/index').read_bytes()
    before_files = repos.work_hashes(repo, repos.paths(IDENTITY))
    args = {'repository': str(repo), 'cellview': IDENTITY, 'allow_incomplete': True}
    try:
        preview = service.export(args)
        assert preview['written'] is False and preview['omissions']['omitted'] == 1
        assert repos.work_hashes(repo, repos.paths(IDENTITY)) == before_files
        again = service.export({**args, 'omission_consent': 'invalid'})
        assert again['written'] is False
        result = service.export({**args, 'omission_consent': preview['omission_consent_required']})
        assert not result['staged'] and result['git_commit'] is None
        directory = repo / snapshot_directory(IDENTITY)
        audit = json.loads((directory / 'omissions.json').read_bytes())
        assert audit['snapshotSha256'] == digest(snap(35))
        assert audit['reportSha256'] == hashlib.sha256((directory / 'omissions.jsonl').read_bytes()).hexdigest()
        assert (repo / '.git/index').read_bytes() == before_index
    finally:
        service.close()


def test_inherited_merge_audit_is_preserved_without_gui(tmp_path):
    repo, _, _ = branches(tmp_path)
    git(repo, 'checkout', 'incoming')
    from layoutdiff.git.store import snapshot_path
    folder = repo / snapshot_directory(IDENTITY)
    store = from_snapshot(snap(20), folder); store.close()
    (repo / snapshot_path(IDENTITY)).unlink()
    raw = b'{"synthetic":"inherited diagnostic"}\n'
    audit = dict(schema='analog-layout-diff/omissions/1', sourceSha256='synthetic',
        snapshotSha256=digest(snap(20)), omitted=1, detached=0, counts={'unknown': 1},
        reportSha256=hashlib.sha256(raw).hexdigest())
    atomic_json(folder / 'omissions.json', audit)
    (folder / 'omissions.jsonl').write_bytes(raw)
    git(repo, 'add', '--all'); git(repo, 'commit', '-m', 'incomplete incoming checkpoint')
    git(repo, 'checkout', 'target')
    git(repo, 'merge', '--no-ff', '--no-commit', 'incoming', check=False)
    service = AgentService(tmp_path / 'agent')
    before = (repo / '.git/index').read_bytes()
    try:
        plan = service.merge_explain({'repository': str(repo), 'cellview': IDENTITY})['cells'][0]
        # Plans from the earlier agent version retained only the audit metadata.
        (service.root / 'plans' / plan['plan_id'] / 'omissions' / (audit['reportSha256'] + '.jsonl')).unlink()
        decisions = {u['id']: 'incoming' for u in plan['units'] if u['status'] == 'unresolved'}
        args = dict(plan_id=plan['plan_id'], generation=0, mode='write', decisions=decisions, native_validation=False)
        preview = service.merge_apply(args)
        assert preview['written'] is False
        result = service.merge_apply({**args, 'omission_consent': preview['omission_consent_required']})
        assert result['git_commit'] is None and result['staged'] is False
        preserved = json.loads((folder / 'omissions.json').read_bytes())
        assert preserved['inherited'] == [audit] and preserved['snapshotSha256'] == digest(snap(20))
        assert (folder / 'omissions.jsonl').read_bytes() == raw
        assert (repo / '.git/index').read_bytes() == before
    finally:
        service.close()
