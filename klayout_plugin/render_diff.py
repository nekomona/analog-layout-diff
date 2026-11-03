"""Compatibility alias for layoutdiff.eda.klayout.render_diff."""
from importlib import import_module
import sys

implementation = import_module("layoutdiff.eda.klayout.render_diff")

if __name__ == "__main__":
    implementation.main()
else:
    sys.modules[__name__] = implementation
