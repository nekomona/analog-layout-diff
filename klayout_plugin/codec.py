"""Compatibility alias for layoutdiff.eda.klayout.codec."""
from importlib import import_module
import sys

implementation = import_module("layoutdiff.eda.klayout.codec")
sys.modules[__name__] = implementation
