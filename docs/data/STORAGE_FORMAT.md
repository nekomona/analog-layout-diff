# Streaming snapshot storage

The current storage schema is `analog-layout-diff/2`, codec 1. `data/storage.py` is
the codec authority; `data/core.py` defines the expanded v1 semantics and object
identity. C++ does not reinterpret layout fields or numbers.

## Git tree

```text
layouts/<library>/<cell>/<view>.layout/
  manifest.json
  objects.jsonl
  definitions.jsonl
```

Path components use reversible UTF-8 percent encoding.
All three files exist, including an empty `definitions.jsonl`. Git is the only
history authority. SQLite indexes, expanded wire streams and temporary patches
are disposable files outside this tree, with no alternate HEAD or commit graph.

The manifest contains exactly `schema: "analog-layout-diff/2"`, `codec: 1`,
`objectCount`, `semanticSha256`, and `files`, mapping the two JSONL filenames to
their SHA-256 digests. `semanticSha256` hashes the fully expanded canonical v1
snapshot. Thus v1 and v2 representations of the same state have the same logical
hash; the representation change does not alter anonymous keys.

### Optional omission audit

An explicitly confirmed incomplete checkpoint adds `omissions.json` and
`omissions.jsonl` beside the three mandatory files. They are not snapshot objects
and do not change the v2 schema or semantic hash. Git history/cell discovery
recognizes changes to either audit file. Both are removed on a complete capture.

The summary schema is `analog-layout-diff/omissions/1`: `sourceSha256` binds the
full normalized capture, `snapshotSha256` binds the supported-only snapshot,
`omitted` and `detached` count affected records, `counts` summarizes rejection
reasons, and `reportSha256` binds the JSONL report. Each report row contains the
original canonical `element` key, `issues`, original `record`, and an `action`
of `omit` or `detach-group`. The report is diagnostic data, not replay input.
Runtime warnings verify that the summary belongs to the selected snapshot.

`omissions.project` uses a disposable SQLite dependency graph and bounded caches.
It rejects unsupported objects, propagates to dependent objects, detaches retained
figures from rejected figure groups, and resolves temporary IDs again to update
all content-addressed links. A strict validation pass follows projection.
This is a Python capture operation; the existing Python/C++ diff kernels consume
the resulting ordinary snapshot without any change in semantics.

## Encoding and identity

JSON uses Python's reference `core.encoded`: sorted field names, compact
separators, ASCII Unicode escapes, finite JSON numbers, and no insignificant
whitespace. JSONL adds one LF after every record. Floating-point formatting
follows the supported Python encoder; C++ preserves those bytes exactly.
Integer `0`, floating `0.0`, boolean `false`, null, an absent field and empty
containers remain distinct. Geometry coordinates remain integer DBU.

Object lines are ordered lexically by the expanded canonical key:

```json
{"defaults":["orient","physOnly","viewName"],"key":"inst:M0","record":{"cellName":"example_nmos","kind":"inst","libName":"EXAMPLE_TECH","name":"M0","pcell":true,"xy":[0,2000]},"refs":{"params":"sha256:<64 lowercase hex digits>"}}
```

The example's reference is illustrative. A real reference must exist and hash
correctly. Envelopes contain `key`, `record`, optional `defaults` and optional
`refs`; unknown envelope fields are rejected. Unknown logical record fields are
retained. Native restoration additionally enforces the supported OA subset.

Named kinds are `cell`, `net`, `term`, `inst`, `mosaic`, `figGroup`, `dependency`.
Their key is `kind:name`. Other kinds use `kind:SHA256(expanded record):occurrence`.
Identical figures retain contiguous occurrence numbers starting at zero, sorted
lexically in the file (so `:10` precedes `:2`). Ordered geometry arrays are never
reordered. Moving anonymous geometry is still delete/add; moving a named
instance is modification. The GUI pairs equal-geometry attribute edits and confidently matched moves
and stretches for presentation. It classifies movement/size-only edits separately
from ordinary modifications. This derived
pairing does not change stored identity or exact forward/reverse patches.

## Explicit default presence

Codec 1 recognizes these defaults:

| Field | Value |
|---|---|
| `props` | `[]` |
| `net`, `pin`, `group` | `null` |
| `viewName` | `"layout"` |
| `orient` | `"R0"` |
| `physOnly` | `false` |

An omitted field is restored only if named in the sorted, unique `defaults`
list. Absence from both `record` and `defaults` means truly absent. Conflicts
are errors. The writer omits defaults only when the envelope becomes smaller.
This is a storage optimization, never an assumption about PDK defaults.

## Immutable definitions

Repeated `params` or `props` blocks of at least 192 encoded bytes can move to
`definitions.jsonl` when used at least twice. A definition has `id`, `field`,
and `value`. Its ID is `sha256:` plus SHA-256 of:

```text
ASCII("ald-definition-1") + NUL + canonical_json({"field": field, "value": value})
```

Definitions are sorted by full ID. A reference restores one complete typed
field, preserving effective PCell parameters and nested properties. An inline
field, default and reference cannot coexist for the same field. Missing,
wrong-type, corrupt and unused definitions are rejected. Changing a block
creates a new ID without renumbering other definitions. These are data, never
programs or external paths. All expanded top-level content is recoverable from
the revision alone; hierarchy masters and PCell programs remain external.

## Streaming and limits

Capture spools records to SQLite with a 4 MiB page cache and file-backed sorting.
Definition expansion uses another bounded cache (32 entries / 4 MiB, except
one larger record). A JSONL line may be at most 16 MiB including LF. Large
individual records can consume considerably more decoded memory; memory is
bounded with respect to object count, not independent of the largest record.

Validation checks canonical bytes, duplicate JSON fields, key order and
multiplicity, definition hashes, counts, semantic hash and file hashes.
`Snapshot.records()` must be exhausted to complete validation; `wire()` does
so before publishing a reusable validated stream. Treat a `Snapshot` source
as immutable for its lifetime. Call `close()` for caches and `dispose()` for
owned temporary captures. Symlink snapshot files are rejected.

The transient wire form is `hex(UTF8 key) TAB canonical expanded record LF`.
Sorted merge-join emits exact operations to disk. Category pairing and paging
use a disposable SQLite index; browser caches retain at most three snapshots
and two selected comparisons. Native review still materializes its selected
before/after states and generates SKILL. It has a higher memory cost.

## Patch bundles and migration

`diff-stream` creates `manifest.json` plus `operations.jsonl`. Patch schema is
`analog-layout-diff/2/patch`; the manifest includes `parent`, `base`, `result`
and `operationsSha256`. Operations have `key`, `before`, `after`, ordered by
key, with null marking absence. `apply-stream` checks hashes, parent, source
digest, every precondition and final digest; reverse mode exchanges the sides.
Reconstructed canonical keys must also match the kernel output. Failed results
are never published. An empty v2 snapshot starts a sequential replay chain.
Operation lines allow up to three snapshot-line limits, accommodating both
records and the key of a large replacement. Expanded individual records retain
the snapshot size bound even when they use definition references.

Save & Commit writes v2. Existing v1 snapshots remain readable. The first
confirmed commit migrates the selected layout, deletes its old `.layout.json`
and adds the v2 directory in one ordinary Git commit, even with zero semantic
changes. Cancel does not migrate. Old revisions are preserved. An explicit
`migrate-v2` command does the same without a new native capture. Conflicting
coexisting v1/v2 data and incomplete v2 directories fail validation.

Embedded operation-chain histories are read as archives. The dictionary API
uses v2 after storage adoption. Reading v1 JSON materializes it in memory.
Git attributes disable automatic text merging for managed files.
Hooks, signing, stale-preview/HEAD checks and index isolation remain active.

## CLI examples

Logical `group` records use the same codec and object-key rules.
Capture resolves their temporary native references with a disk-backed pass
before encoding. See [logical groups](LOGICAL_FORMAT.md#logical-groups) for member
links, duplicate names and explicitly rejected ambiguous references. No v2
schema or C++ protocol change is required.

Run inside the project virtual environment:

```sh
python -m layoutdiff capture LIB TOP before.layout --format v2
python -m layoutdiff encode-v2 old.layout.json converted.layout
python -m layoutdiff decode-v2 converted.layout expanded.json
python -m layoutdiff diff-stream before.layout after.layout change --backend auto
python -m layoutdiff apply-stream before.layout change rebuilt.layout
python -m layoutdiff apply-stream after.layout change original.layout --reverse
python -m layoutdiff migrate-v2 REPO LIB TOP -m "Migrate layout storage to v2"
python -m layoutdiff restore rebuilt.layout fresh_test_cell
python -m layoutdiff backend-info
```

Outputs must be fresh paths. Include the same `--parent` on creation and replay
when using a non-null parent token. The v1 CLI and standalone history remain
available for compatibility.
