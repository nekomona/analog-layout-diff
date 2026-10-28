"""Virtuoso interface; the adapter service remains available at package level."""
from .adapter import VirtuosoAdapter, checked, coverage, render, normalize

__all__ = ["VirtuosoAdapter", "checked", "coverage", "render", "normalize"]
