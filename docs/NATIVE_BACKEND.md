# Optional C++ performance backend

This is a separate, dependency-free C++17 project. It was added after the
Python v2 implementation passed its 81-test validation gate. Python is the
golden reference: `layoutdiff/data/core.py`, `data/storage.py`, `data/streaming.py` and
`data/streampatch.py` define semantics, validate storage and verify replay results.

The native executable accelerates sorted-stream comparison and checked patch
application. It treats canonical JSON records as opaque bytes, avoiding numeric
conversion and Unicode/numeric identity drift. It does not read OA, evaluate
PCell code, parse the v2 codec, build category indexes or replace Virtuoso SKILL.

## Build and install

Use the project's virtual environment and a C++17-capable `g++`:

```sh
python native-performance/build.py --output /path/to/venv/bin/layoutdiff-native
python native-performance/verify.py
python -m layoutdiff backend-info
```

`build.py` writes the executable and adjacent `.json` provenance file. Both
are needed by Python dispatch. On Windows use `venv/Scripts/layoutdiff-native.exe`
and a compatible compiler. Only the Linux g++ 11.5 build has been verified live.
`CMakeLists.txt` supports standalone builds; use `build.py` for an integrated
installation with provenance metadata.

`scripts/install_runtime.py` bundles these sources, builds on the Virtuoso host
when `g++` exists, and starts the existing SKILL-owned supervisor/worker.
`--native required` requires the build; `--native off` skips building it.
To force reference execution, set the backend to `python` (skipping a build does
not remove an already installed executable). No independent resident native
daemon is needed; kernels run as short-lived worker subprocesses.

## Selection and correctness

`auto` selects native for at least **50,000 objects** or a canonical input stream
of at least **32 MiB**. Smaller jobs use Python. Set `ALD_BACKEND=auto|python|native`
or use the operation's `--backend` option. `ALD_NATIVE_TOOL` overrides the binary
path. In Virtuoso use **Runtime > Performance backend...**; the choice persists
in the runtime state directory and affects subsequent operations.

Before using a binary, Python checks its SHA-256 and the recorded source SHA-256
against the packaged source pin, verifies the protocol, and runs Python/native
diff and apply self-tests. Verification is cached per binary modification stamp.
Changed native source requires rebuilding and updating `data/native_source.sha256`.
Provenance is a consistency check, not a cryptographic trust signature.

`auto` falls back to Python when the binary is missing, incompatible or fails.
Explicit `native` reports failure. Temporary native output is discarded before
fallback; output is published only after successful completion. Schema and
replay validation remain Python-owned on both paths. Backend status and the
last selection reason are visible in the GUI and `backend-info`.

## Private process protocol

```text
layoutdiff-native --version
  => layoutdiff-native/1 wire/1 diff apply
layoutdiff-native diff BEFORE.wire AFTER.wire OPERATIONS.jsonl
layoutdiff-native apply SOURCE.wire PATCH.wire RESULT.wire
```

Snapshot wire lines are `hex(UTF8 key) TAB canonical JSON record LF`.
Patch wire lines add before/after JSON separated by TAB, with `null` for absence.
Keys must be strictly increasing; input line length is capped at 64 MiB.
The native apply kernel checks add/delete/replace preconditions. It does not
independently validate JSON schema or semantic hashes, so callers should use
the public Python APIs. The wrapper prevents input/output aliases and stages
output atomically. The raw executable's path guard is only lexical.

## Verification

Compare native operation streams and forward/reverse application with Python
using synthetic records, including typed numbers, Unicode, duplicates, automatic
selection, missing-tool fallback and failed publication. Native and Python bytes
must agree before automatic selection. See [performance methodology](BACKEND_SCALE_RESULTS.md).
