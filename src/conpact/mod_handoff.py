"""
@module conpact.mod_handoff
@description The idle watcher's way into a session through conPACT's Claude
             Code mod (src/mod), which can compact the session it runs in with
             no Remote Control. Three small files per session, under
             ~/.conpact/mod/, and nothing else:
             - beat/<id>.json, written by the mod every BEAT_SECONDS while the
               session runs, and once more with `ended` when it ends: a beat
               younger than FRESH_SECONDS says the mod is there to ask;
             - ask/<id>.json, written here: one request, with an id of its own
               and a time it lapses at, which the mod polls for;
             - answer/<id>.json, written by the mod: `claimed` as it takes a
               request, then how the compaction went.
             The mod cannot delete a file, so it takes each request id once
             (it records the id in its own store) and never one past its
             lapse time; this side removes the ask once it is answered or has
             lapsed, and clears what a session left behind once it is a week
             old.
@input      a session id, the time
@output     whether the mod is there; a request id; the mod's answer to it
@dependencies conpact.compaction, conpact.session_registry;
              stdlib: json, os, time, uuid
"""
from __future__ import annotations

import json
import os
import time
import uuid

from . import compaction, session_registry

# The mod's own timings (src/mod/hooks/handoff.js): it beats every 30 s and
# looks for a request every 2 s.
BEAT_SECONDS = 30
POLL_SECONDS = 2
# Three beats missed and the mod is taken to be gone.
FRESH_SECONDS = 3 * BEAT_SECONDS
# A request the mod has not taken within this long lapses: it will not take it
# later, so the watcher can report a failure without a compaction following it.
ASK_SECONDS = 10
# How far past the lapse the watcher still looks for an answer the mod wrote
# just in time.
GRACE_SECONDS = 3
KEEP_SECONDS = 7 * 24 * 3600
# What the mod's answer says while a compaction it took is under way, and how
# it ended when it ended badly.
TAKEN = ("claimed", "compacted")
REFUSED = ("skipped", "error")


def _folder(kind: str):
    return compaction.STATE_DIR / "mod" / kind


def _path(kind: str, session_id: str):
    if not session_registry.is_valid_session_id(session_id):
        raise ValueError(f"not a plain session id: {session_id!r}")
    return _folder(kind) / f"{session_id}.json"


def beat_path(session_id: str):
    return _path("beat", session_id)


def ask_path(session_id: str):
    return _path("ask", session_id)


def answer_path(session_id: str):
    return _path("answer", session_id)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _read(path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _unlink(path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def alive(session_id: str, now: float) -> bool:
    """Is the session's mod running, and recently enough to answer a request?"""
    beat = _read(beat_path(session_id))
    if beat is None or beat.get("session_id") != session_id or beat.get("ended") is not False:
        return False
    at = beat.get("at")
    return _number(at) and 0 <= now - at <= FRESH_SECONDS


def ask(session_id: str, now: float) -> str:
    """Ask the session's mod to compact it; returns the request's id. An answer
    left from an earlier request is cleared first, so the one read later is this one's."""
    request_id = uuid.uuid4().hex
    _unlink(answer_path(session_id))
    path = ask_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"session_id": session_id, "request_id": request_id, "requested_at": now,
                               "expires_at": now + ASK_SECONDS}), encoding="utf-8")
    os.replace(tmp, path)
    return request_id


def answer(session_id: str, request_id: str) -> dict | None:
    """The mod's answer to this request, or None while it has given none."""
    found = _read(answer_path(session_id))
    if found is None or found.get("session_id") != session_id or found.get("request_id") != request_id:
        return None
    return found if found.get("action") in TAKEN + REFUSED else None


def withdraw(session_id: str, request_id: str) -> None:
    """Remove the ask if it is still this request's."""
    path = ask_path(session_id)
    found = _read(path)
    if found is not None and found.get("request_id") == request_id:
        _unlink(path)


def await_answer(session_id: str, request_id: str, requested_at: float, clock, sleep) -> dict | None:
    """The mod's first answer, waiting until shortly past the request's lapse.
    The ask is removed either way: answered, it has been taken; unanswered, it
    has lapsed and the mod will no longer take it."""
    deadline = requested_at + ASK_SECONDS + GRACE_SECONDS
    try:
        while True:
            found = answer(session_id, request_id)
            if found is not None or clock() >= deadline:
                return found
            sleep(min(POLL_SECONDS / 2, max(deadline - clock(), 0)))
    finally:
        withdraw(session_id, request_id)


def refusal(found: dict) -> str:
    reason = found.get("reason")
    what = "skipped" if found.get("action") == "skipped" else "failed"
    return f"the session's mod {what} the compaction: {reason}" if isinstance(reason, str) and reason \
        else f"the session's mod {what} the compaction"


class Tracker:
    """Follows a compaction the mod took: the transcript says when it finished,
    the mod's answer says when it did not happen at all."""

    def __init__(self, inner, session_id: str, request_id: str, started: float):
        self.inner, self.session_id, self.request_id, self.started = inner, session_id, request_id, started
        self.result = None

    def check(self) -> dict:
        if self.result is not None:
            return self.result
        found = answer(self.session_id, self.request_id)
        if found is not None and found.get("action") in REFUSED:
            self.result = {"state": "error", "detail": refusal(found)}
            return self.result
        if self.inner is None:
            # No transcript to follow: the mod's own word is all there is.
            if found is not None and found.get("action") == "compacted":
                at = found.get("at")
                self.result = {"state": "compacted", "pre_tokens": _count(found.get("tokens_before")),
                               "post_tokens": _count(found.get("tokens_after")),
                               "seconds": round(at - self.started, 1) if _number(at) else 0.0,
                               "trigger": None, "at": None}
                return self.result
            return {"state": "untracked"}
        state = self.inner.check()
        if state["state"] != "compacting":
            self.result = state
        return state

    def wait(self, sleep, step: float) -> dict:
        while True:
            state = self.check()
            if state["state"] != "compacting":
                return state
            sleep(step)


def prune(now: float | None = None) -> None:
    """Remove what sessions left here more than a week ago. Never raises."""
    now = time.time() if now is None else now
    for kind in ("beat", "ask", "answer"):
        try:
            entries = list(os.scandir(_folder(kind)))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_file() and now - entry.stat().st_mtime > KEEP_SECONDS:
                    os.unlink(entry.path)
            except OSError:
                pass
