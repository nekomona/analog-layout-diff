# Virtuoso commit and review toolbar

The plugin uses native toolbars/forms and a bridge-connected worker on the
Virtuoso host. It provides Save & Commit, History and Runtime controls for layout
windows. Read [coverage](CATEGORIES.md) before relying on reconstruction.

## Select the intended CIW

Configure a separate bridge profile/port for each concurrent CIW. Use
`virtuoso-bridge list-windows --top-level --json` and check process/display
identity through the bridge before installing or loading the plugin. Store
site configuration in an ignored `.env`.

Deploy from an environment with Virtuoso Bridge installed and its source checkout
beside this project (the installer bundles that sibling checkout):

```sh
python scripts/install_runtime.py --destination /absolute/path/to/layoutdiff_runtime
```

The target host needs `uv` on PATH. Supply a dedicated absolute destination.
The installer prints its deployment result and loads generated startup code
through the selected bridge connection. Keep generated paths/configuration local.

## Start and stop

The installed plugin is available through **CIW > Layout Diff > Runtime / Commit /
History...** and the **Runtime** button in each layout toolbar. The panel provides
Start, Stop, Restart, worker status/PID, last response, activity, queued work,
logs, review cleanup, recorded-layout selection and commit/history controls.
It remains available while the worker is stopped. Library Manager customization
is unnecessary; the CIW panel can select a library/cell/view without an open layout.

Load this file in CIW after the existing Virtuoso bridge setup:

```lisp
load("/absolute/path/to/layoutdiff_runtime/startup.il")
```

This file installs the CIW menu and
launches the worker through `ipcBeginProcess`; later starts/restarts use the same
SKILL path. No external terminal or Windows background worker is needed.
The loader can be included after the bridge setup in your normal `.cdsinit`.
Add the loader to `.cdsinit` only when you want automatic startup.

For a fresh deployment from this project, run the installer once:

```powershell
python scripts/install_runtime.py --destination /absolute/path/to/layoutdiff_runtime
```

It deploys an isolated Python 3.10 virtual environment, the bridge package and
the plugin on the host, then loads `startup.il` through the current bridge.
`--destination` selects a dedicated remote directory. `--migrate` is a one-time
option that stops an old Windows worker and imports `gui-workspace/histories`
and preferences, refusing to overwrite existing host histories.

Runtime data lives under `analog_layout_diff_runtime/state/`: `histories/`,
`styles.json`, request audit records, `runtime.json`, and
`runtime.log`. The supervisor uses a kernel file lock to reject duplicate starts.
`runtime.lock` is intentionally retained as an unlocked inode after shutdown.

Stop removes review highlights, releases retained database opens and removes the
worker toolbars. Review windows remain open with their reconstructed contents.
The persistent CIW menu and panel can start it again. Histories and preferences
remain on disk. `start_gui.ps1` and the optional `gui-serve`/`gui-stop` CLI commands
now only ask SKILL to perform these actions; they never start a Windows daemon.
An older open review remains read-only after restart. Its Commit action is
blocked; reopen the source revision from the Runtime panel to restore the review
highlight controls for the new session.

## Ownership and shutdown

The SKILL IPC child is a supervisor, separate from the worker that calls the
bridge. It can stop a worker even while that worker is blocked waiting for CIW.
The worker checks that the bridge endpoint's `ipcGetPid()` matches its owning
Virtuoso before touching UI or database state. It uses a local TCP connection;
no SSH or Windows connection is needed after deployment.

`regExitAfter` requests shutdown after Virtuoso accepts exit. Independently, the
supervisor checks the parent PID, Linux start ticks and boot ID every 0.5 seconds,
and detects IPC EOF. PID reuse and zombie processes cannot keep it alive.
GUI Stop allows eight seconds for cleanup, then terminates the owned worker
process group; a hung worker is killed after a further two seconds. Parent death
uses a shorter grace period. The supervisor waits/reaps its worker, removes its
unreferenced session scratch and only locks containing that worker's PID, then exits.
It neither stops the shared bridge daemon nor touches other processes.

Starting with 0.13.0, work bundles and their private native `ALD_TMP_*` libraries
are created under the host's system temp directory (`/tmp/ald-session-*` in the
verified deployment). `runtime.json` records the directory. A native SKILL lease
timer checks all windows displaying/editing the library, full-diff text viewers,
and report forms. Once all references close, it releases owned database opens,
deletes the private library through Cadence, and marks the bundle for deletion.
The worker reaps released bundles during normal operation. On Stop, a small
detached janitor watches release markers and the original Virtuoso process
identity; it needs no bridge calls. This allows windows to outlive the worker.
Parent exit releases the entire session. Legacy review directories are checked
every 15 seconds and deleted only after their registered cellviews are closed.
Saved history, settings and audit evidence are durable data, not discarded session
resources. A machine power loss or SIGKILL of the supervisor itself can require
manual inspection of `worker.lock`; the normal parent-exit and IPC-loss paths
are supervised and tested.

## History & Changes browser

### Restore a saved working layout

Select a checkpoint in either tab and press **Restore checkpoint...**. A temporary
reconstruction must pass the normal native readback checks before the confirmation
form opens. OK backs up the complete native layout (including ignored OA metadata),
closes its direct windows, replaces and saves it, verifies the resulting top-level
objects, and reopens the windows. Cancel changes nothing. Save/discard unsaved edits
first; restore refuses an edit-in-place target or a target still referenced by other
database clients. It never force-purges those references.

The saved OA file's SHA-256 is checked again before replacement to reject a stale
preview. A failed replacement/readback attempts rollback from the native backup.
If rollback fails, a recovery record and native backup copy are preserved under
`state/recovery/`; the temporary native backup remains protected in the live session.
Successful backups remain available until the reopened target windows close.
The current implementation restores existing saved working cellviews, not deleted
cellview directories. A deleted-snapshot commit cannot be used as a restore target.

Git HEAD, index, worktree snapshots, and commit history are untouched by restore.
Use **Save & Commit** afterward to record the restored layout as a new commit.
External hierarchical master contents are not restored; dependency changes remain
warnings. The confirmation identifies the target, commit, and warning count.

### Loading feedback

Only Save & Commit preview preparation (including Git setup) and committing show
a modeless **Layout Diff - Loading** window. Other slow operations, including
review, restore, history and diff loading, show **Loading: ...** in the Layout Diff
window's status line. The text follows actual stages and returns to the revision
summary on completion; failures show an error status. There is no estimated
percentage. Closing the quick-commit popup hides it while the operation continues.
Completion or failure closes it automatically. A synchronous native SKILL
step can briefly occupy Virtuoso's event loop even though the worker is asynchronous.

### Selecting revisions

Open **CIW > Layout Diff > History & Changes...**, or press **History** on a layout
toolbar. The native window follows a Git-client layout:

- **Cell-centric** selects a layout first, followed by its commit history.
- **Git-centric** selects a branch/tag or HEAD, then a commit in its graph,
  followed by a cell changed by that commit. Multiple v2 files are grouped into
  one cell entry; deleted cells remain selectable for their deletion diff.
  Non-layout commits remain visible with an empty cell list. Refs are pinned
  on refresh; no checkout is performed. **More commits** extends the initial
  500-commit window. Merge comparisons use the first parent.

- **Layouts** on the left selects the library/cell/view history.
- **Commit history** shows newest revisions first, with Git hash, message,
  author, date, and added/modified/deleted/modified-net layout-record counts.
- **Commit details** shows the full message, identity, hash and category totals.
- **Affected files** shows actual paths/statuses in the selected Git commit and
  added/deleted text-line counts. Snapshot rows show cell/view/library names;
  selecting one shows its complete repository-relative path above the patch.
- **Change categories** groups the selected layout's changes by layer or master,
  with separate **A / M / D / Modified net** columns. Net-only edits have
  `Modified net / ...` rows and are counted only in the last column. For example,
  `MET1 shapes` can show `10 / 2 / 3 / 0`, while
  `Modified net / MET1 shapes` shows `0 / 0 / 0 / 24`.
  The text overview and full-diff summary use **MN** for Modified net;
  ordinary **M** counts exclude it.
- Select a category for **ten changes per page**. Previous/Next navigates all
  changes; individual record excerpts are bounded for the native text field.
  **Open full diff** opens every field of every change in the selected category.
- **All categories** returns to the overview. From there, **Open full diff**
  exports every changed record across all categories. Selecting an affected
  file instead shows its ordinary Git patch, with additions in green, deletions
  in red and headers in blue. Its full-diff button shows the complete file patch.

Use **Review layout** (or double-click a commit) for the existing read-only
reconstruction and highlight overlays. **Save & Commit** targets the selected
source if it is already open in edit mode and retains the save/preview/confirmation
flow. Successful Git commits refresh an open browser. **Refresh** reloads the
history; **Runtime...** opens the monitoring and lifecycle controls.

History counts use the same display grouping as the category table. Anonymous
figures with only changed typed properties, net/pin/group links or route status
are paired as one M (or MN for connectivity-only edits) when all remaining
fields match. Since 0.15.0, moves and stretches also appear as M when the shared
matcher finds an unambiguous correspondence: native MPP name, exact geometry,
translation, or reciprocal geometric similarity. Nearby ties and crowded
neighborhoods remain A/D. The full records and exact content-addressed patches
are unchanged; matching anonymous figures is a presentation inference, not a
claim of persistent OA identity. Label-text changes remain A/D.

MPP master definitions appear under `<layer> MPPs`; generated members appear
under `<layer> MPP subshapes`. Review/restore regenerates editable native ROD
objects and reuses their generated figures. Earlier checkpoints without MPP
definitions retain only flattened geometry. Make a new checkpoint to retain
MPP editing behavior; the missing definitions cannot be recovered from old Git
snapshots alone.
Duplicate multiplicity is preserved. A named object changing master/category
has one M in an explicit `old category -> new category` row.

Shapes group by layer and non-drawing purpose; labels have separate rows.
Vias use the recorded via-definition name, such as `MET2_MET1`, because the
current snapshot does not contain its resolved metal-pair metadata. Instances
use library/cell and PCell/cell type. Mosaics count as array objects, without
expanding their tiles. Nets, terminals, groups, cellview properties, placement
boundaries and hierarchy dependency hints have their own categories. These
counts describe recorded changes; review overlays can additionally highlight
figures affected by a changed net or master.

File counts describe JSON/text lines, so they need not match category counts.
The display pairing does not modify saved object IDs or infer a new physical
identity. Version 0.9 uses v2 storage with the same expanded logical content.
Legacy standalone histories remain read-only and show “Local history / Not recorded”
for missing author/date metadata; their file table shows history artifacts with
unavailable line counts marked `-`. Browsing does not save layouts or write Git.

Version 0.9 implements streamed processing and lazy history. Unselected commit
counts show `...` until calculated. Selected comparison details use disk-backed
indexes and ten-record pages; large geometry arrays have bounded excerpts.
Full text exports are generated only on request. See the
[measured performance and limits](BACKEND_SCALE_RESULTS.md).

Open **Runtime > Performance backend...** to select `auto`, `python`, or `native`
and inspect tool availability and the last selection reason. Auto selects the
verified C++ merge/apply backend at 50,000 objects or 32 MiB of canonical input;
missing/failed tools fall back to Python. Explicit native mode reports errors.
The choice persists in `state/performance.json` and takes effect on subsequent
operations. The installer builds the optional C++ tool when a host compiler is
available; every launch remains part of the SKILL-owned runtime.

## Commit and browse

1. Open an editable source layout and press **Save & Commit**, or the installed
   **Ctrl+Shift+F12** shortcut. The layout is saved first, then the preview shows
   its repository, branch, identity, counts and semantic diff. Enter a message
   in the focused input and press **Enter / OK** to commit. **Cancel** keeps the
   saved layout and leaves Git unchanged. **View full diff...** opens the full
   patch in a native text viewer; the inline field is shortened for large changes.
   Missing repositories prompt for initialization above the Virtuoso working
   directory. See [Git setup and transaction details](GIT.md).
2. Press **History**. Select a Git revision and press **Review layout**. The log
   filters Git commits by the selected library/cell/view snapshot path,
   `layouts/<library>/<cell>/<view>.layout/`. Semantic diffs are computed
   against the Git first parent. Ordinary Git commits also appear on refresh.
   Older embedded Git snapshots are read directly from their original commits.
   First Save & Commit migrates v1 to v2 without rewriting history. It removes
   the old v1 snapshot and adds the v2 files together in the confirmed commit.
   Runtime `state/histories/` remains available as a read-only legacy archive.
3. Review reconstructs the selected after-state in a fresh
   `LAYOUT_DIFF_TEST/ALD_REVIEW_<nonce>/layout` view, verifies native
   readback, and opens it **read-only**. Review history includes the empty root
   implicitly, so the first commit is reviewed against an empty layout.

Version 0.10.2 accepts native removal of redundant standard-via row/column
overrides when they equal the current technology defaults. Other differences
still fail verification. This comparison-only decision is recorded under
`readback_normalization` in the review artifact; the committed snapshot and
highlight classification remain unchanged. See [format details](FORMAT.md).

### Review controls in 0.11.0

Review windows open with **Enable Dimming** on, scope **all**, and intensity
**50%**. **Untouched** highlights start off; use the Untouched toolbar toggle
to show them. Dimming is set on the review window only and can be adjusted
through Virtuoso's Display Options.

**Modified net** has its own category rows, history/commit summary count, color
and toolbar toggle. Net and terminal metadata, figure net assignments and
instance-terminal connections are connectivity changes. A figure with a
geometry, placement or ordinary property edit stays **Modified**, even when its
connectivity also changes. Pin access directions and pin properties are not
treated as net-only edits. Net/terminal metadata changes highlight the related
unchanged figures under **Modified net**; they no longer flood **Modified**.
The summary counts stored changes, while review counts highlighted figures, so
one changed net can affect many review figures without adding diff records.
Added/deleted nets remain additions/deletions in the connectivity categories.

**Groups** toggles boundary overlays for new, modified and deleted figure and
logical groups. Group edits, membership changes and order changes alone do not
recolor member figures. Independently edited/new figures retain their own
status. Each outline is the bounding rectangle of its geometric members,
including nested groups, pins and instance terminals. Logical-group modifications
are paired for review only when their name/definition identity is unambiguous;
stored content identities and exact diffs remain unchanged.

New/modified group outlines use the after-state. Deleted groups use the previous
snapshot, reconstructed only when necessary in another registered temporary
cell, closed and deleted after collecting bounds. This can add one native
reconstruction to a review containing deleted groups. External master contents
remain current, with the existing dependency warnings. Empty/non-geometric
groups are included in the summary but have no drawable outline. Failures to
obtain previous bounds are reported separately and do not prevent after-state
review. **Fit** includes deleted-group outlines.

**Style…** shows all eight categories in a matrix, with columns for Color,
Wire style, Width and Animation. **Blink** alternates the category's highlights
on/off every 0.5 seconds using a Virtuoso `hiRegTimer` callback. **Steady** keeps
them visible. Color, wire style and width remain independent. A disabled
toolbar category stays hidden through both animation phases. Existing
three-field style preferences migrate to Steady; new Modified net defaults to
blue (or another distinct color when migrating a conflicting older style).
One shared timer visits only live review windows and their eight highlight sets;
it does not iterate layout objects. It stops rescheduling when no visible,
populated category is blinking. Generation guards invalidate pending callbacks
on style changes, stop or reload; closed windows are skipped. Native display
resource blink flags are disabled: they read back correctly on this IC23.1
installation but did not visibly animate window highlights.

The shortcut installer uses the first unused binding from Ctrl+Shift+S,
Ctrl+Shift+G, and Ctrl+Shift+F12. S and G are already assigned in this installation,
so F12 is selected and shown in the toolbar tooltip and CIW. Stop removes only
the binding owned by this plugin; restart reinstalls it. If all candidates are
occupied, the toolbar remains available and none are overwritten.

The redundant standalone **Commit** toolbar button has been removed. The runtime
panel's **Save & Commit** uses the same save/preview/message flow and requires
the selected source to be open for editing. Older `ALDGUICommit` bindkeys also
route to this flow. Save referenced masters separately for stable saved-file
hierarchy fingerprints. Unsaved edits after preview, changed dependency hints,
changed Git HEAD, and dirty managed snapshot files reject confirmation; run Save &
Commit again after resolving the reported condition. Read-only review windows
cannot be saved or committed as source layouts.

Capture errors appear in a modeless result form. Save & Commit handles unknown
OA elements with two explicit confirmations, described below. Every GUI request and its
result/error are retained in `requests/`. Normal successful commits use the
toolbar status instead of opening extra dialogs.

### Committing with unsupported elements (0.14.0)

The saved source is captured completely before preparing a supported-only
candidate. The normal commit preview says **INCOMPLETE CHECKPOINT** when the
candidate omits content. Enter the message and press OK as usual, then:

1. The first warning lists omission reasons and counts. **View all omissions...**
   opens every diagnostic record. **Continue ignoring elements** advances to
   the second warning. **Close** rejects the commit.
2. The second warning explicitly states that rollback/restore to this checkpoint
   will lose ignored elements. **Confirm loss and commit** rechecks the source
   and Git, then commits. **Close** rejects. There is no remembered consent.

Close, the window-manager close control, Escape and the default Enter action
reject the warning; only its explicit Continue/Confirm button accepts it. Each
stage uses a fresh token, so duplicate callbacks cannot skip a warning. A new
Save & Commit expires older previews. Failures and cancellation release candidate
scratch; full-report viewers keep their own system-temp lease until closed.

The full-capture digest includes ignored diagnostic records. If supported or
ignored content, hierarchy, Git HEAD or branch changes during confirmation,
start again. No Git files are written until the final confirmation. Saving the
source still occurs at the start of Save & Commit, even when the commit is rejected.

Omission is conservative: a whole object with unsupported fields is omitted,
as are annotations, connectivity records and logical groups that depend on it.
When a figure group is omitted (including because a member cannot be recorded),
surviving member geometry is retained without that membership. These secondary
omissions and detachments are included in the full report. Essential cell
metadata and malformed/corrupt captures cannot be bypassed. Routes, markers and
Steiners retain the previously agreed always-excluded capture scope.

The Git snapshot directory includes `omissions.json` and `omissions.jsonl` for
incomplete checkpoints. These are diagnostic provenance, not a way to recreate
unknown objects. History, review and restore show the incomplete-checkpoint
warning, including at later unrelated Git revisions. The next complete commit
removes the audit files. Unknown-only changes can create an audit-only commit
with zero geometry changes; identical captures produce no new commit.

## Review controls

The bottom toolbar shows **Untouched**, **Modified**, **Modified net**, **New**,
**Deleted**, and **Groups** toggle buttons. Figure categories have color swatches.
These are independent window-local display groups,
not OA figure groups: existing object group membership and the reconstructed
cell's contents remain intact.

- **Untouched:** the recorded object is unchanged.
- **Modified:** a named object changed, or an anonymous figure has the same
  geometry with changed ordinary properties. Direct referenced-master changes mark
  their instances; deeper dependency changes also appear in metadata/warnings.
- **Modified net:** connectivity-only edits or figures affected by net/terminal
  metadata changes. Other simultaneous edits take priority as Modified.
- **New:** an added object with no such match.
- **Deleted:** previous-state shadows of removed visual objects, defaulting to
  red dashed outlines. Matched property/net changes do not create deleted shadows.
- **Groups:** new/modified/deleted group bounding outlines. Group-only edits do
  not propagate Modified highlighting to members.

Anonymous geometry has no stable edit identity. Moves or geometry changes are
shown conservatively as removal/addition. Attribute matching preserves duplicate
multiplicity but does not establish physical identity among overlapping identical
figures. The **Summary** lists deleted shadows and nonvisual metadata counts.
Shadows are independent window overlays: they are never inserted into the
after-state database or its GDS export.

When needed, the previous snapshot is reconstructed once in a registered helper
cell shared by deleted shadows and deleted-group boundaries. Native highlight
primitives preserve shape contours, labels and curves; native boolean geometry
supplies path end caps, including custom/chamfer path segments. Instances,
arrays and vias use their prior bounds. A failed contour conversion falls back
to its bounding box and is listed in the review artifact and Summary. A failed
previous-state reconstruction stops the review rather than silently omitting
deleted figures. The helper is closed/deleted after extracting independent
geometry. **Fit** includes shadows outside the after-state bounds.

Instances show their outline; mosaics, standard vias and placement boundaries
use bounding rectangles. Other supported figures use native shape highlights.
The review overlays do not alter layer visibility, source objects, or PDK display
packets. Native layout objects and GDS export remain the reconstructed after-state.

**Style...** opens a modeless matrix: one row per category, with color, wire
pattern, width (1/2/3/5 pixels), and Steady/Blink animation columns. Eight colors
and four wire patterns are available. Apply/OK validates all rows and applies
them as one request, updating highlights and toolbar swatches. Cancel discards
unapplied edits. Settings persist for subsequent review sessions.
Each review uses namespaced display resources, so styles do not recolor other
designs. **Fit** frames the entire review, and **Summary** shows counts and
hierarchy warning totals.

Changed hierarchy fingerprints warn without preventing review. A missing master,
incompatible interface, or unsupported top-level OA content can still prevent
native reconstruction. Dependency contents remain external; historical geometry
inside changed masters is not reconstructed.

Named logical-group definitions also belong to Virtuoso session context. Before
reviewing a snapshot that uses definitions other than `unrestricted`, Review
opens its source cellview read-only and closes its owned reference. Reading the
persisted OA data makes definitions such as `lxImplicitBus` and `lxUngen`
available to `dbCreateGroup`; merely loading the Layout XL application is not
sufficient in the tested IC23.1 session. The source is never saved or reopened
for editing by this step. The same context is prepared for prior-state helpers.

The review manifest records `group_definition_context`, including the required
names, source identity and definitions found there. Custom definition schemas
are external dependencies, not inferred from their names. If the original
layout is unavailable and a required definition has not already been loaded,
group creation still fails with a named group/definition diagnostic. Python
adapter callers can supply `group_definition_source=(lib, cell, view)` to
`VirtuosoAdapter.reconstruct`; the GUI supplies it automatically.

## Moved / stretched category (0.16.0)

Position and size edits have their own **Moved / stretched** toolbar toggle,
swatch and style-matrix row. History totals, category rows, full details and
Save & Commit previews use **MS** for this category; ordinary **M** excludes it.
The matrix has nine category rows, each with independent color, line pattern,
width and blinking. Existing saved styles remain intact.

This includes translated vias and cut-array dimensions, shape coordinates and
widths, instance positions and mosaic spacing. Changes to PCell parameters,
properties, layers, masters or orientation stay under Modified, even if the
object also moved. A position/size edit can include connectivity changes;
connectivity-only edits remain Modified net. Net-only and group-boundary behavior
is unchanged.

Via matching uses definition, net, override parameters and reciprocal spatial
correspondence. It is an inferred presentation pairing, not a persistent object
identity. Ambiguous duplicate/crowded candidates remain add/delete. Full details
retain the original fields and explain how each pair was matched.

## Temporary view cleanup

Close review windows, then press **Clean reviews** in the native Runtime panel.

Cleanup deletes only recorded `ALD_REVIEW_<nonce>/layout` views in the configured
review library. It validates the nonce against each manifest and skips any open
cellview. It never deletes source views, whole libraries, histories, or evidence.
Interrupted builds are registered before construction so the next startup can
also reclaim a partially created view.
