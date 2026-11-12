"""Compatibility fallbacks preserve the same repository transaction guarantees."""
from pathlib import Path
import subprocess

import pytest

from layoutdiff.git import compat, scratch
from layoutdiff.git.commit import git
from layoutdiff.git.commit import discover
from layoutdiff.git.merge import RepositoryMerge, resolve
from test_repository_merge import branches, finish_cells


def test_old_rev_parse_echo_is_not_used_as_an_index_path(tmp_path, monkeypatch):
    directory = tmp_path / 'separate git directory'
    def old_git(repo, *args, **kwargs):
        output = b'--git-path\nindex\n' if '--git-path' in args else str(directory).encode() + b'\n'
        return subprocess.CompletedProcess(args, 0, output, b'')
    monkeypatch.setattr(compat, 'git', old_git)
    assert compat.git_path(tmp_path, 'index') == directory / 'index'


def test_gitfile_index_and_revision_validation(tmp_path):
    assert discover(True) is None and discover('') is None
    assert discover(tmp_path / 'missing') is None
    repo = tmp_path / 'tree'; repo.mkdir()
    git(repo, 'init', '--separate-git-dir', str(tmp_path / 'metadata'))
    assert compat.git_path(repo, 'index') == tmp_path / 'metadata' / 'index'
    for ref in ('--all', '-n', 'HEAD\nHEAD', '', None):
        with pytest.raises(ValueError, match='revision'):
            compat.resolve(repo, ref)
    assert compat.resolve(repo, 'HEAD', missing=True) is None
    assert compat.iso_date('2001-02-03 04:05:06 -0330') == '2001-02-03T04:05:06-03:30'


@pytest.mark.parametrize('custom_hooks', [False, True])
def test_clone_merge_preserves_hooks_parents_source_and_cleanup(tmp_path, monkeypatch, custom_hooks):
    monkeypatch.setattr(scratch, 'select', lambda repo: 'clone')
    repo, target, incoming = branches(tmp_path)
    tx = RepositoryMerge.create(tmp_path / 'merge', repo, ['incoming'])
    try:
        assert tx.state['checkout_backend'] == 'clone'
        assert compat.git_path(tx.work, 'MERGE_HEAD').is_file()
        assert not compat.git_path(repo, 'MERGE_HEAD').exists()
        tx.choose_file('notes.txt', 'incoming')
        finish_cells(tx)
        if custom_hooks:
            git(repo, 'config', 'core.hooksPath', str(tmp_path / 'custom source hooks'))
        hook = compat.git_path(repo, 'hooks') / 'pre-commit'
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o755)
        with pytest.raises(RuntimeError):
            tx.commit_step('rejected by source hook')
        assert resolve(repo, 'HEAD') == target
        hook.unlink()
        commit = tx.commit_step('isolated legacy merge')
        assert git(repo, 'show', '-s', '--format=%P', commit).stdout.decode().split() == [target, incoming]
        assert resolve(repo, 'HEAD') == target
        tx.publish()
        assert resolve(repo, 'HEAD') == commit and not tx.work.exists()
        assert not git(repo, 'for-each-ref', '--format=%(refname)', tx.state['ref']).stdout
    finally:
        if tx.work.exists():
            tx.cancel()
