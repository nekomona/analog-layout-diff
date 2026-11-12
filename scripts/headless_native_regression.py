"""Synthetic display-free OA/Git/agent roundtrip in an existing test library.

Requires configured Virtuoso on PATH, Python 3.10+, and an existing dedicated
writable test library. No Bridge daemon or GUI runtime is used on this host.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layoutdiff.data.core import digest
from layoutdiff.data.history import atomic_json
from layoutdiff.data.storage import from_snapshot
from layoutdiff.eda.virtuoso.batch import BatchAdapter
from layoutdiff.eda.virtuoso.sexpr import dumps as sk
from layoutdiff.git.commit import git
from layoutdiff.git.compat import resolve
from layoutdiff.git.store import snapshot_directory, GitSnapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--library', required=True, help='Dedicated synthetic-test library')
    parser.add_argument('--layer', required=True)
    parser.add_argument('--virtuoso', default='virtuoso')
    parser.add_argument('--output', required=True, help='Dedicated local evidence directory outside Git')
    args = parser.parse_args()
    root = Path(args.output).resolve(); root.mkdir(parents=True, exist_ok=False)
    adapter = BatchAdapter(args.virtuoso, args.cwd, root / 'native', writable_library=args.library)
    token = uuid.uuid4().hex[:12]
    cells = ['ald_headless_' + token + '_' + str(i) for i in range(3)]
    snapshots, created = [], []
    try:
        for number, cell in enumerate(cells):
            folder = adapter._job()
            x = number / 100
            body = (f'when(ddGetObj({sk(args.library)} {sk(cell)}) error("Synthetic cell exists")) '
                f'let((cv) cv=dbOpenCellViewByType({sk(args.library)} {sk(cell)} "layout" "maskLayout" "w") '
                'unless(cv error("Cannot create synthetic cell")) unwindProtect(progn('
                f'unless(dbCreateRect(cv list({sk(args.layer)} "drawing") '
                f'list(list({x} 0) list({x + 1} 1))) error("Cannot create test shape")) '
                'unless(dbSave(cv) error("Cannot save test shape"))) dbClose(cv)))')
            adapter._run(folder, body)
            created.append(cell)
            snapshots.append(adapter.capture(args.library, cell))
        with tempfile.TemporaryDirectory(prefix='ald-native-git-') as temp:
            repo = Path(temp) / 'repo'; repo.mkdir()
            git(repo, 'init'); git(repo, 'symbolic-ref', 'HEAD', 'refs/heads/target')
            git(repo, 'config', 'user.name', 'Synthetic Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            identity = [args.library, cells[0], 'layout']
            state = Path(temp) / 'agent'
            def agent(ident, operation, payload):
                path = root / (ident + '.json'); atomic_json(path, payload)
                process = subprocess.run([sys.executable, '-m', 'layoutdiff', 'agent', '--root', str(state),
                    '--request-id', ident, '--operation', operation, '--payload', str(path),
                    '--native-backend', 'batch', '--virtuoso', args.virtuoso,
                    '--virtuoso-cwd', args.cwd, '--validation-library', args.library],
                    capture_output=True, text=True, timeout=300, check=True)
                result = json.loads(process.stdout)
                assert result['status'] == 'complete', result
                return result['result']
            exported = agent('export', 'export', {'repository': str(repo), 'cellview': identity})
            assert exported['capture_state'] == 'saved_oa' and exported['git_commit'] is None
            git(repo, 'add', '--all'); git(repo, 'commit', '-m', 'baseline native export')
            base = resolve(repo, 'HEAD')
            def store(snapshot, message):
                path = repo / snapshot_directory(identity)
                import shutil
                if not path.resolve().is_relative_to(repo.resolve()):
                    raise ValueError('Snapshot path escaped synthetic repository')
                shutil.rmtree(path)
                value = from_snapshot(snapshot, path); value.close()
                git(repo, 'add', '--all'); git(repo, 'commit', '-m', message)
                return resolve(repo, 'HEAD')
            ours = store(snapshots[1], 'target native change')
            git(repo, 'checkout', '-b', 'incoming', base)
            theirs = store(snapshots[2], 'incoming native change')
            git(repo, 'checkout', 'target')
            git(repo, 'merge', '--no-ff', '--no-commit', 'incoming', check=False)
            plan = agent('explain', 'merge_explain', {'repository': str(repo)})['cells'][0]
            decisions = {u['id']: 'incoming' for u in plan['units'] if u['status'] == 'unresolved'}
            resolved = agent('resolve', 'merge_apply', {'plan_id': plan['plan_id'], 'generation': plan['generation'],
                'mode': 'write', 'decisions': decisions})
            assert resolved['validation'] == 'native_readback' and resolved['native']['backend'] == 'batch'
            assert resolved['staged'] is False and resolve(repo, 'HEAD') == ours
            git(repo, 'add', '--all', '--', 'layouts'); git(repo, 'commit', '--no-edit')
            final = resolve(repo, 'HEAD')
            assert git(repo, 'show', '-s', '--format=%P', final).stdout.decode().split() == [ours, theirs]
            history = GitSnapshots(repo, identity)
            try:
                assert digest(history.snapshot(final)) == digest(snapshots[2])
            finally:
                history.close()
            delta = agent('diff', 'diff', {'repository': str(repo), 'cellview': identity, 'left': base, 'right': final})
            assert delta['counts']['moved'] == 1
            assert adapter.capture(args.library, cells[0]) == snapshots[0]
            atomic_json(root / 'result.json', {'git': git(repo, '--version').stdout.decode().strip(),
                'native_export_commit_diff_merge_readback': 'passed', 'source_unchanged': True})
            print((root / 'result.json').read_text())
    finally:
        # Only the exact unique views created by this synthetic driver are removed.
        cleanup = '\n'.join(f'when(ddGetObj({sk(args.library)} {sk(cell)} "layout") '
                            f'ddDeleteObj(ddGetObj({sk(args.library)} {sk(cell)} "layout")))' for cell in created)
        adapter._run(adapter._job(), cleanup)


if __name__ == '__main__':
    main()
