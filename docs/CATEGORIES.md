# Layout content survey

Consult the database attribute and creation references installed with your
Virtuoso version when extending the codec.

| Category | Current treatment | Remaining work |
|---|---|---|
| Cell metadata | DBU, user units, technology name, cell type, typed properties | Library tech itself and OA binary metadata are external |
| Rectangles/polygons | Exact shape records and reconstruction | Mask/color, shape attachment semantics |
| Paths/path segments | Width, ordered points, route status, pathSeg topology; truncate/extend/variable/chamfer/custom ends with all six custom dimensions | Routing-container links |
| Ellipses/arcs/donuts/lines | Native geometry reader/writer; arcs/donuts verified in advanced fixture | Arbitrary-angle corner cases and line GDS semantics need broader tests |
| Labels | Text, origin, orientation, justification, font, height, visibility, drafted/overbar, label type | Expression evaluation context |
| Text displays | Local attribute/parameter/property associations, native display flags, object links and nested property paths | Cross-cellview associates and label override masks remain explicit blockers |
| Properties | Scalars, strings, bools, time, ILList and recursive hierProp | Range/enum/external property types; embedded database references |
| Nets/terminals | Scalar connectivity, signal/global/source/routing metadata, directions, properties | Buses/subnets/aliases/shield relationships/inherited connections |
| Pins | Multiple figures, primary figure, access direction, pin type and properties; local display references | Per-figure access overrides, pinless physical abstracts |
| Ordinary instances | Master identity, transforms, multiplicity, local properties, connections | Per-bit vector connectivity, abutment/ROD semantics, recursive master archive |
| PCells | Effective parameter values plus local instance properties; regenerate through master | Freeze PCell code/plugin/PDK version; sandbox evaluation |
| Mosaics | Simple rectangular ordinary and PCell arrays, pitch and tile orientation | Non-simple/tiled/sparse arrays and array connections |
| Vias | Standard via definition, placement and override parameters | Custom vias, via-layer attributes, variant semantics |
| Figure groups | Ordinary ordered/unordered and nested groups, origin/orientation, member order; shapes, instances, vias and simple mosaics | Modgen/syncClone/placeArea/rowFigure groups and special constraints |
| Placement boundary | Basic native polygon | Edge names, pins/obstructions and special boundary semantics |
| Routes/Steiners | Intentionally excluded from capture/diff in 0.10.1, including group links; member geometry remains tracked | Full topology preservation is outside the approved scope; findings retained for future work |
| Logical groups | Set/collection flags, duplicate names, member order/multiplicity, nested groups, registered definition names and member properties | Cycles, ambiguous identical-object references and portable group-definition rules |
| Markers | Intentionally excluded from capture/diff in 0.10.1, including associations | Annotation/verification preservation is outside the approved scope; findings retained for future work |
| Blockages | Native layer/area polygons, flags, spacing/effective width, density, color and owner/parent links | Halos and other blockage subclasses remain blocked |
| Snap boundary/site pattern | Native snap rectangle with edge names; ordered technology-site transforms | Technology definitions remain external |
| Guides/rows/track/grid patterns, special constraints | Known collections flagged when present | Complete rule/constraint database support |
| ROD multipart paths | Master name, choppability, chop holes, offset/enclosure/rectangle recipes, exact generated geometry and connectivity; reconstruct with native rodCreatePath | Alignment/user handles and subpart terminals remain explicit unsupported content; other ROD/XL associations and coloring are not certified |

`dbWriteSkill` was investigated. Its installed documentation explicitly states
that it does not replicate all attributes, listing coloring, blockages and
physical-only attributes among the limitations. It is therefore not used as a
lossless fallback. GDS XOR validates exported geometry; it cannot establish
equivalence of the full OA object graph.

The route, marker and Steiner [effects investigation](OA_OBJECT_FINDINGS.md)
confirms persistent topology and verification metadata that GDS cannot certify.
The user approved excluding these three categories in 0.10.1; the decision and
replay limitations are recorded in that document. Logical groups are supported
in 0.10.0 within the limits above, with ignored-object links omitted in 0.10.1.
Reconstruction comparisons must use the same selected scope. Master-dependency
fingerprinting is implemented; it detects child changes without archiving child
contents. Recursive hierarchy bundles and an independently certified direct OA
reader remain future work. See the [data model](architecture/LAYOUT_DATA_MODEL.md)
for identity, relationships and the external-environment boundary.
