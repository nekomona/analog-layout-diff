# Logical records and operation-chain format

The expanded interchange schema is `analog-layout-diff/1`. The
[streaming storage codec](STORAGE_FORMAT.md) stores the same records, keys and
semantic hashes in a compact directory. Both representations are supported.

The interchange form is UTF-8 JSON:

```json
{"schema":"analog-layout-diff/1","objects":{}}
```

The empty state is the root of a history. A captured layout adds a `cell:` record
containing integer `dbu`, `units`, `technology`, `cellType` and typed properties,
plus one record per modeled object. Cell/library/view source names are outside
this state, so a reconstruction in a new destination compares equal.

Named kinds (`cell`, `net`, `term`, `inst`, `mosaic`, `figGroup`, `dependency`) use
`kind:name` keys. Anonymous objects use `kind:SHA256(record):occurrence`.
Duplicate identical figures remain separate records. Enumeration order and
in-memory `db:0x...` addresses do not affect identity. Geometry arrays preserve
their meaningful order, including polygon point order; geometrically equivalent
polygon vertex reorderings are reported as content changes.

Content-addressed `layerBlockage`, `areaBlockage`,
`snapBoundary`, `sitePattern` and `textDisplay` records share these containers
and canonical identity rules. Geometric dimensions use integer DBU;
site entries preserve order as `[siteName, [x, y], orientation]`. The full
[field inventory and native behavior](../virtuoso/ANNOTATIONS.md)
is documented separately. Owner, parent and associate links contain canonical
object keys (or the existing pin/instTerm aliases), never database handles.
Property links add an ordered `associateProperty`/`ownerProperty` path from that
object to the property container. Null references differ from absent fields.

A `pathSeg` with either end style `custom` additionally records
`customExtensions`, in this order:
`[beginLeftDiagExt, beginRightDiagExt, beginRightHalfWidth, endLeftDiagExt,
endRightDiagExt, endRightHalfWidth]`. The six integer-DBU values come from
`dbGetPathSegStyle`; together with the existing `beginExt`/`endExt`, they are
passed back to `dbCreatePathSeg`. Preserve the API's orthogonal/diagonal units;
do not apply an additional square-root-of-two conversion. Only custom segments
carry this field.
Fixed truncate/extend/chamfer styles derive their extensions during creation;
the renderer supplies zero for their optional extension arguments.

Custom snapshots lacking required dimensions need a fresh capture and are
rejected, because inventing the missing dimensions would alter geometry.
Chamfer ends need no custom dimension field. The storage codec and C++ backend
retain this logical field.

All modeled coordinate and length fields use integer database units. Conversion
happens in SKILL before printing, avoiding `%L` floating-point rounding of
coordinates. Off-grid values are tagged and rejected by reconstruction rather
than silently quantized. Non-geometric floating values use 17-digit transport
strings and JSON numbers after decoding. `null` and a literal string such as
`"123"` remain distinct from numeric values. An ILList symbol is represented as
`{"symbol":"name"}` and never evaluated by the parser.

Property triples are `[name, valueType, value]`, sorted by name. `hierProp`
contains another list of property triples. Net and terminal links use names.
Each pin-bearing figure records terminal/name, access directions, pin type,
typed properties, figure count and whether it is the primary pin figure. A
multi-figure pin is rebuilt once and other figures are attached to it. Net
association is left to the pin API for pin figures.

Instances retain master library/cell/view, origin, orientation, multiplicity,
physical-only flag, placement/source metadata, effective PCell parameters,
local properties and terminal-to-net connections. Simple mosaics retain rows,
columns, pitch, tile orientation, master and parameters. Virtuoso lists mosaics
among `cv~>instances`; the reader deliberately filters ordinary instances to
avoid recording arrays twice. Standard vias retain the via definition name and
typed override values from `viaHeader~>overrideParams`.

Native reconstruction validation includes this via equivalence:
an explicit integer `cutRows` or `cutColumns` override equal to the destination
technology's corresponding `viaDef~>params` default may disappear on readback.
IC23.1 `dbCreateVia` removes these redundant overrides. Exact comparison runs
first; on a mismatch, a comparison-only projection removes only proven defaults
and re-keys affected logical-group references. Unknown defaults, other via
parameters, geometry, connectivity and properties remain exact. Duplicate
multiplicity is retained; ambiguous referenced duplicates are rejected.

This does not change capture, stored records, Git history, hashes or generic
diff/apply. The returned native snapshot retains Virtuoso's actual parameter
spelling and can therefore have a different raw hash from the committed
snapshot. The decision and queried defaults are recorded in
`readback_normalization_<build-id>.json` and the GUI's `review.json`.
See [native via comparison](../virtuoso/VIA_DEFAULTS.md).
MPP-specific native comparison rules are summarized in the
[processing guide](../architecture/PROCESSING_PIPELINE.md#native-replay-and-readback)
and [MPP findings](../virtuoso/MPP.md); none changes stored identity
or generic diff/apply semantics.

Connectivity categories and group-boundary overlays are presentation data.
Group-only membership edits do not classify members as Modified. Connectivity-only
edits use Modified net; movement/size edits use Moved / stretched, while other
simultaneous edits take precedence as Modified. See
[comparison semantics](../comparison/README.md#change-classification).

`unsupported` records include a category and diagnostic attributes. They permit
inspection and offline comparison, but cannot enter a reconstructable history.
Their references are descriptive hints, not globally unique persistent OA IDs.

Routes, markers and Steiners are deliberately outside the capture
scope. They produce no records, group links or omission counts, so changes to
them alone produce no diff. Physical member geometry and supported connectivity
remain separate tracked records. Ordered figure-group counts/positions are
renumbered over retained members. Replay omits the excluded topology and
annotations. The [capture policy](../virtuoso/ROUTING_SCOPE.md)
defines this boundary. Generic diff/apply preserves the exact data supplied in
existing snapshots; native replay separately enforces its supported scope.

## Logical groups

OA logical `group` records are separate from `figGroup` records. A logical group records `name`, `defName`, `isSet`,
`isCollection`, `isOrdered`, `isUniqueName`, `deleteWhen`, typed `props`, and
`members`. Each member is `{"target": "<object key>", "props": []}`; these
properties belong to the native `groupMem`, not the target object.

Logical groups use anonymous content keys even when named: OA allows several
groups with the same name. Members refer to canonical object keys. Pins and
instance terminals, which are embedded in other records, use aliases containing
compact ASCII JSON: `@pin:["terminal","pin"]` and
`@instTerm:["instance","terminal"]`. Unordered memberships sort canonically;
ordered memberships keep their native order. Collection multiplicity is kept.

The SKILL transport assigns temporary local integers when logical groups or
supported annotation relationships need them. A disk-backed resolver replaces
these with canonical keys, resolves nested groups bottom-up and strips all transport IDs. Layouts
without those relationships require no temporary reference IDs. No OA
handle or capture-local integer becomes a persistent reference.

Replay creates every object and logical group first, then attaches members and
restores `groupMem` properties. The named group definition must already be
registered in the destination Virtuoso environment; this format stores its
name, not the application code/rules that registered it.

Coverage rejects missing targets, cellview members (the native API rejects
them), cyclic group references, and references to indistinguishable duplicate
anonymous targets. Duplicate-named groups targeting distinct objects are
supported. A group member pointing to another unsupported category does not
make that category reconstructable. Such objects still block the complete
capture check.

Changes to a group's properties, membership, order or referenced anonymous
object change its content key. These appear as delete/add records, including
dependent parent groups; the GUI category is **Logical groups**. Logical groups
have no independent geometry, so their changes appear in review metadata and
full diffs rather than an additional highlight shape. The v2 codec and C++ diff
backend preserve these records without a schema or kernel change.

## Hierarchical dependencies

`dependency` records use the logical schema. Captures traverse ordinary instance and mosaic masters recursively,
visiting each in-memory master once to terminate sharing/cycles. The persistent
record is deduplicated by library/cell/view. PCell submasters are traversed for
their references but fingerprinted through the persistent supermaster.
No child geometry, connectivity, properties, or PCell bodies are serialized.

```json
{
  "kind": "dependency",
  "name": "[\"MY_LIB\",\"CHILD\",\"layout\"]",
  "libName": "MY_LIB",
  "cellName": "CHILD",
  "viewName": "layout",
  "pcell": false,
  "fingerprint": {
    "status": "ok",
    "method": "saved-oa-sha256-v1",
    "sha256": "<64 hexadecimal characters>"
  },
  "dirty": false,
  "dirtyCounter": null
}
```

`name` is compact ASCII-escaped JSON of `[libName, cellName, viewName]`.
The key is `dependency:` followed by that name. Hashing occurs on the database
filesystem host; no child OA files are downloaded. Sort the immediate `*.oa`
files by filename, SHA-256 each file's bytes, then SHA-256 the compact ASCII JSON
list of `[filename, file_hash]` pairs. Lock/transient files are excluded. Check
file names, sizes, and nanosecond modification times before/after hashing; a
concurrent change yields `status: unstable`. This is a binary change hint and
can report a save that changes OA bytes without changing geometry.

When saved files cannot be read, the record uses `method: saved-time-hint`,
`savedTime` from Virtuoso's documented `fileTimeStamp`, and a non-OK status
(`unavailable`, `unstable`, or `unresolved`). Capture/restore reports failures
to hash. Dependency checking warns for every non-OK status, even when it is
unchanged. An unsaved referenced view sets `dirty` and retains its relative
`modifiedCounter`; these counters can reset across sessions. They detect edits
within a session but do not certify unsaved content across sessions. Save
referenced views for repeatable saved-file fingerprints.

Dependency records participate in normal reversible diffs and commit integrity
checks. A child-only change thus produces a replacement of its dependency
record. Native restore skips these records during construction, compares them
with live masters, emits warnings, and saves a JSON warning report. It verifies
all remaining top-level records exactly. The returned snapshot contains current
dependency fingerprints, so its overall digest may differ from the requested
requested snapshot while top-level content matches. Snapshots without
dependency records have no archived hierarchy hints to compare.

Offline replay preserves the recorded hints exactly, without accessing Cadence.
`replay --check-dependencies` adds a live, nonblocking check. `restore` checks
automatically. Missing definitions and incompatible interfaces may still cause
native creation errors; only fingerprint drift/unavailability is nonblocking.

These records do not archive revisions or fingerprint the technology database,
external PCell SKILL files, CDF callbacks, plugins, or runtime configuration.
Capture and fingerprinting are sequential reads, not a distributed transaction;
avoid concurrent edits when establishing a reproducible baseline.

## Ordered figure groups

Ordinary `figGroup` records retain `ordered`, `origin`, `orient`, `type`, and
properties. An ordered group also carries integer `memberCount`. Each member
carries its parent name in `group` and its zero-based position in `groupOrder`.
This includes shapes, instances, vias, simple mosaics, and nested figure groups.
Empty ordered groups have `memberCount: 0`. Unordered memberships omit
`groupOrder`.

The reader indexes each native group's `figs` list once. Replay creates every
object before attaching members in the recorded order. Complete contiguous,
unique membership is validated using a temporary disk-backed SQLite index.
Missing required order/count data requires recapture. Reordering
is part of the logical diff and is shown as a property modification in review.
Neither the v1/v2 storage schema nor the C++ kernels require a format change.

Unsupported members also retain group/order diagnostic fields so the report
identifies their actual unsupported category instead of a misleading missing
group member. Such diagnostic records still block commit and reconstruction.

## Standalone operation-chain commits

Commit files carry:

```text
schema, parent, base, result, message, operations, id
operation = {key, before: record|null, after: record|null}
```

SHA-256 hashes use sorted-key JSON with compact separators, ASCII escaping and
nonfinite values prohibited. The commit ID hashes all fields except `id`.
Application verifies the commit hash, expected parent, full base-state hash,
every old-record precondition, canonical object keys, and full result hash.
It applies to a deep copy and returns nothing on failure. Reverse application
swaps before/after and base/result, while still checking the recorded parent.

`History` stores `empty.json`, immutable `commits/<id>.json` and an atomically
replaced `HEAD`. Only one writer may hold `.lock`; stale locks require inspection
before removal. A crash after writing a commit but before advancing HEAD leaves
an unreachable commit, not a half-applied state. The implementation supports a
linear sequence only. It is not intended for concurrent network-filesystem writers.

## Other OpenAccess readers

Implement `SnapshotReader.capture(library, cell, view)` from
`layoutdiff.data.backends`. Convert backend values to these records and call
`layoutdiff.data.core.canonicalize(records)`. The result can enter the same diff,
history and verification pipeline. `JsonReader` consumes such snapshots from an
external extractor, and the CLI `commit` command uses this interchange boundary.

No vendor OA Python package is bundled or assumed. A direct OA adapter needs a
binding compatible with the installed OA version and PCell/plugin environment.
KLayout's GDS reader is an independent geometry oracle; it is not an OA reader
and cannot recover Virtuoso connectivity or PCell semantics from GDS.
