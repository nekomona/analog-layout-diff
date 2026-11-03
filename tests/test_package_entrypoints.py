"""Public entry points must survive movement into functional packages."""
from pathlib import Path
import importlib
from importlib.resources import files
import subprocess
import sys
import types
import xml.etree.ElementTree as ET

import pytest


def test_public_reference_and_adapter_facades_use_canonical_implementations():
    from layoutdiff import canonicalize, diff, apply_diff, empty_snapshot
    from layoutdiff.data import core
    from layoutdiff.eda.virtuoso import VirtuosoAdapter
    from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter as Adapter
    from layoutdiff.virtuoso import VirtuosoAdapter as LegacyAdapter
    assert VirtuosoAdapter is Adapter and diff is core.diff
    assert LegacyAdapter is Adapter
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


def test_eda_package_imports_do_not_require_native_bindings():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', '''
import sys
from importlib.abc import MetaPathFinder
class NoNativeBindings(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pya', 'klayout', 'virtuoso_bridge'}:
            raise AssertionError('Unexpected native import: ' + fullname)
sys.meta_path.insert(0, NoNativeBindings())
import layoutdiff.eda
import layoutdiff.eda.virtuoso
import layoutdiff.eda.klayout
import layoutdiff.virtuoso
import klayout_plugin
'''], cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_legacy_klayout_modules_share_the_canonical_implementation():
    pytest.importorskip('klayout.db')
    for name in ('api', 'codec', 'review', 'gui', 'render_diff', 'generate_demo'):
        canonical = importlib.import_module('layoutdiff.eda.klayout.' + name)
        assert importlib.import_module('klayout_plugin.' + name) is canonical


def test_eda_resources_are_owned_by_the_adapter_packages():
    virtuoso = files('layoutdiff.eda.virtuoso')
    for name in ('reader.il', 'hierarchy.il'):
        assert 'procedure(' in virtuoso.joinpath('skill', name).read_text(encoding='utf-8')
    klayout = files('layoutdiff.eda.klayout')
    assert ET.fromstring(klayout.joinpath('analog_layout_diff.lym').read_text()).tag == 'klayout-macro'
    assert 'added' in klayout.joinpath('style.example.json').read_text()


@pytest.mark.parametrize('configured', [False, True])
def test_klayout_macro_finds_package_and_installs_once(monkeypatch, tmp_path, configured):
    root = Path(__file__).resolve().parents[1]
    macro_path = root / 'layoutdiff/eda/klayout/analog_layout_diff.lym'
    source = ET.parse(macro_path).findtext('text')
    calls = []
    gui = types.ModuleType('layoutdiff.eda.klayout.gui')
    gui.install = lambda: calls.append('install')
    monkeypatch.setitem(sys.modules, gui.__name__, gui)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    if configured:
        monkeypatch.setenv('ANALOG_LAYOUT_DIFF_ROOT', str(root))
        macro_path = tmp_path / 'copied-macro.lym'
    else:
        monkeypatch.delenv('ANALOG_LAYOUT_DIFF_ROOT', raising=False)
    exec(compile(source, str(macro_path), 'exec'), {'__file__': str(macro_path)})
    assert sys.path[0] == str(root)
    assert calls == ['install']


def test_klayout_macro_rejects_invalid_configured_root(monkeypatch, tmp_path):
    macro = files('layoutdiff.eda.klayout').joinpath('analog_layout_diff.lym')
    source = ET.fromstring(macro.read_text()).findtext('text')
    monkeypatch.setenv('ANALOG_LAYOUT_DIFF_ROOT', str(tmp_path))
    with pytest.raises(RuntimeError, match='directory containing layoutdiff'):
        exec(compile(source, str(macro), 'exec'), {'__file__': str(macro)})
