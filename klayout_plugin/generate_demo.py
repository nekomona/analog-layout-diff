"""Compatibility alias for layoutdiff.eda.klayout.generate_demo."""
from importlib import import_module
import sys

implementation = import_module("layoutdiff.eda.klayout.generate_demo")

if __name__ == "__main__":
    implementation.main()
else:
    sys.modules[__name__] = implementation
