"""Check the tracked tree, or all Git refs, for local publication material.

This conservative check complements a manual content/provenance review; it is
not a general secret scanner or proof that arbitrary layout data is synthetic.
"""
import argparse
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RULES = {
    'private host path': re.compile(rb'\x2fdisks\x2f|\x2fhome\x2f(?!user(?:/|\b)|example(?:/|\b))[^/\s"\x27]+/'),
    'site-specific Windows path': re.compile(rb'[A-Za-z]:\\(?:Users|Devel)\\'),
    'dated test library': re.compile(rb'\bLAYOUT_DIFF_TEST_\d'),
    'design identifier': re.compile(rb'\b(?:SCH\d{2}[_A-Za-z0-9]*|[A-Z]+STIM_[A-Za-z0-9_]+)\b'),
    'private network address': re.compile(rb'\b(?:192\.168\.|10\.\d+\.|172\.(?:1[6-9]|2\d|3[01])\.)\d+\.\d+\b'),
    'fixed CIW identifier': re.compile(rb'ciw-\d{4,}'),
}
DOC_RULES = {
    'session date': re.compile(rb'\b20\d{2}[-_/]\d{2}[-_/]\d{2}\b'),
    'session clock time': re.compile(rb'\b\d{1,2}:\d{2}:\d{2}\b'),
}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def check(paths, read):
    errors = []
    count = 0
    for name in paths:
        parts = Path(name).parts
        if '.local' in parts or Path(name).name in ('AGENTS.md', '.env'):
            errors.append((name, 'private file tracked'))
        data = read(name)
        if data is None or b'\0' in data:
            continue
        count += 1
        rules = {**RULES, **(DOC_RULES if name.endswith(('.md', '.rst', '.txt')) else {})}
        for label, pattern in rules.items():
            if pattern.search(data):
                errors.append((name, label))
    return count, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Inspect every tree reachable from every Git ref')
    args = parser.parse_args()
    total, errors = 0, []
    if args.history:
        # Cache by blob/path, so unchanged content is checked once across commits.
        seen = set()
        for commit in git('rev-list', '--all').decode().splitlines():
            entries = {}
            for row in git('ls-tree', '-r', '-z', commit).split(b'\0'):
                if not row:
                    continue
                info, name = row.split(b'\t', 1)
                _, kind, oid = info.split()
                if kind != b'blob':
                    continue
                key = (oid, name)
                if key not in seen:
                    seen.add(key)
                    entries[name.decode()] = oid.decode()
            count, found = check(entries, lambda name: git('cat-file', 'blob', entries[name]))
            total += count
            errors.extend((commit[:12] + ':' + name, issue) for name, issue in found)
    else:
        paths = git('ls-files', '-z').decode().split('\0')[:-1]
        def read(name):
            path = ROOT / name
            return path.read_bytes() if path.is_file() else None
        total, errors = check(paths, read)
    for name, issue in errors:
        print(f'ERROR {name}: {issue}')
    print(f'Checked {total} text files; {len(errors)} publication issues.')
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
