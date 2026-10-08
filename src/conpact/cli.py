"""
@module conpact.cli
@description Command-line surface, reached through tools/bridge_send.py - which a
             Bash allow rule lets an agent run WITHOUT a permission prompt. So it
             can do only two state-changing things, and only to the session it is
             running in (--self, resolved from the runtime): send a constructed
             /compact now (--compact), or record a request for the Stop hook to
             send it at turn end (--request) - optionally only if the context is
             by then at least --min-context-tokens. There is no free-text sending.
             Explicit selectors exist only to inspect another session with
             --dry-run. --token-status reports how fresh the stored login token
             is, without showing it.
@input      argv flags (target, action, focus, dry-run)
@output     human-readable status on stdout, errors on stderr; exit code
            (0 ok, 1 failed, 2 usage error)
@dependencies conpact.bridge_client, conpact.compaction, conpact.home,
              conpact.session_registry, conpact.token_store;
              stdlib: argparse, sys
"""
from __future__ import annotations

import argparse
import sys

from . import bridge_client, compaction, home, session_registry, token_store

EXPLICIT_SELECTORS = ("name", "pid", "host_session_id", "session_id")
_SUFFIXES = {"k": 1_000, "m": 1_000_000}


def token_count(text: str) -> int:
    """Parse a token count: 150000, 150k or 1.5m."""
    raw = text.strip().lower()
    scale = _SUFFIXES.get(raw[-1:], 1)
    number = raw[:-1] if scale != 1 else raw
    try:
        value = float(number) * scale
        whole = int(value)
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError(f"not a token count: {text!r} (use e.g. 150000, 150k or 1.5m)")
    if value != whole:
        raise argparse.ArgumentTypeError(f"not a whole number of tokens: {text!r}")
    try:
        return compaction.validate_min_context_tokens(whole)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Compact the current Claude Code session now, or record a request "
                    "for the Stop hook to compact it at the end of the turn.")
    target = ap.add_argument_group("target")
    target.add_argument("--self", action="store_true",
                        help="the session this command runs in (resolved from the runtime)")
    target.add_argument("--name", help="another session, by name (--dry-run only)")
    target.add_argument("--pid", type=int, help="another session, by process id (--dry-run only)")
    target.add_argument("--host-session-id", dest="host_session_id",
                        help="another session, by local_ id (--dry-run only)")
    target.add_argument("--session-id", dest="session_id",
                        help="another session, by session id (--dry-run only)")
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--compact", action="store_true", help="send /compact now")
    action.add_argument("--request", action="store_true",
                        help="record a request; the Stop hook sends /compact at turn end")
    action.add_argument("--token-status", action="store_true",
                        help="report whether the stored login token is fresh (never prints it)")
    ap.add_argument("--focus", default="",
                    help=f"optional focus hint for /compact (one line, max {compaction.MAX_FOCUS_CHARS} chars)")
    ap.add_argument("--min-context-tokens", type=token_count, default=None, metavar="N",
                    help="with --request: fire only if the context is at least N tokens at turn end "
                         "(e.g. 150000, 150k, 1.5m)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the target and show what would happen; send and record nothing")
    return ap


def _check_target(ap: argparse.ArgumentParser, args) -> None:
    if args.min_context_tokens is not None and not args.request:
        ap.error("--min-context-tokens only applies to --request")
    explicit = [s for s in EXPLICIT_SELECTORS if getattr(args, s) is not None]
    if args.self and explicit:
        ap.error("--self cannot be combined with an explicit selector")
    if not args.self and not explicit:
        ap.error("choose a target: --self (or an explicit selector with --dry-run)")
    if explicit and not args.dry_run:
        ap.error("explicit selectors are inspection-only: add --dry-run, or use --self")


def _fail(message: str) -> int:
    sys.stderr.write(f"error    : {message}\n")
    return 1


def _resolve(args) -> dict:
    if args.self:
        return session_registry.resolve_self()
    return session_registry.resolve_target(
        name=args.name,
        pid=args.pid,
        host_session_id=args.host_session_id,
        session_id=args.session_id,
    )


def _token_status() -> int:
    try:
        status = token_store.token_status()
    except token_store.TokenError as exc:
        return _fail(f"token: {exc}")
    print(f"token    : {'fresh' if status['fresh'] else 'EXPIRED - a send would refresh it first'}")
    expires = status["expires_in_seconds"]
    if expires is None:
        print("expiry   : not recorded")
    elif expires >= 0:
        print(f"expiry   : in {expires}s")
    else:
        print(f"expiry   : {-expires}s ago")
    print(f"refresh  : {'possible' if status['can_refresh'] else 'NOT possible (no refresh token stored)'}")
    return 0


def _request(record: dict, args) -> int:
    session_id = record.get("sessionId")
    if not compaction.is_valid_session_id(session_id):
        return _fail(f"target has no usable sessionId ({session_id!r}); nothing recorded")
    if args.dry_run:
        print("dry-run  : request not recorded")
        return 0
    path = compaction.request_compaction(session_id, focus=args.focus,
                                         min_context_tokens=args.min_context_tokens)
    print(f"request  : recorded at {path}")
    if args.min_context_tokens is not None:
        print(f"condition: fires only if the context is at least {args.min_context_tokens} tokens at turn end")
    return 0


def _compact(record: dict, args) -> int:
    try:
        result = compaction.compact_record(record, focus=args.focus, dry_run=args.dry_run)
    except (token_store.TokenError, OSError, ValueError, KeyError) as exc:
        return _fail(f"send: {type(exc).__name__}: {exc}")
    print(f"text     : {result['text']!r}")
    if not result["sent"]:
        print("dry-run  : nothing sent")
        return 0
    print(f"token    : {'refreshed first' if result['token_refreshed'] else 'used as stored'}")
    print(f"HTTP {result['http_status']}: {result['response'][:600]}")
    return 0 if bridge_client.is_success(result["http_status"]) else 1


def main(argv=None) -> int:
    home.migrate()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.token_status:
        return _token_status()
    _check_target(ap, args)
    try:
        record = _resolve(args)
    except session_registry.TargetError as exc:
        return _fail(f"target: {exc}")

    print(f"target   : {record.get('name')!r} pid={record.get('pid')} status={record.get('status')}")
    print(f"sessionId: {record.get('sessionId')}")
    print(f"host     : {record.get('hostSessionId')}")
    print(f"bridge   : {record.get('bridgeSessionId')}")

    if args.request:
        return _request(record, args)
    return _compact(record, args)
