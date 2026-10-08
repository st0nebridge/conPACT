"""
@module conpact.session_registry
@description Resolve live Claude Code session records and bind a compaction
             target. The current ("self") session is bound only from the
             runtime's own signals - per-process session records cross-checked
             against hook/Bash/MCP environment variables and process ids - never
             from a model-supplied identifier. Also the single definition of a
             plain (path-safe) session id.
@input      a target selector (name / pid / hostSessionId / sessionId) or the
            ambient runtime environment for self-resolution
@output     a single session record dict that carries a usable bridgeSessionId
            (resolve_self_unbound returns the same record without that last
            requirement, for telling the user Remote Control is off)
@dependencies stdlib: json, os, pathlib, re
"""
from __future__ import annotations

import json
import os
import pathlib
import re

CLAUDE_DIR = pathlib.Path(os.path.expanduser("~")) / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"

# Claude Code session ids are UUIDs. Anything that is not a plain id must never
# become part of a file path or a glob pattern.
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def is_valid_session_id(session_id) -> bool:
    return isinstance(session_id, str) and _SESSION_ID.fullmatch(session_id) is not None

# Runtime-set bindings present in the Bash/hook environment of a live session.
ENV_HOST = "CLAUDE_CODE_HOST_SESSION_ID"   # local_...
ENV_SESSION = "CLAUDE_CODE_SESSION_ID"     # uuid
ENV_PID = "CLAUDE_PID"                      # process id


class TargetError(RuntimeError):
    """A session target could not be resolved unambiguously."""


def load_records(sessions_dir: pathlib.Path | None = None) -> list[dict]:
    """Every readable ~/.claude/sessions/<pid>.json record."""
    directory = sessions_dir or SESSIONS_DIR
    out: list[dict] = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _require_bridge(record: dict) -> dict:
    if not record.get("bridgeSessionId"):
        raise TargetError(
            f"session {record.get('name')!r} has no bridgeSessionId "
            "(Remote Control is not connected for it)"
        )
    return record


def resolve_target(
    name: str | None = None,
    pid: int | None = None,
    host_session_id: str | None = None,
    session_id: str | None = None,
    sessions_dir: pathlib.Path | None = None,
) -> dict:
    """Resolve an explicitly-selected session record. Raises on none / ambiguous."""
    if name is None and pid is None and host_session_id is None and session_id is None:
        raise TargetError("no target selector provided")
    matches = [
        r for r in load_records(sessions_dir)
        if (name is not None and r.get("name") == name)
        or (pid is not None and r.get("pid") == pid)
        or (host_session_id is not None and r.get("hostSessionId") == host_session_id)
        or (session_id is not None and r.get("sessionId") == session_id)
    ]
    if not matches:
        raise TargetError("no session record matched the selector")
    if len(matches) > 1:
        pids = ", ".join(str(r.get("pid")) for r in matches)
        raise TargetError(f"ambiguous target, matched pids: {pids}")
    return _require_bridge(matches[0])


def _env_identity(environ: dict | None = None) -> dict:
    env = environ if environ is not None else os.environ
    return {
        "host": env.get(ENV_HOST),
        "session": env.get(ENV_SESSION),
        "pid": env.get(ENV_PID),
    }


def _cross_check(record: dict, identity: dict) -> int:
    """
    Count how many runtime identifiers agree with a record.

    A field absent *on the record* is "no information" for that axis (skipped),
    not a match and not a conflict - older records may not carry every field. But
    a field present on both sides that differs is an explicit conflict and
    disqualifies the record entirely (returns -1), so a stale or foreign record
    can never be selected.
    """
    agree = 0
    for key, field in (("host", "hostSessionId"), ("session", "sessionId"), ("pid", "pid")):
        want = identity[key]
        if want is None:
            continue
        have = record.get(field)
        if have is None:
            continue
        if key == "pid":
            try:
                match = int(have) == int(want)
            except (TypeError, ValueError):
                match = False
        else:
            match = have == want
        if match:
            agree += 1
        else:
            return -1
    return agree


def resolve_self(
    environ: dict | None = None,
    session_id: str | None = None,
    sessions_dir: pathlib.Path | None = None,
) -> dict:
    """The current session, bound and usable: identity checked, Remote Control connected.

    Everything that sends uses this one. Its only difference from
    ``resolve_self_unbound`` is the last line, and that line is the whole
    guarantee that a caller cannot send to a session that has no bridge.
    """
    return _require_bridge(resolve_self_unbound(environ, session_id, sessions_dir))


def resolve_self_unbound(
    environ: dict | None = None,
    session_id: str | None = None,
    sessions_dir: pathlib.Path | None = None,
) -> dict:
    """
    Bind the current session as the target from runtime signals only.

    The record comes back whether or not Remote Control is connected for it, so
    the caller can *say* something about a session it cannot send to (the idle
    notifier's "Remote Control is off" toast). Nothing that sends may use this:
    use ``resolve_self``.

    Priority order for the authoritative session id: an explicit ``session_id``
    (e.g. the id a Stop hook receives on stdin) wins, otherwise the ambient
    environment is used. A record is accepted only when at least two independent
    runtime identifiers agree and none conflict, so a stale or foreign record can
    never be selected.
    """
    identity = _env_identity(environ)
    if session_id is not None:
        identity = {**identity, "session": session_id}

    present = [k for k in ("host", "session", "pid") if identity[k] is not None]
    if not present:
        raise TargetError(
            "no runtime session identity available "
            f"(need one of ${ENV_HOST} / ${ENV_SESSION} / ${ENV_PID} or an explicit session_id)"
        )

    scored = []
    for record in load_records(sessions_dir):
        score = _cross_check(record, identity)
        if score > 0:
            scored.append((score, record))

    if not scored:
        raise TargetError("no session record matched the current runtime identity")

    best = max(s for s, _ in scored)
    winners = [r for s, r in scored if s == best]
    if len(winners) > 1:
        raise TargetError("runtime identity matched more than one record; refusing to guess")

    # Require corroboration: a single identifier is not enough to fire a
    # self-modifying command at a session.
    if best < 2 and len(present) >= 2:
        raise TargetError("insufficient corroboration between runtime identifiers")

    return winners[0]
