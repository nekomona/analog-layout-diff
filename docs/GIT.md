# Git workflow

## Native Save & Commit

The installed layout toolbar has **Save & Commit**, bound to **Ctrl+Shift+F12**
in the current Virtuoso session. It saves the edited cellview, then shows the
repository, branch, layout, change counts and semantic diff. The message input
receives focus. **Enter** or **OK** creates a Git commit; **Cancel** leaves the
layout saved and creates no commit. **View full diff...** opens the complete
preview in Virtuoso's text viewer when the inline preview is shortened.

The worker discovers Git above `getWorkingDir()`. If no repository exists, a
native form proposes the parent directory and offers to initialize it on OK.
Users may choose an existing repository instead. Optional author fields set
only that repository's Git configuration. Cancel initializes nothing. The
selected repository is remembered for that Virtuoso working directory in
`state/git.json`; changing the working directory triggers discovery again.

Choose a dedicated repository for your layout snapshots.

Version 0.9 stores one canonical snapshot per cellview in
`layouts/<library>/<cell>/<view>.layout/`, with `manifest.json`, `objects.jsonl`
and `definitions.jsonl`. See the [exact v2 codec](FORMAT_V2.md).
Names are UTF-8 percent-encoded
when necessary; reserved filesystem names are fully encoded, and case-colliding
file paths are rejected for cross-platform safety. Schema/version information
is in each snapshot; the path records source identity. No per-layout HEAD,
operation files, commit IDs or identity manifest are created.

The first commit also adds `layouts/.gitattributes` rules disabling automatic
text merging for legacy snapshots, JSONL files and v2 manifests. Subsequent
commits normally change only the selected snapshot's files. Ordinary Git diffs
show localized object lines and small manifest/definition changes.
Raw OA files, scratch data and Cadence locks are excluded.

**History & Changes** uses Git commit IDs, messages, author/date and affected
files directly. Semantic object counts/diffs compare snapshots in the selected
commit and its first parent. The log is filtered by the selected cellview;
unrelated Git commits are omitted. Ordinary command-line Git commits, including
commits affecting multiple cellview snapshots, are supported. File counts cover
the whole selected Git commit; object counts cover the selected cellview.
Historical reads use Git blobs, independent of worktree/index edits.

**Review layout** reconstructs the selected snapshot directly. Deleted snapshots
remain in history with semantic deletion counts; select an earlier revision to
open a native review. Branch/merge creation remains outside the GUI; externally
created merge commits are compared with their first parent. Detached HEAD can
be browsed, but Save & Commit requires an attached branch.

### Existing histories

V1 `layouts/<library>/<cell>/<view>.layout.json` snapshots remain readable. The
next confirmed Save & Commit adds v2 and deletes v1 in the same Git transaction,
including when the semantic content is unchanged. Cancel leaves Git unchanged.
Alternatively run `python -m layoutdiff migrate-v2 REPO LIB CELL`. Old revisions
are retained; conflicting coexisting v1/v2 snapshots are rejected. The v1
reader materializes old JSON, so migration does not share v2's low-memory bound.

Old `.layoutdiff/histories/<SHA256(identity)>/latest.layout.json` blobs are read
directly from their original Git commits; custom operation chains are not
replayed for Git browsing. First Save & Commit adopts the new snapshot path,
including when there are no semantic changes. Preview explains this transition;
Cancel leaves storage unchanged. Old files and Git commits are retained, and
later commits never update the archived custom history. No history is rewritten.

Pre-Git runtime histories remain read-only archives in the browser. Their first
Save & Commit captures a new initial Git snapshot; it does not import their
entire local chain. The standalone CLI remains available for explicit operation
chains and regression fixtures. All GUI commit controls use Save & Commit.

Preview does not alter Git files or the index. Confirmation checks the saved
layout and its hierarchy hints again and rejects stale previews, changed Git
HEAD/branch, and uncommitted changes to files it would write. No-change captures
do not make empty commits, except the explicit adoption of legacy storage.
A private commit index includes the snapshot and any required namespace attribute
rule; unrelated staged and unstaged work is preserved. The normal
`git commit` command runs repository hooks and configured signing. Errors appear
in the result form and runtime log; there is no automatic push. Interactive
credential/signing prompts are unsuitable for this background worker.

The supervisor removes only exact-token Git locks owned by its worker after
shutdown. An interrupted commit can leave managed worktree files needing review;
the next preview rejects that dirty history instead of overwriting it.

## Legacy command-line snapshots and semantic Git diffs

The following v1 workflow remains supported. For the new JSONL CLI and checked
streamed patch replay, use the examples in [FORMAT_V2.md](FORMAT_V2.md).

Capture canonical snapshots as `*.layout.json` and commit them with ordinary
Git commands. Git stores the original JSON; a local textconv driver presents
object fields and hierarchy fingerprints in `git diff`, `git show`, and `git log -p`.
No Cadence connection is required to review Git history.

Run the following from `analog-layout-diff/`, using an existing repository's
**root** as `REPO`. For a separate layout history repository, first run
`git init D:/my-layout-history` and use that directory as `REPO`.

```powershell
python -m layoutdiff git-setup REPO
python -m layoutdiff capture MY_LIB MY_TOP REPO/top.layout.json
git -C REPO add .gitattributes top.layout.json
git -C REPO commit -m "Initial layout"

# After editing the top or a descendant in Virtuoso:
python -m layoutdiff capture MY_LIB MY_TOP REPO/top.layout.json
git -C REPO diff -- top.layout.json
git -C REPO add top.layout.json
git -C REPO diff --cached -- top.layout.json
git -C REPO commit -m "Move a device inside a child"
git -C REPO log -p -- top.layout.json

# Extract the original blob safely, including on Windows PowerShell:
python -m layoutdiff git-extract REPO HEAD~1 top.layout.json old.layout.json
python -m layoutdiff restore old.layout.json restored_unique_name
```

Restore checks top-level reconstruction exactly, with the documented
[comparison-only via-default equivalence](FORMAT.md) in 0.10.2. This accepts
Virtuoso removing a redundant row/column default without rewriting any Git
snapshot. External-master drift produces
warnings and a report in `artifacts/dependency_warnings_<build-id>.json`.
`artifacts/restored.layout.json` contains the actual readback, including current
fingerprints. Missing master definitions or incompatible terminal interfaces
can still prevent Virtuoso from constructing an instance; fingerprint changes
alone never reject reconstruction.

`git-setup` optionally writes local `diff.layoutdiff.*` configuration and appends
`*.layout.json diff=layoutdiff -merge` to `.gitattributes`, preserving other
lines. It does not stage files, commit, install hooks, or change global Git
settings. It rejects subdirectories of a repository so a request cannot
silently configure the parent. Run it once on each machine/clone; the local
driver uses absolute paths to this Python environment and package. Rerun after
moving either path. To undo, remove that attributes line and run
`git -C REPO config --local --remove-section diff.layoutdiff`.

Git GUI clients that honor textconv can display the same representation. Some
GUIs and hosted code review sites display raw JSON; that JSON is still sorted
and reviewable. Raw JSON remains the replay input. Do not save or apply a
textconv patch as a layout snapshot. `-merge` marks conflicting snapshots for
manual resolution; automatic layout merging is outside this single-parent tool.

The separate append-only `History` format remains useful for integrity-checked
operations from an empty state. It can also be tracked in Git (`empty.json`,
`HEAD`, `commits/*.json`); exclude its `captures/` folder and `.lock`. To review
those commit files with the same driver, add an explicit attributes entry such
as `my-history/commits/*.json diff=layoutdiff -merge`. The setup command only
associates `*.layout.json` by default.

Command-line captures are explicit and never save designer edits. The native
Save & Commit action saves only the edited cellview; save referenced cells first
when you want stable saved-OA fingerprints. Child contents remain external and
are represented by dependency hints.
