"""Thin entry point -> conpact.codex_remote_cli: Codex's Remote Control here.

    python tools/codex_remote.py                 what remote control is doing (read-only)
    python tools/codex_remote.py start           start the shared app-server daemon
    python tools/codex_remote.py stop            stop it
    python tools/codex_remote.py enable          turn remote control on for this machine
    python tools/codex_remote.py disable         turn it off
    python tools/codex_remote.py pair            print a short-lived pairing code
    python tools/codex_remote.py clients         list the paired clients
    python tools/codex_remote.py revoke ID       unpair one

Only `show` reads; every other command is the action you just typed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.codex_remote_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
