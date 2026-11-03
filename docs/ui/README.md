# UI package

`layoutdiff.ui` coordinates the CLI, native toolbar, history browser, review and
checkpoint restore. It calls the `virtuoso`, `git`, `comparison` and `data`
services. The [runtime](../runtime/README.md) owns deployment and process lifetime.
Use the [CLI guide](CLI.md) for command dependencies and preservation limits.

## Save and commit

The layout toolbar provides **Save & Commit**, **History**, **Merge** and **Runtime**.
Save & Commit saves the edited cellview, previews repository/branch/identity,
change counts and semantic details, then focuses the commit-message field.
**Enter** or **OK** commits; **Cancel** leaves the native layout saved.
**View full diff...** opens complete details when the preview is shortened.

If no repository is found above the Virtuoso working directory, a native form
offers a repository choice or initialization. Review windows cannot be saved or
committed as source layouts. Save referenced masters separately for repeatable
saved-file hierarchy fingerprints. Edits after preview, changed dependencies or
Git state, and dirty managed snapshot files require a fresh preview.

The shortcut installer chooses the first unused binding from Ctrl+Shift+S,
Ctrl+Shift+G and Ctrl+Shift+F12. The toolbar tooltip shows the selected binding.
Occupied bindings are preserved; if all candidates are occupied, use the toolbar.

## History and changes browser

Open **CIW > Layout Diff > History & Changes...** or the layout **History** button.
The browser offers two selection paths:

- **Cell-centric:** choose a library/cell/view, then one of its commits.
- **Git-centric:** choose a branch/tag, a commit, and one of its changed cells.

The log shows Git hash, message, author/date and semantic change counts.
Affected files show ordinary Git line counts and patches. The category pane
groups shapes by layer, vias by definition and instances by master, plus
connectivity, groups and metadata. It displays A/M/D/MN/MS totals. Select a
category for ten changes per page; full details include all fields and matching
evidence. **All categories** restores the overview and full change export.
Unselected revision counts are computed lazily.

**Review layout** reconstructs the selected snapshot, checks native readback and
opens a temporary read-only view. Missing masters or unsupported native content
can prevent reconstruction. Hierarchy drift emits warnings; it does not recreate
referenced-master revisions. Required logical-group definitions are loaded by
reading the designated source view read-only when available.

## Review controls

| Control | Meaning |
| --- | --- |
| Untouched | Unchanged figures; highlights start off |
| Modified | Ordinary properties, layers, masters, orientation or PCell parameters changed |
| Moved / stretched | Position/size edits without an ordinary modification |
| Modified net | Connectivity-only edits or figures affected by connectivity metadata |
| New / Deleted | Unmatched additions and prior-state shadows |
| Groups | New, modified and deleted group boundaries |

Classification and matching are defined by [comparison](../comparison/README.md).
Movement may include connectivity changes; ordinary modifications take priority.
Group-only edits do not recolor every member. Stored-record counts and visible
highlight counts differ when one net/master change affects several figures.

Reviews start with dimming enabled at 50% intensity. Each category has its own
toggle, swatch and style. **Style...** provides nine rows: six figure categories
and three group-boundary categories. Rows configure color, wire pattern, width
(1/2/3/5 pixels), and Steady/Blink animation. Blink uses a shared guarded timer;
disabled categories remain hidden. Apply/OK validates all rows; Cancel discards
unapplied edits. Styles persist for subsequent reviews.

Deleted shadows and prior group bounds use a shared, temporary before-state
reconstruction when needed. Highlights are independent overlays; source and
after-state OA geometry remain unchanged. A failed contour conversion falls back
to a bounding box and is reported. A failed before-state reconstruction stops
review. **Fit** includes shadows and deleted-group bounds; **Summary** reports
counts, fallbacks and dependency warnings.

## Restore a saved working layout

**Restore checkpoint...** constructs and verifies the chosen checkpoint, presents
the replacement for confirmation, keeps a native backup, and checks readback after
replacement. Unsaved or still-referenced targets are refused. Restore does not
create a Git commit; use Save & Commit to record the resulting working state.
The selected Git checkpoint remains unchanged. See the
[interaction sequence](INTERACTION_SEQUENCES.md#review-and-restore-interaction).

## Interactive merge editor

Open **Merge** on the layout toolbar or **CIW > Layout Diff > Merge branches...**.
The target is the selected repository's current branch. Enter incoming branches
in integration order, or resume an existing session. The repository panel lists
affected cells and ordinary-file conflicts, with 100-row pages. Open a cell to
work in its temporary native layout editor.

The left dock lists decisions with a category filter and 50-row pages. Categories
retain the movement/stretch and modified-net distinctions. **Pick** finds decisions
at a canvas point; overlapping candidates require an explicit row choice. The
right dock explains the decision, correspondence evidence and dependencies.
Base appears in gray, Target in cyan and Incoming in magenta; the Result uses
normal layout layers. Each branch overlay can be toggled independently, and
**Blink** animates enabled overlays. Deleted alternatives remain visible as
prior-state contours. Group-only changes show group boundaries; net-only changes
show connected figures. Bounding-box fallbacks and overlapping branch changes
are reported as review hints, not DRC/LVS results.

Choose Target, Incoming, Base, a compatible combination, or Keep Both when the
objects are independent anonymous figures. **Preview** reconstructs and checks
the candidate without accepting it. **Accept preview** records the decision.
**Edit result** enables native layout tools; **Accept edits** captures and verifies
the result, while **Cancel edits** restores the previous accepted state. Accepted
manual edits reopen earlier explicit decisions conservatively, since native tools
can change any part of the cell. **Undo decision** and **Redo decision** operate on
the persistent journal, independently of native undo history.

The optional serialized preview is a separate dock. **Validate** verifies the
accepted result; **Finish merge** marks that cell validated for its repository
transaction. Resolve and validate all cells, then use **Commit step** in the
repository panel. Continue the selected incoming-branch sequence and finally
**Publish to target**. See [Git integration](../git/README.md#graphical-branch-integration)
for publication and recovery behavior. OA source replacement remains a separate
checkpoint-restore action.

**Suspend** closes disposable native views while retaining accepted decisions.
Closing an editor also releases its native helper leases; unaccepted edits are
not journaled. Resume rebuilds from accepted data. Native alternatives are built
from the selected objects and required dependency closure. A branch overlay is
limited to 2,000 selected objects and reports truncation; compound dependencies
can require a larger helper reconstruction. The full Result and final validation
always contain all records. Merge analysis currently materializes three snapshots
in Python, so whole-cell reconstruction and validation remain substantial costs
for large cells. The existing C++ exact-diff backend does not implement three-way
merge semantics.

## Unsupported elements and omission audits

Strict native capture/replay rejects unsupported content. Save & Commit offers
a supported-only checkpoint after the normal preview/message flow:

1. **Continue ignoring elements** accepts omission of the listed unsupported data.
2. **Confirm loss and commit** confirms that restoring this checkpoint loses it.

Closing either warning rejects the commit. **View all omissions...** lists each
omitted object, dependent record and detached group membership. Consent is bound
to the capture; the source, hierarchy and unknown content are checked again
before committing. Malformed storage and unsupported essential metadata remain
errors. Explicitly excluded routes, markers and Steiners produce no omission audit.

Git stores `omissions.json` and `omissions.jsonl` beside the supported snapshot.
History, review and restore identify incomplete checkpoints. The diagnostic audit
is not replay input and does not guarantee lossless future recovery. See
[CLI preservation limits](CLI.md) and [the audit format](../data/STORAGE_FORMAT.md#optional-omission-audit).

## Loading and cleanup

Save & Commit preparation/committing uses a modeless loading popup. Other slow
actions report inline **Loading: ...** status. Capture failures appear in the
result form; request results/errors are retained in runtime audits.

Reviews may remain visible after worker Stop. Temporary bundles stay until all
referencing layout/text windows close; a cleanup janitor can outlive the worker.
Use **Clean reviews** after closing windows. The
[runtime guide](../runtime/README.md#temporary-resources-and-cleanup) defines ownership.

## Source map

`cli.py` implements commands; `worker.py` coordinates workflows; `browser.py`
supplies cell/repository models; `restore.py` enforces checkpoint replacement.
`merge.py` coordinates graphical decisions and repository sessions; the native
merge forms and views live in `eda/virtuoso`. `skill/` contains the other native
forms, callbacks and toolbar integration. See
[interaction sequences](INTERACTION_SEQUENCES.md) for cross-package calls.
