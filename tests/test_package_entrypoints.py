"""Public entry points must survive movement into functional packages."""
from pathlib import Path
import subprocess
import sys


def test_public_reference_and_adapter_facades_use_canonical_implementations():
    from layoutdiff import canonicalize, diff, apply_diff, empty_snapshot
    from layoutdiff.data import core
    from layoutdiff.virtuoso import VirtuosoAdapter
    from layoutdiff.virtuoso.adapter import VirtuosoAdapter as Adapter
    assert VirtuosoAdapter is Adapter and diff is core.diff
    before = empty_snapshot()
    after = canonicalize([{'kind': 'rect', 'bBox': [[0, 0], [1, 1]], 'props': []}])
    assert apply_diff(before, diff(before, after)) == after


def test_runtime_module_entrypoint_and_core_do_not_require_bridge():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-m', 'layoutdiff.runtime', '--help'],
                            cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'supervise' in result.stdout and 'reap' in result.stdout
    result = subprocess.run([sys.executable, '-c',
        'import sys; import layoutdiff.data.storage, layoutdiff.comparison.changeindex; '
        'assert not any(n.startswith("virtuoso_bridge") for n in sys.modules)'],
        cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_old_and_canonical_textconv_entries_work_outside_checkout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    snapshot = root/'tests/fixtures/legacy_history/example-latest.json'
    outputs = []
    for script in ('layoutdiff/git_driver.py', 'layoutdiff/git/driver.py'):
        result = subprocess.run([sys.executable, str(root/script), str(snapshot)],
                                cwd=tmp_path, capture_output=True)
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] and b'Analog layout snapshot' in outputs[0]
