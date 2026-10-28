# Data package

`layoutdiff.data` defines canonical layout state and exact reversible operations.
It runs without Virtuoso, Git or a GUI. Python defines semantics; the optional
C++ backend processes validated canonical bytes.

| Topic | Reference |
| --- | --- |
| Representations, identities and relationships | [Data model](MODEL.md) |
| Expanded records and standalone operation chains | [Logical format](LOGICAL_FORMAT.md) |
| Compact snapshots, integrity and patch bundles | [Storage format](STORAGE_FORMAT.md) |
| Measurement scope and resource costs | [Performance methodology](PERFORMANCE.md) |
| Optional kernel build and dispatch | [C++ backend](../native-performance/README.md) |

## Responsibilities

| Source | Responsibility |
| --- | --- |
| [core.py](../../layoutdiff/data/core.py) | Canonical values, keys, hashes, reference diff/apply |
| [storage.py](../../layoutdiff/data/storage.py) | Streaming snapshot encoding, expansion and validation |
| [streaming.py](../../layoutdiff/data/streaming.py) | Exact sorted-stream merge and application |
| [streampatch.py](../../layoutdiff/data/streampatch.py) | Checked patch bundles and staged publication |
| [history.py](../../layoutdiff/data/history.py) | Standalone single-parent chains and atomic JSON |
| [backends.py](../../layoutdiff/data/backends.py) | Snapshot-reader integration boundary |
| [acceleration.py](../../layoutdiff/data/acceleration.py) | Backend selection, provenance and parity checks |

Canonical equality distinguishes types, absent fields, explicit defaults and
duplicate multiplicity. Patch application verifies its source, preconditions and
result before publication. Inferred visual correspondence belongs to
[comparison](../comparison/README.md) and never changes these identities.
Git commit authority belongs to [git](../git/README.md); standalone operation
chains are an independent explicit CLI feature.
