"""Dependency-free Git/agent regression; set LAYOUTDIFF_GIT to an old executable.

All repositories, requests and snapshots are synthetic and temporary. No native
connection is used. Run this with Python 3.10+ on the Git executable's host.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layoutdiff.data.core import canonicalize, digest
from layoutdiff.git.merge import RepositoryMerge
from layoutdiff.git.commit import git, prepare, commit
from layoutdiff.git.compat import resolve, git_path
from layoutdiff.git.store import GitSnapshots, snapshot_path
from layoutdiff.data.history import atomic_json

IDENTITY = ['TEST', 'headless', 'layout']


def snapshot(x):
    return canonicalize([{'kind': 'cell', 'name': '', 'dbu': 1000, 'technology': 'TEST'},
        {'kind': 'rect', 'layerName': 'M1', 'bBox': [[x, 0], [x + 100, 100]]}])


def run():
    with tempfile.TemporaryDirectory(prefix='ald-headless-regression-') as temp:
        root = Path(temp); repo = root / 'repo with spaces'; repo.mkdir()
        git(repo, 'init'); git(repo, 'symbolic-ref', 'HEAD', 'refs/heads/target')
        git(repo, 'config', 'user.name', 'Synthetic Test')
        git(repo, 'config', 'user.email', 'test@example.invalid')
        first = commit(prepare(repo, IDENTITY, snapshot(0)), 'initial')['git_commit']
        (repo / 'notes.txt').write_text('staged\n')
        git(repo, 'add', '--', 'notes.txt')
        index = git(repo, 'ls-files', '--stage', '--', 'notes.txt').stdout
        second = commit(prepare(repo, IDENTITY, snapshot(10)), 'second')['git_commit']
        assert git(repo, 'ls-files', '--stage', '--', 'notes.txt').stdout == index
        git(repo, 'commit', '-m', 'ordinary staged work')
        store = GitSnapshots(repo, IDENTITY)
        try:
            assert store.revisions() == [second, first]
            assert 'T' in store.metadata(second)['date'] and '%aI' not in store.metadata(second)['date']
        finally:
            store.close()
        git(repo, 'checkout', '-b', 'incoming', first)
        incoming = commit(prepare(repo, IDENTITY, snapshot(20)), 'incoming')['git_commit']
        git(repo, 'checkout', 'target')
        ours = resolve(repo, 'HEAD')
        git(repo, 'merge', '--no-ff', '--no-commit', incoming, check=False)
        assert git_path(repo, 'MERGE_HEAD').exists()
        state = root / 'state'
        def agent(ident, operation=None, payload=None, result=False):
            command = [sys.executable, '-m', 'layoutdiff.agent', '--root', str(state), '--request-id', ident]
            if result:
                command += ['--result']
            else:
                request = root / (ident + '.json'); atomic_json(request, payload)
                command += ['--operation', operation, '--payload', str(request)]
            response = subprocess.run(command, capture_output=True, text=True, check=True)
            value = json.loads(response.stdout)
            assert value['status'] == 'complete', value
            return value['result']
        explained = agent('explain', 'merge_explain', {'repository': str(repo)})
        plan, = explained['cells']
        decisions = {u['id']: 'incoming' for u in plan['units'] if u['status'] == 'unresolved'}
        written = agent('resolve', 'merge_apply', {'plan_id': plan['plan_id'], 'generation': plan['generation'],
            'mode': 'write', 'decisions': decisions, 'native_validation': False})
        assert written['staged'] is False and resolve(repo, 'HEAD') == ours
        assert agent('resolve', result=True) == written
        git(repo, 'add', '--all', '--', 'layouts')
        git(repo, 'commit', '--no-edit')
        assert git(repo, 'show', '-s', '--format=%P', 'HEAD').stdout.decode().split() == [ours, incoming]
        delta = agent('diff', 'diff', {'repository': str(repo), 'cellview': IDENTITY,
                                     'left': first, 'right': 'HEAD', 'limit': 1})
        assert delta['counts']['moved'] == 1
        page = agent('page', 'diff', {'analysis_id': delta['analysis_id'], 'offset': 0, 'limit': 1})
        assert page['digests'] == delta['digests'] and page['items'] == delta['items']
        assert Path(page['exact_operations']).exists()
        git(repo, 'checkout', '-b', 'isolated-incoming', first)
        commit(prepare(repo, IDENTITY, snapshot(30)), 'other layout')
        (repo / 'notes.txt').write_text('other branch\n')
        git(repo, 'add', '--', 'notes.txt'); git(repo, 'commit', '-m', 'other ordinary file')
        git(repo, 'checkout', 'target')
        original = resolve(repo, 'HEAD')
        tx = RepositoryMerge.create(root / 'isolated', repo, ['isolated-incoming'])
        try:
            assert resolve(repo, 'HEAD') == original
            tx.choose_file('notes.txt', 'incoming')
            for key in tx.state['cells']:
                session = tx.cell(key)
                for unit in session.unresolved():
                    session.decide(unit, 'incoming', session.generation)
                tx.validate_cell(key, digest(session.snapshot))
            git(repo, 'config', 'core.hooksPath', str(root / 'source hooks'))
            hook = git_path(repo, 'hooks') / 'pre-commit'
            hook.parent.mkdir(exist_ok=True)
            hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o755)
            try:
                tx.commit_step('must reject')
                raise AssertionError('Source hook was bypassed')
            except RuntimeError:
                pass
            hook.unlink()
            merged = tx.commit_step('isolated merge')
            assert resolve(repo, 'HEAD') == original
            tx.publish()
            assert resolve(repo, 'HEAD') == merged and not tx.work.exists()
        finally:
            if tx.work.exists() and tx.state['phase'] != 'published':
                tx.cancel()
        print(json.dumps({'git': git(repo, '--version').stdout.decode().strip(),
                          'commit_history_diff_merge': 'passed', 'durable_paging': 'passed',
                          'isolated_merge_backend': tx.state['checkout_backend']}))


if __name__ == '__main__':
    run()
