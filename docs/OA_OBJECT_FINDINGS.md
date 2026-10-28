# Native object findings

These guides describe reusable API behavior within the supported subset.
Validate behavior against the documentation installed with your Virtuoso release.

| Topic | Guide |
| --- | --- |
| Excluded routing topology and annotations | [Routing scope](findings/ROUTING_SCOPE.md) |
| Logical group identity and session definitions | [Groups](findings/GROUPS.md) |
| Redundant standard-via overrides | [Via defaults](findings/VIA_DEFAULTS.md) |
| Editable multipart paths and inferred correspondence | [MPPs and matching](findings/MPP_AND_MATCHING.md) |
| Blockages, boundaries, sites and text displays | [Annotations](findings/ANNOTATIONS.md) |

## Approved design decision: exclude routes, markers and Steiners

Capture deliberately excludes these categories and their group links. Supported
independent member geometry and connectivity remain tracked. Replay does not
recreate the excluded topology or annotations. See [routing scope](findings/ROUTING_SCOPE.md).
