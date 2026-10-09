"""
@module conpact.idle_arming
@description The Stop hook's half of the idle notifier. At a turn end it decides
             whether the session is worth watching: the notifier is on, the
             transcript shows the context size and the prompt-cache lifetime,
             the context is at least the minimum, the cache has not expired, the
             session is not silenced, its runtime record can be found and the
             user has not archived it. Remote Control being off is not a reason
             not to watch: the toast then asks for it instead of offering to
             compact (D-020), which is why the record is resolved unbound.
             If so it records a new watch generation - which retires any older
             watcher for the session - and starts a detached watcher for it. The watch has one or two stages: the last
             comes lead_seconds before the cache expires (never earlier than 60%
             of the way through its lifetime), and when the user sets an idle time
             an early one comes first, so dismissing that one does not cancel the
             other. All of these come from the user's settings (conpact.settings).
             Routine skips are silent; an armed watch, a refusal or an error is
             logged.
@input      the Stop hook JSON (session_id, transcript_path)
@output     a status dict (armed / skip / not_armed / error); a watch marker; a
            detached watcher process
@dependencies conpact.app_sessions, conpact.cache_window, conpact.compact_progress,
              conpact.detach, conpact.idle_state, conpact.session_registry, conpact.settings;
              stdlib: os, pathlib, time
"""
from __future__ import annotations

import os
import pathlib
import time

from . import (app_sessions, cache_window, compact_progress, detach, idle_state, session_registry,
               settings as user_settings)

WATCH_MODULE = "conpact.idle_watch"
MIN_FRACTION = 0.6
SRC_ROOT = str(pathlib.Path(__file__).resolve().parents[1])


def too_small(context_tokens: int, context_window, settings: dict) -> str | None:
    """Why this session is not worth a toast, or None.

    A fraction where the app reports a window, an absolute count where it does
    not. The two are not interchangeable and the difference is not academic:
    ChatGPT Desktop's whole window is 258,400 tokens, so an absolute minimum of
    300,000 - an ordinary size for a Claude session, which can hold 589,000 -
    silenced that app completely, including a session sitting at 94% full. A
    fraction says what the setting actually means, which is "cheap to pick up
    again", and cheapness is relative to the window.

    Claude Code records no window anywhere - not in the transcript, not in the
    session record - so there is nothing there to take a fraction of, and the
    absolute minimum remains the rule for it. It is not a fallback that will
    quietly stop being used; it is the answer for an app that does not say.
    """
    if context_window:
        fill = context_tokens / context_window * 100
        wanted = settings["min_context_fill"]
        if fill < wanted:
            return (f"context {context_tokens:,} tokens is {fill:.0f}% of the "
                    f"{context_window:,} window < minimum {wanted}%")
        return None
    minimum = settings["min_context_tokens"]
    if context_tokens < minimum:
        return f"context {context_tokens} tokens < minimum {minimum}"
    return None


def stages(window: cache_window.CacheWindow, settings: dict) -> list[dict]:
    """The toasts this watch should show, in order, each with the time it ends.

    The last one comes lead_seconds before the cache expires (never earlier than
    60% of the way through its lifetime). When the user sets an idle time, an
    early one comes first and closes itself, so dismissing it leaves the last one
    to come anyway. An early time at or after the last one would only duplicate it.
    """
    expiry_at = window.last_call + max(window.ttl - settings["lead_seconds"], MIN_FRACTION * window.ttl)
    found = []
    early = settings["idle_seconds"]
    if early is not None and window.last_call + early < expiry_at:
        at = window.last_call + early
        found.append({"kind": "early", "at": at, "until": min(at + settings["early_toast_seconds"], expiry_at)})
    found.append({"kind": "expiry", "at": expiry_at, "until": window.expires_at})
    return found


def mute_left(session_id: str, window: cache_window.CacheWindow, now: float) -> float | None:
    """Seconds this session is still silenced for; None if it is not (the mute is
    then cleared: it ended, or the session has been used since it was set)."""
    mute = idle_state.read_mute(session_id)
    if mute is None:
        return None
    if now < mute["until"] and window.last_call <= mute["after_call"]:
        return mute["until"] - now
    idle_state.clear_mute(session_id)
    return None


def arm(hook_input: dict, environ=None, sessions_dir=None, clock=time.time, spawner=None, reader=None) -> dict:
    session_id = hook_input.get("session_id")
    if not session_registry.is_valid_session_id(session_id):
        return {"action": "skip", "reason": "no usable session_id"}
    settings = user_settings.load()
    if not settings[user_settings.TOGGLE]:
        return {"action": "skip", "reason": "idle notifier is switched off"}
    transcript = hook_input.get("transcript_path")
    window = (reader or cache_window.read_window)(transcript if isinstance(transcript, str) else None)
    if window is None:
        return {"action": "skip", "reason": "transcript shows no context size and cache lifetime"}
    small = too_small(window.context_tokens, None, settings)
    if small:
        return {"action": "skip", "reason": small}
    now = clock()
    if window.expires_at <= now:
        return {"action": "skip", "reason": "prompt cache already expired"}
    silenced = mute_left(session_id, window, now)
    if silenced is not None:
        return {"action": "skip", "reason": f"silenced for this session for another {round(silenced)} s"}
    due = stages(window, settings)
    fire_at = due[0]["at"]
    try:
        # Unbound on purpose: a session with Remote Control off is still watched,
        # so the toast can say so instead of the turn end going quiet (D-020).
        record = session_registry.resolve_self_unbound(environ=environ, session_id=session_id,
                                                       sessions_dir=sessions_dir)
    except session_registry.TargetError as exc:
        return {"action": "not_armed", "reason": f"session not bound: {exc}"}
    if app_sessions.is_archived(record.get("hostSessionId"), environ):
        return {"action": "skip", "reason": "the session is archived"}

    watch = {"session_id": session_id, "armed_at": now, "last_call": window.last_call, "ttl": window.ttl,
             "context_tokens": window.context_tokens, "fire_at": fire_at, "expires_at": window.expires_at,
             "stages": due, "name": record.get("name"), "pid": record.get("pid"), "transcript_path": transcript,
             # Where this turn's transcript ends: a compaction after it - the
             # agent's own, which the mod runs just after this Stop - shows up
             # past here, and the watch stands down for it.
             "transcript_size": compact_progress.size(transcript),
             "host_session_id": record.get("hostSessionId")}
    generation = idle_state.write_marker(session_id, watch)
    argv = [detach.windowless_python(), "-m", WATCH_MODULE, session_id, generation]
    env = {**(os.environ if environ is None else environ), "PYTHONPATH": SRC_ROOT}
    try:
        pid = (spawner or detach.spawn)(argv, env=env)
    except OSError as exc:
        idle_state.clear_marker(session_id, generation)
        return {"action": "error", "reason": f"watcher did not start: {exc}"}
    asks_for_remote = "" if record.get("bridgeSessionId") else \
        "; Remote Control is off, so the toast will ask for it rather than offer to compact"
    return {"action": "armed",
            "reason": f"watcher started; acts in {round(fire_at - now)} s "
                      f"if the session stays idle{asks_for_remote}",
            "watcher_pid": pid, "context_tokens": window.context_tokens, "ttl": window.ttl,
            "fire_at": fire_at, "expires_at": window.expires_at}


def run(hook_input: dict, **options) -> dict:
    """arm(), logging everything but routine skips. Never raises: it runs in the Stop hook."""
    try:
        status = arm(hook_input, **options)
    except Exception as exc:  # the hook must never fail because of the notifier
        status = {"action": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if status.get("action") != "skip":
        details = {k: v for k, v in status.items() if k != "action"}
        idle_state.append_log({"event": status.get("action"), "session_id": hook_input.get("session_id"),
                               **details})
    return status
