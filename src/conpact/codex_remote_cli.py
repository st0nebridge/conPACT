"""
@module conpact.codex_remote_cli
@description The Codex remote-control command. `show` reads the state of this
             machine and changes nothing; every other command is an action the
             user has just typed, which is the whole of its authority (D-019,
             D-021): `start` / `stop` our own app-server, `enable` / `disable`
             remote control on it, `pair` to mint a short-lived code for one
             client, `claimed` to ask whether a code has been taken up, `clients`
             to list what is paired and `revoke` to unpair one. It never enrols
             conPACT as a remote-control client and never touches a thread.
@input      argv
@output     text on stdout (refusals on stderr); exit code 0 when the command
            was done, 1 when it was refused, 2 for a usage error
@dependencies conpact.codex_remote, conpact.home; stdlib: argparse, json, sys
"""
from __future__ import annotations

import argparse
import json
import sys

from . import codex_remote, home

SHOW = "show"

# The app-server we run, started and stopped as a process.
HOST_ACTIONS = ("start", "stop")
# Everything else is a call on it.
RPC_ACTIONS = {"enable": codex_remote.enable, "disable": codex_remote.disable,
               "pair": codex_remote.pairing_code, "remote": codex_remote.remote_status}

NEEDS = {
    codex_remote.NO_CLI: "install the Codex CLI, or open ChatGPT Desktop once so it installs one",
    "host": "start our own app-server:   python tools/codex_remote.py start",
    "remote_control": "turn remote control on:    python tools/codex_remote.py enable",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python tools/codex_remote.py",
        description="Codex's Remote Control on this machine. With no command, shows the state "
                    "and changes nothing.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(SHOW, help="what remote control is doing here (read-only)")
    commands.add_parser("start", help="start our own app-server (loopback, token-protected)")
    commands.add_parser("stop", help="stop it")
    commands.add_parser("enable", help="offer this app-server for remote control")
    commands.add_parser("disable", help="stop offering it")
    commands.add_parser("pair", help="print a short-lived pairing code for one client")
    commands.add_parser("remote", help="what the app-server says about its own remote control")
    claimed = commands.add_parser("claimed", help="has a pairing code been taken up yet?")
    claimed.add_argument("code", metavar="CODE")
    claimed.add_argument("--manual", action="store_true", help="it is a manual pairing code")
    commands.add_parser("clients", help="list the clients paired to this machine")
    unpair = commands.add_parser("revoke", help="unpair one client by its id")
    unpair.add_argument("client_id", metavar="CLIENT_ID")
    return parser


def show_lines(status: dict) -> list[str]:
    """The state of remote control here, as a person reads it."""
    host = status["host"]
    enrolled = ("not enrolled" if not status["enrolled"] else
                f'{status["server_name"]} via {status["remote_host"]}'
                f'{"" if status["enabled"] else "  (switched off)"}')
    offered = status.get("offered")
    if host["ready"]:
        ours = (f'running on 127.0.0.1:{host["port"]} (pid {host["pid"]})'
                + (f' - remote control {offered}' if offered else ""))
    elif host["running"]:
        ours = f'pid {host["pid"]} is alive but not answering on port {host["port"]}'
    else:
        ours = "not running"
    lines = [
        "Codex remote control",
        f'  codex CLI        {status["cli"] or "not found"}',
        f'  our app-server   {ours}',
        f'  enrolled as      {enrolled}',
        f'  desktop app      {"may share its app-server" if status["desktop_shares_daemon"] else "does not share one"}',
        f'                   {status["desktop_detail"]}',
    ]
    if status["ready"]:
        lines.append("  ready            yes - this machine can be driven remotely")
    else:
        lines.append("  ready            no")
        lines.extend(f"    {NEEDS.get(need, need)}" for need in status["needs"])
    return lines


def _report(name: str, outcome: dict, out, err) -> int:
    """One action's result. A refusal is printed as a refusal and exits 1; it is
    never dressed up as a success, and never raised."""
    if not outcome["done"]:
        print(f'{name}: {outcome["message"]}', file=err)
        if outcome["detail"]:
            print(f'  {_text(outcome["detail"])}', file=err)
        return 1
    print(f"{name}: done", file=out)
    if outcome["detail"]:
        print(f'  {_text(outcome["detail"])}', file=out)
    return 0


def _text(detail) -> str:
    return json.dumps(detail, indent=2) if isinstance(detail, (dict, list)) else str(detail)


def main(argv=None, out=None, err=None, environ=None, asker=None, opener=None) -> int:
    home.migrate()
    out, err = out or sys.stdout, err or sys.stderr
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    command = args.command or SHOW
    if command == SHOW:
        state = codex_remote.status(environ, asker, opener=opener)
        print("\n".join(show_lines(state)), file=out)
        return 0
    if command in HOST_ACTIONS:
        return _report(command, getattr(codex_remote, command)(environ), out, err)
    if command in RPC_ACTIONS:
        return _report(command, RPC_ACTIONS[command](environ, opener), out, err)
    if command == "clients":
        return _report(command, codex_remote.clients(environ, opener), out, err)
    if command == "claimed":
        return _report(command, codex_remote.pairing_status(args.code, args.manual,
                                                            environ, opener), out, err)
    return _report(command, codex_remote.revoke(args.client_id, environ, opener), out, err)
