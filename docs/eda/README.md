# EDA adapters

`layoutdiff.eda` owns the tool-specific interfaces. Importing the package does
not load EDA bindings, open a design, or launch a background process.

| Subpackage | Responsibility | Guide |
| --- | --- | --- |
| `layoutdiff.eda.virtuoso` | Native OA/ROD capture, scope checks, reconstruction, hierarchy hints and readback | [Virtuoso](virtuoso/README.md) |
| `layoutdiff.eda.klayout` | Static GDS/OASIS capture, reconstruction, review, macro UI and snapshot images | [KLayout](klayout/README.md) |

Both use `layoutdiff.data` for canonical records, storage and exact operations.
Their native content contracts remain distinct: the KLayout static format does
not encode Virtuoso connectivity, PCell programs or ROD semantics. This package
organization does not introduce an automatic cross-tool snapshot converter.

Install `analog-layout-diff[klayout]` for the optional standalone KLayout Python
bindings. Virtuoso needs the separately installed Bridge and a live native
connection; see [Bridge setup](../runtime/BRIDGE.md). Pure data/Git operations
and importing `layoutdiff.eda` require neither dependency.

## Entry points and compatibility

```python
from layoutdiff.eda.virtuoso import VirtuosoAdapter
from layoutdiff.eda.klayout.codec import read_layout, write_layout
```

```sh
python -m layoutdiff capture MY_LIB MY_CELL snapshot.json
python -m layoutdiff.eda.klayout capture source.oas snapshot.json --top TOP
python -m layoutdiff.eda.klayout.render_diff before.json after.json diff.png
```

`layoutdiff.virtuoso` retains its package-level adapter/helper exports as a small
compatibility module. Its old implementation submodule imports, such as
`layoutdiff.virtuoso.adapter`, move to `layoutdiff.eda.virtuoso.adapter`.
The `klayout_plugin` namespace and its documented module commands are forwarding
wrappers; new code and macros use `layoutdiff.eda.klayout`.

Native SKILL resources live in `layoutdiff/eda/virtuoso/skill/`. The KLayout
macro and style example live in `layoutdiff/eda/klayout/`. They are included in
the wheel. The existing Virtuoso GUI entry points remain in `ui/skill/`.
