"""Explicit checkpoint restoration; Git index, worktree, and refs stay untouched."""
import hashlib
from pathlib import Path
from .sexpr import dumps as sk, loads
from .history import atomic_json
from .dependencies import native_snapshot
from .virtuoso import VirtuosoAdapter
from .core import digest


def disk_stamp(worker, identity):
    args = ' '.join(sk(x) for x in identity)
    if worker.execute(f'ALDGUIRequireSaved({sk(identity)})') != 't':
        raise ValueError('Save or discard the target layout edits before restoring a checkpoint.')
    path = loads(worker.execute(f'ddGetObj({args})~>readPath')) + '/layout.oa'
    if getattr(worker.client, 'layoutdiff_local_files', False):
        local = Path(path)
    else:
        local = worker.adapter.artifacts / 'target-before.oa'
        worker.client.download_file(path, str(local))
    h = hashlib.sha256()
    with local.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def prepare(worker, identity, revision):
    for old in list(worker.restore_plans):
        cancel(worker, old)
    state = worker.browser_state
    owned = not (state and state['model'] and state['model'].identity == identity)
    model = worker.history_model(identity) if owned else state['model']
    try:
        _, after = model.pair(revision)
        from .omissions import warning
        omission_warning = warning(model.store.omissions(revision)) if model.store else ''
    finally:
        if owned:
            model.close()
    if not after['objects']:
        raise ValueError('This checkpoint deletes the snapshot. Select an existing checkpoint to restore.')
    meta = after['objects']['cell:']
    if worker.client.library.get(identity[0]).technology_library != meta['technology']:
        raise ValueError('Target technology differs from checkpoint')
    stamp = disk_stamp(worker, identity)
    lib = worker.temporary_library(meta['technology'])
    adapter = VirtuosoAdapter(worker.client, worker.adapter.artifacts, writable_library=lib)
    worker.execute('ALDGUIStatus("Reconstructing and verifying restore checkpoint")')
    actual = adapter.reconstruct(after, lib, 'checkpoint', group_definition_source=identity)
    token = worker.active_work['token']
    plan = dict(token=token, identity=list(identity), commit=revision, stamp=stamp,
                library=lib, checkpoint='checkpoint', expected=digest(native_snapshot(actual)),
                artifacts=str(worker.adapter.artifacts), warnings=adapter.last_dependency_warnings)
    worker.restore_plans[token] = plan
    atomic_json(worker.adapter.artifacts / 'restore.json', {k: v for k, v in plan.items() if k != 'expected'})
    # Retain the verified checkpoint until the asynchronous OK/Cancel callback.
    worker.execute(f'ALDGUILeases[{sk(token)}][\'hold]=t')
    text = (f"Restore {' / '.join(identity)}\nCheckpoint: {revision}\n\n"
            + (omission_warning + '\n\n' if omission_warning else '') +
            f"The checkpoint has been reconstructed and verified ({len(after['objects'])} records).\n"
            f"Hierarchy warnings: {len(adapter.last_dependency_warnings)}\n\n"
            "OK replaces and saves the current layout. Its layout windows will close and reopen. "
            "Save or discard any unsaved edits first. A native backup is retained until the reopened target windows close.\n\n"
            "Git history and its index stay unchanged. Use Save & Commit afterward to record the restore.\n"
            "External hierarchical masters are not restored. The target is rechecked before replacement.")
    worker.execute(f'ALDGUIRestoreConfirm({sk(token)} {sk(text)})')
    return {k: plan[k] for k in ('token', 'identity', 'commit', 'library', 'warnings')}


def cancel(worker, token):
    plan = worker.restore_plans.pop(token, None)
    if plan:
        worker.execute(f'ALDGUILeases[{sk(token)}][\'hold]=nil')
    return {'cancelled': bool(plan)}


def apply(worker, token):
    plan = worker.restore_plans.pop(token, None)
    if not plan:
        raise ValueError('Restore preview expired. Select the checkpoint again.')
    target, lib = plan['identity'], plan['library']
    args = ' '.join(sk(x) for x in target)
    replaced = False
    windows = []
    try:
        if disk_stamp(worker, target) != plan['stamp']:
            raise ValueError('Target changed after restore preview. Prepare the restore again.')
        worker.execute('ALDGUIStatus("Backing up the native layout before replacement")')
        # This single SKILL call rechecks modified state, copies every OA object
        # including deliberately ignored annotations, and closes direct windows.
        windows = loads(worker.execute(f'ALDGUIRestoreBackup({sk(target)} {sk(lib)})')) or []
        replaced = True
        worker.execute(f'ALDGUIRestoreCopy({sk(lib)} "checkpoint" {sk(target)})')
        actual = worker.adapter.capture(*target, dependencies=False)
        if digest(native_snapshot(actual)) != plan['expected']:
            raise ValueError('Restored target readback differs from verified checkpoint')
        worker.execute(f'ALDGUIRestoreOpen({sk(target)} {sk(windows)})')
        worker.execute(f'ALDGUILeases[{sk(token)}][\'watchCells]=list({sk(target)})')
        worker.notice(f"Restored {'/'.join(target)} to {plan['commit'][:12]}.\n"
                      "Git is unchanged. Use Save & Commit to record the restore.\n"
                      f"Native backup: {lib}/backup/layout (kept until the target windows close).")
        return dict(restored=target, commit=plan['commit'], backup=[lib, 'backup', 'layout'])
    except Exception as exc:
        if replaced:
            try:
                worker.execute(f'ALDGUIRestoreCopy({sk(lib)} "backup" {sk(target)})')
            except Exception as rollback:
                import shutil
                recovery = {k: v for k, v in plan.items() if k != 'expected'}
                recovery.update(error=str(exc), rollback_error=str(rollback))
                worker.execute(f'ALDGUILeases[{sk(token)}][\'recovery]=t')
                atomic_json(worker.root / 'recovery' / (token + '.json'), recovery)
                if getattr(worker.client, 'layoutdiff_local_files', False):
                    saved = worker.root / 'recovery' / token / 'oa'
                    try:
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(Path(plan['artifacts']) / 'oa', saved)
                        recovery['native_backup_directory'] = str(saved / 'backup')
                    except OSError as archive_error:
                        recovery['backup_archive_error'] = str(archive_error)
                atomic_json(worker.root / 'recovery' / (token + '.json'), recovery)
                raise RuntimeError(f'Restore failed and rollback needs attention. Native backup: {lib}/backup/layout. '
                                   f'Recovery record: {worker.root / "recovery" / (token + ".json")}') from rollback
        if windows:
            worker.execute(f'ALDGUIRestoreOpen({sk(target)} {sk(windows)})')
        raise
    finally:
        worker.execute(f'ALDGUILeases[{sk(token)}][\'hold]=nil')
