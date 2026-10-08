"""Thin entry point -> conpact.mcp_server. Register it with python.exe directly
(not through a .cmd wrapper): the server binds to the session of its parent process."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
