"""Repository-local Git plumbing, compatible with Git 1.8.3.1 and later."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import subprocess

OID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')


def git(repo, *args, env=None, data=None, check=True, output=None):
    process_env = os.environ.copy()
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                'GIT_PREFIX', 'GIT_GLOB_PATHSPECS', 'GIT_NOGLOB_PATHSPECS', 'GIT_ICASE_PATHSPECS'):
        process_env.pop(key, None)
    process_env.update(env or {})
    process_env['GIT_OPTIONAL_LOCKS'] = '0'
    process_env['GIT_LITERAL_PATHSPECS'] = '1'
    process_env['GIT_TERMINAL_PROMPT'] = '0'
    stream = open(output, 'wb') if output else None
    try:
        result = subprocess.run([os.environ.get('LAYOUTDIFF_GIT', 'git'), *map(str, args)],
            cwd=repo, input=data, stdout=stream or subprocess.PIPE, stderr=subprocess.PIPE,
            env=process_env, timeout=90)
    finally:
        if stream:
            stream.close()
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip() or 'Git command failed')
    return result


def git_path(repo, name):
    """Resolve administrative paths without assuming .git is a directory.

    Old rev-parse can echo an unknown option and exit successfully. Never turn
    that output into a filesystem path. The callers use per-worktree state;
    modern Git also resolves common-directory paths such as hooks correctly.
    """
    if not name or name.startswith('-') or any(c in name for c in '\0\r\n'):
        raise ValueError('Invalid Git administrative path')
    result = git(repo, 'rev-parse', '--git-path', name, check=False)
    value = result.stdout.decode().strip()
    if result.returncode or not value or '\n' in value or value.startswith('--'):
        value = git(repo, 'rev-parse', '--git-dir').stdout.decode().strip()
        if not value or '\n' in value or value.startswith('--'):
            raise ValueError('Cannot locate the Git directory')
        value = str(Path(value) / name)
    path = Path(value)
    return (path if path.is_absolute() else Path(repo) / path).resolve()


def resolve(repo, ref, *, missing=False):
    """Resolve one revision safely without modern --end-of-options."""
    if (not isinstance(ref, str) or not ref or ref.startswith('-') or
            any(c in ref for c in '\0\r\n')):
        raise ValueError('Expected a Git revision, not an option')
    result = git(repo, 'rev-parse', '--verify', ref + '^{commit}', check=False)
    value = result.stdout.decode().strip()
    if result.returncode or not OID.fullmatch(value):
        if missing:
            return None
        raise ValueError('Cannot resolve Git revision: ' + ref)
    return value


def iso_date(value):
    """Normalize the legacy %ai representation to %aI's timezone-aware ISO form."""
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S %z').isoformat()


def worktree_backend(repo):
    result = git(repo, 'worktree', '-h', check=False)
    help_text = result.stdout + result.stderr
    return 'worktree' if all(re.search(rb'worktree\s+' + command + rb'\b', help_text)
                             for command in (b'add', b'remove')) else 'clone'
