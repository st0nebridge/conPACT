"""
@module conpact.platforms
@description One shape for "a session conPACT might compact", whichever
             desktop app it belongs to, and one answer for why a given session
             cannot be compacted right now. Claude Code keeps a per-process JSON
             record and a JSONL transcript; ChatGPT Desktop (Codex) keeps a row
             in a SQLite state store and a JSONL rollout. The fields that matter
             - what is it called, where is it working, how full is its context,
             is it a throwaway, has the user archived it, can we reach it - exist
             on both, so callers that only want to look (the CLI, the readiness
             report, anything that lists) ask here instead of branching. Nothing
             here binds, sends or compacts: the self-binding rules of D-005 and
             D-012 are untouched and stay on each platform's own modules.
@input      the process environment; optionally one platform name
@output     normalised session records, which platforms have state on this
            machine, and the reason a session is not compactable
@dependencies conpact.codex_meter, conpact.codex_threads,
              conpact.session_registry, conpact.spin_off; stdlib: pathlib
"""
from __future__ import annotations

import pathlib

from . import codex_home, codex_meter, codex_threads, session_registry, spin_off

CLAUDE = "claude"
CODEX = "codex"
PLATFORMS = (CLAUDE, CODEX)

# Why a session cannot be compacted, most decisive first.
SPIN_OFF = "spin_off"
ARCHIVED = "archived"
BUSY = "busy"
UNREACHABLE = "unreachable"

REASONS = {
    SPIN_OFF: "a throwaway the app spawned for itself, which is never resumed",
    ARCHIVED: "the user has archived it",
    BUSY: "a running app holds this thread open, so its rollout must not be touched",
    UNREACHABLE: "there is no route to it (Claude Code: Remote Control is off)",
}


def _session(**fields) -> dict:
    base = {"platform": None, "id": None, "title": "", "cwd": None, "transcript": None,
            "context_tokens": None, "context_window": None, "state": None,
            "archived": False, "spin_off": False, "busy": False, "reachable": True}
    base.update(fields)
    return base


def fill(session) -> float | None:
    """How full the context is, 0.0-1.0, when both numbers are known."""
    if not isinstance(session, dict):
        return None
    tokens, window = session.get("context_tokens"), session.get("context_window")
    if isinstance(tokens, int) and isinstance(window, int) and window > 0:
        return tokens / window
    return None


def blocked(session) -> str | None:
    """The reason this session cannot be compacted now, or None. The order is
    deliberate: a spin-off is not worth compacting whatever else is true of it,
    and a thread a running app holds must not be touched whatever we want."""
    if not isinstance(session, dict):
        return UNREACHABLE
    if session.get("spin_off"):
        return SPIN_OFF
    if session.get("archived"):
        return ARCHIVED
    if session.get("busy"):
        return BUSY
    if not session.get("reachable"):
        return UNREACHABLE
    return None


def installed(environ=None) -> list[str]:
    """Which platforms have state on this machine, in PLATFORMS order."""
    found = []
    try:
        if session_registry.SESSIONS_DIR.exists():
            found.append(CLAUDE)
    except OSError:
        pass
    try:
        if codex_home.state_db(environ).is_file():
            found.append(CODEX)
    except OSError:
        pass
    return found


def claude_sessions(environ=None, measure: bool = True) -> list[dict]:
    """Claude Code's live sessions, as this module's shape. A session with no
    bridgeSessionId is listed and marked unreachable rather than dropped: that
    is the state the user most needs told about (D-20260920-020)."""
    from . import context_meter                       # local: keeps the import graph flat
    out = []
    for record in session_registry.load_records():
        session_id = record.get("sessionId")
        transcript = context_meter.find_transcript(session_id) if session_id else None
        tokens = context_meter.current_context_tokens(transcript) if (measure and transcript) else None
        out.append(_session(
            platform=CLAUDE, id=session_id, title=record.get("name") or "",
            cwd=record.get("cwd"), transcript=transcript, context_tokens=tokens,
            spin_off=spin_off.is_spin_off(record.get("cwd")),
            reachable=bool(record.get("bridgeSessionId")),
        ))
    return out


def codex_session_of(record, environ=None, measure: bool = True) -> dict:
    """One Codex thread record as this module's shape. Anything that decides
    whether a thread may be compacted goes through here, so that a listing and a
    compaction can never disagree about the same thread."""
    if not isinstance(record, dict):
        return _session(platform=CODEX, reachable=False)
    rollout = record.get("rollout_path")
    path = pathlib.Path(rollout) if rollout else None
    look = measure and path is not None
    return _session(
        platform=CODEX, id=record.get("id"), title=record.get("label") or "",
        cwd=record.get("cwd"), transcript=path,
        context_tokens=codex_meter.current_context_tokens(path) if look else None,
        context_window=codex_meter.context_window(path) if look else None,
        state=codex_meter.turn_state(path) if look else None,
        archived=codex_threads.is_archived(record),
        spin_off=codex_threads.is_spin_off(record),
        busy=codex_threads.is_loaded(record.get("id"), environ),
    )


def codex_sessions(environ=None, limit: int | None = None, measure: bool = True) -> list[dict]:
    """ChatGPT Desktop's threads, as this module's shape."""
    return [codex_session_of(record, environ, measure)
            for record in codex_threads.threads(environ, limit=limit)]


def sessions(platform: str | None = None, environ=None, limit: int | None = None,
             measure: bool = True) -> list[dict]:
    """Every session conPACT can see, on one platform or on both."""
    out = []
    if platform in (None, CLAUDE):
        out.extend(claude_sessions(environ, measure=measure))
    if platform in (None, CODEX):
        out.extend(codex_sessions(environ, limit=limit, measure=measure))
    return out
