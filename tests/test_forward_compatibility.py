"""Data preservation is broader than native reconstruction support."""
import json

from layoutdiff.data.core import canonicalize, encoded, empty_snapshot
from layoutdiff.data.storage import from_snapshot, load
from layoutdiff.data.streampatch import create, apply
from layoutdiff.git import commit as gc
from layoutdiff.git.store import GitSnapshots
from layoutdiff.virtuoso.omissions import project, DETAILS
from layoutdiff.virtuoso.support import coverage


def records():
    return [dict(kind='cell', name='', dbu=1000, units='micron', cellType='maskLayout',
                 technology='test', props=[]),
            dict(kind='rect', layerName='M1', purpose='drawing',
                 bBox=[[0, 0], [1000, 1000]], props=[]),
            dict(kind='futureObject', props=[],
                 diagnosticAttributes=[['owner', ['@diagnostic-ref', 'rect', None,
                                                  [[0, 0], [1, 1]]]]],
                 futurePayload={'values': [None, False, 0, 0.0, 'uninterpreted']})]


def test_unknown_records_and_fields_survive_data_codec_and_stream_patches(tmp_path):
    original = canonicalize(records())
    assert coverage(original)  # Storable JSON is not necessarily replayable OA.
    empty = from_snapshot(empty_snapshot(), tmp_path/'empty')
    full = from_snapshot(original, tmp_path/'full')
    try:
        assert encoded(load(full.path)) == encoded(original)
        create(empty, full, tmp_path/'patch', backend='python')
        replay = apply(empty, tmp_path/'patch', tmp_path/'replay', backend='python')
        try:
            assert encoded(replay.materialize()) == encoded(original)
        finally:
            replay.close()
    finally:
        empty.close(); full.close()


def test_confirmed_incomplete_git_snapshot_retains_diagnostic_payload_in_sidecar(tmp_path):
    rows = records()
    full = from_snapshot(canonicalize(rows), tmp_path/'full')
    supported = project(full, tmp_path/'supported', tmp_path/'omissions.jsonl')
    repo = tmp_path/'repo'; repo.mkdir()
    gc.git(repo, 'init')
    gc.git(repo, 'config', 'user.name', 'Archive Test')
    gc.git(repo, 'config', 'user.email', 'archive@example.invalid')
    identity = ['TEST', 'future', 'layout']
    preview = gc.prepare_v2(repo, identity, supported, backend='python')
    try:
        result = gc.commit(preview, 'Test incomplete checkpoint archive')
        store = GitSnapshots(repo, identity)
        try:
            raw = gc.git(repo, 'show', result['git_commit']+':'+store.v2+'/'+DETAILS).stdout
            assert raw == supported.omission_report.read_bytes()
            assert json.loads(raw)['record'] == rows[-1]
            assert store.snapshot(result['git_commit']) == canonicalize(rows[:-1])
            assert store.omissions(result['git_commit'])['omitted'] == 1
            # Core snapshot extraction/conversion doesn't carry the audit files.
            portable = from_snapshot(store.snapshot(result['git_commit']), tmp_path/'portable')
            try:
                assert not (portable.path/DETAILS).exists()
            finally:
                portable.close()
        finally:
            store.close()
    finally:
        preview.close(); supported.close(); full.close()
