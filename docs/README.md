# Layout Diff documentation

Current release: **0.18.0**, as declared in [pyproject.toml](../pyproject.toml).
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
| `eda` | Tool-specific interfaces: Virtuoso OA/ROD and KLayout static layouts | [EDA adapters](eda/README.md) |
| `git` | Immutable snapshot history, commit transactions and semantic Git tools | [Git guide](git/README.md) |
| `ui` | CLI, native toolbar, history browser, review and checkpoint restore | [UI guide](ui/README.md) |
| `runtime` | Deployment, process identity, worker ownership and resource cleanup | [Runtime guide](runtime/README.md) |

## Supporting components

| Component | Guide |
| --- | --- |
| External Virtuoso Bridge dependency and connections | [Bridge integration](runtime/BRIDGE.md) |
| Optional C++ kernel | [Native performance backend](native-performance/README.md) |
| EDA subpackages | [Virtuoso](eda/virtuoso/README.md), [KLayout](eda/klayout/README.md) |
| Cross-package GUI requests | [Interaction sequences](ui/INTERACTION_SEQUENCES.md) |
| Setup and documentation maintenance | [Development](development/README.md) |
| Contribution workflow and pull requests | [Contributing](../CONTRIBUTING.md) |
| Commit and pull request titles | [Commit convention](development/COMMITS.md) |
| Test responsibilities and limits | [Verification](development/VERIFICATION.md) |

```text
docs/
  architecture/          Package/process map and cross-package pipeline
  data/                  Model, logical/storage formats and performance
  comparison/            Matching, classification, groups and paging
  eda/
    virtuoso/            Capture coverage and native OA/ROD behavior
    klayout/             Static GDS/OASIS adapter, review and rendering
  git/                   Snapshot history, commit and textconv
  ui/                    CLI, native workflows and interaction sequences
  runtime/               Deployment, ownership and cleanup
  native-performance/    Optional C++ kernel
  development/           Contribution, verification and publication checks
```

Local runbooks, agent instructions, installation reports and captured design
data belong in ignored local storage. Public examples and fixtures use
synthetic data. See [documentation maintenance](development/README.md#documentation-maintenance).
