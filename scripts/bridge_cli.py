"""Run the installed bridge CLI without the stale Windows launcher."""
from virtuoso_bridge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
