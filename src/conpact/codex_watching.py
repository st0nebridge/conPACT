"""
@module conpact.codex_watching
@description What the idle watcher has to do differently when the thing it is
             watching is a ChatGPT Desktop thread rather than a Claude Code
             session. It is the Codex half of `watching.Platform`, and it is
             four answers:

               resumed     - a Claude session announces itself through a runtime
                             record with a status; a Codex thread has no such
                             record, so "used since we armed" is read from the
                             rollout: a call later than the one the watch was
                             armed against, or a turn currently running.
               reachable   - always true. Remote Control is Claude's relay and
                             has no part here: a Codex thread is compacted
                             through the sidecar or an app-server of our own, so
                             there is no bridge to be off, and the toast never
                             has to ask for one.
               ensure_idle - the same question as `resumed`, asked at the moment
                             of acting rather than while waiting.
               send        - `codex_compact.compact`, which routes through the
                             sidecar and returns an outcome rather than an HTTP
                             status. codex_compact observes the target rollout
                             through recorded completion, interruption or its
                             deadline before returning; a start acknowledgement
                             alone is never reported as success.

             The thread is re-read at every check rather than trusted from the
             marker, because the whole point of the watch is that the user may
             come back to the thread while it waits.
@input      a thread id, the watch marker, and the watcher's Deps
@output     a watching.Platform
@dependencies conpact.codex_compact, conpact.codex_meter, conpact.codex_threads,
              conpact.codex_window, conpact.platforms, conpact.watching
"""
from __future__ import annotations

from . import codex_compact, codex_meter, codex_threads, codex_window, platforms, watching

# A call this much later than the one we armed against means the thread was used.
MOVED_SECONDS = 1.0


def _thread(thread_id: str, deps):
    return codex_threads.thread(thread_id, deps.environ)


def resumed(thread_id: str, marker: dict, deps) -> str | None:
    """Why this watch should stop, or None - read from the thread itself."""
    thread = _thread(thread_id, deps)
    if thread is None:
        return "closed"
    if codex_threads.is_archived(thread):
        return "archived"
    rollout = thread.get("rollout_path")
    if codex_meter.turn_state(rollout) != codex_meter.IDLE:
        return "resumed"
    armed_against = marker.get("last_call")
    latest = codex_window.last_call(rollout)
    if latest is None or not isinstance(armed_against, (int, float)):
        return None
    return "resumed" if latest - armed_against > MOVED_SECONDS else None


def reachable(thread_id: str, deps) -> bool:
    """Always: there is no bridge in the Codex path, so there is none to be off."""
    return True


def ensure_idle(thread_id: str, marker: dict, deps) -> dict:
    """The thread, still idle - or raise, which is how the caller stops."""
    reason = resumed(thread_id, marker, deps)
    if reason:
        raise watching.Interrupted(reason)
    thread = _thread(thread_id, deps)
    if thread is None:
        raise watching.Interrupted("closed")
    return thread


def send(thread_id: str, marker: dict, deps) -> dict:
    """Compact the thread, and say what happened in the watcher's own shape."""
    try:
        ensure_idle(thread_id, marker, deps)
        started = deps.clock()
        outcome = codex_compact.compact(thread_id, deps.environ)
    except watching.Interrupted as exc:
        return {"outcome": {"event": exc.reason}, "state": {"state": "closed"}}
    except (OSError, ValueError) as exc:
        return {"outcome": {"event": "error", "reason": f"{type(exc).__name__}: {exc}"},
                "state": {"state": "error", "detail": str(exc)}}
    if not outcome.get("compacted"):
        detail = str(outcome.get("detail") or outcome.get("message") or "refused")
        return {"outcome": {"event": "failed", "reason": detail, "sent_at": started},
                "state": {"state": "error", "detail": detail}}
    # codex_compact already observed the target rollout's completed compaction.
    return {"outcome": {"event": "compacted", "sent_at": started}, "state": {"state": "sent"}}


def platform() -> watching.Platform:
    return watching.Platform(name=platforms.CODEX, resumed=resumed, reachable=reachable,
                             ensure_idle=ensure_idle, send=send)
