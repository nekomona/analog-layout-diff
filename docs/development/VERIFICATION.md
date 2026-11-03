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
