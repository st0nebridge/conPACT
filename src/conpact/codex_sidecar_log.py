"""
@module conpact.codex_sidecar_log
@description An optional tap on the sidecar's two pipes, for the one question a
             proxy cannot answer from the outside: what did the desktop actually
             ask for, and what did it get back?

             It is off unless `CONPACT_SIDECAR_LOG` names a file, and when it is
             off the sidecar does not build one - no file, no cost, no change to
             a single byte on the wire. When it is on it still changes nothing:
             it is handed a copy of each chunk *after* the stream has been dealt
             with, and every call into it is guarded, because a diagnostic that
             can break the thing it is diagnosing is worse than no diagnostic.

             What it writes is deliberately thin. This traffic carries the user's
             account, their plan, their usage and their conversations, and a log
             is a file that outlives the question it was opened for. So a line
             records the direction, the id, the method, whether the reply was an
             error and what it said, and the size - enough to see which call
             failed and why, and nothing that would be regrettable to leave on
             disk. `CONPACT_SIDECAR_LOG_BODIES=1` asks for whole bodies, for when
             the summary is not enough, and it has to be asked for.
@input      a writer, and (from the environment) whether to run at all
@output     one text line per JSON-RPC message, appended
@dependencies stdlib: json, os, pathlib, threading, time
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time

LOG_ENV = "CONPACT_SIDECAR_LOG"
BODIES_ENV = "CONPACT_SIDECAR_LOG_BODIES"

TO_CODEX = ">"          # the desktop asked
TO_DESKTOP = "<"        # the app-server answered the desktop
LIFTED = "!"            # the app-server answered us, and the desktop never saw it

MAX_BODY = 4000         # a whole body is for diagnosis, not for archiving

# The only values worth lifting out of a notification: which thread it concerns.
# An id is not content - it is what makes a turn-end event actionable.
ID_KEYS = ("threadId", "thread_id", "turnId", "conversationId")


def summarise(line: bytes, bodies: bool = False) -> str:
    """One JSON-RPC message, as much of it as is worth keeping.

    Anything that is not JSON is recorded as its size alone: it is either
    framing we do not model or something we should not be reading.
    """
    if bodies:
        text = line.decode("utf-8", "replace")
        return text if len(text) <= MAX_BODY else text[:MAX_BODY] + f"...(+{len(text) - MAX_BODY}B)"
    try:
        message = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return f"<non-json {len(line)}B>"
    if not isinstance(message, dict):
        return f"<json {type(message).__name__} {len(line)}B>"

    parts = []
    if message.get("id") is not None:
        parts.append(f"id={message['id']}")
    if message.get("method"):
        parts.append(f"method={message['method']}")
    params = message.get("params")
    if isinstance(params, dict):
        parts.append(f"params keys={sorted(params)}")
        for key in ID_KEYS:                # the id that says which thread it was
            if isinstance(params.get(key), str):
                parts.append(f"{key}={params[key]}")
    error = message.get("error")
    if isinstance(error, dict):
        parts.append(f"ERROR code={error.get('code')} {str(error.get('message'))[:200]!r}")
    elif "result" in message:
        result = message["result"]
        if isinstance(result, dict):
            parts.append(f"result keys={sorted(result)}")
        elif result is None:
            parts.append("result=null")
        else:
            parts.append(f"result {type(result).__name__}")
    parts.append(f"{len(line)}B")
    return "  ".join(parts)


class Tap:
    """Whole lines out of a byte stream, written to the log as they complete.

    One per direction, because each holds the partial line its own stream is in
    the middle of. Writes are serialised on a shared lock so two directions
    cannot interleave inside one line.
    """

    def __init__(self, write, lock, bodies: bool = False):
        self._write = write
        self._lock = lock
        self._bodies = bodies
        self._held = b""

    def note(self, direction: str, chunk: bytes) -> None:
        """Record whatever complete lines `chunk` finishes. Never raises."""
        try:
            self._held += chunk
            while b"\n" in self._held:
                line, _, self._held = self._held.partition(b"\n")
                if line.strip():
                    self._emit(direction, summarise(line, self._bodies))
        except Exception:                      # a tap must not break a pipe
            self._held = b""

    def _emit(self, direction: str, text: str) -> None:
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        with self._lock:
            try:
                self._write(f"{stamp} {direction} {text}\n")
            except Exception:
                pass


def open_tap(environ=None):
    """Two taps and a closer, or None when the log is not asked for.

    Returns `(to_codex, to_desktop, close)`; the same file, one lock, separate
    line buffers. A path that cannot be opened is not an error - it means the
    sidecar runs exactly as it would have without it.
    """
    env = os.environ if environ is None else environ
    named = env.get(LOG_ENV)
    if not named or not str(named).strip():
        return None
    try:
        path = pathlib.Path(str(named).strip())
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8", buffering=1)   # line buffered
    except OSError:
        return None
    bodies = str(env.get(BODIES_ENV, "")).strip().lower() in ("1", "true", "yes", "on")
    lock = threading.Lock()
    handle.write(f"\n=== sidecar log opened {time.strftime('%Y-%m-%d %H:%M:%S')} "
                 f"pid {os.getpid()} bodies={bodies} ===\n")
    return (Tap(handle.write, lock, bodies), Tap(handle.write, lock, bodies), handle.close)
