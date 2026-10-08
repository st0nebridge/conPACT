"""
@module conpact.codex_arming
@description The Codex half of the idle notifier's arming. ChatGPT Desktop uses
             its sidecar's turn/completed event; Codex CLI launched through
             conPACT uses Codex's current Stop hook. A sweep remains for older
             or unintegrated clients, so it looks at
             every thread and asks the same questions `idle_arming` asks of a
             session: is the notifier on, is the thread big enough to be worth
             compacting, is its prompt cache still alive, is it between turns, is
             it silenced, and is it a thread we are allowed to touch at all.

             A thread that passes gets the same watch marker and the same
             detached watcher as a Claude session, with `platform: "codex"` in
             the marker so the watcher knows which side it is on. The stages, the
             mute, the hold and the toast are shared rather than written twice;
             only the questions above and the compaction itself differ.

             A thread already being watched is left alone unless what the watcher
             was armed with has gone stale, because re-arming on every sweep
             would retire a live watcher and start its timer again, and a sweep
             may run often.
@input      the process environment and the user's settings; (injected) the
            clock, the thread reader and the spawner
@output     a status dict per thread (armed / skip / not_armed / error) and a
            summary; a watch marker and a detached watcher per armed thread
@dependencies conpact.codex_meter, conpact.codex_threads, conpact.codex_window,
              conpact.compaction, conpact.compaction_claim, conpact.codex_compact,
              conpact.detach, conpact.home, conpact.idle_arming, conpact.idle_state,
              conpact.platforms, conpact.settings; stdlib: os, pathlib, time
"""
from __future__ import annotations

import os
import pathlib
import time

from . import (codex_compact, codex_meter, codex_threads, codex_window,
               compaction, compaction_claim, detach, home, idle_arming, idle_state, platforms,
               settings as user_settings)

WATCH_MODULE = "conpact.idle_watch"
SRC_ROOT = str(pathlib.Path(__file__).resolve().parents[1])

# A watcher already running for this thread is left in place unless the call it
# was armed against is older than this - which means the thread has been used
# since, and the watch is measuring from the wrong moment.
STALE_SECONDS = 1.0


def _skip(thread_id, reason):
    return {"action": "skip", "thread_id": thread_id, "reason": reason}


def already_watched(thread_id: str, window, now: float) -> bool:
    """Is there a live watch for this thread, armed against the same last call?

    A sweep runs often, and re-arming writes a new generation, which retires the
    running watcher and restarts its timer - so a thread that never changed
    would never reach its toast.
    """
    marker = idle_state.read_marker(thread_id)
    if marker is None:
        return False
    if marker.get("expires_at", 0) <= now:
        return False                                   # that watch is over
    armed_against = marker.get("last_call")
    if not isinstance(armed_against, (int, float)):
        return False
    return abs(armed_against - window.last_call) < STALE_SECONDS


def consider(thread: dict, settings: dict, now: float, environ=None, reader=None):
    """The watch this thread should have, or a refusal saying why not."""
    thread_id = thread.get("id")
    session = platforms.codex_session_of(thread, environ, measure=False)
    blocked = platforms.blocked(session)
    if blocked in (platforms.SPIN_OFF, platforms.ARCHIVED):
        return _skip(thread_id, platforms.REASONS.get(blocked, blocked))

    window = (reader or codex_window.read_window)(thread.get("rollout_path"))
    if window is None:
        return _skip(thread_id, "the rollout shows no call to measure from")
    small = idle_arming.too_small(window.context_tokens,
                                  codex_meter.context_window(thread.get("rollout_path")),
                                  settings)
    if small:
        return _skip(thread_id, small)
    if window.expires_at <= now:
        return _skip(thread_id, "prompt cache already expired")
    if codex_meter.turn_state(thread.get("rollout_path")) != codex_meter.IDLE:
        return _skip(thread_id, "a turn is still running")
    silenced = idle_arming.mute_left(thread_id, window, now)
    if silenced is not None:
        return _skip(thread_id, f"silenced for another {round(silenced)} s")
    if already_watched(thread_id, window, now):
        return _skip(thread_id, "already watched, armed against the same call")

    due = idle_arming.stages(window, settings)
    return {"action": "arm", "thread_id": thread_id, "stages": due, "window": window,
            "watch": {"platform": platforms.CODEX, "session_id": thread_id, "armed_at": now,
                      "last_call": window.last_call, "ttl": window.ttl,
                      "context_tokens": window.context_tokens, "fire_at": due[0]["at"],
                      "expires_at": window.expires_at, "stages": due,
                      "name": thread.get("label") or thread.get("name"),
                      "transcript_path": thread.get("rollout_path"),
                      "ttl_is_modelled": codex_window.TTL_IS_MEASURED_NOT_DECLARED}}


def arm_thread(thread: dict, settings: dict, now: float, environ=None,
               spawner=None, reader=None) -> dict:
    """Arm one thread, or say why not."""
    decided = consider(thread, settings, now, environ, reader)
    if decided["action"] != "arm":
        return decided
    thread_id, watch = decided["thread_id"], decided["watch"]
    generation = idle_state.write_marker(thread_id, watch)
    argv = [detach.windowless_python(), "-m", WATCH_MODULE, thread_id, generation]
    env = {**(os.environ if environ is None else environ), "PYTHONPATH": SRC_ROOT}
    try:
        pid = (spawner or detach.spawn)(argv, env=env)
    except OSError as exc:
        idle_state.clear_marker(thread_id, generation)
        return {"action": "error", "thread_id": thread_id,
                "reason": f"watcher did not start: {exc}"}
    return {"action": "armed", "thread_id": thread_id, "watcher_pid": pid,
            "context_tokens": watch["context_tokens"], "fire_at": watch["fire_at"],
            "expires_at": watch["expires_at"],
            "reason": f"watcher started; acts in {round(watch['fire_at'] - now)} s "
                      f"if the thread stays idle"}


def arm_one(thread_id: str, environ=None, clock=time.time, spawner=None,
            reader=None, threads=None) -> dict:
    """Arm the one thread the sidecar just watched finish a turn.

    The sweep predates Codex's Stop hook; the sidecar and integrated CLI now
    provide exact turn ends, so this asks the same questions of one session instead
    of all of them. The sweep stays: it catches sessions that were already idle
    when the sidecar started, and machines with no sidecar at all.
    """
    settings = user_settings.load()
    if not settings[user_settings.TOGGLE]:
        return {"action": "skip", "thread_id": thread_id,
                "reason": "idle notifier is switched off"}
    try:
        rows = threads if threads is not None else codex_threads.threads(environ)
    except (OSError, ValueError) as exc:
        return {"action": "error", "thread_id": thread_id,
                "reason": f"{type(exc).__name__}: {exc}"}
    for row in rows or []:
        if row.get("id") == thread_id:
            return arm_thread(row, settings, clock(), environ, spawner, reader)
    return {"action": "skip", "thread_id": thread_id,
            "reason": "the app-server named a thread we cannot find on disk yet"}


def sweep(environ=None, clock=time.time, spawner=None, reader=None, threads=None,
          limit=None) -> dict:
    """Look at every Codex thread and arm the ones worth watching."""
    settings = user_settings.load()
    if not settings[user_settings.TOGGLE]:
        return {"action": "skip", "reason": "idle notifier is switched off", "armed": []}
    now = clock()
    try:
        rows = threads if threads is not None else codex_threads.threads(environ, limit=limit)
    except (OSError, ValueError) as exc:
        return {"action": "error", "reason": f"{type(exc).__name__}: {exc}", "armed": []}

    outcomes = []
    for row in rows or []:
        try:
            outcomes.append(arm_thread(row, settings, now, environ, spawner, reader))
        except Exception as exc:                # one bad thread must not stop the sweep
            outcomes.append({"action": "error", "thread_id": row.get("id"),
                             "reason": f"{type(exc).__name__}: {exc}"})
    armed = [o for o in outcomes if o["action"] == "armed"]
    return {"action": "swept", "looked_at": len(outcomes), "armed": armed,
            "outcomes": outcomes,
            "reason": f"{len(armed)} of {len(outcomes)} Codex threads armed"}


def run(**options) -> dict:
    """sweep(), logging anything that armed or went wrong. Never raises: it runs
    from the Stop hook, which must not fail because of the notifier."""
    try:
        status = sweep(**options)
    except Exception as exc:
        status = {"action": "error", "reason": f"{type(exc).__name__}: {exc}", "armed": []}
    for outcome in status.get("outcomes", []):
        if outcome["action"] in ("armed", "error"):
            idle_state.append_log({"event": f"codex_{outcome['action']}",
                                   "session_id": outcome.get("thread_id"),
                                   "platform": platforms.CODEX,
                                   **{k: v for k, v in outcome.items()
                                      if k not in ("action", "thread_id")}})
    return status


def _context_tokens(thread_id: str, environ=None) -> int | None:
    """Current context for one thread, read from its rollout."""
    for row in codex_threads.threads(environ) or []:
        if row.get("id") == thread_id:
            return codex_meter.current_context_tokens(row.get("rollout_path"))
    return None


def _turn_state(thread_id: str, environ=None):
    """Read the exact thread's state; absence or an unreadable store is unknown."""
    try:
        for row in codex_threads.threads(environ) or []:
            if row.get("id") == thread_id:
                return codex_meter.turn_state(row.get("rollout_path"))
    except Exception:
        pass
    return None


def queued_compaction(thread_id: str, compacter=None, requests_dir=None,
                      measurer=None, settings=None, environ=None,
                      ended_at_ns=None) -> dict | None:
    """Run a compaction an agent queued for this thread, or None if none was.

    The Codex half of D-20260919-006's intent/execution split: the MCP tool
    records the intent and executes nothing, and the turn end is what runs it.
    Claude's turn end is its Stop hook; Codex's is the sidecar watching
    `turn/completed`, which is what calls this.

    The request is claimed before it is run, so it fires at most once even if
    two turn endings arrive together - the same rule as D-20260919-010.
    """
    pending = compaction.pending_request(thread_id, requests_dir=requests_dir)
    if pending is None:
        return None
    requested = compaction_claim.requested_at_ns(pending)
    if ((ended_at_ns is not None and requested > ended_at_ns)
            or _turn_state(thread_id, environ) != codex_meter.IDLE):
        return {"action": "deferred", "thread_id": thread_id,
                "reason": "request awaits its own turn end and an observably idle thread"}
    claimed = compaction.consume_request(thread_id, requests_dir=requests_dir,
                                         not_after_ns=ended_at_ns)
    if claimed is None:
        if compaction.pending_request(thread_id, requests_dir=requests_dir) is not None:
            return {"action": "deferred", "thread_id": thread_id,
                    "reason": "a newer request awaits its own turn end"}
        return None
    try:
        minimum = compaction.validate_min_context_tokens(claimed.get("min_context_tokens"))
    except ValueError as problem:
        return {"action": "skip", "thread_id": thread_id,
                "focus": claimed.get("focus", ""),
                "reason": f"invalid request: {problem}; not compacting"}
    if minimum is None:
        values = user_settings.load() if settings is None else settings
        minimum = values.get("closure_min_context_tokens")
    tokens = None
    if minimum is not None:
        try:
            tokens = (measurer or _context_tokens)(thread_id, environ)
        except Exception:
            tokens = None
        if tokens is None:
            return {"action": "skip", "thread_id": thread_id,
                    "focus": claimed.get("focus", ""),
                    "min_context_tokens": minimum, "context_tokens": None,
                    "reason": "context size unavailable; minimum cannot be checked; not compacting"}
        if tokens < minimum:
            return {"action": "skip", "thread_id": thread_id,
                    "focus": claimed.get("focus", ""),
                    "min_context_tokens": minimum, "context_tokens": tokens,
                    "reason": f"context {tokens} tokens < minimum {minimum}; not compacting"}
    if _turn_state(thread_id, environ) != codex_meter.IDLE:
        return {"action": "skip", "thread_id": thread_id,
                "reason": "thread resumed before compaction; not compacting"}
    outcome = (compacter or codex_compact.compact)(thread_id)
    return {"action": "compacted" if outcome.get("compacted") else "compaction_failed",
            "thread_id": thread_id,
            "focus": claimed.get("focus", ""),
            "min_context_tokens": minimum, "context_tokens": tokens,
            "reason": ("compacted at the end of the turn" if outcome.get("compacted") else
                       str(outcome.get("detail") or outcome.get("message") or
                           outcome.get("reason") or "compaction did not complete"))}


def run_one(thread_id: str, **options) -> dict:
    """arm_one, logged, never raising - it is started by the sidecar.

    A compaction the agent queued is run first and instead: having just
    compacted, there is nothing for a toast to offer.
    """
    compacter = options.pop("compacter", None)
    requests_dir = options.pop("requests_dir", None)
    measurer = options.pop("measurer", None)
    closure_settings = options.pop("closure_settings", None)
    via = options.pop("via", "sidecar turn/completed")
    ended_at_ns = options.pop("ended_at_ns", None)
    environ = options.get("environ")
    try:
        ran = queued_compaction(thread_id, compacter, requests_dir, measurer,
                                closure_settings, environ, ended_at_ns)
        status = ran if ran is not None else arm_one(thread_id, **options)
    except Exception as exc:
        status = {"action": "error", "thread_id": thread_id,
                  "reason": f"{type(exc).__name__}: {exc}"}
    # Every outcome, including a skip. A sweep logs only what it did because it
    # looks at every session each time and the refusals are noise; a hook fires
    # once per turn end, and "the hook fired and decided not to" is exactly the
    # thing that is otherwise invisible - it cost an afternoon to find out by
    # hand that an aborted turn leaves no usage record to measure from.
    idle_state.append_log({"event": f"codex_{status['action']}",
                           "session_id": thread_id, "platform": platforms.CODEX,
                           "via": via,
                           **{k: v for k, v in status.items()
                              if k not in ("action", "thread_id")}})
    return status


def wait_after_stop(thread_id, clock=None, sleep=None):
    """Give the owning turn two seconds to record its end after its hook exits.
    No request is sent here; unknown/running state still defers in run_one."""
    now, pause = clock or time.monotonic, sleep or time.sleep
    stop = now() + 2.0
    while now() < stop:
        if _turn_state(thread_id) == codex_meter.IDLE:
            return True
        pause(0.1)
    return False


def main(argv=None) -> int:      # pragma: no cover - the standalone entry point
    home.migrate()
    import json
    import sys as _sys
    args = list(_sys.argv[1:] if argv is None else argv)
    after_stop = bool(args and args[-1] == "--after-stop")
    if after_stop:
        args.pop()
    if len(args) in (2, 4) and args[0] == "--thread":
        options = {}
        if len(args) == 4:
            if args[2] != "--ended-at-ns":
                return 2
            options["ended_at_ns"] = int(args[3])
        if after_stop:
            wait_after_stop(args[1])
        status = run_one(args[1], **options)
    else:
        status = run()
    print(json.dumps({k: v for k, v in status.items() if k != "outcomes"}, indent=2, default=str))
    return 0


if __name__ == "__main__":       # pragma: no cover
    import sys
    sys.exit(main())
