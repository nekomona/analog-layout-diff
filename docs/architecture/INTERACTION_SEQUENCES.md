# GUI interaction sequences

Detailed request paths complement the [functional package diagram](PROGRAM_STRUCTURE.md).
The package structure is the overview; these sequences expand individual operations.

## Save and commit interaction

```mermaid
sequenceDiagram
    actor User
    participant UI as Virtuoso GUI and SKILL queue
    participant Worker as GuiWorker
    participant Adapter as VirtuosoAdapter
    participant Native as Native capture services
    participant Codec as Snapshot and coverage
    participant Commit as Git preview and transaction
    User->>UI: Save & Commit button or shortcut
    UI->>UI: Save selected edited layout
    UI->>UI: Enqueue quick-preview
    Worker->>UI: Poll and drain requests through bridge
    Worker->>Adapter: Capture selected identity
    Adapter->>Native: ALDRead and hierarchy services through bridge
    Native-->>Adapter: Typed records and dependency hints
    Adapter->>Codec: Resolve links, check coverage, encode snapshot
    Codec-->>Worker: Validated snapshot and optional omission audit
    Worker->>Commit: Prepare against Git HEAD and selected snapshot
    Commit-->>Worker: Preview token, counts, category details
    Worker->>UI: Show preview and focus message field
    User->>UI: Enter / OK with message
    UI->>UI: Enqueue quick-commit with token
    Worker->>UI: Poll confirmation request
    opt Snapshot has an omission audit
        Worker->>UI: Show first unsupported-content confirmation
        User->>UI: Continue
        UI->>UI: Enqueue quick-omit-continue
        Worker->>UI: Poll and show final rollback-loss confirmation
        User->>UI: Confirm data loss
        UI->>UI: Enqueue quick-omit-confirm
        Worker->>UI: Poll final confirmation with one-use token
    end
    Worker->>Adapter: Recheck saved source and hierarchy
    Worker->>Commit: Check token, HEAD/branch, source and managed files
    Commit->>Commit: Private index, normal git commit, hooks/signing
    Commit-->>Worker: New Git revision or failure
    Worker->>UI: Publish outcome and finish loading
```

Cancel releases the preview without a Git commit; the initial layout save has
already happened. Preparation and confirmation are separate queued requests
joined by a preview token. The Git transaction preserves unrelated staged and
unstaged work. [Git workflow](../GIT.md) specifies stale-preview rejection,
repository discovery and migration behavior.
Each omission acceptance consumes a separate one-use token; a repeated callback
cannot count as the next confirmation. Rejecting either prompt cancels the commit.

## Review and restore interaction

```mermaid
sequenceDiagram
    actor User
    participant UI as History and review GUI
    participant Worker as GuiWorker
    participant History as HistoryBrowser and GitSnapshots
    participant Review as Classification and native adapter
    participant Native as Virtuoso OA and highlight services
    User->>UI: Select commit and Review layout
    UI->>UI: Enqueue review request
    Worker->>UI: Poll request through bridge
    Worker->>History: Read selected commit and first-parent states
    History-->>Worker: Before and after snapshots
    Worker->>Review: Classify and allocate temporary library
    Review->>Native: Build after-state with native objects and MPPs
    Review->>Native: Settle generated cell, capture and verify readback
    Native-->>Review: Actual state and dependency warnings
    opt Deleted figures or previous group boundaries
        Worker->>Review: Build temporary before-state helper
        Review->>Native: Extract shadow primitives and group bounds
        Review->>Native: Release helper object handles and closed cell
    end
    Worker->>Native: Open read-only review and assign highlight styles
    Native-->>UI: Review window, toolbar and category overlays
    User->>UI: Close review and any additional referencing windows
    UI->>Native: Lease callback checks windows, forms and OA opens
    Native-->>Worker: RELEASED marker becomes available for reaping
```

Category selection does not require native reconstruction; the browser can
display semantic changes from Git/codec/index data alone. Review additionally
needs native masters and technology. Deleted shadows are independent drawing
primitives; the final review does not depend on keeping its before-state helper
cell open. Group boundaries do not recursively recolor every member.

Restore reuses the reconstruction/validation adapter but has a separate
`ui/restore.py` state machine: prepare a verified checkpoint, retain a plan token,
ask for confirmation, recheck the target, create a native backup, replace/save
and verify the working view. Restore does not advance Git; Save & Commit records
the restored state afterward. See [checkpoint workflow](../VIRTUOSO_GUI.md#restore-a-saved-working-layout).
