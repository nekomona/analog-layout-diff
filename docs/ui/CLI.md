# CLI independence and unsupported-content preservation

The CLI exposes file-only operations and direct native adapter calls. Its
dependencies and preservation limits are described below.

## CLI dependency boundary

| Operation | Requirements | Layout Diff GUI worker/supervisor |
| --- | --- | --- |
| `capture`, `restore`, `record` with `--native-backend bridge` (default) | Python package, Virtuoso, bridge daemon/connection, accessible libraries/PDK | Not required |
| `capture`, `restore`, `record` with `--native-backend batch` | Python package on the OA host, configured Virtuoso executable and libraries/PDK | Not required; no bridge daemon or display |
| `agent` | Python package, Git, request JSON; optional native batch backend | Not required |
| `encode-v2`, `decode-v2`, `diff`, `apply`, `diff-stream`, `apply-stream` | Python package and files | Not required; no bridge needed |
| `gui-serve`, `gui-stop`, `gui-clean`, interactive review/commit tools | Installed plugin and shared bridge; GUI operations use its worker | Required for interactive workflow |

The small bridge daemon is distinct from the Layout Diff runtime. Native CLI
commands instantiate `VirtuosoAdapter` directly, load `virtuoso/skill/reader.il`
as needed, and call the database through the bridge. They do not queue work to
the GUI worker. A one-shot hierarchy fingerprint helper may run on the host;
it is not a persistent Layout Diff service. The batch backend starts a fresh
`virtuoso -nograph -nocdsinit -restore` process for each native job. It clears
`DISPLAY` and `CDS_NOGRAPH_DISPLAY`, loads database helpers without the GUI
plugin or Bridge monitor, and captures saved OA state. It still needs Virtuoso,
its license and the configured libraries/PDK; it cannot see another session's
unsaved edits. The environment must already be configured before invocation.

The default bridge backend uses `VirtuosoClient.from_env()` and the Bridge-resolved profile.
The Layout Diff CLI has no Bridge `--profile`/`--env` options; use the active
environment's profile binding or pass a selected client through the Python API.
See [connection setup](../runtime/BRIDGE.md#connection-paths).

From an activated environment with the package available:

```sh
python -m layoutdiff capture LIB CELL snapshot.layout --format v2
python -m layoutdiff restore snapshot.layout replay_cell --library TEST_LIB --allow-library TEST_LIB
python -m layoutdiff decode-v2 snapshot.layout expanded.json
python -m layoutdiff encode-v2 expanded.json encoded.layout
python -m layoutdiff capture LIB CELL snapshot.layout --format v2 \
  --native-backend batch --virtuoso-cwd /projects/example
python -m layoutdiff restore snapshot.layout replay_cell --library TEST_LIB --allow-library TEST_LIB \
  --native-backend batch --virtuoso-cwd /projects/example
```

Restore only creates a fresh destination; it refuses an existing cellview.
Its destination technology must match. Referenced masters and custom native
group definitions must be available. Use `--group-definition-source LIB CELL VIEW`
to read persisted custom definitions from a source view before reconstruction.
`--virtuoso` selects the batch executable; `--virtuoso-cwd` selects the working
directory containing `cds.lib`. A restore creates only a fresh destination and
verifies its native readback. Batch jobs retain scripts, capture files and logs
under the command's artifacts directory; a failed or timed-out job reports that
location and is not automatically retried.

Standalone capture uses `/tmp/ald_*` transport files and a local `artifacts/`
directory. It does not get the GUI runtime's window/lease-based scratch cleanup.
File-only diff/apply reconstructs serialized data, not a native OA cellview.

## Semantic Git operations without a GUI

`python -m layoutdiff agent` and `python -m layoutdiff.agent` are equivalent
headless entry points. See the [agent guide](../agent/README.md#headless-cli-and-ssh-transport)
for request JSON, persisted pagination and optional native validation. Python
performs semantic diff/merge; system Git resolves revisions and supplies blobs.
Use ordinary `git add`, `git commit` and `git log` for staging, commits and
history. The CLI `commit` command still belongs to the standalone legacy history;
it is not a system-Git wrapper.

## What unsupported-content preservation currently means

| Path | Preserved data | Limit |
| --- | --- | --- |
| `capture --format v1` | Supported records and captured unsupported diagnostic records; reports coverage issues | Some native state is not fully encoded |
| `capture --format v2` | Supported records | Strict capture rejects unsupported content, with the complete report |
| v1 to v2 encoding / decoding / exact diff / patch replay | Unknown logical record kinds and fields already present in the input | Unknown snapshot schemas/envelope fields remain rejected; no OA semantics are inferred |
| Confirmed incomplete GUI Git commit | Supported snapshot plus `omissions.json` and `omissions.jsonl` | Diagnostic records are audit data, not replay input |
| Consented incomplete agent export/merge write | Supported snapshot plus hash-bound omission audit and complete report | Consent binds the candidate and Git inputs; system Git staging/commit remains separate |
| Native restore | Supported snapshot | Unsupported records in the replay input are rejected |

The omission report contains each original normalized record, its canonical
key, rejection reasons and action. It is committed alongside the layout, with
hashes binding the report, full capture and supported snapshot. The audit stays bound to the checkpoint for inspection.

However, this is **not a lossless future restoration guarantee**:

- `ALDOpaqueObject` records exposed attributes; unknown relationships become
  `@diagnostic-ref` hints containing type, optional name and bounding box.
  These are not unique object IDs and do not encode a complete reference graph.
- Other unsupported features may only have a marker or partial representation.
  Generic attributes can have unspecified units or derived/native-only state.
  A future writer cannot recover information that the current reader did not capture.
- Omission files are outside the core snapshot's semantic hash and patch model.
  Their own audit hashes preserve integrity, but `GitSnapshots.snapshot()` and
  ordinary encode/decode of the resulting snapshot do not carry the audit
  sidecars. The CLI `git-extract` currently handles a v1 JSON blob only,
  not a v2 directory bundle. Archive the entire committed layout directory
  when retaining this evidence.
- Later complete commits remove omission files from their current tree; older
  Git revisions retain them. There is no automatic migration that converts old
  diagnostic records into newly supported native objects.

## Explicit ignores remain excluded

Routes, markers and Steiners remain intentionally ignored, including their
group memberships. Their ordinary member shapes/vias and supported connectivity
are still tracked. They are not candidates for an unsupported-object archive.
The exclusion decision precedes native capture; the generic JSON codec itself
does not reinterpret or filter manually supplied records.

## Verification and limits

Permanent offline coverage lives in `tests/test_forward_compatibility.py`,
including complete omission-audit readback from disposable Git commits and
core-only conversions that leave audit sidecars behind. Native verification
requires a configured Virtuoso/bridge connection and a dedicated synthetic test
library. Verify import/call-path independence separately from a literal
stopped-runtime test. Keep execution reports and session state local.
