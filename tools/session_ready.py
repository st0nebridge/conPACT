"""Thin entry point -> conpact.session_ready: what each live session still needs.

    python tools/session_ready.py

Prints one row per live Claude Code session: whether Remote Control is on (its
record has a bridgeSessionId), whether this checkout's MCP server is running
under it, and when the Stop hook was last seen for it - then what to do about
anything missing. It only reads; it changes nothing. Exit code 1 if any session
needs something.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.session_ready import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
