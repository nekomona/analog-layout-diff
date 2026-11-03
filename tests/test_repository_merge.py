from pathlib import Path
import pytest

from layoutdiff.data.core import canonicalize, digest
from layoutdiff.git.commit import git
from layoutdiff.git.merge import RepositoryMerge, resolve
from layoutdiff.git.store import snapshot_path, GitSnapshots
from layoutdiff.data.history import atomic_json


def snap(x):
    return canonicalize([{'kind': 'cell', 'name': '', 'dbu': 1000, 'technology': 'TEST'},
        {'kind': 'rect', 'layerName': 'M1', 'bBox': [[x, 0], [x+100, 100]]}])


def write(repo, cell, x):
    p = repo / snapshot_path(['TEST', cell, 'layout'])
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(p, snap(x))


def commit(repo, message):
    git(repo, 'add', '--all')
    git(repo, 'commit', '-m', message)
    return resolve(repo, 'HEAD')


def branches(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    git(repo, 'init', '-b', 'target')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    write(repo, 'a', 0); write(repo, 'b', 0)
    (repo / 'notes.txt').write_text('base\n')
    commit(repo, 'base')
    git(repo, 'branch', 'incoming')
    write(repo, 'a', 10); (repo / 'notes.txt').write_text('target\n')
    target = commit(repo, 'target')
    git(repo, 'switch', 'incoming')
    write(repo, 'a', 20); write(repo, 'b', 20)
    (repo / 'notes.txt').write_text('incoming\n')
    incoming = commit(repo, 'incoming')
    git(repo, 'switch', 'target')
    return repo, target, incoming


def finish_cells(tx):
    for key in tx.state['cells']:
        session = tx.cell(key)
        for ident in session.unresolved():
            session.decide(ident, 'incoming', session.generation)
        tx.validate_cell(key, digest(session.snapshot))


def test_real_two_parent_merge_all_cells_and_explicit_publication(tmp_path):
    repo, target, incoming = branches(tmp_path)
    tx = RepositoryMerge.create(tmp_path / 'merge', repo, ['incoming'])
    try:
        assert resolve(repo, 'HEAD') == target
        assert len(tx.state['cells']) == 2
        with pytest.raises(ValueError, match='ordinary-file'):
            tx.commit_step('merge')
        tx.choose_file('notes.txt', 'incoming')
        with pytest.raises(ValueError, match='Validate every affected'):
            tx.commit_step('merge')
        finish_cells(tx)
        sha = tx.commit_step('merge layouts')
        assert git(repo, 'show', '-s', '--format=%P', sha).stdout.decode().split() == [target, incoming]
        assert resolve(repo, 'HEAD') == target
        resumed = RepositoryMerge(tx.path)
        assert resumed.publish() == sha
        assert not git(repo, 'status', '--porcelain').stdout
        assert (repo / 'notes.txt').read_text() == 'incoming\n'
        store = GitSnapshots(repo, ['TEST', 'b', 'layout'])
        try:
            assert store.snapshot(sha) == snap(20)
        finally:
            store.close()
    finally:
        if tx.state['phase'] != 'published' and tx.work.exists():
            RepositoryMerge(tx.path).cancel()


def test_stale_publication_and_dirty_start_never_touch_source(tmp_path):
    repo, target, incoming = branches(tmp_path)
    tx = RepositoryMerge.create(tmp_path / 'merge', repo, ['incoming'])
    try:
        tx.choose_file('notes.txt', 'target'); finish_cells(tx); tx.commit_step('merge')
        (repo / 'user.txt').write_text('work')
        with pytest.raises(ValueError, match='local changes'):
            tx.publish()
        changed = commit(repo, 'new target')
        with pytest.raises(ValueError, match='stale'):
            tx.publish()
        assert resolve(repo, 'HEAD') == changed
    finally:
        tx.cancel()


def test_sequential_branches_form_ordered_two_parent_chain(tmp_path):
    repo, target, incoming = branches(tmp_path)
    git(repo, 'switch', '-c', 'third')
    write(repo, 'c', 30); third = commit(repo, 'third')
    git(repo, 'switch', 'target')
    tx = RepositoryMerge.create(tmp_path / 'merge', repo, ['incoming', 'third'])
    try:
        tx.choose_file('notes.txt', 'incoming'); finish_cells(tx)
        first = tx.commit_step('first')
        assert tx.state['phase'] == 'resolving' and tx.state['step'] == 1
        finish_cells(tx)
        second = tx.commit_step('second')
        assert git(repo, 'show', '-s', '--format=%P', second).stdout.decode().split() == [first, third]
        assert tx.state['phase'] == 'ready'
    finally:
        tx.cancel()


def test_hook_failure_retains_resolutions_for_retry(tmp_path):
    repo, target, incoming = branches(tmp_path)
    tx = RepositoryMerge.create(tmp_path / 'merge', repo, ['incoming'])
    try:
        tx.choose_file('notes.txt', 'incoming'); finish_cells(tx)
        hook = repo / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o755)
        with pytest.raises(RuntimeError):
            tx.commit_step('reject')
        assert tx.state['phase'] == 'resolving'
        assert resolve(repo, 'HEAD') == target
        hook.unlink()
        tx.commit_step('retry')
    finally:
        tx.cancel()
