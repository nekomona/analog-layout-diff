"""Owned merge checkouts: linked worktrees when available, local clones otherwise."""
from pathlib import Path
import shutil
import stat

from layoutdiff.git.compat import git, git_path, resolve, worktree_backend


def select(repo):
    return worktree_backend(repo)


def pins(state):
    return [(state['ref'] + '-input-' + str(i), sha) for i, sha in enumerate(
        [state['original']['head'], *[v['sha'] for v in state['incoming']]])]


def create(state):
    repo, work = Path(state['repo']), Path(state['worktree'])
    backend = state.get('checkout_backend', 'worktree')
    for ref, sha in pins(state):
        git(repo, 'update-ref', ref, sha)
    if work.exists():
        return
    if backend == 'worktree':
        git(repo, 'worktree', 'add', '--detach', str(work), state['head'])
    elif backend == 'clone':
        # No alternates or hardlinks: the clone owns its objects and merge state.
        git(repo, 'clone', '--no-hardlinks', '--no-checkout', str(repo), str(work))
        (git_path(work, 'layoutdiff-owner')).write_text(state['ref'], encoding='ascii')
        sync_policy(state)
        git(work, 'checkout', '--detach', state['head'])
    else:
        raise ValueError('Unknown merge checkout backend')


def sync_policy(state):
    if state.get('checkout_backend', 'worktree') != 'clone':
        return
    repo, work = Path(state['repo']), Path(state['worktree'])
    if git_path(work, 'layoutdiff-owner').read_text() != state['ref']:
        raise ValueError('Merge clone ownership changed')
    # Local clones do not inherit repository-local identity/signing or hooks.
    # Refresh before each commit so source hook changes are still honored.
    def policy(key):
        return key.startswith(('user.', 'commit.', 'gpg.', 'i18n.')) or key in {
            'core.autocrlf', 'core.safecrlf', 'core.filemode', 'core.symlinks'}
    previous = git(work, 'config', '--local', '--list', '-z').stdout.split(b'\0')
    for key in {entry.decode().split('\n', 1)[0] for entry in previous if entry}:
        if policy(key):
            git(work, 'config', '--local', '--unset-all', key)
    entries = git(repo, 'config', '--local', '--list', '-z').stdout.split(b'\0')
    for entry in entries:
        if not entry:
            continue
        key, separator, value = entry.decode().partition('\n')
        if policy(key):
            git(work, 'config', '--local', key, value if separator else 'true')
    # Copy the *effective* hook directory. Old Git ignores core.hooksPath, so
    # blindly copying that setting could otherwise bypass its real .git/hooks.
    source = git_path(repo, 'hooks')
    target = git_path(work, 'layoutdiff-owner').parent / 'hooks'
    git(work, 'config', '--local', 'core.hooksPath', str(target))
    if target.exists():
        shutil.rmtree(target)
    if source.is_dir():
        shutil.copytree(source, target)


def retain(state, commit):
    repo, work = Path(state['repo']), Path(state['worktree'])
    if state.get('checkout_backend', 'worktree') == 'clone':
        git(work, 'update-ref', 'refs/layoutdiff/result', commit)
        git(repo, 'fetch', '--no-tags', str(work), 'refs/layoutdiff/result:' + state['ref'])
    else:
        git(repo, 'update-ref', state['ref'], commit)
    if resolve(repo, state['ref']) != commit:
        raise ValueError('Merge commit transfer failed')


def remove(state):
    repo, work = Path(state['repo']), Path(state['worktree']).resolve()
    if work.exists():
        if state.get('checkout_backend', 'worktree') == 'clone':
            owner = git_path(work, 'layoutdiff-owner')
            if (work.name != 'tree' or not work.parent.name.startswith('ald-merge-git-') or
                    owner.parent != work / '.git' or owner.read_text() != state['ref']):
                raise ValueError('Refusing to remove an unowned merge clone')
            def writable(function, path, error):
                target = Path(path)
                if (not isinstance(error[1], PermissionError) or target.is_symlink() or
                        not target.resolve().is_relative_to(work)):
                    raise error[1]
                target.chmod(stat.S_IREAD | stat.S_IWRITE)
                function(path)
            shutil.rmtree(work, onerror=writable)
        else:
            git(repo, 'worktree', 'remove', '--force', str(work))
    for ref, _ in pins(state):
        git(repo, 'update-ref', '-d', ref)
