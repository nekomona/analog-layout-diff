"""Resolve layouts in an existing Git merge without committing other staged work.

Inputs come from immutable parents or the existing stage-0 index, never from
conflict-marker text. Native decisions are prepared in a disposable worktree and
installed into only the managed layout paths under the original index lock.
"""
from __future__ import annotations
import contextlib
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from layoutdiff.data.core import digest, empty_snapshot, validate
from layoutdiff.data.history import atomic_json
from layoutdiff.data.merge_session import MergeSession
from layoutdiff.data.storage import FILES, Snapshot, strict_json
from layoutdiff.data.streaming import file_digest
from layoutdiff.git.commit import git
from layoutdiff.git.merge import RepositoryMerge, resolve, scratch_root
from layoutdiff.git.store import GitSnapshots, path_identity, snapshot_path, snapshot_directory, blob


def git_path(repo, name):
    p = Path(git(repo, 'rev-parse', '--git-path', name).stdout.decode().strip())
    return p if p.is_absolute() else Path(repo) / p


def active_merge(repo):
    if not repo or not git_path(repo, 'MERGE_HEAD').exists():
        return None
    parents = git_path(repo, 'MERGE_HEAD').read_text().split()
    head = resolve(repo, 'HEAD')
    branch = git(repo, 'symbolic-ref', '--quiet', 'HEAD', check=False).stdout.decode().strip()
    indexed = git(repo, 'diff', '--cached', '--name-only', '--no-renames', '-z', head).stdout.decode().split('\0')
    unmerged = git(repo, 'diff', '--name-only', '--diff-filter=U', '-z').stdout.decode().split('\0')
    paths = sorted(set(indexed + unmerged) - {''})
    conflicts = sorted(set(unmerged) - {''})
    cells = sorted({tuple(ident) for p in paths if (ident := path_identity(p))})
    conflicted = sorted({tuple(ident) for p in conflicts if (ident := path_identity(p))})
    unsupported = [p for p in paths if path_identity(p) is None and
                   (p.endswith('.layout.json') or '.layout/' in p or p.startswith('.layoutdiff/histories/'))]
    reason = ''
    bases = git(repo, 'merge-base', '--all', head, parents[0], check=False).stdout.decode().split() if len(parents) == 1 else []
    if len(parents) != 1 or len(bases) != 1:
        reason = 'The layout editor requires one incoming parent and one common merge base.'
    elif unsupported:
        reason = 'Unrecognized or legacy layout storage needs migration before graphical resolution: ' + ', '.join(unsupported[:4])
    return dict(head=head, branch=branch, parents=parents, base=bases[0] if len(bases)==1 else None,
                cells=[list(v) for v in cells], conflicted=[list(v) for v in conflicted],
                paths=paths, conflicts=conflicts, reason=reason)


def cell_paths(identity):
    return [snapshot_path(identity), *[snapshot_directory(identity) + '/' + n
                                     for n in (*FILES, 'omissions.json', 'omissions.jsonl')]]


def index_entries(repo, paths):
    return git(repo, 'ls-files', '--stage', '-z', '--', *paths).stdout


def parsed_entries(raw):
    for line in raw.split(b'\0'):
        if line:
            prefix, path = line.split(b'\t', 1)
            mode, oid, stage = prefix.decode().split()
            yield path.decode(), mode, oid, int(stage)


def safe_file(repo, name):
    path = Path(repo)
    for part in Path(name).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Managed layout path contains a symlink: ' + name)
    if path.exists() and not path.is_file():
        raise ValueError('Managed layout file is not regular: ' + name)
    return path


def work_hashes(repo, paths):
    return {name: file_digest(p) if (p := safe_file(repo, name)).exists() else None for name in paths}


def staged_snapshot(repo, identity, entries, folder):
    """Read a complete, already-staged cell even if other files are unmerged."""
    prefix = snapshot_directory(identity)
    records = {p: (mode, oid) for p, mode, oid, stage in parsed_entries(entries) if stage == 0}
    folder.mkdir(parents=True)
    for path, (mode, oid) in records.items():
        if mode not in {'100644', '100755'}:
            raise ValueError('Staged layout must contain regular files')
        dest = folder / Path(path).name
        git(repo, 'cat-file', 'blob', oid, output=dest)
    if prefix + '/manifest.json' in records:
        stored = Snapshot(folder)
        try:
            result = stored.materialize()
        finally:
            stored.close()
        old = folder / Path(snapshot_path(identity)).name
        if old.exists() and strict_json(old.read_bytes()) != result:
            raise ValueError('Conflicting staged v1/v2 snapshots')
    elif snapshot_path(identity) in records:
        result = strict_json((folder / Path(snapshot_path(identity)).name).read_bytes())
        validate(result)
    elif records:
        raise ValueError('Incomplete staged layout bundle')
    else:
        result = empty_snapshot()
    audit = strict_json((folder / 'omissions.json').read_bytes()) if (folder / 'omissions.json').exists() else None
    if audit is not None and (not isinstance(audit, dict) or audit.get('snapshotSha256') != digest(result) or audit.get('schema') != 'analog-layout-diff/omissions/1' or
                  any(type(audit.get(k)) is not int or audit[k] < 0 for k in ('omitted', 'detached'))):
        raise ValueError('Staged omission audit does not match its snapshot')
    if audit is None and (folder / 'omissions.jsonl').exists():
        raise ValueError('Staged omission report has no valid audit')
    return result, audit


class ActiveMerge(RepositoryMerge):
    @classmethod
    def create(cls, path, repo, *, expected=None):
        repo, path = Path(repo).resolve(), Path(path).resolve()
        info = active_merge(repo)
        if info is None:
            raise ValueError('There is no active Git merge')
        if expected is not None and digest(info) != expected:
            raise ValueError('Active merge changed after discovery; refresh Merge')
        if info['reason'] or not info['cells']:
            raise ValueError(info['reason'] or 'The active merge has no managed layout changes')
        folded = [tuple(v.casefold() for v in ident) for ident in info['cells']]
        if len(set(folded)) != len(folded):
            raise ValueError('Layout identities collide on a case-insensitive filesystem')
        path.mkdir(parents=True, exist_ok=False)
        work = Path(tempfile.mkdtemp(prefix='ald-merge-git-', dir=scratch_root())).resolve() / 'tree'
        paths = sorted({p for identity in info['cells'] for p in cell_paths(identity)})
        entries = index_entries(repo, paths)
        state = dict(schema='layoutdiff-repository-merge/1', mode='active', repo=str(repo),
            original={'branch': info['branch'], 'head': info['head']}, head=info['head'], base=info['base'],
            incoming=[{'label': 'Active MERGE_HEAD', 'sha': info['parents'][0]}], step=0, phase='preparing',
            worktree=str(work), ref='refs/layoutdiff/merges/' + uuid.uuid4().hex, commits=[], cells={},
            files={p: None for p in info['conflicts'] if path_identity(p) is None}, paths=info['paths'],
            managed_paths=paths, source_index=hashlib.sha256(entries).hexdigest(),
            source_files=work_hashes(repo, paths), source_merge=info, index_entries=entries.decode())
        atomic_json(path / 'repository.json', state)
        git(repo, 'worktree', 'add', '--detach', str(work), info['head'])
        result = cls(path)
        result.begin()
        return result

    def check_source(self, *, files=True):
        current = active_merge(self.repo)
        original = self.state['source_merge']
        if current is None or any(current[k] != original[k] for k in ('head', 'branch', 'parents', 'base')):
            raise ValueError('The active Git merge changed or ended; open it again')
        if files and (hashlib.sha256(index_entries(self.repo, self.state['managed_paths'])).hexdigest() != self.state['source_index'] or
                      work_hashes(self.repo, self.state['managed_paths']) != self.state['source_files']):
            raise ValueError('Layout files or their staged entries changed while reviewing; reopen the active merge to preserve those edits')
        return current

    def begin(self):
        s = self.state
        if s['phase'] != 'preparing':
            raise ValueError('Active merge is already prepared')
        self.check_source()
        if not self.work.exists():
            git(self.repo, 'worktree', 'add', '--detach', str(self.work), s['head'])
        for identity in s['source_merge']['cells']:
            key = digest(identity)
            if key in s['cells']:
                continue
            store = GitSnapshots(self.repo, identity, revision=s['head'])
            folder = self.path / 'step-0' / (key + '-' + uuid.uuid4().hex[:8])
            audits = []
            try:
                if identity in s['source_merge']['conflicted']:
                    revisions = [s['base'], s['head'], s['incoming'][0]['sha']]
                    snapshots = [store.snapshot(rev) for rev in revisions]
                    for rev in revisions:
                        audit = store.omissions(rev)
                        if audit:
                            self.retain_audit(audits, audit, blob(self.repo, rev, snapshot_directory(identity) + '/omissions.jsonl'))
                else:
                    with tempfile.TemporaryDirectory(prefix='ald-index-layout-') as temp:
                        snapshot, audit = staged_snapshot(self.repo, identity,
                            index_entries(self.repo, cell_paths(identity)), Path(temp) / 'layout')
                        # A stage-0 resolution is authoritative. Model it as a
                        # one-sided update, avoiding inferred two-sided conflicts.
                        original = store.snapshot(s['head'])
                        snapshots = [original, original, snapshot]
                        if audit:
                            self.retain_audit(audits, audit, (Path(temp)/'layout/omissions.jsonl').read_bytes())
                MergeSession.create(folder, *snapshots, metadata={'identity': identity, 'repository': str(self.path),
                    'cell_key': key, 'label': ' / '.join(identity) + (' (active conflict)' if identity in s['source_merge']['conflicted'] else ' (preserve staged layout)')})
                s['cells'][key] = dict(identity=identity, session=str(folder), validated=None, audits=audits)
                self.save()
            finally:
                store.close()
        self.check_source()
        s['phase'] = 'resolving'; self.save()

    def retain_audit(self, audits, audit, raw):
        if raw is None or hashlib.sha256(raw).hexdigest() != audit['reportSha256']:
            raise ValueError('Omission report missing or corrupt')
        if audit['reportSha256'] not in {a['reportSha256'] for a in audits}:
            folder = self.path / 'omissions'; folder.mkdir(exist_ok=True)
            (folder / (audit['reportSha256'] + '.jsonl')).write_bytes(raw)
            audits.append(audit)

    def choose_file(self, path, side):
        raise ValueError('Resolve ordinary-file conflicts with your Git tool; this session stages layout files only')

    def publish(self):
        raise ValueError('This session resolves the existing merge; finish it with your Git tool after reviewing all staged files')

    @contextlib.contextmanager
    def index_lock(self, registry=None):
        index = git_path(self.repo, 'index')
        lock = index.with_name('index.lock')
        token = f'layoutdiff:{os.getpid()}:{uuid.uuid4().hex}'
        staging = index.with_name('index.ald-' + uuid.uuid4().hex)
        if registry:
            atomic_json(registry, [{'path': str(lock), 'pid': os.getpid(), 'token': token, 'index_staging': str(staging)}])
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, token.encode()); os.close(fd)
        try:
            yield index, staging
        finally:
            staging.unlink(missing_ok=True)
            if lock.exists() and lock.read_bytes() == token.encode():
                lock.unlink()
            if registry:
                atomic_json(registry, [])

    def commit_step(self, message='', *, omission_consent=False, registry=None):
        """Stage layout resolutions only. Never commit another tool's index."""
        s = self.state
        if s['phase'] != 'resolving':
            raise ValueError('The active merge is not accepting layout resolutions')
        self.check_source()
        if any(c['audits'] or self.cell(k).state.get('omissions') for k,c in s['cells'].items()) and not omission_consent:
            raise ValueError('Incomplete snapshots require explicit omission-loss consent')
        for cell in s['cells'].values():
            self._write_cell(cell)
        desired = index_entries(self.work, s['managed_paths'])
        desired_files = work_hashes(self.work, s['managed_paths'])
        backup = self.path / 'before-files'; backup.mkdir(exist_ok=True)
        with self.index_lock(registry) as (index, staging):
            self.check_source()
            shutil.copyfile(index, staging)
            env = {'GIT_INDEX_FILE': str(staging)}
            git(self.repo, 'update-index', '--force-remove', '--', *s['managed_paths'], env=env)
            git(self.repo, 'update-index', '-z', '--index-info', data=desired, env=env)
            for number, name in enumerate(s['managed_paths']):
                source = safe_file(self.repo, name)
                if source.exists():
                    shutil.copyfile(source, backup / str(number))
            s.update(phase='applying', result_index=hashlib.sha256(desired).hexdigest(), result_files=desired_files)
            self.save()
            installed = False
            try:
                for name in s['managed_paths']:
                    self.replace_file(name, self.work / name if desired_files[name] is not None else None)
                os.replace(staging, index)
                installed = True
                s['phase'] = 'staged'; self.save()
            except BaseException:
                if not installed:
                    self.restore_files()
                    s['phase'] = 'resolving'; self.save()
                raise
        self.cleanup()
        return {'staged_layouts': len(s['cells']), 'git_commit': None}

    def replace_file(self, name, source):
        path = safe_file(self.repo, name)
        if source is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + '.ald-' + uuid.uuid4().hex)
            try:
                shutil.copyfile(source, temp)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)

    def restore_files(self):
        now = work_hashes(self.repo, self.state['managed_paths'])
        for name, value in now.items():
            if value not in (self.state['source_files'][name], self.state['result_files'][name]):
                raise ValueError('Interrupted staging encountered newer layout edits; inspect the retained before-files backup')
        for number, name in enumerate(self.state['managed_paths']):
            self.replace_file(name, self.path / 'before-files' / str(number) if self.state['source_files'][name] is not None else None)

    def recover_apply(self, registry=None):
        if self.state['phase'] != 'applying':
            raise ValueError('No interrupted staging to recover')
        with self.index_lock(registry):
            self.check_source(files=False)
            current = hashlib.sha256(index_entries(self.repo, self.state['managed_paths'])).hexdigest()
            if current == self.state['result_index'] and work_hashes(self.repo, self.state['managed_paths']) == self.state['result_files']:
                self.state['phase'] = 'staged'; self.save()
            elif current == self.state['source_index']:
                self.restore_files(); self.state['phase'] = 'resolving'; self.save()
            else:
                raise ValueError('Interrupted layout staging no longer matches the index; inspect the retained backup')
        if self.state['phase'] == 'staged':
            self.cleanup()

    def cancel(self):
        if self.state['phase'] == 'applying':
            raise ValueError('Recover interrupted staging before discarding this session')
        super().cancel()  # Deletes only our linked worktree; never git merge --abort.
