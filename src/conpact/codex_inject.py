"""
@module conpact.codex_inject
@description Reach the app-server ChatGPT Desktop is actually running, through
             the sidecar that stands in its stdio path (`codex_sidecar`). This is
             the one route to a thread the desktop holds open - the live thread,
             the whole point of compaction - because that rollout may only be
             written by the app-server holding its per-thread lock, and that
             app-server has no socket of its own. The sidecar offers a control
             connection; a request written to it is forwarded into the
             app-server's stdin, and the tagged reply is lifted back out of the
             stream before the desktop sees it. This is the one path used for
             Codex compaction: a loaded thread compacts directly; only an
             explicit not-loaded refusal allows a metadata-only resume and one
             compaction submission. It rides
             the session the desktop already initialised.

             The channel is a loopback TCP port guarded by a capability token,
             which is one shape on every platform - the sidecar is one Python
             module everywhere, so this is one client everywhere. The token is
             the first line sent and it comes from the record the sidecar wrote;
             a connection that does not present it has nothing forwarded.

             A missing owning record or unopened channel allows the caller's
             ordinary routing checks. Once a request is attempted, a refusal or
             timeout is returned without retrying through another executor.
             It only reads its own tagged reply, and reply delivery cannot hold
             the desktop's shared output stream.
@input      a Codex thread id, the process environment, and (injected) the
            transport
@output     acceptance (never completed compaction), or None when there is
            no sidecar to route through
@dependencies conpact.compaction; stdlib: json, os, socket, time, uuid
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid

from . import compaction

RECORD = "codex-sidecar.json"
OWNERS = "codex-sidecars"
OWNER_ENV = "CONPACT_CODEX_OWNER_PID"
RESUME = "thread/resume"
COMPACT = "thread/compact/start"

DEADLINE = 600.0                          # a compaction is a model call
POLL = 0.2                                # how long a read waits before re-checking
CONNECT_WAIT = 3.0


def record_path():
    return compaction.STATE_DIR / RECORD


def owner_pid(environ=None):
    env = os.environ if environ is None else environ
    try:
        value = int(env.get(OWNER_ENV, ""))
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def read_record(environ=None, require_owner=False):
    """What the sidecar wrote: where to reach it, the token it wants, the pid it
    is, and the id tag its replies carry. None when there is no sidecar, or the
    record makes no sense - both mean "route the ordinary way"."""
    owner = owner_pid(environ)
    if require_owner and owner is None:
        return None
    paths = ([compaction.STATE_DIR / OWNERS / f"{owner}.json"] if owner else [])
    paths.append(record_path())
    record = None
    for path in paths:
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(candidate, dict) and (owner is None or candidate.get("parent_pid") == owner):
            record = candidate
            break
    if not isinstance(record, dict):
        return None
    address, token, tag = record.get("address"), record.get("token"), record.get("tag")
    if not all(isinstance(field, str) and field for field in (address, token, tag)):
        return None
    host, sep, port = address.rpartition(":")
    if not sep or not port.isdigit() or not host:
        return None
    return {"address": address, "host": host, "port": int(port),
            "token": token, "tag": tag, "pid": record.get("pid")}


class _Channel:
    """The sidecar's control connection: a loopback socket that opens with the
    token and then carries whole JSON lines. Reads take the deadline as a socket
    timeout, so a hung app-server is a timeout here and never a hang upstream."""

    def __init__(self, host: str, port: int, token: str):
        self.sock = socket.create_connection((host, port), CONNECT_WAIT)
        self.buffer = b""
        try:
            self.sock.sendall(token.encode("utf-8") + b"\n")
        except OSError:
            self.close()
            raise

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def read_line(self, deadline: float):
        """One newline-terminated line, or None once the deadline passes."""
        while b"\n" not in self.buffer:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self.sock.settimeout(min(left, POLL))
            try:
                block = self.sock.recv(65536)
            except (socket.timeout, TimeoutError):
                continue
            if not block:
                raise OSError("the sidecar closed the connection")
            self.buffer += block
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _open(record):
    return _Channel(record["host"], record["port"], record["token"])


def _request(method: str, thread_id: str, tag: str) -> tuple[str, bytes]:
    request_id = f"{tag}{uuid.uuid4().hex}"
    params = {"threadId": thread_id}
    if method == RESUME:
        params["excludeTurns"] = True
    body = json.dumps({"id": request_id, "method": method, "params": params}) + "\n"
    return request_id, body.encode("utf-8")


def _await_reply(channel, request_id, stop):
    """The reply to one injected request, matched by id. Lines that are not ours
    - the desktop's own traffic never carries our tag, but a notification might
    ride the same connection - are skipped. None on timeout."""
    while True:
        if time.monotonic() >= stop:
            return None
        line = channel.read_line(stop)
        if line is None:
            return None
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message


def not_loaded(reply, thread_id):
    """Only Codex's explicit missing loaded-thread refusal permits a resume."""
    error = reply.get("error")
    return isinstance(error, dict) and error.get("code") == -32600 and \
        error.get("message") == f"thread not found: {thread_id}"


def compact_thread(thread_id, environ=None, opener=None, deadline: float = DEADLINE):
    """Compact one thread through the sidecar, or None when there is no sidecar.

    The sidecar reaches the desktop's own app-server, which is the process that
    may write its thread's rollout. Loaded threads are not resumed. A known
    not-loaded refusal permits a metadata-only resume and one submission.
    Requests carry our id tag, and only their own
    replies are lifted back to us.

    A return of None means there is no sidecar to route through - the caller then
    falls back. A dict is a real outcome, accepted or refused. `opener` defaults
    to None and is resolved on this module at call time, so the conftest guard
    that stands for "no test opens the real channel" bites; a default bound at
    import would sail past it.
    """
    record = read_record(environ, require_owner=True)
    if record is None:
        return None
    open_channel = _open if opener is None else opener
    stop = time.monotonic() + deadline
    try:
        channel = open_channel(record)
    except OSError:
        return None                        # no sidecar reachable: fall back
    try:
        methods = [COMPACT]
        for method in methods:
            if time.monotonic() >= stop:
                return {"compacted": False, "via": "sidecar",
                        "detail": "the compaction deadline expired before sending " + method}
            request_id, body = _request(method, thread_id, record["tag"])
            channel.send(body)
            reply = _await_reply(channel, request_id, stop)
            if reply is None:
                return {"compacted": False, "via": "sidecar",
                        "detail": f"the app-server did not answer {method} in time"}
            if "error" in reply:
                if method == COMPACT and len(methods) == 1 and not_loaded(reply, thread_id):
                    methods.extend((RESUME, COMPACT))
                    continue
                return {"compacted": False, "via": "sidecar", "detail": reply["error"]}
        return {"compacted": False, "accepted": True, "via": "sidecar",
                "detail": reply.get("result")}
    except OSError as problem:
        return {"compacted": False, "via": "sidecar",
                "detail": f"{type(problem).__name__}: {problem}"}
    finally:
        channel.close()
