# Git package

`layoutdiff.git` owns immutable snapshot reads, isolated commit transactions and
repository-local semantic diff tooling. Git supplies commit IDs, ancestry,
branches, tags and author metadata. Derived caches have no commit authority.

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
where they exist. Branch creation and automatic layout merging are outside the GUI.

The reader also accepts single-file v1 snapshots and embedded operation-chain
snapshot blobs. A confirmed commit can adopt the directory representation in one
ordinary Git transaction. `migrate-v2 REPO LIB CELL` performs explicit conversion;
conflicting coexisting formats fail validation. Existing Git revisions are retained.
Standalone runtime chains are read-only GUI inputs; GUI commits write Git snapshots.

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
| [tools.py](../../layoutdiff/git/tools.py) | Local setup, extraction and semantic textconv |
| [driver.py](../../layoutdiff/git/driver.py) | Textconv executable entry |
