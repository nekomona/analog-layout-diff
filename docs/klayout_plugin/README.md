# KLayout input, history and colored review

This isolated integration reads GDS/OASIS or a live KLayout `Layout`, records a
selected cell and its reachable hierarchy in the existing checked `History`,
reconstructs static layouts, and opens a disposable colored review in KLayout.
It also renders a deterministic PNG with KLayout's real `LayoutView` renderer.
No Virtuoso connection is needed. Implementation and tests are under
`klayout_plugin/`; the shared `layoutdiff` package is imported unchanged.
Documentation lives under `docs/`; generated outputs are ignored by Git.

Gray is unchanged content, orange is changed content, green is added content,
and red hollow ghosts show removed objects **and old changed positions**.
This example is synthetic geometry, not a PDK-verified circuit.

## Command-line use

Start in `/path/to/analog-layout-diff`:

```powershell
$py = '.venv\Scripts\python.exe'
& $py -m klayout_plugin capture before.gds before.json --top TOP
& $py -m klayout_plugin init my-history
& $py -m klayout_plugin commit my-history before.json -m 'Initial stream snapshot'
& $py -m klayout_plugin commit my-history after.oas --top TOP -m 'Move device and reroute'
& $py -m klayout_plugin log my-history
& $py -m klayout_plugin replay my-history latest.json
& $py -m klayout_plugin restore my-history restored-new.oas
& $py -m klayout_plugin review new-review --history my-history
```

`replay`, `restore`, and history `review` accept `--at FULL_COMMIT_SHA256`.
History review compares that revision to its parent, including the first commit
against an empty state. Replay verifies commit hashes and object preconditions.
An unchanged capture writes no commit. A stale expected HEAD rejects a writer.
Only reachable revisions are selected by the CLI. The history format remains
the parent's `analog-layout-diff/1` linear, single-parent history.

Direct comparison and the small image helper do not need a history:

```powershell
& $py -m klayout_plugin review new-review --before before.gds --after after.oas --before-top TOP --after-top TOP
& $py -m klayout_plugin.render_diff before.gds after.oas diff.png --before-top TOP --after-top TOP
& $py -m klayout_plugin.render_diff before.json after.json diff.png --width 1400 --height 720
```

Use `EMPTY` as the before input to review an initial snapshot. JSON inputs
already select their top; `--before-top` and `--after-top` apply only to streams.
A stream with multiple top cells requires an explicit selection. Filenames are
restricted to `.gds`, `.gds2`, `.gdsii`, `.oas`, or `.oasis`; exports use `.gds`
or `.oas`. Every output path/directory must be new. Existing files, including
source files, are refused rather than overwritten. Input layouts are never
saved or modified. Temporary rendering files are removed after each render.

`review` produces:

| File | Purpose |
|---|---|
| `review.oas` | Disposable review database, with the after geometry and before ghosts |
| `review.lyp` | KLayout layer colors, line patterns and names |
| `review.json` | Exact object classification, inferred pairs, metadata operations and source-layer map |
| `review.png` | Headless snapshot with legend and counts |
| `style.json` | The applied review style |

To inspect the offline review in desktop KLayout, open `review.oas`, then load
`review.lyp` through the layer-list properties menu. Each category and original
layer/datatype gets a separate layer named, for example, `CHANGED | 2/0 M2`.
The original layer map is also in `review.json`. The generated review is marked
with the layout property `layoutdiff.review` so the GUI refuses to commit it as
a source design.

For headless rendering and tests, use `uv venv` and `uv pip install --python <venv-python>
klayout pillow pytest`; never install globally. Run from the directory containing
both `layoutdiff/` and `klayout_plugin/`. This isolated folder is deliberately not
added to the parent packaging configuration.

## KLayout GUI

Desktop KLayout **0.30.7 or later**, with Python 3.10+ support, is required.
The macro uses embedded `pya`, so the desktop GUI does not require pip's KLayout
package or Pillow. The Python environment used for headless images is separate.

1. Open the source layout in desktop KLayout and select the cell to capture.
2. Open Macro Development, add this `klayout_plugin` directory as a macro
   location, and run `analog_layout_diff.lym`. Keep the macro in this folder.
   If it is copied elsewhere, set `ANALOG_LAYOUT_DIFF_ROOT` to the directory
   containing `layoutdiff/` and `klayout_plugin/` before starting KLayout.
3. Use **Tools → Analog Layout Diff → Commit / history / review**.
4. Initialize a named new history directory, or choose an existing one. Enter a
   message and select **Commit selected source cell**. Unsaved in-memory edits
   are included; capture does not save the design.
5. Select a revision and choose **Review revision vs parent**, or choose
   **Review source vs HEAD** before committing. The review opens in a separate
   tab. Return to the source tab before making another capture/commit.
6. **Export revision to NEW OAS** reconstructs the selected state into a fresh
   file. **Capture selected cell to JSON** is also available in the Tools menu.

For a direct one-session load, run this in KLayout's Python console:

```python
import sys
sys.path.insert(0, '/path/to/analog-layout-diff')
from klayout_plugin.gui import install
install()
```

The installer is idempotent in one session. It keeps menu actions, dialog
callbacks and temporary review files alive while KLayout runs. Reviews apply
local view preferences only. The source view's geometry, colors and editor
state are not changed. Database capture rejects recursive hierarchy and shapes
outside the supported subset rather than emitting a partial snapshot.

Desktop integration requires separate verification of menu insertion, dialogs,
file choosers and tab switching with embedded `pya`. Database/view API tests alone
do not establish interactive GUI behavior. See
[verification methodology](../development/VERIFICATION.md).

## Classification and style

Canonical equality is exact content accounting, including duplicate
multiplicity. There is no stable object identity in ordinary GDS geometry.
Unchanged objects have equal canonical records. Changed pairs are a review
inference, used only when exactly one unmatched before and one unmatched after
object share the same owning cell, layer and shape type. Instances pair only
within the same owner/master bucket. Ambiguous edits remain added/removed.
Use `--exact-only`, or uncheck the GUI pairing option, to disable inference.
The checked history always retains the original reversible add/delete changes.

Child-only edits propagate to every occurrence in the display. A moved/added/
removed instance colors its descendant geometry. The visual review expands
occurrences but shares native one-shape leaf cells to preserve exact KLayout
path-width rounding and arbitrary-angle text transforms. It is a visual
artifact, not a historical reconstruction. Counts in the legend are stored
objects; `visible_occurrences` in the report counts displayed shapes. For
example, one changed child shape used in an array may produce many highlights.

Metadata changes, including cell/layout properties, DBU and used layer names,
are listed explicitly in `review.json`. A cell-property-only change does not
arbitrarily color all its geometry. Reviews require equal DBU values; a DBU
change can be recorded/replayed, but requires explicit normalization before
visual comparison. The default 250,000-object occurrence budget fails early
for very large hierarchies/arrays; override it with CLI `--limit` if needed.

Copy [style.example.json](../../klayout_plugin/style.example.json), then pass `--style custom.json`
to `review` or the image helper. The GUI's **Load review colors and styles**
action loads the same file for subsequent reviews. Partial overrides are valid:

```json
{"background":"#ffffff","added":{"color":"#0077cc","fill":false,"width":3}}
```

Colors are `#RRGGBB`, `fill` is boolean, width is 1–8, and `line_style` is the
KLayout built-in pattern index 0–7. PNG dimensions are bounded to 400–8192 by
250–8192. The helper fixes background/grid/text settings and uses a bundled
Pillow bitmap font for its legend. Identical inputs, style, dimensions and
KLayout/Pillow versions produce identical PNG bytes; cross-version pixel
identity is not promised.

## Snapshot boundary and limitations

Snapshots use the existing `analog-layout-diff/1` envelope and canonical keys,
with an explicit **`klayout-static/1` backend marker**. The KLayout adapter
rejects Virtuoso/OA snapshots. These records are not the Virtuoso native codec
and must not be passed to its reconstruction backend.

Stored data includes numeric used layers with names, integer DBU geometry,
boxes, polygons with holes, paths and extensions/round ends, text attributes,
cells, complex instance transforms, regular arrays, duplicates, and typed
layout/cell/shape/instance properties. All reachable cells, including shared
and empty masters, are bundled. The selected top's name and child cell names
are meaningful state. Unreachable cells and unused layers are excluded.

PCell/library content is captured as **evaluated static geometry**. It does not
retain generators, parameters, library bindings, technology configuration,
netlists, connectivity, constraints, editor transactions, auxiliary metadata,
or other OA semantics. A GDS file cannot supply those missing semantics.
GDS/OAS import captures the database KLayout produces with its default reader
options, not exact stream bytes or record ordering. JSON is the authoritative
exact state. Reconstruction checks that its complete modeled native snapshot
equals the requested snapshot before exporting. Stream exports can normalize
geometry or properties: GDS may fracture hole polygons and cannot express all
KLayout property types. OASIS is generally richer, but export is not claimed as
an exact archive of stream syntax or unmodeled database state.

## Tests and evidence

```powershell
& $py -m pytest klayout_plugin/tests -q --basetemp=klayout_plugin/.test-tmp -o cache_dir=klayout_plugin/.pytest_cache
& $py -m klayout_plugin.generate_demo klayout_plugin/evidence/new-demo
```

The demo uses synthetic geometry. Verify snapshot equality, exported geometry
and deterministic rendering separately; see [verification](../development/VERIFICATION.md).
