"""Thin entry point -> the Codex sidecar shim's install/status/uninstall.

The shim lets conPACT compact a thread ChatGPT Desktop is *actively* using,
by standing in the desktop's own app-server stdio path (the desktop resolves it
through CODEX_CLI_PATH). `install` makes the shim itself, so there is no build
step to remember; a ChatGPT restart is needed for the desktop to pick it up.

    python tools/codex_sidecar.py status       what is built / installed / running
    python tools/codex_sidecar.py install      point the desktop's CODEX_CLI_PATH at the shim
    python tools/codex_sidecar.py uninstall    undo it (leaves the machine as it was)
    python tools/codex_sidecar.py window       the same two actions, in a window

For one click, run `install-sidecar.cmd` (Windows) or `install-sidecar.sh`
(macOS, Linux) in this folder - both just open that window.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact import codex_sidecar_install as install  # noqa: E402


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "status"

    if command == "status":
        s = install.status()
        print("Codex sidecar shim")
        print(f"  platform        {s['platform']}")
        print(f"  built           {'yes' if s['built'] else 'no'}   {s['exe']}")
        print(f"  marker written  {'yes' if s['marker_written'] else 'no'}")
        env = s["env_value"]
        print(f"  CODEX_CLI_PATH  {env if env else '(unset)'}")
        if s["platform"] == "darwin":
            print(f"  persistent      {s['env_persistent_value'] or '(unset)'}")
            print(f"  caller domain   {s['env_caller_value'] or '(unset)'}")
            print(f"  GUI domain      {s['env_gui_value'] or '(unset)'}")
            print(f"  env mismatch    {'yes' if s['env_discrepancy'] else 'no'}")
        print(f"  points at shim  {'yes' if s['env_points_at_shim'] else 'no'}")
        print(f"  shim running    {'yes' if s['sidecar_running'] else 'no'}")
        print(f"  installed       {'yes' if s['installed'] else 'no'}")
        print(f"  codex marker    {s['codex_pinned'] or '(not recorded)'}")
        print(f"  codex newest    {s['codex_newest'] or '(not found)'}")
        print(f"  marker newest   {'yes' if s['codex_is_newest'] else 'no'}")
        print(f"  codex selected  {s.get('codex_selected') or '(not found)'}")
        print(f"  app bundle      {s.get('codex_bundle') or '(not found)'}")
        print(f"  app version     {s.get('codex_bundle_version') or '(not found)'}")
        print(f"  selection       {s.get('codex_selection', 'unavailable')} (next launch)")
        if s.get("derived_override_paths"):
            print("  derived config  " + ", ".join(s["derived_override_paths"]))
        if not s["installed"]:
            print("\n  install it:      python tools/codex_sidecar.py install")
            print("  or in a window:  python tools/codex_sidecar.py window")
        return 0

    if command == "window":
        from conpact import codex_sidecar_window
        codex_sidecar_window.run()
        return 0

    if command in ("install", "uninstall"):
        outcome = getattr(install, command)()
        print(outcome["message"] or ("done" if outcome["done"] else "failed"))
        if outcome.get("detail"):
            print(f"  {outcome['detail']}")
        return 0 if outcome["done"] else 1

    print(f"unknown command {command!r}; expected status, install, uninstall or window",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
