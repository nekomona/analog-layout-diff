# Layout data model and scope

This guide describes the current data model; [v1 logical records](LOGICAL_FORMAT.md) and the
[v2 storage codec](STORAGE_FORMAT.md) define the serialization contract.
[Program structure](../architecture/PROGRAM_STRUCTURE.md) maps these representations to the
runtime processes, source modules and their interfaces.

## Three representations of one layout

| Representation | Purpose | Authority and lifetime |
| --- | --- | --- |
| Native OA cellview plus ROD state | Geometry, connectivity, placement, annotations and editing behavior in Virtuoso | Source database; native handles belong to one session |
| Expanded logical snapshot | Portable, typed records with deterministic identities; exact diff/apply semantics | Python reference model, schema `analog-layout-diff/1` |
| Compact v2 snapshot directory | Git-readable JSONL storage of the same logical records | Committed design state, schema `analog-layout-diff/2`, codec 1 |

SKILL transport, SQLite indexes, expanded wire streams, generated replay code,
review cellviews and images are derived artifacts. None defines another commit
tree. Git owns GUI history; the standalone operation-chain CLI remains available
for sequential replay and compatibility tests.

The captured cell's source library/cell/view identity is carried by its Git path,
outside the logical snapshot. A fresh destination can therefore compare equal
without pretending to have the source name or native handles.

## Modeled object graph

| Family | Logical content | Relationships and limits |
| --- | --- | --- |
| Cell | DBU, user units, technology name, cell type, properties | Technology definitions remain external |
| Drawings | Rectangles, polygons, paths, pathSegs, lines, ellipses, arcs, donuts, labels | Exact supported attributes, geometry, net/pin/group links; no automatic polygon-vertex normalization |
| Connectivity | Nets, terminals, embedded single/multiple-figure pins, instance-terminal connections | Names and explicit aliases; bus/subnet and inherited-connectivity coverage is incomplete |
| Instances | Master identity, transform, multiplicity, physical-only flag, placement metadata, effective PCell parameters, properties, connections | Masters and PCell programs are external |
| Mosaics and vias | Simple rectangular ordinary/PCell arrays; standard via definition, placement and overrides | Sparse/tiled arrays and custom vias remain unsupported |
| Figure groups | Named `figGroup`, transform, ordered/unordered membership | Member figures carry group name and optional position; specialized XL groups have coverage limits |
| Logical groups | Content-addressed `group`, definition name, flags, deletion policy, members and member properties | Duplicate names and multiplicity allowed; registered definition rules remain external |
| Placement and annotations | PRBoundary, snapBoundary, layer/area blockages, sitePattern, textDisplay | Owner/parent/associate links and property paths are explicit; supported subset only |
| ROD multipart paths | `mpp` recipe on the master path; `mppOwner` on generated figures | Recipe and exact generated geometry both matter; no separate OA MPP collection |
| Hierarchy hints | One `dependency` per descendant library/cell/view | Fingerprints and dirty hints, without archiving child contents |

The [category survey](../virtuoso/COVERAGE.md) lists supported fields and remaining
coverage. The [Virtuoso guide](../virtuoso/README.md) covers native API behavior.

## Coordinates, values and properties

Geometry coordinates and dimensions are integer database units. SKILL scales
them before printing to avoid ordinary floating-point transport rounding.
Off-grid geometry is tagged and rejected for reconstruction rather than rounded.
Path-segment custom ends retain all six documented custom dimensions; diagonal
values use the native API convention without an extra square-root conversion.

Canonical JSON uses sorted field names, compact separators, ASCII escaping and
finite numbers. Integer `0`, float `0.0`, boolean `false`, null, absent fields,
empty containers and strings remain distinct. Ordered point arrays retain order.
Properties are typed `[name, valueType, value]` triples; `hierProp` recursively
contains triples. Transport symbols are data and are never evaluated as SKILL.

## Identity and references

| Object kind | Canonical key |
| --- | --- |
| `cell`, `net`, `term`, `inst`, `mosaic`, `figGroup`, `dependency` | `kind:name` |
| Other kinds, including logical `group` | `kind:SHA256(expanded-record):occurrence` |

Occurrence numbers preserve duplicate multiplicity. Logical groups need content
keys because OA permits repeated names such as `lxMTM`. Native `db:0x...` handles
and capture-local integer IDs never become committed identity.

Most graph edges use canonical keys. Pins and instance terminals are embedded
records, addressed through `@pin:["terminal","pin"]` and
`@instTerm:["instance","terminal"]` aliases. Annotation property associations
also retain an ordered path to the nested property container. Figure-group
membership uses group names and optional member positions; net links use names.

The disk-backed resolver replaces transport IDs before hashing, resolves nested
groups and annotation dependencies, and rejects missing/cyclic/ambiguous links.
Referencing one of several indistinguishable anonymous targets is rejected;
ordinary duplicate geometry without such an ambiguous reference is supported.

A moved anonymous shape changes its key and produces exact delete/add operations.
The GUI can derive a Modified correspondence from geometry or an MPP name.
That pairing is presentation data and cannot change patch identity or hashes.

## Multipart paths need recipe and generated figures

Reading only `cv~>shapes` flattens an MPP semantically even if its metal is right.
Capture additionally reads named ROD objects and their subparts, retaining master
name, choppability, chop holes, offset/enclosure/rectangle recipes, dimensions,
spacing, distribution and recipe connectivity. Each generated figure retains its
own exact geometry, properties and actual connectivity.

Replay creates the native ROD path and reuses generated figures by full geometry
within their owner, avoiding a second flattened copy. The source's recipe net
name can be stale while its generated figure is attached to a different live
net. Those are separate fields. A recipe-only dangling name is retained and
does not require a nonexistent OA net; an actual figure connection does.

MPP omission is atomic. Unsupported alignment, custom handles, subpart pins or
terminals, custom subpart names or an unsupported member can remove the entire
MPP from a user-confirmed incomplete checkpoint. A snapshot without recipes reconstructs flattened geometry; missing editing
semantics cannot be inferred.
See [MPP findings](../virtuoso/MPP.md).

## Capture scope and external dependencies

Routes, markers and Steiners are deliberately excluded, including links from
retained groups to those objects. Their independently stored member metal/vias
and supported connectivity remain captured. These categories can persist in OA;
the exclusion is a scope decision, not evidence that they are all temporary.
See [the routing investigation](../virtuoso/ROUTING_SCOPE.md).

Descendant hints deduplicate persistent masters, hash saved OA files, and retain
dirty/time fallback information. PCell submasters are traversed but fingerprinted
through their persistent definitions. Hints do not archive child contents,
technology, CDF callbacks, external SKILL, plugins or a complete PDK environment.
Dependency drift warns during replay and does not itself stop it; unavailable
masters or incompatible interfaces can still prevent native creation.

There is also an explicit incomplete-checkpoint path for unknown content:
complete-scan diagnostics, two user confirmations, dependency-aware projection,
then strict validation of the retained graph. Optional omission audits record
what was lost. Approved scope exclusions produce no omission records. See
[capture and omission processing](../architecture/PROCESSING_PIPELINE.md#capture-and-coverage).

## Git-compatible storage

```text
layouts/<encoded-library>/<encoded-cell>/<encoded-view>.layout/
  manifest.json
  objects.jsonl
  definitions.jsonl
  omissions.json       # present only for a confirmed incomplete checkpoint
  omissions.jsonl      # diagnostic records, not replay objects
```

Objects are sorted by expanded key, with one deterministic JSON envelope per
line. Explicit default-presence lists and immutable definitions compact repeated
parameters/properties without losing types or field absence. The manifest binds
object count, file hashes and the expanded semantic SHA-256. V1 and v2 can encode
the same logical state with the same semantic hash. Definitions are data, not
external paths or executable code.

V2 changes storage rather than OA coverage. New supported record fields do not
need a new container schema when they obey the same logical contract. Native
coverage still determines whether a snapshot can be reconstructed.

## OA, streams and the KLayout adapter

GDS comparison checks exported geometry and labels. It cannot establish group,
connectivity, PCell, constraint or annotation equivalence. `dbWriteSkill` also
documents attribute omissions and is not a lossless OA fallback.

An independent OA reader may emit these logical records if it implements the
same type, identity and relationship rules. A general Python OA implementation
has not been certified. The [KLayout adapter](../klayout_plugin/README.md#snapshot-boundary-and-limitations)
uses a separate `klayout-static/1` marker and bundles reachable static cells.
Its evaluated geometry snapshots are rejected by the Virtuoso reconstruction
adapter; they do not supply native PCell or connectivity semantics.
