# Analog Layout Diff

Git snapshots and semantic review for analog layouts in Cadence Virtuoso.
Capture layout state, compare geometry, connectivity and properties, then
reconstruct a recorded revision in a fresh cellview. Native operations use
[virtuoso-bridge-lite](https://github.com/Arcadia-1/virtuoso-bridge-lite);
file-only comparison and replay run independently of Cadence.

[Quick start](#quick-start) · [Documentation](docs/README.md) ·
[Architecture](docs/architecture/PROGRAM_STRUCTURE.md) ·
[Contributing](CONTRIBUTING.md)

## What it does

| Capability | Workflow |
| --- | --- |
| Capture and version | Canonical layout records stored as deterministic, reviewable JSONL in Git |
| Compare and review | Geometry, connectivity and property changes, conservative movement matching, category counts and native highlights |
| Reconstruct and verify | Fresh-cell reconstruction with native readback and hierarchy-drift warnings |
| Work from files | Exact diff/apply, integrity-checked replay and the KLayout GDS/OASIS adapter |

The Virtuoso toolbar provides **Save & Commit**, **History** and **Runtime**.
Save & Commit saves the edited view, previews changes and commits after
confirmation. Review opens a temporary read-only reconstruction. See the
[UI guide](docs/ui/README.md) for review styles and checkpoint restore.

## Quick start

From a checkout, use `uv` and a virtual environment:

```sh
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[verify]"
```

On Linux use `.venv/bin/python`. Activate the environment before running commands.
With two existing JSON snapshots, compare and apply changes offline:

```sh
python -m layoutdiff diff before.json after.json change.json
python -m layoutdiff apply before.json change.json replayed.json
```

For native capture, install the `virtuoso-bridge` distribution in the same
environment and establish its connection to the intended CIW. Follow
[Bridge setup](docs/runtime/BRIDGE.md), then capture or reconstruct:

```sh
python -m layoutdiff capture MY_LIB MY_CELL snapshot.json
python -m layoutdiff restore snapshot.json reconstructed_cell --library TEST_LIB --allow-library TEST_LIB
```

Create a dedicated writable test library with compatible technology first.
Restore refuses an existing destination. Installing Layout Diff alone does not
install Bridge. The supplied GUI installer also requires the source arrangement
described in [runtime deployment](docs/runtime/README.md#deployment).

## Scope

The native codec supports a defined OA/ROD subset. Referenced masters, technology
and PCell programs remain external; hierarchy fingerprints do not archive child
layouts. Unknown content blocks strict reconstruction. Supported-only GUI commits
require explicit loss confirmation and retain an omission audit. Use a separate
database archive for production recovery.

See [native coverage](docs/eda/virtuoso/COVERAGE.md),
[preservation limits](docs/ui/CLI.md), and the
[KLayout frontend](docs/eda/klayout/README.md). GDS comparison verifies exported
geometry and labels, rather than the full native object graph.

## Contribute

Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, change boundaries, validation
and pull requests. Use commit subjects such as
`fix(comparison): preserve ambiguous via matches as additions and deletions`;
the [commit convention](docs/development/COMMITS.md) defines types and scopes.

```sh
python -m pytest tests -q --basetemp=.test-tmp-run
python scripts/check_docs.py
python scripts/check_publication.py
```

Public examples and fixtures use synthetic data. Keep agent instructions,
site configuration and captured designs in ignored local storage.
