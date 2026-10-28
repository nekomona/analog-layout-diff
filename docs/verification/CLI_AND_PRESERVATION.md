# CLI independence and unsupported-content preservation

Capability assessment for **0.17.1**. This is a capability assessment;
the native capture policy and storage format are unchanged.

## CLI dependency boundary

| Operation | Requirements | Layout Diff GUI worker/supervisor |
| --- | --- | --- |
| `capture`, `restore` | Python package, Virtuoso, bridge daemon/connection, accessible libraries/PDK | Not required |
| `encode-v2`, `decode-v2`, `diff`, `apply`, `diff-stream`, `apply-stream` | Python package and files | Not required; no bridge needed |
| `gui-serve`, `gui-stop`, `gui-clean`, interactive review/commit tools | Installed plugin and shared bridge; GUI operations use its worker | Required for interactive workflow |

The small bridge daemon is distinct from the Layout Diff runtime. Native CLI
commands instantiate `VirtuosoAdapter` directly, load `virtuoso/skill/reader.il`
as needed, and call the database through the bridge. They do not queue work to
the GUI worker. A one-shot hierarchy fingerprint helper may run on the host;
it is not a persistent Layout Diff service. A direct OA reader or batch-Virtuoso
launcher is not implemented, so native CLI operations do not eliminate Virtuoso
or its bridge requirement.

From an activated environment with the package available:

```sh
python -m layoutdiff capture LIB CELL snapshot.layout --format v2
python -m layoutdiff restore snapshot.layout replay_cell --library TEST_LIB --allow-library TEST_LIB
python -m layoutdiff decode-v2 snapshot.layout expanded.json
python -m layoutdiff encode-v2 expanded.json encoded.layout
```

Restore only creates a fresh destination; it refuses an existing cellview.
Its destination technology must match. Referenced masters and custom native
group definitions must be available. The current CLI does not expose the
adapter's `group_definition_source` argument, so source-defined custom groups
may require first reading their source layout in the same Virtuoso session.

Standalone capture uses `/tmp/ald_*` transport files and a local `artifacts/`
directory. It does not get the GUI runtime's window/lease-based scratch cleanup.
File-only diff/apply reconstructs serialized data, not a native OA cellview.

## What unsupported-content preservation currently means

| Path | Preserved data | Limit |
| --- | --- | --- |
| `capture --format v1` | Supported records and captured unsupported diagnostic records; reports coverage issues | Some native state is not fully encoded |
| `capture --format v2` | Supported records | Strict capture rejects unsupported content, with the complete report |
| v1 to v2 encoding / decoding / exact diff / patch replay | Unknown logical record kinds and fields already present in the input | Unknown snapshot schemas/envelope fields remain rejected; no OA semantics are inferred |
| Confirmed incomplete GUI Git commit | Supported snapshot plus `omissions.json` and `omissions.jsonl` | Diagnostic records are audit data, not replay input |
| Native restore | Supported snapshot | Unsupported records in the replay input are rejected |

The omission report contains each original normalized record, its canonical
key, rejection reasons and action. It is committed alongside the layout, with
hashes binding the report, full capture and supported snapshot. Thus existing
incomplete commits already carry useful evidence for later support work.

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
  sidecars. The CLI `git-extract` currently handles a legacy v1 JSON blob only,
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

Any future archival design should keep three distinct policies: supported
objects are replayed, unsupported objects are archived but not yet replayed,
and explicitly ignored objects remain excluded.

## Proposed extension, not implemented

Use a versioned, data-only opaque-object archive for unsupported nonignored
content. Preserve typed attribute values with units, stable capture-local
object references, relationships to supported records, producer/Cadence/PDK
version metadata, and explicit completeness/missing-field indicators. Bind the
archive to the layout checkpoint and carry it through Git export, standalone
codec operations and patch replay. Future support should migrate records
explicitly and validate native readback; old opaque data must never execute as
SKILL. Keep the existing double confirmation wherever native rollback still
loses unsupported objects.

An OA binary backup could provide an additional native recovery path, but it
would have separate technology/hierarchy dependencies and could contain
explicitly ignored objects. It is not an implementation of the requested
exclusion policy and is not proposed as this text snapshot's payload.

## Verification and limits

Permanent offline coverage lives in `tests/test_forward_compatibility.py`,
including complete omission-audit readback from disposable Git commits and
core-only conversions that leave audit sidecars behind. Native verification
requires a configured Virtuoso/bridge connection and a dedicated synthetic test
library. Verify import/call-path independence separately from a literal
stopped-runtime test. Keep execution reports and session state local.
