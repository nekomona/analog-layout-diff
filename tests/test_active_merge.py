"""Existing Git merges stage only graphical resolutions, never another tool's work."""
import hashlib
import pytest
from layoutdiff.data.core import digest, empty_snapshot
from layoutdiff.data.storage import from_snapshot, Snapshot
from layoutdiff.git.active_merge import ActiveMerge, active_merge, cell_paths, index_entries, staged_snapshot
from layoutdiff.git.merge import open_repository, resolve, RepositoryMerge
from layoutdiff.git.commit import git
from layoutdiff.git.store import snapshot_directory, snapshot_path
from test_repository_merge import branches, finish_cells, snap, commit


def conflicted(tmp_path, v2=False):
    repo, target, incoming = branches(tmp_path)
    if v2:
        for branch in ('target', 'incoming'):
            git(repo, 'switch', branch)
            for cell, x in [('a', 10 if branch=='target' else 20), ('b', 0 if branch=='target' else 20)]:
                identity = ['TEST', cell, 'layout']
                stored = from_snapshot(snap(x), repo/snapshot_directory(identity)); stored.close()
                (repo/snapshot_path(identity)).unlink()
            commit(repo, 'v2 snapshots')
        git(repo, 'switch', 'target')
        target, incoming = resolve(repo, 'HEAD'), resolve(repo, 'incoming')
    assert git(repo, 'merge', '--no-ff', '--no-commit', 'incoming', check=False).returncode == 1
    return repo, target, incoming


def indexed_snapshot(repo, cell, tmp_path):
    identity = ['TEST', cell, 'layout']
    return staged_snapshot(repo, identity, index_entries(repo, cell_paths(identity)), tmp_path/cell)[0]


@pytest.mark.parametrize('v2', [False, True])
def test_active_stage_preserves_other_index_entries_worktree_and_merge(tmp_path, v2):
    repo, target, incoming = conflicted(tmp_path, v2)
    (repo/'user.txt').write_text('staged'); git(repo, 'add', 'user.txt')
    (repo/'user.txt').write_text('unstaged')
    other = index_entries(repo, ['notes.txt', 'user.txt'])
    index = (repo/'.git/index').read_bytes()
    info = active_merge(repo)
    assert ['TEST','a','layout'] in info['conflicted']
    tx = ActiveMerge.create(tmp_path/'active', repo, expected=digest(info))
    try:
        assert (repo/'.git/index').read_bytes() == index
        # New unrelated work after opening is also retained.
        (repo/'later.txt').write_text('later'); git(repo, 'add', 'later.txt')
        later = index_entries(repo, ['later.txt'])
        finish_cells(tx)
        assert tx.commit_step()['git_commit'] is None
        assert tx.state['phase'] == 'staged' and not tx.work.exists()
        assert isinstance(open_repository(tx.path), ActiveMerge)
        assert resolve(repo, 'HEAD') == target and resolve(repo, 'MERGE_HEAD') == incoming
        assert index_entries(repo, ['notes.txt', 'user.txt']) == other
        assert index_entries(repo, ['later.txt']) == later
        assert (repo/'user.txt').read_text() == 'unstaged'
        assert git(repo, 'diff', '--name-only', '--diff-filter=U').stdout.decode().strip() == 'notes.txt'
        assert indexed_snapshot(repo, 'a', tmp_path) == snap(20)
        assert indexed_snapshot(repo, 'b', tmp_path) == snap(20)
        assert not (repo/'.git/index.lock').exists()
    finally:
        if tx.work.exists(): tx.cancel()


def test_existing_manual_staged_resolution_is_preserved(tmp_path):
    repo, _, _ = conflicted(tmp_path)
    from test_repository_merge import write
    write(repo, 'a', 77); git(repo, 'add', snapshot_path(['TEST','a','layout']))
    tx = ActiveMerge.create(tmp_path/'active', repo)
    try:
        cell = next(c for c in tx.state['cells'].values() if c['identity'][1]=='a')
        from layoutdiff.data.merge_session import MergeSession
        assert MergeSession(cell['session']).snapshot == snap(77)
        finish_cells(tx); tx.commit_step()
        assert indexed_snapshot(repo, 'a', tmp_path) == snap(77)
    finally:
        if tx.work.exists(): tx.cancel()


@pytest.mark.parametrize('change', ['files', 'index', 'merge'])
def test_stale_source_rejected_without_overwriting_new_edits(tmp_path, change):
    repo, _, _ = conflicted(tmp_path)
    tx = ActiveMerge.create(tmp_path/'active', repo)
    try:
        finish_cells(tx)
        p = repo/snapshot_path(['TEST','a','layout'])
        if change in {'files','index'}:
            p.write_text('new user edits')
            if change=='index': git(repo, 'add', str(p))
        else:
            git(repo, 'merge', '--abort')
        index, content = (repo/'.git/index').read_bytes(), p.read_bytes()
        with pytest.raises(ValueError, match='changed|ended'):
            tx.commit_step()
        assert (repo/'.git/index').read_bytes() == index and p.read_bytes()==content
    finally:
        tx.cancel()


def test_cancel_does_not_abort_user_merge(tmp_path):
    repo, target, incoming = conflicted(tmp_path)
    index = (repo/'.git/index').read_bytes()
    tx = ActiveMerge.create(tmp_path/'active', repo)
    tx.cancel()
    assert (repo/'.git/index').read_bytes()==index
    assert resolve(repo, 'MERGE_HEAD') == incoming and resolve(repo, 'HEAD')==target


def test_failure_during_worktree_install_restores_source_and_allows_retry(tmp_path, monkeypatch):
    repo, _, _ = conflicted(tmp_path)
    tx = ActiveMerge.create(tmp_path/'active', repo)
    index = git(repo, 'ls-files', '--stage', '-z').stdout
    original = tx.replace_file
    calls = 0
    def fail_once(name, source):
        nonlocal calls
        calls += 1
        if calls == 2: raise OSError('simulated install failure')
        return original(name, source)
    try:
        finish_cells(tx)
        monkeypatch.setattr(tx, 'replace_file', fail_once)
        with pytest.raises(OSError, match='simulated'):
            tx.commit_step()
        assert tx.state['phase']=='resolving'
        tx.check_source()
        assert git(repo, 'ls-files', '--stage', '-z').stdout==index
        monkeypatch.setattr(tx, 'replace_file', original)
        tx.commit_step()
    finally:
        if tx.work.exists(): tx.cancel()


def test_lost_staging_response_recovers_completed_index(tmp_path, monkeypatch):
    repo, target, _ = conflicted(tmp_path)
    tx = ActiveMerge.create(tmp_path/'active', repo)
    save = tx.save
    def fail():
        if tx.state['phase']=='staged': raise OSError('lost response')
        save()
    try:
        finish_cells(tx)
        monkeypatch.setattr(tx, 'save', fail)
        with pytest.raises(OSError, match='lost response'): tx.commit_step()
        resumed = open_repository(tx.path)
        assert resumed.state['phase']=='applying'
        resumed.recover_apply()
        assert resumed.state['phase']=='staged' and resolve(repo,'HEAD')==target
        assert not resumed.work.exists()
    finally:
        if tx.work.exists(): open_repository(tx.path).cancel()


def test_non_layout_merge_and_staged_standalone_start(tmp_path):
    repo, _, _ = branches(tmp_path)
    (repo/'staged.txt').write_text('pending'); git(repo, 'add', 'staged.txt')
    before = (repo/'.git/index').read_bytes()
    with pytest.raises(ValueError, match='local changes'):
        RepositoryMerge.create(tmp_path/'blocked', repo, ['incoming'])
    assert (repo/'.git/index').read_bytes()==before
    commit(repo, 'ordinary commit')
    git(repo,'switch','-c','text-only')
    (repo/'more.txt').write_text('text only'); incoming=commit(repo,'no layouts')
    git(repo,'switch','target'); target=resolve(repo,'HEAD')
    tx=RepositoryMerge.create(tmp_path/'text',repo,['text-only'])
    try:
        assert not tx.state['cells']
        result=tx.commit_step('text-only merge')
        assert git(repo,'show','-s','--format=%P',result).stdout.decode().split()==[target,incoming]
    finally:
        tx.cancel()

def test_active_add_delete_and_incomplete_audit_consent(tmp_path):
    from layoutdiff.data.history import atomic_json
    repo, _, _ = branches(tmp_path)
    git(repo,'switch','incoming')
    identity=['TEST','c','layout']
    folder=repo/snapshot_directory(identity)
    stored=from_snapshot(snap(30),folder); stored.close()
    raw=b'{"element":"synthetic","issues":["unknown"],"record":{"kind":"unknown"}}\n'
    audit=dict(schema='analog-layout-diff/omissions/1',snapshotSha256=digest(snap(30)),sourceSha256='synthetic',
               reportSha256=hashlib.sha256(raw).hexdigest(),omitted=1,detached=0,counts={'unknown':1})
    atomic_json(folder/'omissions.json',audit); (folder/'omissions.jsonl').write_bytes(raw)
    (repo/snapshot_path(['TEST','b','layout'])).unlink()
    commit(repo,'add incomplete cell and delete another');git(repo,'switch','target')
    git(repo,'merge','--no-ff','--no-commit','incoming',check=False)
    tx=ActiveMerge.create(tmp_path/'active',repo)
    try:
        finish_cells(tx)
        with pytest.raises(ValueError,match='omission-loss consent'):tx.commit_step()
        tx.commit_step(omission_consent=True)
        assert indexed_snapshot(repo,'b',tmp_path)==empty_snapshot()
        assert indexed_snapshot(repo,'c',tmp_path)==snap(30)
        _,retained=staged_snapshot(repo,identity,index_entries(repo,cell_paths(identity)),tmp_path/'audit')
        assert retained['omitted']==1
    finally:
        if tx.work.exists():tx.cancel()


def test_interrupted_apply_recovery_restores_original_files(tmp_path,monkeypatch):
    repo,_,_=conflicted(tmp_path)
    tx=ActiveMerge.create(tmp_path/'active',repo)
    replace=tx.replace_file
    calls=0
    def fail(name,source):
        nonlocal calls
        calls+=1
        if calls>1: raise OSError('simulated worker exit')
        replace(name,source)
    try:
        finish_cells(tx);monkeypatch.setattr(tx,'replace_file',fail)
        with pytest.raises(OSError):tx.commit_step()
        resumed=open_repository(tx.path)
        assert resumed.state['phase']=='applying'
        resumed.recover_apply()
        assert resumed.state['phase']=='resolving'
        resumed.check_source()
        resumed.commit_step()
    finally:
        if tx.work.exists():open_repository(tx.path).cancel()
