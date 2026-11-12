# Verification methodology

Run the offline suite with `python -m pytest tests -q`.
Permanent fixtures contain synthetic data. They cover canonical identity,
duplicate multiplicity, type distinctions, exact forward/reverse patches,
legacy histories, v2 streaming storage, Git transactions, matching, review,
omission audits and package entry points.

Native verification requires a dedicated test library. Verify capture and replay
with native readback, exercise GUI callbacks and resource cleanup, and compare
source fingerprints before and after read-only operations. Use independent GDS
XOR and label comparison as a separate geometry check. It does not verify native
connectivity, groups, constraints, or ROD editability.

Compare Python and C++ results byte-for-byte when changing the optional backend.
Measure validation, matching, Git work, capture and native replay separately;
see [performance methodology](../data/PERFORMANCE.md).

Coverage remains bounded by [supported categories](../eda/virtuoso/COVERAGE.md), external
technology/master definitions and the target Virtuoso version. See the
[CLI assessment](../ui/CLI.md) for unsupported-data limits.
Local execution logs, installation snapshots and design measurements belong in
ignored local storage and do not form part of the public documentation.

## Agent and MCP checks

`tests/test_agent.py` uses real synthetic Git repositories for v1/v2 conflict
explanations, preserved staged resolutions, semantic movement/stretch pairing,
secondary connectivity changes, cached pages, stale-input rejection, batch merge
decisions, export guards and failed-write rollback. It checks that explanation
leaves files/index unchanged and writes leave staging/commits to the caller.
`tests/test_agent_mcp.py` exercises the standalone stdio catalog, Bridge transport
exceptions, request-ID recovery, SKILL string escaping and paged results.

Live checks additionally require the updated worker in the intended CIW. Verify
`layout_capabilities`, submit/retrieve a read-only diff, explain a disposable
Git conflict and compare its index/files before and after. Exercise export and
native-validated merge writes only with synthetic layouts in a dedicated test
library; verify source modification state and native readback separately. If the
configured Bridge/CIW is unavailable, report file-only remote checks separately
from unverified SKILL/native behavior. See the [agent guide](../agent/README.md).

## Headless and legacy Git checks

`tests/test_git_compat.py` covers legacy administrative-path parsing, gitfiles,
revision validation and clone-based merge publication with source hooks.
`tests/test_headless.py` covers persisted/pinned diff pages, corrupt inputs,
display-free subprocess boundaries, missing completion, timeouts and audited
incomplete export. The SSH proxy tests execute the real host CLI and recover a
lost asynchronous submission reply without replaying it.

Run the dependency-free integration driver against both the system executable
and a real Git 1.8.3.1 build; a simulated shim does not establish compatibility:

```sh
python scripts/headless_regression.py
LAYOUTDIFF_GIT=/path/to/git-1.8.3.1 python scripts/headless_regression.py
```

For display-free native verification, use an existing dedicated writable test
library, its configured working directory and a valid drawing layer:

```sh
python scripts/headless_native_regression.py --cwd /projects/test \
  --library TEST_LIB --layer M1 --output /tmp/headless-native-evidence
```

The driver creates unique synthetic views, captures/exports them, uses ordinary
Git commits and a real merge, resolves through the headless CLI with native batch
readback, and verifies that the original synthetic source remains unchanged.
It removes only its created views and retains native job scripts/logs in the
specified new evidence directory. It does not contact a CIW or GUI worker.
Also exercise the CLI `capture` and `restore` batch entry points when changing
argument routing. PDK-specific groups, vias and ROD features require their own
native fixtures; a simple rectangle roundtrip does not validate those features.

## Graphical merge checks

`test_merge.py`, `test_merge_relationships.py`, `test_merge_index.py` and
`test_merge_ui.py` exercise three-way rules, anonymous ambiguity, compounds,
reference remapping, journal corruption/staleness, preview boundaries, omission
consent and bounded navigation. `test_repository_merge.py` uses isolated synthetic
Git repositories for parent ordering, multi-cell validation, ordinary conflicts,
stale publication and hook failures.

`scripts/merge_native_smoke.py` verifies docked forms and native controls.
`scripts/merge_native_regression.py --complex --repository` adds synthetic pins,
ordered groups, an MPP with associated text, preview/accept/edit/undo/resume,
native readback and a real isolated Git merge through worker dispatch. Both
scripts require explicit technology/layer arguments and use disposable libraries.
Neither reads production geometry. Run GDS XOR separately when changing geometry
serialization; graphical merge acceptance itself relies on native readback.

`scripts/merge_benchmark.py` measures analysis, indexing, indexed page/pick queries
and result materialization for 1K/10K/100K synthetic cells with sparse branch edits.
Use `--trace-memory` separately for Python allocation peaks, since tracing adds
substantial timing overhead. These timings exclude native capture/reconstruction,
Git processes and EDA licenses. Retain machine-specific measurements under ignored
evidence storage. Native alternatives use dependency closures; the complete
three-way analysis and Result are still held in Python memory.


## Active Git merges and menu upgrades

`tests/test_active_merge.py` exercises immutable parent reads, preserved staged
resolutions, layout-only staging with ordinary conflicts, v1/v2 input, additions,
deletions, omission consent, stale state, cancellation, and interrupted staging.
`tests/test_gitcommit.py` checks v1/v2 preservation of unrelated staged and unstaged
work and snapshots across ordinary commits. Native regression commands are:

```sh
python scripts/ui_menu_native_smoke.py --profile PROFILE
python scripts/merge_native_regression.py --profile PROFILE --technology TECH --layer LAYER --active
```

The menu smoke upgrades the connected plugin's controls, checks repeated installation
and separate forms, then closes the test forms. The active regression uses synthetic
repositories and native helper cells; it verifies graphical validation and stage-only
completion. Neither test edits a source design layout.
