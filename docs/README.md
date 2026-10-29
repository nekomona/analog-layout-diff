# Layout Diff documentation

Current release: **0.17.1**, as declared in [pyproject.toml](../pyproject.toml).
These guides describe the current implementation. Schema and protocol numbers
identify supported data contracts.

Start with [program structure](architecture/PROGRAM_STRUCTURE.md) for package and
process boundaries, then the [processing pipeline](architecture/PROCESSING_PIPELINE.md)
for the complete capture-to-review flow.

## Functional packages

| Package | Responsibility | Start here |
| --- | --- | --- |
| `data` | Canonical state, storage, exact operations, standalone chains and acceleration | [Data guide](data/README.md) |
| `comparison` | Geometric correspondence, change classification, category indexes and group bounds | [Comparison guide](comparison/README.md) |
| `virtuoso` | Native capture/replay, coverage, OA/ROD relationships and readback | [Virtuoso guide](virtuoso/README.md) |
| `git` | Immutable snapshot history, commit transactions and semantic Git tools | [Git guide](git/README.md) |
| `ui` | CLI, native toolbar, history browser, review and checkpoint restore | [UI guide](ui/README.md) |
| `runtime` | Deployment, process identity, worker ownership and resource cleanup | [Runtime guide](runtime/README.md) |

## Supporting components

| Component | Guide |
| --- | --- |
| External Virtuoso Bridge dependency and connections | [Bridge integration](runtime/BRIDGE.md) |
| Optional C++ kernel | [Native performance backend](native-performance/README.md) |
| Separate static-layout frontend | [KLayout tools](klayout_plugin/README.md) |
| Cross-package GUI requests | [Interaction sequences](ui/INTERACTION_SEQUENCES.md) |
| Setup, contribution and documentation | [Development](development/README.md) |
| Test responsibilities and limits | [Verification](development/VERIFICATION.md) |

```text
docs/
  architecture/          Package/process map and cross-package pipeline
  data/                  Model, logical/storage formats and performance
  comparison/            Matching, classification, groups and paging
  virtuoso/              Capture coverage and native object behavior
  git/                   Snapshot history, commit and textconv
  ui/                    CLI, native workflows and interaction sequences
  runtime/               Deployment, ownership and cleanup
  native-performance/    Optional C++ kernel
  klayout_plugin/        Separate GDS/OASIS frontend
  development/           Contribution, verification and publication checks
```

Local runbooks, agent instructions, installation reports and captured design
data belong in ignored local storage. Public examples and fixtures use
synthetic data. See [documentation maintenance](development/README.md#documentation-maintenance).
