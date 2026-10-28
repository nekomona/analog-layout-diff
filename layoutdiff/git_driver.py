"""Compatibility entry point for existing repository-local textconv commands."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layoutdiff.git.tools import main

if __name__ == "__main__":
    main()
