# Comparison package

`layoutdiff.comparison` derives review meaning from exact operations. It owns
conservative correspondence, change classification, group bounds, category counts
and paging. It does not change stored keys, patches or replay results.

## Matching

The matcher first pairs native MPP names and identical geometry, then considers
unique translations, translations supported by several figures and reciprocal
geometric candidates. Candidates must agree in shape family, layer and owner.
Ambiguous or crowded candidates remain additions/deletions. Every inferred pair
retains its matching evidence in full details. Duplicate multiplicity is preserved.

Standard vias have origins and parameter overrides without a stored footprint.
The point pass groups compatible definition, purpose, net and nondimensional
overrides, prefers identical geometry, then considers size/orientation edits.
Reciprocal nearest choices require a sufficiently separated runner-up. Large
groups use bounded spatial searches. Pairing infers edit intent without creating
persistent identity on the source database.

## Change classification

| Category | Meaning |
| --- | --- |
| Untouched | Canonical content is unchanged |
| Modified | Ordinary property, layer, master, orientation or PCell-parameter edits; takes priority over simultaneous geometry/connectivity edits |
| Moved / stretched | Position/size changes, optionally with connectivity changes, without an ordinary modification |
| Modified net | Connectivity-only edits or visible figures affected by net/terminal metadata |
| New / Deleted | Unmatched additions/deletions |
| Group boundaries | New, modified or deleted figure/logical-group membership or metadata |

Position/size fields include shape coordinates and widths, instance origins,
mosaic pitch, via origins and cut-array dimensions. Category summaries use **A**,
**M**, **D**, **MN** and **MS**; ordinary M excludes MS. Group-only changes do not
mark every member Modified. Group outlines use geometric member bounds and
remain distinct from figure classification.

Stored-record counts, inferred pairs, native highlighted figures and Git text
line counts measure different things. One changed net or referenced master can
affect many visible figures without adding the same number of records.

## Categories and paging

Shapes are grouped by layer, vias by definition, and instances/PCells by master,
alongside connectivity, groups and metadata. `CategoryDiff` provides the in-memory
reference; `ChangeIndex` spools exact operations and categories to SQLite. Both
use the same matching/classification rules. The browser returns ten changes per
page and produces complete detail text only when requested.

| Source | Responsibility |
| --- | --- |
| [matching.py](../../layoutdiff/comparison/matching.py) | Bounded shape/via correspondence |
| [geometry_changes.py](../../layoutdiff/comparison/geometry_changes.py) | Position/size field projection |
| [review.py](../../layoutdiff/comparison/review.py) | Visible-object status |
| [review_groups.py](../../layoutdiff/comparison/review_groups.py) | Group pairing and boundary targets |
| [categories.py](../../layoutdiff/comparison/categories.py) | Category rules, counts and detail formatting |
| [changeindex.py](../../layoutdiff/comparison/changeindex.py) | Disk-backed indexing and paging |

The [UI guide](../ui/README.md#review-controls) describes display controls.
[Native replay](../eda/virtuoso/README.md) verifies reconstructed content separately
from these presentation rules. See [performance methodology](../data/PERFORMANCE.md)
when measuring matching costs independently of exact stream merging.
