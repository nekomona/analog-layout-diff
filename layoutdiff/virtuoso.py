"""Compatibility exports; native implementation lives in layoutdiff.eda.virtuoso."""
from layoutdiff.eda.virtuoso import VirtuosoAdapter, checked, coverage, render, normalize

__all__ = ["VirtuosoAdapter", "checked", "coverage", "render", "normalize"]
