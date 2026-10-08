"""
@module conpact.codex_compact
@description Compact one ChatGPT Desktop (Codex) thread. Codex has no slash
             command and no bridge: compaction is the JSON-RPC method
             `thread/compact/start`, served by an app-server. There are two
             routes, and which one a thread needs is the difference between a
             free thread and a live one. A thread no app holds is compacted by an
             app-server of our own: connect, resume, compact, and Codex's own
             per-thread writer lock keeps that safe. A thread the desktop holds
             open - the live thread, the one worth compacting - can only be
             written by the app-server that holds its lock, which is the
             desktop's, a stdio child with no socket. That one is reached through
             the sidecar shim (`codex_inject` -> `codex_sidecar`), which stands
             in the desktop's own app-server stdin. When no sidecar is installed
             a busy thread is still refused, so every refusal remains an answer,
             never an exception: a thread that is archived or a spin-off is left
             exactly as it was however we might reach it.
             An accepted RPC is only a start: the exact target rollout must
             record compaction and the matching turn's completion before success.
@input      a Codex thread id, the process environment, and (injected) the way
            to start a subprocess
@output     an outcome dict saying whether the thread was compacted and, when it
            was not, which of the named reasons applies
@dependencies conpact.codex_appserver, conpact.codex_completion,
              conpact.codex_host, conpact.codex_inject, conpact.codex_meter,
              conpact.codex_threads, conpact.platforms; stdlib: queue, time
"""
from __future__ import annotations

import queue
import time

from . import (codex_appserver, codex_completion, codex_host, codex_inject,
               codex_meter, codex_threads, platforms)
from .codex_appserver import ARGS, CLIENT, INITIALIZE, AppServer, codex_cli

RESUME = "thread/resume"
COMPACT = "thread/compact/start"

# The blocking reasons this module branches on, named from platforms so the
# routing reads plainly.
SPIN_OFF = platforms.SPIN_OFF
ARCHIVED = platforms.ARCHIVED
BUSY = platforms.BUSY

# A compaction is a model call on the user's account; a resume is not.
HANDSHAKE_TIMEOUT = codex_appserver.HANDSHAKE_TIMEOUT
COMPACT_TIMEOUT = 600.0

NO_CLI = "no_cli"
NO_THREAD = "no_thread"
FAILED = "failed"
UNOBSERVED = "completion_unobserved"

NOT_COMPACTED = {
    NO_CLI: "the codex executable could not be found on this machine",
    NO_THREAD: "no thread with that id is in Codex's state store",
    FAILED: "the app-server refused or did not answer",
    UNOBSERVED: "Codex accepted compaction, but its completion has not been confirmed",
}


def _outcome(compacted: bool, reason=None, detail=None) -> dict:
    return {"compacted": compacted, "reason": reason, "detail": detail,
            "message": None if compacted else (
                platforms.REASONS.get(reason) or NOT_COMPACTED.get(reason) or "not compacted")}


def _remaining(stop, limit=None):
    left = stop - time.monotonic()
    if left <= 0:
        raise TimeoutError("the compaction deadline expired")
    return left if limit is None else min(left, limit)


def _through_host(thread_id, environ=None, opener=None,
                  timeout: float = COMPACT_TIMEOUT, tracker=None, stop=None) -> dict | None:
    """Compact through conPACT's listener, or None when it is not running.

    ``conpact-codex`` connects the terminal UI to this same app-server.  A
    second authenticated WebSocket therefore reaches the process that owns the
    thread's writer lock.  Ask for compaction directly first (the common live
    CLI case); if the thread is merely free, resume it on this server and retry.
    """
    owner = codex_inject.owner_pid(environ)
    if owner is not None:
        recorded = codex_host.read_record()
        if recorded is None or recorded.get("pid") != owner:
            return None
    stop = time.monotonic() + timeout if stop is None else stop
    server = None
    try:
        server, refused = codex_host.open_server(
            environ, opener, timeout=_remaining(stop, HANDSHAKE_TIMEOUT), expected_pid=owner)
        if refused is not None:
            return None if refused.get("reason") == codex_host.NOT_RUNNING else \
                _outcome(False, FAILED, refused.get("detail") or refused.get("message"))
        done = server.request(COMPACT, {"threadId": thread_id}, _remaining(stop))
        if "error" not in done:
            return _finished(tracker, done.get("result"), stop)
        if not codex_inject.not_loaded(done, thread_id):
            return _outcome(False, FAILED, done["error"])
        resumed = server.request(RESUME, {"threadId": thread_id, "excludeTurns": True},
                                 _remaining(stop, HANDSHAKE_TIMEOUT))
        if "error" in resumed:
            return _outcome(False, FAILED, resumed["error"])
        done = server.request(COMPACT, {"threadId": thread_id}, _remaining(stop))
        if "error" in done:
            return _outcome(False, FAILED, done["error"])
        return _finished(tracker, done.get("result"), stop)
    except (OSError, ValueError, TimeoutError, queue.Empty) as problem:
        return _outcome(False, FAILED, f"{type(problem).__name__}: {problem}")
    finally:
        if server is not None:
            server.close()


def _finished(tracker, acknowledgement, stop):
    observed = tracker.wait(stop)
    state = observed["state"]
    outcome = _outcome(state == "completed",
                       None if state == "completed" else
                       UNOBSERVED if state == "unobserved" else FAILED,
                       acknowledgement if state == "completed" else observed["detail"])
    return {**outcome, "accepted": True, "turn_id": observed.get("turn_id")}


def compact(thread_id, environ=None, spawn=None, host_opener=None,
            timeout: float = COMPACT_TIMEOUT) -> dict:
    """Compact one Codex thread, or say why not.

    Every thread that may be compacted goes through the sidecar - the desktop's
    own app-server, which is the only process that may write any rollout. A
    thread the desktop holds is loaded; a free one is resumed there first. The
    guards run before anything is sent, in platforms.blocked's order, so an
    archived or spin-off thread is never touched however we could reach it. When
    no sidecar is installed the own-app-server path below is the fallback: it can
    reach only a free thread, so a busy one is then refused.
    """
    record = codex_threads.thread(thread_id, environ)
    if record is None:
        return _outcome(False, NO_THREAD)
    session = platforms.codex_session_of(record, environ, measure=False)
    reason = platforms.blocked(session)
    if reason in (SPIN_OFF, ARCHIVED):
        return _outcome(False, reason)     # never to be touched, by any route

    if codex_meter.turn_state(record.get("rollout_path")) != codex_meter.IDLE:
        return _outcome(False, FAILED, "target thread is running or its idle state is unknown")
    try:
        tracker = codex_completion.Rollout(record.get("rollout_path"))
    except (OSError, ValueError) as exc:
        return _outcome(False, FAILED, f"cannot observe target compaction: {exc}")
    stop = time.monotonic() + timeout

    # The sidecar handles both the live thread and a free one; it is the whole
    # of Codex compaction whenever it is installed.
    injected = codex_inject.compact_thread(record["id"], environ,
                                         deadline=max(0, stop - time.monotonic()))
    if injected is not None:
        if injected.get("accepted") or injected.get("compacted"):
            return _finished(tracker, injected.get("detail"), stop)
        return _outcome(False, FAILED, injected.get("detail"))

    # A terminal UI launched by ``conpact-codex`` is a client of our own
    # listener.  That server, not the TUI process, owns the rollout lock, and a
    # second authenticated connection can safely compact it.  This also handles
    # a free thread without starting another app-server.
    hosted = _through_host(record["id"], environ, host_opener, timeout, tracker, stop)
    if hosted is not None:
        return hosted

    if codex_inject.owner_pid(environ) is not None:
        return _outcome(False, FAILED, "the owning app-server's compaction channel is unavailable; "
                        "restart its conPACT integration")

    # No sidecar: fall back to an app-server of our own, which can reach a free
    # thread only. A busy thread has nowhere to go, so it is refused.
    if reason == BUSY:
        return _outcome(False, BUSY)
    cli = codex_cli(environ)
    if cli is None:
        return _outcome(False, NO_CLI)

    server = None
    try:
        server = codex_appserver.connect(cli, ARGS, environ, spawn,
                                        _remaining(stop, HANDSHAKE_TIMEOUT))
        resumed = server.request(RESUME, {"threadId": record["id"], "excludeTurns": True},
                                 _remaining(stop, HANDSHAKE_TIMEOUT))
        if "error" in resumed:
            return _outcome(False, FAILED, resumed["error"])
        done = server.request(COMPACT, {"threadId": record["id"]}, _remaining(stop))
        if "error" in done:
            return _outcome(False, FAILED, done["error"])
        return _finished(tracker, done.get("result"), stop)
    except (OSError, ValueError, TimeoutError, queue.Empty) as problem:
        return _outcome(False, FAILED, f"{type(problem).__name__}: {problem}")
    finally:
        if server is not None:
            server.close()
