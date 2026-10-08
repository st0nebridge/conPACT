"""
@module conpact.codex_host
@description conPACT's own Codex app-server: the interface we run, rather
             than one we borrow. Codex ships a shared local daemon for this, but
             it refuses to start from the CLI ChatGPT Desktop installs (it wants
             a packaged one, with a `codex-package.json` beside it) and it listens
             on an AF_UNIX socket Python on Windows cannot open. A plain
             `codex app-server --listen ws://127.0.0.1:<port>` has neither
             problem: it starts from the CLI that is already here, serves
             `/readyz` and a WebSocket on `/rpc`, and outlives the process that
             started it, so a toast click and a command an hour later reach the
             same server.

             It is started with `--ws-auth capability-token` and given only the
             SHA-256 of a freshly minted token, so the secret never reaches the
             app-server process and every upgrade without it is refused with 401
             - measured, on loopback as well as off it. The token itself is kept
             in conPACT's own state folder (D-009), readable by this user and
             so by anything running as them: the same boundary Codex's own
             control socket has, and the reason the listener is bound to
             127.0.0.1 and never to an address anything else can route to.
@input      the process environment, and (injected) the ways to pick a port,
            start a process, ask `/readyz` and open a socket
@output     an outcome dict per action, a read-only view of what is running, and
            an open JSON-RPC conversation with it
@dependencies conpact.codex_appserver, conpact.compaction,
              conpact.detach; stdlib: contextlib, hashlib, json, os, secrets,
              socket, time, urllib
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import socket
import time
import urllib.error
import urllib.request

from . import codex_appserver, compaction, detach

HOST = "127.0.0.1"
RECORD = "codex-host.json"
TOKEN_BYTES = 32

READY_TIMEOUT = 90.0
READY_POLL = 0.25
READY_ASK = 2.0

NO_CLI = "no_cli"
NOT_RUNNING = "not_running"
NOT_READY = "not_ready"
FAILED = "failed"

NOT_DONE = {
    NO_CLI: "the codex executable could not be found on this machine",
    NOT_RUNNING: "no app-server of ours is running",
    NOT_READY: "the app-server was started but never answered /readyz",
    FAILED: "the app-server could not be started or reached",
}


def record_path():
    """Ours, under `~/.conpact/` - never inside Codex's own state
    (D-030, D-20260923-048)."""
    return compaction.STATE_DIR / RECORD


def _outcome(done: bool, reason=None, detail=None) -> dict:
    return {"done": done, "reason": reason, "detail": detail,
            "message": None if done else (NOT_DONE.get(reason) or "not done")}


def read_record():
    """What we last started, or None. A record we cannot parse is no record: it
    must never raise into a hook or a toast."""
    try:
        record = json.loads(record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    port, pid = record.get("port"), record.get("pid")
    if not isinstance(port, int) or not isinstance(pid, int):
        return None
    return {"port": port, "pid": pid, "token": record.get("token") or None,
            "started_at": record.get("started_at")}


def write_record(port: int, pid: int, token: str) -> None:
    """Replace the record atomically, and ask for owner-only permissions. Windows
    does not honour the mode the way POSIX does, which is why the listener is
    bound to loopback rather than relying on it."""
    target = record_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    body = {"port": port, "pid": pid, "token": token, "started_at": int(time.time())}
    temp.write_text(json.dumps(body), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(temp, 0o600)
    os.replace(temp, target)


def clear_record() -> None:
    with contextlib.suppress(OSError):
        record_path().unlink()


def mint_token() -> tuple[str, str]:
    """A token and the digest the app-server is given instead of it."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hashlib.sha256(token.encode()).hexdigest()


def free_port(binder=None) -> int:
    """A port nothing is listening on. There is a race between letting it go and
    the app-server taking it; losing it shows up as a server that never becomes
    ready, which is already an outcome we report."""
    with (binder or socket.socket)() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def ready(port: int, asker=None, timeout: float = READY_ASK) -> bool:
    """Has the app-server finished starting? `/readyz` is its own answer to that,
    and the desktop app asks the daemon the same kind of question."""
    url = f"http://{HOST}:{port}{codex_appserver.READY_PATH}"
    try:
        with (asker or urllib.request.urlopen)(url, timeout=timeout) as answer:
            return 200 <= getattr(answer, "status", 0) < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def running(environ=None, asker=None) -> dict:
    """What our app-server is doing, without changing anything: is the process we
    started still alive, and is it answering?"""
    record = read_record()
    if record is None:
        return {"running": False, "ready": False, "port": None, "pid": None}
    alive = detach.pid_alive(record["pid"])
    return {"running": bool(alive), "ready": bool(alive) and ready(record["port"], asker),
            "port": record["port"], "pid": record["pid"]}


def start(environ=None, spawn=None, asker=None, binder=None,
          timeout: float = READY_TIMEOUT, sleep=time.sleep) -> dict:
    """Start our app-server if it is not already up, and wait for it to answer.

    Already running and ready is a success with nothing done, because that is
    what the caller wanted; a record pointing at a process that has gone is
    replaced rather than trusted.
    """
    current = running(environ, asker)
    if current["ready"]:
        return _outcome(True, detail={"port": current["port"], "pid": current["pid"],
                                      "already": True})
    if current["running"]:
        stop(environ)
    cli = codex_appserver.codex_cli(environ)
    if cli is None:
        return _outcome(False, NO_CLI)

    token, digest = mint_token()
    port = free_port(binder)
    argv = [str(cli), *codex_appserver.listen_args(HOST, port, digest)]
    try:
        pid = (spawn or detach.spawn)(argv, environ)
    except OSError as problem:
        return _outcome(False, FAILED, f"{type(problem).__name__}: {problem}")

    write_record(port, pid, token)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready(port, asker):
            return _outcome(True, detail={"port": port, "pid": pid, "already": False})
        if not detach.pid_alive(pid):
            clear_record()
            return _outcome(False, FAILED, "the app-server exited while starting")
        sleep(READY_POLL)
    return _outcome(False, NOT_READY, {"port": port, "pid": pid})


def stop(environ=None, killer=None) -> dict:
    """Stop the app-server we started and forget it. Nothing else is signalled:
    the pid comes from our own record, never from a search."""
    record = read_record()
    if record is None:
        return _outcome(False, NOT_RUNNING)
    try:
        (killer or _kill)(record["pid"])
    except OSError as problem:
        return _outcome(False, FAILED, f"{type(problem).__name__}: {problem}")
    finally:
        clear_record()
    return _outcome(True, detail={"pid": record["pid"]})


def _kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, 9)


def open_server(environ=None, opener=None, timeout=None, expected_pid=None):
    """An open JSON-RPC conversation with our app-server, or a named refusal.
    Returns (server, None) or (None, outcome), so no caller has to catch."""
    current = running(environ)
    if not current["running"]:
        return None, _outcome(False, NOT_RUNNING)
    record = read_record()
    if record is None:                               # it went away between the two reads
        return None, _outcome(False, NOT_RUNNING)
    if expected_pid is not None and record["pid"] != expected_pid:
        return None, _outcome(False, FAILED, "the listener record no longer names the owning app-server")
    try:
        server = codex_appserver.connect_ws(
            HOST, record["port"], record["token"],
            codex_appserver.HANDSHAKE_TIMEOUT if timeout is None else timeout, opener)
    except (OSError, ValueError) as problem:
        return None, _outcome(False, FAILED, f"{type(problem).__name__}: {problem}")
    return server, None
