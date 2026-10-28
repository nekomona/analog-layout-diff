# Analog layout diff

An experimental layout versioning tool for Cadence Virtuoso. It stores canonical
cellview snapshots in Git, compares revisions semantically, and reconstructs a
revision in a fresh cellview. The optional standalone operation-chain CLI supports
replay from an empty state. File-only operations do not require Cadence; native
capture and reconstruction use the installed `virtuoso_bridge` package.

Start with the [documentation index](docs/README.md),
[program structure](docs/architecture/PROGRAM_STRUCTURE.md),
[data model](docs/architecture/LAYOUT_DATA_MODEL.md), and
[processing pipeline](docs/architecture/PROCESSING_PIPELINE.md).

## Install

Use `uv` and a virtual environment:

```sh
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[verify]"
```

On Linux use `.venv/bin/python`. Native commands also require an installed
Virtuoso Bridge package and an active connection to the intended CIW. See the
[GUI guide](docs/VIRTUOSO_GUI.md) for deployment. The pure diff/history package
has no runtime dependencies; stream-layout operations additionally use KLayout.

## Snapshot and history CLI

Run these commands in the activated environment. Names below are placeholders;
select your own source and a dedicated writable test library.

```sh
python -m layoutdiff capture MY_LIB MY_CELL before.json
python -m layoutdiff coverage before.json
python -m layoutdiff diff before.json after.json change.json
python -m layoutdiff apply before.json change.json replayed.json
python -m layoutdiff init my-history
python -m layoutdiff record my-history MY_LIB MY_CELL -m "Initial layout"
python -m layoutdiff log my-history
python -m layoutdiff replay my-history latest.json
python -m layoutdiff restore latest.json reconstructed_cell --library TEST_LIB --allow-library TEST_LIB
```

`record` rejects unsupported native content. `capture` can retain diagnostics in
v1; strict v2 capture requires fully supported content. Reconstruction refuses an
existing destination. The default writable library is `LAYOUT_DIFF_TEST`; create
and attach your own test library before native use, or supply `--allow-library`.
See [formats](docs/FORMAT_V2.md) and [CLI preservation limits](docs/verification/CLI_AND_PRESERVATION.md).

## Git and native GUI

The toolbar provides **Save & Commit**, **History**, and **Runtime**. Save & Commit
saves the edited layout, previews changes, and commits after confirmation.
Cancel leaves the layout saved. Git is the commit authority; snapshots live at
`layouts/<library>/<cell>/<view>.layout/` as deterministic JSONL and a manifest.
History supports cell and Git revision selection, category counts, paged changes,
full diffs, and temporary read-only native review.

Review distinguishes Modified, Modified net, Moved / stretched, New, Deleted and
Untouched content, with group boundaries and configurable styles. Anonymous
geometry correspondence is inferred conservatively; exact patches remain
content-based. The guarded Restore checkpoint workflow verifies a reconstruction
before asking to replace a saved working layout. See the
[Git workflow](docs/GIT.md) and [GUI guide](docs/VIRTUOSO_GUI.md).

## Supported content and limits

The codec covers integer-DBU geometry, labels, typed properties, scalar
connectivity, ordinary/PCell instances, simple mosaics, standard vias, ordinary
figure groups, logical groups, supported placement annotations, and supported
ROD multipart-path recipes and generated figures. See the
[coverage table](docs/CATEGORIES.md) for attribute-level limits.

Technology, referenced masters and PCell programs remain external dependencies.
Hierarchy fingerprints detect drift without archiving child layouts. Routes,
markers and Steiners are excluded; their independent member geometry remains
tracked. Unknown native content blocks strict reconstruction. The GUI can commit
a supported-only checkpoint after two explicit confirmations and retains an
omission audit. That audit does not guarantee future native restoration.

This versioned OA subset should not be the sole archive of a production database.
GDS XOR checks exported geometry and labels, not native connectivity or editing
semantics. The optional [C++ backend](docs/NATIVE_BACKEND.md) accelerates validated
stream merging and patch application. The separate [KLayout adapter](docs/KLAYOUT.md)
handles static GDS/OASIS data and snapshot images.

## Development

```sh
python -m pytest tests klayout_plugin/tests -q --basetemp=.test-tmp-run
python scripts/check_docs.py
python scripts/check_publication.py
```

See [development](docs/DEVELOPMENT.md) and [verification](docs/VERIFICATION.md).
Generated evidence and local agent instructions are ignored. Public examples and
fixtures use synthetic data; keep site configuration and captured designs local.
