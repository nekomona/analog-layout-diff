"""Compatibility alias for layoutdiff.eda.klayout.gui."""
from importlib import import_module
import sys

implementation = import_module("layoutdiff.eda.klayout.gui")
sys.modules[__name__] = implementation
