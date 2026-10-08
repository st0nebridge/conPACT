"""
@module conpact.closure_hook
@description Stop-hook entrypoint. Claude Code runs this at the end of a turn and
             passes the session context as JSON on stdin. If (and only if) a
             compaction request was recorded for THIS session, the hook claims it
             (at most once), measures the session's context from its transcript,
             and - unless the minimum context size is not reached (the request's
             own, else the user's default from conpact.settings) -
             fires a real /compact into the session over the bridge, after the
             final answer. Every outcome of a claimed request is reported
             truthfully (compacted / below_threshold / failed / error) and
             appended to a small log that never contains the token. Unless it
             has just sent /compact, it then hands the turn end to the idle
             notifier (idle_arming), which may start a watcher for the session,
             and sweeps ChatGPT Desktop's threads (codex_arming), which has no
             turn end of its own to be called at.
             The hook never blocks the stop, never writes to stdout, stays silent
             when nothing was claimed, and never raises.
@input      hook JSON on stdin (session_id, transcript_path, cwd, ...)
@output     process exit code 0 (always); a one-line status on stderr and one
            log line per claimed request
@dependencies conpact.bridge_client, conpact.compaction,
              conpact.codex_arming, conpact.context_meter, conpact.home, conpact.idle_arming,
              conpact.session_registry, conpact.settings,
              conpact.token_store; stdlib: json, sys, time
"""
from __future__ import annotations

import json
import sys
import time

from . import (bridge_client, codex_arming, compaction, context_meter, home, idle_arming,
               session_registry, settings, token_store)

LOG_PATH = compaction.STATE_DIR / "hook-log.jsonl"

# What firing can raise in normal operation: target resolution, login, network
# and file access (urllib's URLError is an OSError), and malformed data.
FIRING_ERRORS = (session_registry.TargetError, token_store.TokenError, OSError, ValueError, KeyError)


def read_hook_input(stream=None) -> dict:
    """Parse the hook JSON from stdin; tolerate an empty or malformed payload."""
    stream = stream or sys.stdin
    try:
        raw = stream.read()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def run(hook_input: dict, sessions_dir=None, requests_dir=None, compactor=None, measure=None) -> dict:
    """
    Core logic, separated from stdin/exit handling for testability.

    Returns a status dict: action is "skip" (nothing pending), "compacted" (the
    bridge accepted /compact), "below_threshold" (the context was smaller than
    the request's minimum, so nothing was sent), "failed" (the bridge refused
    it) or "error" (it could not be fired). A claimed request is never re-armed,
    whatever happens.
    """
    session_id = hook_input.get("session_id")
    if not session_id:
        return {"action": "skip", "reason": "no session_id in hook input"}

    request = compaction.consume_request(session_id, requests_dir=requests_dir)
    if request is None:
        return {"action": "skip", "reason": "no compaction request for this session"}

    transcript = hook_input.get("transcript_path")
    tokens = (measure or context_meter.current_context_tokens)(transcript if isinstance(transcript, str) else None)
    sizes = {"context_tokens": tokens, "min_context_tokens": request.get("min_context_tokens")}
    try:
        minimum = compaction.validate_min_context_tokens(sizes["min_context_tokens"])
    except ValueError as exc:
        return {"action": "error", "reason": f"invalid request: {exc}; not compacting", **sizes}
    if minimum is None:  # the agent set none: the user's default applies (None: always compact)
        minimum = sizes["min_context_tokens"] = settings.load()["closure_min_context_tokens"]
    if minimum is not None:
        if tokens is None:
            return {"action": "error", "reason": "context size could not be measured; not compacting", **sizes}
        if tokens < minimum:
            return {"action": "below_threshold",
                    "reason": f"context {tokens} tokens < minimum {minimum}; not compacting", **sizes}

    compact = compactor or compaction.compact_self
    try:
        result = compact(
            focus=request.get("focus", ""),
            session_id=session_id,
            sessions_dir=sessions_dir,
        )
    except FIRING_ERRORS as exc:
        return {"action": "error", "reason": f"{type(exc).__name__}: {exc}", **sizes}
    status = result.get("http_status")
    if not bridge_client.is_success(status):
        return {"action": "failed", "reason": f"bridge returned HTTP {status}", "result": result, **sizes}
    return {"action": "compacted", "reason": f"bridge returned HTTP {status}", "result": result, **sizes}


def record_outcome(status: dict, session_id, log_path=None) -> None:
    """Append one JSON line describing a claimed request's outcome. Never the token."""
    result = status.get("result") or {}
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "action": status.get("action"),
        "reason": status.get("reason", ""),
        "http_status": result.get("http_status"),
        "token_refreshed": result.get("token_refreshed"),
        "context_tokens": status.get("context_tokens"),
        "min_context_tokens": status.get("min_context_tokens"),
    }
    path = log_path or LOG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the log is diagnostics only; it must not disturb the stop


def main(argv=None) -> int:
    home.migrate()                   # before anything is read; never raises
    hook_input = read_hook_input()
    try:
        status = run(hook_input)
    except Exception as exc:  # last resort: a Stop hook must never raise
        status = {"action": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if status.get("action") != "skip":
        record_outcome(status, hook_input.get("session_id"))
        # Status goes to stderr only; stdout must stay clean so the hook adds no
        # control output to the session. A routine turn end prints nothing.
        sys.stderr.write(f"[conpact.closure_hook] {status.get('action')}: {status.get('reason', '')}\n")
    if status.get("action") != "compacted":
        idle_arming.run(hook_input)  # logs its own outcome; never raises
        # Codex has no turn end of its own to hook (D-20260921-031), so its
        # threads are swept here: this is the one moment conPACT is reliably
        # running on a machine that has both apps. A machine with only ChatGPT
        # Desktop does not use our CLI Stop-hook route and must run the sweep itself -
        # `python -m conpact.codex_arming` - which is why it is an entry point.
        codex_arming.run()          # logs its own outcomes; never raises
    return 0


if __name__ == "__main__":
    sys.exit(main())
