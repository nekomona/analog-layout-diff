"""Compatibility alias for layoutdiff.eda.klayout.review."""
from importlib import import_module
import sys

implementation = import_module("layoutdiff.eda.klayout.review")
sys.modules[__name__] = implementation
