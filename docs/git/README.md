# Git package

`layoutdiff.git` owns immutable snapshot reads, isolated commit transactions and
repository-local semantic diff tooling. Git supplies commit IDs, ancestry,
branches, tags and author metadata. Derived caches have no commit authority.

## Git compatibility

Git 1.8.3.1 and later are supported without a shell shim. The shared runner uses
the subprocess working directory instead of `git -C`. Administrative index and
merge paths use `--git-path` when supported and fall back to `--git-dir` without
assuming `.git` is a directory. Revision resolution validates inputs and full
commit IDs without `--end-of-options`; metadata uses `%ai` and normalizes its
timezone to ISO format. `LAYOUTDIFF_GIT` can select a specific Git executable.

Isolated repository merges use linked worktrees when both add and remove are
available. Older Git uses a local clone with independent objects, index and
merge state. The transaction retains its backend across restarts, protects
pinned input commits, refreshes source hook/identity/signing settings before
committing, and transfers completed commits back before explicit publication.
Ordinary-file choices use path-specific checkout, with explicit deletion handling.

Agents use the [headless semantic interface](../agent/README.md#headless-cli-and-ssh-transport)
alongside ordinary system Git. Capture and native readback are separate native
operations; stored-snapshot comparison and logical merge need no Virtuoso.

## Snapshot storage

Each cellview is stored at `layouts/<library>/<cell>/<view>.layout/`, with
`manifest.json`, `objects.jsonl` and `definitions.jsonl`, plus an omission audit
for an explicitly confirmed incomplete checkpoint. Path components use reversible
UTF-8 percent encoding; reserved names and case collisions are checked.
See [the storage contract](../data/STORAGE_FORMAT.md).

Managed Git attributes disable automatic text merging for snapshot files.
Raw OA files, scratch output and Cadence locks stay outside managed snapshots.

## Commit transaction

[Save & Commit](../ui/README.md#save-and-commit) saves the edited native view,
captures it, and prepares a preview without altering the index or Git files.
Confirmation rejects a changed source/hierarchy, HEAD or branch, stale consent,
or dirty managed files. A private index includes only the selected snapshot and
required namespace attributes, preserving unrelated staged/unstaged work.

The transaction invokes ordinary `git commit`, including repository hooks and
configured signing. Failures are reported without an automatic push. Interactive
credential/signing prompts are unsuitable for the background worker. The runtime
can remove exact-token locks owned by its stopped worker; an interrupted commit
can still leave managed files requiring review.

The worker discovers Git above Virtuoso's working directory. If none is found,
the UI offers an explicit repository choice or initialization. Repository and
optional author settings are local to that choice. Detached HEAD supports browsing;
Save & Commit requires an attached branch. Identical captures do not create an
empty commit, except explicit adoption of another supported storage representation.

## History reads

`GitSnapshots` reads immutable blobs for a selected commit and first parent,
independently of unrelated worktree/index edits. Cell history filters commits by
the chosen cellview. Repository history can select branches/tags and changed cells.
Externally created multi-cell or merge commits can be browsed; merges compare
with their first parent. Deleted snapshots remain reviewable through a revision
where they exist. Branch creation remains outside the GUI. Graphical branch
integration is described below.

The reader also accepts single-file v1 snapshots and embedded operation-chain
snapshot blobs. A confirmed commit can adopt the directory representation in one
ordinary Git transaction. `migrate-v2 REPO LIB CELL` performs explicit conversion;
conflicting coexisting formats fail validation. Existing Git revisions are retained.
Standalone runtime chains are read-only GUI inputs; GUI commits write Git snapshots.

## Graphical branch integration

**CIW > Layout Diff > Merge / Resolve active conflicts...** starts a transaction from the selected
repository's current attached branch. Incoming refs are pinned to commit IDs in
the entered order. Each incoming branch is integrated with a separate two-parent
commit; already-integrated ancestors are skipped. A unique common ancestor is
required. Unrelated histories and multiple merge bases are refused.

The transaction creates a detached isolated checkout in system temporary storage:
a linked worktree on modern Git, or an independent local clone on legacy Git.
Git merges ordinary paths there. Every affected managed cell, including changes
on only one side, is reconstructed and validated through the native merge editor.
Managed snapshot bundles are regenerated from those decisions. Git's textual
merge output is never authoritative for layout records. Ordinary-file conflicts
have Base/Target/Incoming choices, a patch viewer, and an explicit resolution
requirement. **All affected paths** includes automatically merged ordinary files.
Embedded legacy history bundles must be migrated before branch integration.

**Commit step** uses normal `git commit`, including hooks/signing. The resulting
tree must match the validated index and have the expected two parents. A hook
that changes that tree prevents publication. **Publish to target** separately
fast-forwards the original clean checkout, after checking its branch and HEAD.
Neither action replaces an OA source cell or pushes a remote. Native replacement
uses the existing explicit checkpoint-restore flow.

Decisions and transaction state persist below the runtime's `merges` and
`merge-repositories` directories. Suspended Git worktrees remain in system temp,
outside a runtime session's disposable TMPDIR. An internal Git ref protects
prepared commits. Resume recovers interrupted preparation, commit and publication
when their pinned state can be verified. Unexpected external changes stop the
transaction for inspection. Completed or explicitly cancelled transactions remove
their isolated checkouts and internal refs; decision journals remain as local audits.

Incomplete source snapshots retain their diagnostic reports in the merged bundle.
Commit requires two loss confirmations, including after manual edits introduce
unsupported content. These reports are conservative inherited diagnostics, not a
replayable archive. Removing a whole incomplete cell is refused while its omission
audit needs preservation. Explicitly ignored routes, markers and Steiners remain
ignored.

## Existing Git merge

When `MERGE_HEAD` exists, **Resolve active Git merge** opens the layouts in that
merge. Supported managed v1/v2 bundles are recognized by their encoded paths.
Inputs come from Base, HEAD and MERGE_HEAD blobs; conflict-marker text is never
parsed. Already resolved stage-0 layout bundles are preserved and validated.
The initial implementation requires one incoming parent and one merge base.
Legacy/unrecognized layout storage is reported for migration.

After every cell passes graphical validation, **Stage layout resolutions**
regenerates its managed bundle, locks the original index, copies the latest index,
and replaces only the selected layout entries and worktree files. Unrelated
staged files, unstaged edits and ordinary-file conflict stages remain intact.
There is no commit, publication, hook execution, or `git merge --abort`. Review
all staged files and finish the merge in your normal Git tool. Omission audits
require the same two loss confirmations before staging.

The source branch, parent IDs, managed index entries and managed worktree bytes
are pinned. Changes to those inputs require reopening; unrelated-file work may
continue. A staging journal and before-file backup permit recovery of interrupted
installation. Resume refuses newer conflicting edits rather than overwriting them.
Discard releases only this editor's helper worktree. It leaves the active merge
and prior staged resolutions in place.

## Ordinary commits and staged files

| Situation | Behavior |
| --- | --- |
| Commit changes no layouts | Visible in Git-centric history; changed-cell list is empty. Cell-centric history skips it. Snapshot lookup retains the latest applicable layout. |
| Save & Commit with unrelated staged/unstaged files | Only the selected layout and required attributes enter the commit; other staged blobs and worktree edits are retained. Applies to v1 and v2. |
| Managed layout files already dirty/staged | Save & Commit refuses to overwrite them. |
| Save & Commit during an active merge | Directs the user to Merge; finish the Git merge first. |
| Start a new isolated branch merge with staged/local files | Refused until the original checkout is clean. |
| Active merge with other staged files/conflicts | Stages layouts only; other files remain for the normal Git workflow. |
| Incoming branch has no managed layout changes | Isolated integration can create its ordinary two-parent commit without a cell editor. |

## Semantic text conversion

For explicit single-file snapshots, run from an activated environment:

```sh
python -m layoutdiff git-setup REPO
python -m layoutdiff capture MY_LIB MY_CELL REPO/top.layout.json
git -C REPO add .gitattributes top.layout.json
git -C REPO commit -m "Initial layout"
git -C REPO diff -- top.layout.json
git -C REPO log -p -- top.layout.json
python -m layoutdiff git-extract REPO HEAD top.layout.json extracted.json
```

`git-setup` requires the repository root. It writes local `diff.layoutdiff.*`
configuration and appends `*.layout.json diff=layoutdiff -merge`, preserving other
attributes. It does not stage, commit, install hooks or change global settings.
Rerun it after moving the interpreter or package. To undo, remove the attributes
line and run `git -C REPO config --local --remove-section diff.layoutdiff`.

Textconv is offline review text; raw JSON remains replay input. Hosted viewers
may show raw JSON. `git-extract` handles a v1 JSON blob; retain the full directory
when exporting a directory snapshot with omission sidecars. See
[CLI limits](../ui/CLI.md#what-unsupported-content-preservation-currently-means).

## Source map

| Source | Responsibility |
| --- | --- |
| [store.py](../../layoutdiff/git/store.py) | Immutable snapshot discovery and reads |
| [commit.py](../../layoutdiff/git/commit.py) | Preview, stale checks, isolated commit and rollback |
| [merge.py](../../layoutdiff/git/merge.py) | Pinned branch preparation, cell validation, two-parent commits and publication |
| [active_merge.py](../../layoutdiff/git/active_merge.py) | Active-merge discovery, staged-input preservation and layout-only resolution staging |
| [tools.py](../../layoutdiff/git/tools.py) | Local setup, extraction and semantic textconv |
| [driver.py](../../layoutdiff/git/driver.py) | Textconv executable entry |
