"""
@module conpact.compact_progress
@description Tell when a /compact sent over the bridge has finished. Claude Code
             writes a compact boundary entry to the session transcript when a
             compaction completes, with the context size before and after and
             its duration. A Tracker follows the transcript from its size just
             before the send, reading only what was appended since, in bounded
             chunks, so a large transcript is never re-read. Claude Code can
             append copies of earlier rows while compacting, an earlier boundary
             among them, so a boundary counts only if it is stamped at or after
             the send.
@input      the transcript path, its size before the send, the send time, a clock
@output     a state: compacting (elapsed seconds), compacted (tokens before and
            after, seconds, trigger, time) or unconfirmed (no boundary in time)
@dependencies stdlib: datetime, json, os
"""
from __future__ import annotations

import datetime
import json
import os

TRACK_SECONDS = 600
MAX_READ = 4 * 1024 * 1024


def size(path) -> int | None:
    """The file's size in bytes, or None if it cannot be read."""
    try:
        return os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        return None


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def stamp(at) -> float | None:
    """A transcript timestamp as epoch seconds (UTC when it names no zone), or None."""
    if not isinstance(at, str):
        return None
    try:
        when = datetime.datetime.fromisoformat(at)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when.timestamp()


def boundary(entry) -> dict | None:
    """What a main-thread compact boundary entry records, or None for any other entry."""
    if not (isinstance(entry, dict) and entry.get("type") == "system"
            and entry.get("subtype") == "compact_boundary" and not entry.get("isSidechain")):
        return None
    meta = entry.get("compactMetadata")
    meta = meta if isinstance(meta, dict) else {}
    trigger, at = meta.get("trigger"), entry.get("timestamp")
    return {"pre_tokens": _count(meta.get("preTokens")), "post_tokens": _count(meta.get("postTokens")),
            "duration_ms": _count(meta.get("durationMs")),
            "trigger": trigger if isinstance(trigger, str) else None, "at": at if isinstance(at, str) else None}


class Tracker:
    """Follows one transcript after one send until a boundary appears or time runs out."""

    def __init__(self, path: str, offset: int, started: float, clock, limit: float = TRACK_SECONDS):
        self.path, self.offset, self.started, self.clock, self.limit = path, offset, started, clock, limit
        self.pending = b""
        self.result = None

    def _scan(self) -> dict | None:
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(MAX_READ)
        except OSError:
            return None
        self.offset += len(chunk)
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()  # an incomplete last line waits for the rest
        for line in lines:
            try:
                found = boundary(json.loads(line))
            except ValueError:
                continue
            finished = stamp(found["at"]) if found else None
            if finished is not None and finished >= self.started:
                return found
        return None

    def check(self) -> dict:
        if self.result is not None:
            return self.result
        found = self._scan()
        elapsed = self.clock() - self.started
        if found:
            duration = found.pop("duration_ms")
            seconds = duration / 1000 if duration is not None else elapsed
            self.result = {"state": "compacted", "pre_tokens": found["pre_tokens"],
                           "post_tokens": found["post_tokens"], "seconds": round(seconds, 1),
                           "trigger": found["trigger"], "at": found["at"]}
        elif elapsed >= self.limit:
            self.result = {"state": "unconfirmed", "seconds": round(elapsed, 1)}
        else:
            return {"state": "compacting", "elapsed": elapsed}
        return self.result

    def wait(self, sleep, step: float) -> dict:
        """Check every `step` seconds until the compaction finished or the time ran out."""
        while True:
            state = self.check()
            if state["state"] != "compacting":
                return state
            sleep(step)
