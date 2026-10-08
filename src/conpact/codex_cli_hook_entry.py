"""
@module conpact.codex_cli_hook_entry
@description Import the Stop hook from this installation even outside a checkout.
@input Stop-hook JSON on stdin
@output The hook's exit status
@dependencies conpact.codex_cli_hook; stdlib: pathlib, sys
"""
import pathlib
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from conpact.codex_cli_hook import main
    raise SystemExit(main())
