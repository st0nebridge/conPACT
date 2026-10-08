"""Thin CLI shim -> conpact.cli. Kept at this path for the existing Bash allow rule."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
