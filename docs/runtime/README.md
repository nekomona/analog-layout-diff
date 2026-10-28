# Runtime package

`layoutdiff.runtime` owns supervisor/worker processes, process identity, locks,
session workspaces and cleanup. SKILL launches the supervisor on the Virtuoso
host; the supervisor starts a Python UI worker. The worker calls the local shared
bridge. A bridge-free cleanup janitor can remain after worker Stop.

## Select the intended CIW

Use a separate bridge profile/port for each concurrent CIW. Check process/display
identity with `virtuoso-bridge list-windows --top-level --json` and bridge calls
before loading the plugin. Store site configuration in an ignored `.env`.
The worker verifies the bridge endpoint's process identity before UI/database work.

## Deployment

Use a virtual environment with Virtuoso Bridge installed and its source checkout
beside this project; the installer bundles that sibling checkout. The target host
needs `uv` on PATH. Select a dedicated absolute directory:

```sh
python scripts/install_runtime.py --destination /absolute/path/to/layoutdiff_runtime
```

The installer deploys isolated bridge/plugin sources and a Python environment,
optionally builds the C++ kernel, generates `startup.il`, and loads it through
the selected bridge. `--native required` requires a compiler/build; `--native off`
skips the build. The generated startup file can be loaded after bridge setup from
`.cdsinit` when automatic startup is wanted. Keep generated host paths local.

The optional `--migrate` imports a local `gui-workspace` chain/preferences archive
and refuses to overwrite host histories. New GUI commits use Git snapshots.

## Start and stop

Use **CIW > Layout Diff** or the toolbar **Runtime** button for Start, Stop,
Restart, status/logs, layout selection, review cleanup and backend configuration.
The `gui-serve`, `gui-stop` and `gui-clean` CLI commands request native runtime
actions. They do not launch a persistent local desktop worker.

The supervisor uses a kernel file lock to reject duplicate starts. Its lock inode
remains after shutdown. Stop releases worker-owned highlights/database opens and
removes worker toolbars/bindings. Persistent CIW controls can start it again.
Open review windows keep their reconstructed contents; reopen a revision after
restart to attach fresh highlight controls. Git snapshots and preferences persist.

## Ownership and shutdown

The supervisor never calls SKILL. It watches the original Virtuoso PID, Linux
start identity/boot ID and IPC lifetime while owning the worker process group.
The worker polls `ALDGUIQueue` through the shared local bridge after callbacks
return. Requests run serially; loading indicators do not imply parallel database
mutation. Request files record completed results/errors, not pending queue state.

An exit callback requests shutdown; independent parent/IPC checks handle process
death, PID reuse and zombies. The supervisor can stop a worker blocked on CIW.
See the [process diagram](../architecture/PROGRAM_STRUCTURE.md#deployment-and-process-boundaries)
and [verification methodology](../development/VERIFICATION.md).

## Temporary resources and cleanup

`workspace.py` allocates token-owned bundles under the host's system temporary
directory. Captures, replay code, exports, diagnostics, review OA and restore
backups belong to these bundles. Native lease callbacks track referencing layout
and text windows. A sealed bundle is releasable only after its last native
reference closes. Worker Stop can leave a janitor waiting for those releases;
verified Virtuoso process death permits final session cleanup.

Cleanup checks ownership tokens/manifests and skips open views. Interrupted builds
are registered before construction. It must not delete source views, whole
libraries, durable snapshots or another session's resources. Exact-token worker
Git locks can be reclaimed after shutdown; unrelated locks remain untouched.

## Durable state

| Location | Owner and purpose |
| --- | --- |
| Selected design Git repository | Snapshot commits and optional omission audits |
| Deployed app and runtime `state/` | Repository selection, styles/backend preferences, status, logs and request audits |
| System-temp session bundles | Reference-tracked native and filesystem scratch |
| Derived SQLite/wire/browser caches | Closed with their owning snapshot/index/browser |

[supervisor.py](../../layoutdiff/runtime/supervisor.py) implements launch/monitor/reap
modes; [workspace.py](../../layoutdiff/runtime/workspace.py) handles work bundles.
The [UI guide](../ui/README.md) describes user workflows over these resources.
