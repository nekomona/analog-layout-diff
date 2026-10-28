# Virtuoso package

`layoutdiff.virtuoso` translates native OA/ROD state into canonical records and
reconstructs supported records through Virtuoso Bridge. Native APIs, technology,
referenced masters and PCell programs remain external dependencies.

## Capture and reconstruction

Capture reads native state, scales geometry to integer DBU, decodes typed
transport, resolves temporary references and validates coverage. Direct capture
does not save designer edits. The [Save & Commit UI](../ui/README.md#save-and-commit)
explicitly saves before capture.

Reconstruction requires a fresh destination and compatible technology. It creates
prerequisites before dependants, orders equal-priority records by canonical
content/key, attaches group members after their targets, and checks native
readback. Referenced masters regenerate from the available environment.
Hierarchy fingerprints warn about drift without archiving child contents.

Native comparison checks exact content first, then only documented equivalence
rules. These rules do not change committed data or generic diff/apply. See the
[processing pipeline](../architecture/PROCESSING_PIPELINE.md#native-replay-and-readback).

## Native object references

| Topic | Guide |
| --- | --- |
| Supported fields and remaining limits | [Coverage](COVERAGE.md) |
| Excluded routes, markers and Steiners | [Capture policy](ROUTING_SCOPE.md) |
| Logical group identity and session definitions | [Groups](GROUPS.md) |
| Standard-via default readback | [Via defaults](VIA_DEFAULTS.md) |
| Editable multipart paths and callback ordering | [MPP replay](MPP.md) |
| Blockages, boundaries, sites and local text displays | [Annotations](ANNOTATIONS.md) |
| Record identities and hierarchy hints | [Logical format](../data/LOGICAL_FORMAT.md) |
| Unsupported objects and omission audits | [CLI preservation limits](../ui/CLI.md) |

## Implementation ownership

`adapter.py` coordinates capture/replay; `support.py` checks coverage;
`omissions.py` projects explicitly confirmed incomplete checkpoints.
`logical_groups.py`, `oa_content.py` and `mpp.py` resolve native relationships
and creation ordering. `native_equivalence.py` contains narrow readback rules.
`dependencies.py` and `hash_views.py` supply hierarchy hints. `sexpr.py` handles
data-only transport, `paths.py` supplies scratch paths, and `skill/` provides
native readers. `geometry.py` performs stream export and independent KLayout
geometry/label checks.

Validate SKILL behavior against the docs installed with the target Virtuoso
release. GDS XOR cannot establish connectivity, group, annotation or ROD editing
equivalence. Use the [runtime guide](../runtime/README.md) for deployment and
the [verification guide](../development/VERIFICATION.md) for test responsibilities.
