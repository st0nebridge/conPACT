"""
@module conpact.settings_cli
@description The settings command. `show` lists every setting with its value,
             what it does and the values it accepts (a changed value also shows
             its default); `set KEY VALUE [KEY VALUE ...]` changes settings, all
             or none; `reset [KEY ...]` puts some or all back to their defaults.
             With no command, or `window`, it opens the settings window.
@input      argv
@output     text on stdout (errors on stderr); exit code 0, or 2 for a refused
            or malformed command; settings changed on disk
@dependencies conpact.home, conpact.settings, conpact.settings_window (lazily); stdlib: argparse, sys
"""
from __future__ import annotations

import argparse
import sys

from . import home, settings


def row(key: str, value) -> str:
    """One setting's line: its key and value, and its default when the value differs."""
    default = settings.get(key).default
    changed = "" if value == default else f"   (default {settings.describe(key, default)})"
    return f"  {key:<28} {settings.describe(key, value)}{changed}"


def show_lines(values: dict) -> list[str]:
    lines = [f"conPACT settings: {settings.settings_path()}", ""]
    for s in settings.SETTINGS:
        lines.append(row(s.key, values[s.key]))
        lines.append(f"      {s.help} Allowed: {settings.allowed(s.key)}.")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python tools/settings.py",
        description="Show or change conPACT's settings. With no command, opens the settings window.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("show", help="list every setting, its value and what it accepts")
    change = commands.add_parser("set", help="change settings: KEY VALUE [KEY VALUE ...] (all or none)")
    change.add_argument("pairs", nargs="*", metavar="KEY VALUE")
    back = commands.add_parser("reset", help="put the named settings (or all) back to their defaults")
    back.add_argument("keys", nargs="*", metavar="KEY")
    commands.add_parser("window", help="open the settings window")
    return parser


def _set(pairs: list, out) -> None:
    if not pairs or len(pairs) % 2:
        raise ValueError("set needs KEY VALUE pairs, e.g. set min_context_tokens 150k")
    changes = {key: settings.parse(key, text) for key, text in zip(pairs[::2], pairs[1::2])}
    values = settings.save(changes)
    print(f"Saved. {settings.APPLIES}", file=out)
    for key in changes:
        print(row(key, values[key]), file=out)


def _reset(keys: list, out) -> None:
    values = settings.reset(keys or None)
    print(f"Reset {', '.join(keys)}." if keys else "Reset every setting.", file=out)
    print("\n".join(show_lines(values)), file=out)


def main(argv=None, out=None, err=None, opener=None) -> int:
    home.migrate()
    out, err = out or sys.stdout, err or sys.stderr
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command in (None, "window"):
        if opener is None:
            from . import settings_window
            opener = settings_window.run
        opener()
        return 0
    try:
        if args.command == "show":
            print("\n".join(show_lines(settings.load())), file=out)
        elif args.command == "set":
            _set(args.pairs, out)
        else:
            _reset(args.keys, out)
    except ValueError as exc:
        print(f"error: {exc}", file=err)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
