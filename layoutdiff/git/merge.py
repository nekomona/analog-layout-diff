"""Recoverable, isolated repository merges. Git owns the commit graph.

Managed bundles are always regenerated from semantic decisions. Ordinary paths
use Git's merge and explicit stage choices for conflicts. Publication fast
forwards the original clean checkout only after a separate user action.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import shutil
import tempfile
import uuid

from layoutdiff.data.core import digest
from layoutdiff.data.history import atomic_json, read_json
from layoutdiff.data.merge_session import MergeSession
from layoutdiff.data.storage import from_snapshot, FILES
from layoutdiff.git.commit import git, discover, revision, json_bytes
from layoutdiff.git.store import GitSnapshots, path_identity, snapshot_directory, snapshot_path, blob


def resolve(repo, ref):
    return git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').stdout.decode().strip()


def clean(repo):
    if git(repo, 'status', '--porcelain', '--untracked-files=all').stdout:
        raise ValueError('Repository has local changes; commit or stash them before merging or publishing')


def changed(repo, a, b):
    return [p for p in git(repo, 'diff', '--name-only', '--no-renames', '-z', a, b).stdout.decode().split('\0') if p]


def scratch_root():
    """Resumable Git worktrees must outlive a runtime's disposable TMPDIR."""
    root = Path(tempfile.gettempdir()).resolve()
    for parent in (root, *root.parents):
        if parent.name.startswith('ald-session-'):
            return parent.parent
    return root


class RepositoryMerge:
    @classmethod
    def create(cls, path, repo, incoming):
        repo, path = Path(repo).resolve(), Path(path).resolve()
        if discover(repo) != repo:
            raise ValueError('Select a Git repository root')
        clean(repo)
        original = revision(repo)
        if not original['head']:
            raise ValueError('Merge requires an existing target commit')
        if not incoming:
            raise ValueError('Select at least one incoming branch')
        pinned = [{'label': ref, 'sha': resolve(repo, ref)} for ref in incoming]
        git(repo, 'var', 'GIT_AUTHOR_IDENT'); git(repo, 'var', 'GIT_COMMITTER_IDENT')
        path.mkdir(parents=True, exist_ok=False)
        work = Path(tempfile.mkdtemp(prefix='ald-merge-git-', dir=scratch_root())).resolve() / 'tree'
        state = {'schema': 'layoutdiff-repository-merge/1', 'repo': str(repo), 'original': original,
                 'incoming': pinned, 'step': 0, 'head': original['head'], 'worktree': str(work),
                 'phase': 'created', 'commits': [], 'cells': {}, 'files': {},
                 'ref': 'refs/layoutdiff/merges/' + uuid.uuid4().hex}
        atomic_json(path / 'repository.json', state)
        git(repo, 'worktree', 'add', '--detach', str(work), original['head'])
        result = cls(path)
        result.begin()
        return result

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.state = read_json(self.path / 'repository.json')
        if self.state['schema'] != 'layoutdiff-repository-merge/1':
            raise ValueError('Unknown repository merge format')
        self.repo = Path(self.state['repo'])
        self.work = Path(self.state['worktree'])

    def save(self):
        atomic_json(self.path / 'repository.json', self.state)

    def begin(self):
        """Prepare one pinned branch at a time, keeping earlier parents visible."""
        s = self.state
        if s['phase'] not in {'created', 'between', 'preparing'}:
            raise ValueError('This merge step is already prepared')
        if s['phase'] == 'created' and not self.work.exists():
            git(self.repo, 'worktree', 'add', '--detach', str(self.work), s['head'])
        while s['step'] < len(s['incoming']):
            incoming = s['incoming'][s['step']]['sha']
            if git(self.repo, 'merge-base', '--is-ancestor', incoming, s['head'], check=False).returncode == 0:
                s['step'] += 1
                self.save()
                continue
            bases = git(self.repo, 'merge-base', '--all', s['head'], incoming, check=False).stdout.decode().split()
            if len(bases) != 1:
                raise ValueError('Merge requires one common ancestor; unrelated histories and multiple merge bases need separate preparation')
            base = bases[0]
            paths = sorted(set(changed(self.repo, base, s['head']) + changed(self.repo, base, incoming)))
            identities = set()
            for p in paths:
                ident = path_identity(p)
                if ident:
                    identities.add(tuple(ident))
                elif p.startswith('.layoutdiff/histories/'):
                    raise ValueError('Migrate legacy history storage to snapshot bundles before branch merging')
                elif '.layout/' in p and p.startswith('layouts/'):
                    raise ValueError('Unknown file in managed layout bundle: ' + p)
            folded = [tuple(v.casefold() for v in ident) for ident in identities]
            if len(set(folded)) != len(folded):
                raise ValueError('Layout identities collide on a case-insensitive filesystem')
            s.update(base=base, phase='preparing', cells={}, files={}, paths=paths)
            self.save()
            merge_head = git(self.work, 'rev-parse', '--verify', 'MERGE_HEAD', check=False)
            if merge_head.returncode:
                result = git(self.work, 'merge', '--no-ff', '--no-commit', incoming, check=False)
                merge_head = git(self.work, 'rev-parse', '--verify', 'MERGE_HEAD', check=False)
            else:
                result = merge_head
            if merge_head.returncode or merge_head.stdout.decode().strip() != incoming:
                raise RuntimeError('Git did not prepare the expected merge: ' + result.stderr.decode(errors='replace'))
            for identity in sorted(identities):
                key = digest(identity)
                folder = self.path / ('step-' + str(s['step'])) / (key + '-' + uuid.uuid4().hex[:8])
                store = GitSnapshots(self.repo, identity, revision=s['head'])
                try:
                    snapshots = [store.snapshot(r) for r in (base, s['head'], incoming)]
                    audits = []
                    for rev in (base, s['head'], incoming):
                        audit = store.omissions(rev)
                        if audit and audit['reportSha256'] not in {a['reportSha256'] for a in audits}:
                            raw = blob(self.repo, rev, snapshot_directory(identity) + '/omissions.jsonl')
                            if raw is None or hashlib.sha256(raw).hexdigest() != audit['reportSha256']:
                                raise ValueError('Omission diagnostic report is missing or corrupt')
                            reports = self.path / 'omissions'; reports.mkdir(exist_ok=True)
                            (reports / (audit['reportSha256'] + '.jsonl')).write_bytes(raw)
                            audits.append(audit)
                    MergeSession.create(folder, *snapshots, metadata={'identity': list(identity),
                        'label': ' / '.join(identity), 'repository': str(self.path), 'cell_key': key})
                    s['cells'][key] = {'identity': list(identity), 'session': str(folder),
                                       'validated': None, 'audits': audits}
                finally:
                    store.close()
            s['files'] = {p: None for p in self.conflicts() if path_identity(p) is None}
            s['phase'] = 'resolving'
            self.save()
            return
        s['phase'] = 'ready'
        self.save()

    def conflicts(self):
        return [p for p in git(self.work, 'diff', '--name-only', '--diff-filter=U', '-z').stdout.decode().split('\0') if p]

    def cell(self, key):
        return MergeSession(self.state['cells'][key]['session'])

    def validate_cell(self, key, snapshot_digest):
        if self.state['phase'] != 'resolving':
            raise ValueError('Merge is not accepting cell decisions')
        session = self.cell(key)
        if session.unresolved() or digest(session.snapshot) != snapshot_digest:
            raise ValueError('Cell validation is stale or conflicts remain')
        self.state['cells'][key]['validated'] = {'head': session.head, 'digest': snapshot_digest}
        self.save()

    def choose_file(self, path, side):
        if self.state['phase'] != 'resolving' or path not in self.state['files']:
            raise ValueError('Unknown ordinary-file conflict')
        if side not in {'base', 'target', 'incoming'}:
            raise ValueError('Choose base, target or incoming for the file')
        rev = {'base': self.state['base'], 'target': self.state['head'],
               'incoming': self.state['incoming'][self.state['step']]['sha']}[side]
        entry = git(self.work, 'ls-tree', '-z', rev, '--', path).stdout
        if entry:
            git(self.work, 'restore', '--source=' + rev, '--staged', '--worktree', '--', path)
        else:
            git(self.work, 'rm', '-f', '--ignore-unmatch', '--', path)
        self.state['files'][path] = side
        self.save()

    def _write_cell(self, cell):
        session = MergeSession(cell['session'])
        if cell['validated'] != {'head': session.head, 'digest': digest(session.snapshot)} or session.unresolved():
            raise ValueError('Validate every affected cell in the graphical editor before committing')
        identity = cell['identity']
        prefix = snapshot_directory(identity)
        # Refuse symlink traversal before writing managed regular files.
        folder = self.work
        for part in Path(prefix).parts:
            folder /= part
            if folder.is_symlink():
                raise ValueError('Managed layout path contains a symlink')
        if git(self.work, 'ls-files', '--others', '--exclude-standard', '-z', '--', prefix).stdout:
            raise ValueError('Unexpected untracked files in the managed bundle')
        for path in git(self.work, 'ls-files', '-z', '--', prefix).stdout.decode().split('\0'):
            if path and path_identity(path) != identity:
                raise ValueError('Unexpected tracked file in the managed bundle: ' + path)
        git(self.work, 'rm', '-r', '-f', '--ignore-unmatch', '--', prefix, snapshot_path(identity))
        audits = list(cell['audits'])
        manual = session.state.get('omissions')
        if manual and manual['reportSha256'] not in {a['reportSha256'] for a in audits}:
            audits.append(manual)
        if not session.snapshot['objects']:
            if audits:
                raise ValueError('Deleting an incomplete cell requires preserving its omission audit; choose a retained snapshot')
            return
        with tempfile.TemporaryDirectory(prefix='ald-merge-codec-') as temp:
            stored = from_snapshot(session.snapshot, Path(temp) / 'layout')
            stored.close()
            folder.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                shutil.copyfile(Path(temp) / 'layout' / name, folder / name)
        if audits:
            reports, counts = [], Counter()
            for a in audits:
                p = self.path / 'omissions' / (a['reportSha256'] + '.jsonl')
                if not p.exists():
                    p = session.path / 'omissions' / p.name
                raw = p.read_bytes()
                if hashlib.sha256(raw).hexdigest() != a['reportSha256']:
                    raise ValueError('Omission report changed')
                reports.append(raw); counts.update(a['counts'])
            raw = b''.join(reports)
            audit = dict(schema='analog-layout-diff/omissions/1', sourceSha256=digest(audits),
                snapshotSha256=digest(session.snapshot), omitted=sum(a['omitted'] for a in audits),
                detached=sum(a['detached'] for a in audits), counts=dict(counts),
                reportSha256=hashlib.sha256(raw).hexdigest(), inherited=audits)
            (folder / 'omissions.json').write_bytes(json_bytes(audit))
            (folder / 'omissions.jsonl').write_bytes(raw)
        git(self.work, 'add', '--', prefix)

    def commit_step(self, message, *, omission_consent=False):
        s = self.state
        if s['phase'] != 'resolving' or not message.strip():
            raise ValueError('A resolving merge and nonempty commit message are required')
        if any(v is None for v in s['files'].values()):
            raise ValueError('Resolve every ordinary-file conflict first')
        if resolve(self.work, 'HEAD') != s['head']:
            raise ValueError('Preparation worktree HEAD changed; inspect recovery before continuing')
        if any(c['audits'] or self.cell(k).state.get('omissions') for k, c in s['cells'].items()) and not omission_consent:
            raise ValueError('Incomplete snapshots require explicit omission-loss consent')
        for cell in s['cells'].values():
            self._write_cell(cell)
        if self.conflicts():
            raise ValueError('Unresolved Git paths remain')
        expected_tree = git(self.work, 'write-tree').stdout.decode().strip()
        incoming = s['incoming'][s['step']]['sha']
        if git(self.work, 'rev-parse', '--verify', 'MERGE_HEAD').stdout.decode().strip() != incoming:
            raise ValueError('Git merge parent changed')
        s.update(phase='committing', expected_tree=expected_tree, message=message)
        self.save()
        path = self.path / 'message.txt'; path.write_text(message, encoding='utf-8')
        try:
            git(self.work, 'commit', '--file', str(path))
        except BaseException:
            if resolve(self.work, 'HEAD') == s['head']:
                s['phase'] = 'resolving'; self.save()
            raise
        return self.recover_commit()

    def recover_commit(self):
        s = self.state
        if s['phase'] != 'committing':
            raise ValueError('No interrupted commit to recover')
        result = resolve(self.work, 'HEAD')
        if result == s['head']:
            s['phase'] = 'resolving'; self.save()
            return None
        parents = git(self.work, 'show', '-s', '--format=%P', result).stdout.decode().split()
        incoming = s['incoming'][s['step']]['sha']
        if parents != [s['head'], incoming]:
            raise ValueError('Prepared commit has unexpected parents; inspect the isolated worktree')
        tree = git(self.work, 'show', '-s', '--format=%T', result).stdout.decode().strip()
        if tree != s['expected_tree']:
            raise ValueError('A Git hook changed the validated tree; inspect the isolated worktree before publication')
        git(self.repo, 'update-ref', s['ref'], result)
        s['commits'].append(result); s['head'] = result; s['step'] += 1; s['phase'] = 'between'
        self.save()
        self.begin()
        return result

    def publish(self):
        s = self.state
        if s['phase'] != 'ready':
            raise ValueError('Complete every selected incoming branch first')
        if revision(self.repo) != s['original']:
            raise ValueError('Target branch advanced or changed; publication is stale')
        clean(self.repo)
        s['phase'] = 'publishing'; self.save()
        try:
            git(self.repo, 'merge', '--ff-only', '--no-edit', s['head'])
        except BaseException:
            if revision(self.repo) == s['original']:
                s['phase'] = 'ready'; self.save()
            raise
        return self.recover_publish()

    def recover_publish(self):
        s = self.state
        if s['phase'] != 'publishing':
            raise ValueError('No publication to recover')
        current = revision(self.repo)
        if current == s['original']:
            s['phase'] = 'ready'; self.save()
            return None
        if current != {'branch': s['original']['branch'], 'head': s['head']}:
            raise ValueError('Publication state changed; inspect the target checkout')
        clean(self.repo)
        s['phase'] = 'published'; self.save(); self.cleanup()
        return s['head']

    def cleanup(self):
        """Only completed/explicitly cancelled transactions release Git resources."""
        if self.state['phase'] not in {'published', 'cancelled'}:
            raise ValueError('Suspend retains the preparation worktree for recovery')
        if self.work.exists():
            # Git verifies that this is a registered linked worktree.
            git(self.repo, 'worktree', 'remove', '--force', str(self.work))
        if self.work.parent.exists() and self.work.parent.name.startswith('ald-merge-git-'):
            self.work.parent.rmdir()
        git(self.repo, 'update-ref', '-d', self.state['ref'])

    def cancel(self):
        if self.state['phase'] == 'published':
            raise ValueError('Published merge cannot be cancelled; use Git revert')
        self.state['phase'] = 'cancelled'; self.save(); self.cleanup()
