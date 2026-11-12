"""Remote repository reads and guarded snapshot writes; Git owns history/index."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import uuid

from layoutdiff.data.core import digest, empty_snapshot, validate
from layoutdiff.data.history import atomic_json
from layoutdiff.data.storage import FILES, Snapshot, from_snapshot, strict_json
from layoutdiff.git.commit import git, discover, json_bytes
from layoutdiff.git.active_merge import cell_paths, git_path, index_entries, safe_file, work_hashes
from layoutdiff.git.store import GitSnapshots, snapshot_path, snapshot_directory
from layoutdiff.git.compat import resolve


def repository(path):
    path = Path(path)
    if not path.is_absolute() or discover(path) != path.resolve():
        raise ValueError("repository must be the absolute Git worktree root on the Virtuoso host")
    return path.resolve()


def commit_id(repo, ref):
    result = resolve(repo, ref, missing=True)
    if result is None:
        if ref == 'HEAD' and git(repo, 'symbolic-ref', '--quiet', 'HEAD', check=False).returncode == 0:
            if not git(repo, 'rev-parse', '--verify', 'HEAD', check=False).stdout:
                return None
        raise ValueError("Cannot resolve Git revision: " + ref)
    return result


def paths(identity):
    return [*cell_paths(identity), 'layouts/.gitattributes']


def guard(repo, identity):
    names = paths(identity)
    return {'head': commit_id(repo, 'HEAD'),
            'branch': git(repo, 'symbolic-ref', '--quiet', 'HEAD', check=False).stdout.decode().strip(),
            'index': hashlib.sha256(index_entries(repo, names)).hexdigest(),
            'files': work_hashes(repo, names),
            'merge_head': git_path(repo, 'MERGE_HEAD').read_text() if git_path(repo, 'MERGE_HEAD').exists() else None}


def check_guard(repo, identity, expected):
    if guard(repo, identity) != expected:
        raise ValueError("Git inputs, managed files or staged entries changed; analyze again")


def worktree_snapshot(repo, identity):
    for name in cell_paths(identity):
        safe_file(repo, name)
    directory = repo / snapshot_directory(identity)
    legacy = repo / snapshot_path(identity)
    audit = directory / 'omissions.json'
    if directory.exists():
        if not (directory / 'manifest.json').exists():
            raise ValueError("Incomplete working-tree snapshot bundle")
        store = Snapshot(directory)
        try:
            value = store.materialize()
        finally:
            store.close()
        if legacy.exists() and strict_json(legacy.read_bytes()) != value:
            raise ValueError("Conflicting working-tree v1/v2 snapshots")
    elif legacy.exists():
        value = strict_json(legacy.read_bytes())
        validate(value)
    else:
        value = empty_snapshot()
    omissions = strict_json(audit.read_bytes()) if audit.exists() else None
    if omissions and omissions.get('snapshotSha256') != digest(value):
        raise ValueError("Working-tree omission audit does not match its snapshot")
    return value, omissions


def revision_snapshot(repo, identity, sha):
    store = GitSnapshots(repo, identity, revision=sha)
    try:
        return store.snapshot(sha), store.omissions(sha) if sha else None
    finally:
        store.close()


@contextmanager
def locked_index(repo):
    """Keep Git staging out of the brief write transaction; never change the index."""
    lock = git_path(repo, 'index').with_name('index.lock')
    token = ('layoutdiff-agent:' + uuid.uuid4().hex).encode()
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, token)
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        if lock.exists() and lock.read_bytes() == token:
            lock.unlink()


def omission_token(repo, identity, snapshot, expected, audit=None):
    directory = repo / snapshot_directory(identity)
    if audit or any((directory / name).exists() for name in ('omissions.json', 'omissions.jsonl')):
        return digest({'snapshot': digest(snapshot), 'audit': audit, 'guard': expected})
    return None


def write_snapshot(repo, identity, snapshot, expected, journal, *, audit=None, report=None, omission_consent=None):
    """Install only a selected complete snapshot, retaining a recovery journal."""
    validate(snapshot)
    from layoutdiff.eda.virtuoso.support import coverage
    issues = coverage(snapshot)
    if issues:
        raise ValueError('Snapshot has reconstruction blockers: ' + '; '.join(issues[:10]))
    check_guard(repo, identity, expected)
    directory, legacy = snapshot_directory(identity), snapshot_path(identity)
    token = omission_token(repo, identity, snapshot, expected, audit)
    if token and not snapshot['objects']:
        raise ValueError('Deleting an incomplete cell requires retaining its omission audit')
    if token and omission_consent != token:
        raise ValueError('Incomplete snapshots require consent bound to the current preview')
    if audit:
        if (not snapshot['objects'] or audit['snapshotSha256'] != digest(snapshot) or
                report is None or hashlib.sha256(report).hexdigest() != audit['reportSha256']):
            raise ValueError('Invalid omission audit or report; incomplete cell deletion is refused')
    existing = repo / directory
    if existing.exists() and any(p.name not in (*FILES, 'omissions.json', 'omissions.jsonl') or
                                not p.is_file() or p.is_symlink() for p in existing.iterdir()):
        raise ValueError('Unexpected files in managed snapshot bundle')
    journal = Path(journal)
    journal.mkdir(parents=True, exist_ok=False)
    desired = {}
    if not snapshot['objects']:
        desired = {name: None for name in cell_paths(identity) if (repo / name).exists()}
    elif (repo / legacy).exists() and not existing.exists() and not audit:
        desired[legacy] = json_bytes(snapshot)
    else:
        store = from_snapshot(snapshot, journal / 'candidate')
        store.close()
        desired.update({directory + '/' + name: (journal / 'candidate' / name).read_bytes() for name in FILES})
        if (repo / legacy).exists():
            desired[legacy] = None
    for name, data in (('omissions.json', json_bytes(audit) if audit else None), ('omissions.jsonl', report if audit else None)):
        if data is not None or (repo / directory / name).exists():
            desired[directory + '/' + name] = data
    attr = 'layouts/.gitattributes'
    previous = (repo / attr).read_bytes() if (repo / attr).exists() else b''
    rules = [b'*.layout.json -merge', b'*.jsonl -merge', b'**/*.layout/manifest.json -merge']
    extra = [r for r in rules if r not in previous.splitlines()]
    if extra and snapshot['objects']:
        desired[attr] = previous + (b'\n' if previous and not previous.endswith(b'\n') else b'') + b'\n'.join(extra) + b'\n'
    desired = {name: data for name, data in desired.items()
               if data != ((repo / name).read_bytes() if (repo / name).exists() else None)}
    originals, installed = {}, {}
    receipt = {'repository': str(repo), 'cellview': identity, 'expected': expected,
               'snapshot_digest': digest(snapshot), 'files': list(desired), 'state': 'prepared'}
    with locked_index(repo):
        check_guard(repo, identity, expected)
        for number, name in enumerate(desired):
            p = safe_file(repo, name)
            originals[name] = p.read_bytes() if p.exists() else None
            if p.exists():
                (journal / ('before-' + str(number))).write_bytes(originals[name])
        atomic_json(journal / 'write.json', receipt)
        try:
            for name, data in desired.items():
                p = safe_file(repo, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                if data is None:
                    p.unlink(missing_ok=True)
                else:
                    temp = p.with_name(p.name + '.ald-' + uuid.uuid4().hex)
                    try:
                        temp.write_bytes(data)
                        os.replace(temp, p)
                    finally:
                        temp.unlink(missing_ok=True)
                installed[name] = data
        except BaseException:
            # Never roll back a newer external edit over our failed write.
            for name, data in installed.items():
                p = repo / name
                if (p.read_bytes() if p.exists() else None) == data:
                    old = originals[name]
                    if old is None:
                        p.unlink(missing_ok=True)
                    else:
                        p.write_bytes(old)
            receipt['state'] = 'failed'
            atomic_json(journal / 'write.json', receipt)
            raise
        receipt['state'] = 'written'
        atomic_json(journal / 'write.json', receipt)
    if existing.exists() and not any(existing.iterdir()):
        existing.rmdir()
    return {'repository': str(repo), 'cellview': identity, 'files': list(desired),
            'snapshot_digest': digest(snapshot), 'staged': False, 'git_commit': None,
            'recovery_journal': str(journal / 'write.json')}
