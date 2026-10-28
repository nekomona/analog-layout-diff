# Performance methodology

The v2 pipeline uses sorted JSONL, bounded expansion caches, SQLite spooling and
streaming merge/patch operations. The optional C++ kernel accelerates opaque-byte
merge and apply; Python remains responsible for validation and semantics.

Measure these workloads separately:

- Encoding, validation and serialization, including peak worker memory.
- Exact merge/apply kernel throughput and Python/C++ byte parity.
- Category construction and inferred shape/via matching.
- Git preview/publication and history loading.
- Native capture, reconstruction/readback and GUI review resources.

Use independently generated records and state dataset size, edit fraction,
record families, cache state, backend, platform and memory scope. A worker-only
memory result excludes Virtuoso, Git and optional child processes. Do not infer
whole-workflow speed from a merge-kernel measurement.

Scratch snapshots, indexes, wire streams and patches can coexist. Large records,
hierarchy fingerprints and materialized native review have separate resource
costs. No fixed benchmark time is a guarantee for an arbitrary layout.
See [backend selection](NATIVE_BACKEND.md) and the
[pipeline](architecture/PROCESSING_PIPELINE.md#scaling-and-backend-selection).
