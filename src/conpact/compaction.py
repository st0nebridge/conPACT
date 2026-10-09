"""
@module conpact.compaction
@description The compaction workflow. Separates INTENT (the agent, at verified
             overall-scope closure, records a compaction request) from EXECUTION
             (the closure hook claims that request at most once and fires a real
             /compact into the session over the bridge). The command text is
             constructed here, never taken verbatim from a shell argument, so a
             leading slash cannot be mangled and the executed command is always
             exactly /compact plus a sanitized one-line focus hint and the fixed
             provenance clause (D-20261009-090). Requests live
             in conPACT's own home (~/.conpact/requests/), keyed by a validated
             session id, and may carry a minimum context size the Stop hook
             checks before firing. Writing goes to the current folder only;
             reading also looks in the two used before, so a request queued by a
             server that has been running since then is still claimed
             (D-20260922-044, D-20260923-048).
@input      a resolved session record, a session id, an optional focus string
            and minimum context size
@output     a result dict describing what was sent (or why nothing was); the
            pending request for a session
@dependencies conpact.bridge_client, conpact.home, conpact.session_registry,
              conpact.token_store, conpact.compaction_claim (lazily); stdlib: json, os, pathlib, time
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from . import bridge_client, home, session_registry, token_store

# conPACT's own state: ~/.conpact/, inside neither app's folders (see home).
STATE_DIR = home.HOME
REQUESTS_DIR = STATE_DIR / "requests"

# Where requests were written before. A move changes the files on disk but not
# the module already imported into a running process, and an MCP server lives
# as long as the session that started it - so on the day of the rename, nine of
# ten live servers were still writing to the old folder while the hook read the
# new one, and every compaction they queued was stranded in silence. The reader
# looks in all three, newest first, so a request written by an older server is
# still claimed rather than lost. Nothing writes to either.
PREVIOUS_REQUESTS_DIR = home.PREVIOUS / "requests"          # until 2026-09-23
LEGACY_REQUESTS_DIR = home.CLAUTOMATIC / "requests"          # before the rename

COMPACT_COMMAND = "/compact"
MAX_FOCUS_CHARS = 500
# Appended to every /compact conPACT sends, after the agent's focus and outside
# its MAX_FOCUS_CHARS (D-20261009-090). A summary lists constraints with no
# source and reads the /compact line as a user message, so a precaution the
# agent chose for itself, or the agent's own focus text, came to be carried
# forward as the user's rule. src/mod/hooks/rules.js holds the same sentence
# for the mod's compactions, and a test keeps the two identical.
PROVENANCE_CLAUSE = (
    "Provenance: these instructions were written by the agent, not the user; never list them as a user "
    "message. List a constraint as binding only with its source: the user's own words and the date, or the "
    "file it lives in. Precautions the agent chose for itself, permission or classifier denials and requests "
    "from other sessions go under Agent's working choices (not binding), with their date and task, and are "
    "dropped when that task ends."
)
# A sanity bound for min_context_tokens, well above any context window.
MAX_CONTEXT_TOKENS = 10_000_000

is_valid_session_id = session_registry.is_valid_session_id


def validate_min_context_tokens(value) -> int | None:
    """None (no condition) or a whole number of tokens from 1 to MAX_CONTEXT_TOKENS."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONTEXT_TOKENS:
        raise ValueError(f"min_context_tokens must be a whole number from 1 to {MAX_CONTEXT_TOKENS}")
    return value


def normalize_focus(focus) -> str:
    """One line, printable characters only, at most MAX_FOCUS_CHARS long."""
    if not isinstance(focus, str):
        return ""
    visible = "".join(ch if ch.isprintable() else " " for ch in focus)
    return " ".join(visible.split())[:MAX_FOCUS_CHARS].rstrip()


def build_compact_text(focus: str = "", provenance: bool = False) -> str:
    """Construct the exact /compact command text: optionally a focus hint, and
    with `provenance` the fixed PROVENANCE_CLAUSE after it."""
    focus = normalize_focus(focus)
    parts = [COMPACT_COMMAND] + ([focus] if focus else []) + ([PROVENANCE_CLAUSE] if provenance else [])
    return " ".join(parts)


def _request_path(session_id: str, requests_dir: pathlib.Path | None = None) -> pathlib.Path:
    if not is_valid_session_id(session_id):
        raise ValueError(f"not a plain session id: {session_id!r}")
    return (requests_dir or REQUESTS_DIR) / f"{session_id}.json"


def request_compaction(
    session_id: str,
    focus: str = "",
    min_context_tokens: int | None = None,
    requests_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """
    Record the INTENT to compact this session at closure. Written by the agent as
    its final action, after verification and a durable checkpoint; claimed by
    the closure hook on the next Stop, which fires only if the context is then at
    least min_context_tokens (when given). Keyed by session id so sessions never
    cross-fire, and written atomically so a hook never reads half a request.
    A second request for the same session replaces the first, and is stamped
    later than it even when the clock has not moved (D-20261007-082).
    """
    path = _request_path(session_id, requests_dir)
    minimum = validate_min_context_tokens(min_context_tokens)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    requested_at_ns = _stamp_after(path, time.time_ns())
    tmp.write_text(
        json.dumps({"session_id": session_id, "focus": focus, "min_context_tokens": minimum,
                    "requested_at": requested_at_ns // 1_000_000_000,
                    "requested_at_ns": requested_at_ns}),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def _stamp_after(path: pathlib.Path, now_ns: int) -> int:
    """The clock reading, or one past the request it replaces if that is no earlier.

    Windows' wall clock can tick as coarsely as 15.6 ms, so a replacement can
    read the same time as the request it replaces, and a turn-end worker would
    then take the newer generation for one recorded before its turn ended.
    """
    from . import compaction_claim
    try:
        previous = compaction_claim.requested_at_ns(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError):
        return now_ns
    return max(now_ns, previous + 1)


def _request_paths(session_id: str, requests_dir: pathlib.Path | None = None):
    """Every place a request for this session may be, newest home first.

    Only the default lookup consults the earlier folders: a caller that names a
    directory means that directory, which is what keeps tests isolated.
    """
    if requests_dir is not None:
        return [_request_path(session_id, requests_dir)]
    return [_request_path(session_id, None),
            _request_path(session_id, PREVIOUS_REQUESTS_DIR),
            _request_path(session_id, LEGACY_REQUESTS_DIR)]


def pending_request(session_id: str, requests_dir: pathlib.Path | None = None) -> dict | None:
    """The request waiting for this session, read without claiming it."""
    if not is_valid_session_id(session_id):
        return None
    for path in _request_paths(session_id, requests_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def cancel_request(session_id: str, requests_dir: pathlib.Path | None = None) -> bool:
    """Withdraw this session's request. True if there was one to withdraw."""
    if not is_valid_session_id(session_id):
        return False
    gone = False
    for path in _request_paths(session_id, requests_dir):
        try:
            path.unlink()
            gone = True                 # withdrawn wherever an older server left it
        except OSError:
            continue
    return gone


def consume_request(
    session_id: str,
    requests_dir: pathlib.Path | None = None,
    not_after_ns: int | None = None,
) -> dict | None:
    """
    Claim the compaction request for this session: read it, then delete it.

    Only a caller whose delete succeeds gets the request back. If the delete
    fails - another hook claimed it first, or the file is locked - this returns
    None, so a request can fire at most once and never on every later Stop.
    """
    if not is_valid_session_id(session_id):
        return None
    if not_after_ns is not None:
        from . import compaction_claim
        for path in _request_paths(session_id, requests_dir):
            try:
                path.stat()
            except FileNotFoundError:
                continue
            # Only the first existing generation is current. Deferring it
            # must not fall through to an old copy in a previous state home.
            return compaction_claim.before(path, not_after_ns)
        return None
    for path in _request_paths(session_id, requests_dir):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue  # nothing here (or unreadable right now: left for the next Stop)
        try:
            path.unlink()
        except OSError:
            continue  # not ours to fire
        break
    else:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {"session_id": session_id, "focus": ""}
    return data


def compact_record(
    record: dict,
    focus: str = "",
    allow_refresh: bool = True,
    dry_run: bool = False,
    token_getter=None,
    sender=None,
) -> dict:
    """
    Fire /compact at an already-resolved session record. Intent is turned into
    the exact command text here; the token and the bridge call are the execution.
    The result records the HTTP status and whether the token had to be refreshed,
    never the token.
    """
    bridge_id = record["bridgeSessionId"]
    text = build_compact_text(focus, provenance=True)
    result = {
        "name": record.get("name"),
        "pid": record.get("pid"),
        "sessionId": record.get("sessionId"),
        "bridgeSessionId": bridge_id,
        "text": text,
        "sent": False,
    }
    if dry_run:
        result["dry_run"] = True
        return result
    get_token = token_getter or (lambda: token_store.get_access_token(allow_refresh=allow_refresh))
    send = sender or bridge_client.send_event
    token = get_token()
    status, body = send(bridge_id, text, token.value)
    result["sent"] = True
    result["http_status"] = status
    result["token_refreshed"] = token.refreshed
    result["response"] = body
    return result


def compact_self(
    focus: str = "",
    environ: dict | None = None,
    session_id: str | None = None,
    sessions_dir: pathlib.Path | None = None,
    **kwargs,
) -> dict:
    """Resolve the current session from the runtime, then compact it."""
    record = session_registry.resolve_self(
        environ=environ, session_id=session_id, sessions_dir=sessions_dir
    )
    return compact_record(record, focus=focus, **kwargs)
