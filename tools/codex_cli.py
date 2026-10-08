"""Thin entry point for the conPACT-enabled Codex CLI launcher."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.codex_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
