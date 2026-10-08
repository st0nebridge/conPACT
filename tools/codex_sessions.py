"""
@module tools.codex_sessions
@description Read-only report of what conPACT can see on each desktop app:
             every session, how full its context is, and - the part worth
             printing - why it could not be compacted right now. It changes
             nothing, starts nothing and sends nothing, which is what lets it
             sit beside the deliberately narrow bridge_send.py (D-20260919-008)
             without widening anything: this is the diagnostic half of
             D-20260920-019, extended to ChatGPT Desktop.
@input      argv flags (--platform, --all, --limit, --quiet, --remote)
@output     one line per session on stdout; exit code 0, or 2 for a usage error
@dependencies conpact.codex_remote, conpact.codex_remote_cli,
              conpact.platforms; stdlib: argparse, pathlib, sys
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from conpact import codex_remote, codex_remote_cli, platforms    # noqa: E402


def parse(argv=None):
    parser = argparse.ArgumentParser(
        description="What conPACT can see on Claude Code and ChatGPT Desktop (read-only).")
    parser.add_argument("--platform", choices=platforms.PLATFORMS,
                        help="only this one (default: both)")
    parser.add_argument("--all", action="store_true",
                        help="include spin-offs and archived sessions")
    parser.add_argument("--limit", type=int, default=20,
                        help="how many Codex threads to read (default: 20)")
    parser.add_argument("--quiet", action="store_true", help="no measuring, names only")
    parser.add_argument("--remote", action="store_true",
                        help="also show Codex's remote-control state for this machine")
    return parser.parse_args(argv)


def line(session) -> str:
    fill = platforms.fill(session)
    reason = platforms.blocked(session)
    tokens = session["context_tokens"]
    return (f'{session["platform"]:<7} {str(session["id"])[:8]:<9} '
            f'{"" if tokens is None else f"{tokens:>8,}":>9} '
            f'{"" if fill is None else f"{fill:>6.0%}":>7} '
            f'{session["state"] or "":<8} {reason or "ready":<12} {session["title"][:44]!r}')


def main(argv=None) -> int:
    args = parse(argv)
    here = platforms.installed()
    if not here:
        print("Neither Claude Code nor ChatGPT Desktop has any state on this machine.")
        return 0
    print(f"installed: {', '.join(here)}")
    if args.remote and platforms.CODEX in here:
        print()
        print("\n".join(codex_remote_cli.show_lines(codex_remote.status())))
        print()
    print(f'{"app":<7} {"id":<9} {"context":>9} {"full":>7} {"state":<8} {"status":<12} title')
    print("-" * 100)
    shown = 0
    for session in platforms.sessions(args.platform, limit=args.limit, measure=not args.quiet):
        if not args.all and platforms.blocked(session) in (platforms.SPIN_OFF, platforms.ARCHIVED):
            continue
        print(line(session))
        shown += 1
    if not shown:
        print("(nothing but spin-offs and archived sessions; pass --all to see them)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
