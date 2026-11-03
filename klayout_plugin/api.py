"""Compatibility alias for layoutdiff.eda.klayout.api."""
from importlib import import_module
import sys

implementation = import_module("layoutdiff.eda.klayout.api")
sys.modules[__name__] = implementation
