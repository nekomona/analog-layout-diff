from types import SimpleNamespace
import json
import pytest
import layoutdiff.ui.restore as restore


def worker(tmp_path, *, copy_error=False, rollback_error=False, local=False):
    calls = []
    def execute(code):
        calls.append(code)
        if code.startswith('ALDGUIRestoreBackup'):
            return '("a" "a")'
        if code.startswith('ALDGUIRestoreCopy'):
            if '"checkpoint"' in code and copy_error:
                raise RuntimeError('copy failed')
            if '"backup"' in code and rollback_error:
                raise RuntimeError('rollback failed')
        return 't'
    value = SimpleNamespace(root=tmp_path, execute=execute, calls=calls,
        client=SimpleNamespace(layoutdiff_local_files=local),
        adapter=SimpleNamespace(capture=lambda *args, **kwargs: {'objects': {}}),
        notice=lambda text: None)
    value.restore_plans = {'token': dict(token='token', identity=['TEST','source','layout'],
        library='ALD_TMP_test', commit='abc', stamp='saved', expected='not-the-actual-digest',
        artifacts=str(tmp_path/'artifacts'))}
    return value


def test_stale_restore_never_replaces_target(tmp_path, monkeypatch):
    value = worker(tmp_path)
    monkeypatch.setattr(restore, 'disk_stamp', lambda *a: 'changed')
    with pytest.raises(ValueError, match='changed after'):
        restore.apply(value, 'token')
    assert not any('RestoreCopy' in c or 'RestoreBackup' in c for c in value.calls)
    assert value.calls[-1].endswith("['hold]=nil")


def test_copy_failure_attempts_native_rollback_and_reopens_windows(tmp_path, monkeypatch):
    value = worker(tmp_path, copy_error=True)
    monkeypatch.setattr(restore, 'disk_stamp', lambda *a: 'saved')
    with pytest.raises(RuntimeError, match='copy failed'):
        restore.apply(value, 'token')
    assert any('ALDGUIRestoreCopy' in c and '"backup"' in c for c in value.calls)
    assert any('ALDGUIRestoreOpen' in c and '("a" "a")' in c for c in value.calls)


def test_readback_failure_rolls_back(tmp_path, monkeypatch):
    value = worker(tmp_path)
    monkeypatch.setattr(restore, 'disk_stamp', lambda *a: 'saved')
    monkeypatch.setattr(restore, 'native_snapshot', lambda s: s)
    with pytest.raises(ValueError, match='readback differs'):
        restore.apply(value, 'token')
    assert any('ALDGUIRestoreCopy' in c and '"backup"' in c for c in value.calls)


def test_rollback_failure_protects_backup_even_if_archive_fails(tmp_path, monkeypatch):
    value = worker(tmp_path, copy_error=True, rollback_error=True, local=True)
    monkeypatch.setattr(restore, 'disk_stamp', lambda *a: 'saved')
    with pytest.raises(RuntimeError, match='rollback needs attention'):
        restore.apply(value, 'token')
    record = json.loads((tmp_path/'recovery/token.json').read_text())
    assert record['rollback_error'] == 'rollback failed'
    assert 'backup_archive_error' in record  # No native backup directory in this injected-failure fixture.
    assert any("['recovery]=t" in c for c in value.calls)
