"""
@module conpact.codex_appserver
@description One JSON-RPC conversation with a Codex app-server, over either
             transport it offers. `codex app-server` on stdio is a server private
             to the call that started it, which is what a one-shot compaction
             wants. `--listen ws://IP:PORT` is a server that outlives its caller
             and can be reached again by a different process, which is what the
             remote-control surface wants, and it is the only such transport open
             to us here: the shared daemon's control socket is AF_UNIX, which
             Python on Windows cannot open, and the daemon refuses to run from
             the CLI ChatGPT Desktop installs anyway.
             Nothing here decides *whether* a thread may be touched - that stays
             in `platforms.blocked` - and nothing here starts a listener; this is
             the transport the compaction and the remote-control surface share.
@input      the codex executable (found from the environment), the argv or the
            address that selects a transport, and (injected) the way to start a
            subprocess or open a socket
@output     a live server object whose `request` returns one reply dict per call
@dependencies conpact.codex_ws; stdlib: json, os, pathlib, plistlib, queue,
              shutil, subprocess, sys, threading, time, uuid
"""
from __future__ import annotations

import json
import os
import pathlib
import plistlib
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import codex_ws

CLIENT = {"name": "conpact", "version": "1"}
INITIALIZE = "initialize"

# Measured, not assumed: without this the app-server answers
# "remoteControl/status/read requires experimentalApi capability". The other
# four fields of its `InitializeCapabilities` are left unset, because asking for
# a capability we do not use would be asking for notifications we ignore.
CAPABILITIES = {"experimentalApi": True}

# The transports. `ARGS` is a private stdio server; `listen_args` is one that
# listens, and `PROXY_ARGS` reaches the shared daemon when there is one.
ARGS = ("app-server",)
PROXY_ARGS = ("app-server", "proxy")
RPC_PATH = "/rpc"
READY_PATH = "/readyz"

# Measured: a listener refuses every upgrade with 401 unless the caller presents
# this token, on loopback as well as off it. The server is given only the
# token's SHA-256, so the secret itself never reaches the app-server process.
LISTEN = "--listen"
WS_AUTH = ("--ws-auth", "capability-token")
WS_DIGEST = "--ws-token-sha256"


def listen_args(host: str, port: int, digest: str) -> tuple:
    """The argv that starts an app-server listening on one loopback port, open
    only to whoever holds the token behind `digest`."""
    return (*ARGS, LISTEN, f"ws://{host}:{port}", *WS_AUTH, WS_DIGEST, digest)

CLI_VAR = "CODEX_CLI_PATH"
CLI_GLOB = ("OpenAI", "Codex", "bin", "*", "codex.exe")

# Those folders are named by a content hash, so their names carry no order at
# all: sorting them picks whichever hash happens to sort last, which has nothing
# to do with which build Codex actually installed. Measured on 2026-09-22, that
# chose the build from 2026-09-18 over the one from 2026-09-19 - a shim pinned
# to it would still be running the previous Codex a week later, and that folder
# held a bare codex.exe while the current one shipped three helper binaries
# beside it (the command runner, the code-mode host, the sandbox setup) that
# codex resolves relative to itself. Recency is the only signal on disk.

# The sidecar shim drops this beside itself, naming the real codex. When it is
# installed, CODEX_CLI_PATH points the *desktop* at the shim; our own tooling
# must reach the real executable, so it resolves through the marker.
REAL_CODEX_MARKER = "real-codex.txt"

# One lever pins the codex everything here runs - the shim and our own
# app-servers alike. It is the escape hatch D-20260922-039 leaves open: the
# resolver deliberately follows Codex's newest build, so a user who needs a
# particular one says so here rather than hoping a sort keeps choosing it.
REAL_CODEX_ENV = "CONPACT_CODEX_REAL"

HANDSHAKE_TIMEOUT = 60.0


def _names(folder):
    return {entry.name.lower() for entry in folder.iterdir()}


def hollow(named, newest, lister=None):
    """Whether `named` is a build Codex has started pruning.

    A prune deletes the old build's folder, but a codex.exe some process still
    holds open survives it, leaving the bare executable without the helpers
    codex resolves beside itself (measured 2026-10-02: every command then fails
    to spawn the code-mode host). So a build is hollow when the newest install
    holds a file beside its codex that `named`'s folder lacks. A folder that
    cannot be listed is not evidence of anything, and is not called hollow.
    """
    if newest is None or os.path.normcase(str(named)) == os.path.normcase(str(newest)):
        return False
    listing = lister or _names
    try:
        return bool(listing(pathlib.Path(newest).parent)
                    - listing(pathlib.Path(named).parent))
    except OSError:
        return False


def usable(named, environ=None) -> bool:
    """Whether a codex conPACT wrote down may still be run: it is a file, and
    not a build Codex has hollowed out since (D-20260922-041, D-20261002-063)."""
    path = pathlib.Path(named)
    return path.is_file() and not hollow(path, newest_build(environ))


def selected_build(recorded=None, environ=None, platform=None):
    """An explicit pin, then the newest install, then the install-time fallback.

    Resolve afresh for each launch: a complete older build can be pruned while
    its app-server is still running, so waiting for missing helpers is too late.
    """
    env = os.environ if environ is None else environ
    pin = env.get(REAL_CODEX_ENV)
    if pin and pathlib.Path(pin).is_file():
        return pathlib.Path(pin)
    where = platform or ("win32" if env.get("LOCALAPPDATA") else sys.platform)
    newest = newest_build(env, where)
    if newest is not None:
        return newest
    # A macOS marker can name an executable in an old or renamed backup app.
    # If the active ChatGPT bundle has no compatible CLI, the safe recovery is
    # to leave the override unavailable rather than mix app versions.
    if where == "darwin":
        return None
    if recorded and usable(recorded, env):
        return pathlib.Path(recorded)
    return None


def _through_sidecar(path, environ=None):
    """The real codex behind the shim, or `path` unchanged when it is not one.
    The marker is a fallback; an installed update takes precedence."""
    try:
        marker = path.parent / REAL_CODEX_MARKER
        if marker.is_file():
            real = marker.read_text(encoding="utf-8").strip()
            if real:
                selected = selected_build(real, environ)
                if selected is not None:
                    return selected
                env = os.environ if environ is None else environ
                where = "win32" if env.get("LOCALAPPDATA") else sys.platform
                return None if where == "darwin" else pathlib.Path(real)
    except OSError:
        pass
    return path


# Where the desktop keeps the codex it runs when CODEX_CLI_PATH is unset, off
# Windows. The macOS resolver shipped the binary directly under Resources in
# 26.917, then moved it into the signed CodexCLI.app bundle in 26.930. Keep both
# layouts: an update that removes the recorded old path must still be discovered
# before the sidecar starts. Only the active ChatGPT.app is eligible on macOS;
# rollback and renamed backup bundles must never become its runtime dependency.
BUNDLED = {
    "darwin": (("/Applications/ChatGPT.app", "Contents/Resources/codex"),
               ("/Applications/ChatGPT.app",
                "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
               ("~/Applications/ChatGPT.app", "Contents/Resources/codex"),
               ("~/Applications/ChatGPT.app",
                "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")),
    "linux": (("/opt", "*/resources/codex"),
              ("/usr/lib", "*/resources/codex"),
              ("~/.local/share", "*/resources/codex")),
}


def _newest(candidates):
    """The newest file among `candidates`, or None.

    Newest by modification time, because the folder names are content hashes and
    carry no order. Ties break on the name so the answer is stable, and a build
    we cannot stat is skipped rather than allowed to lose the whole lookup.
    """
    best, best_key = None, None
    try:
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                key = (candidate.stat().st_mtime, candidate.parent.name)
            except OSError:
                continue                  # that build went away mid-scan
            if best_key is None or key > best_key:
                best, best_key = candidate, key
    except OSError:
        return best                       # the scan itself failed; keep what we had
    return best


def newest_install(local: pathlib.Path):
    """The most recently installed codex under LOCALAPPDATA, or None. A scan
    that cannot even start is None too, not a crash."""
    try:
        candidates = local.glob(str(pathlib.Path(*CLI_GLOB)))
    except OSError:
        return None
    return _newest(candidates)


def _bundled(environ, platform):
    env = os.environ if environ is None else environ
    home = env.get("HOME") or os.path.expanduser("~")
    for base, pattern in BUNDLED.get(platform, ()):
        root = pathlib.Path(home, base[2:]) if base.startswith("~/") else pathlib.Path(base)
        try:
            yield from root.glob(pattern)
        except OSError:
            continue


def bundle_details(executable) -> dict:
    """The outer application bundle and its displayed version, when present."""
    path = pathlib.Path(executable)
    apps = [parent for parent in path.parents if parent.suffix.lower() == ".app"]
    if not apps:
        return {"bundle": None, "version": None}
    bundle = apps[-1]
    try:
        with open(bundle / "Contents" / "Info.plist", "rb") as handle:
            info = plistlib.load(handle)
        version = info.get("CFBundleShortVersionString")
    except (OSError, ValueError, plistlib.InvalidFileException):
        version = None
    return {"bundle": str(bundle),
            "version": version if isinstance(version, str) else None}


def newest_build(environ=None, platform=None):
    """The codex the desktop app would run on this machine, or None.

    Windows' cache under LOCALAPPDATA and Store app bundles under ProgramFiles,
    else the codex in the active macOS app or a Linux app bundle that ships one.
    """
    env = os.environ if environ is None else environ
    local = env.get("LOCALAPPDATA")
    if local:
        # LOCALAPPDATA means this is a Windows-shaped environment even when
        # the Python runtime calls itself cygwin or msys.  Do not fall through
        # to the host's app bundles when that explicit install root is empty:
        # on a Mac that would make an isolated Windows lookup unexpectedly find
        # ChatGPT Desktop in /Applications.
        cached = newest_install(pathlib.Path(local))
        # CODEX_CLI_PATH bypasses Desktop's normal bundle relocation. The cache
        # can therefore contain only last week's build even after an update.
        # Prefer the relocated copy on equal timestamps.
        bundled = _newest(_windows_bundled(env))
        if bundled is None:
            return cached
        try:
            return bundled if cached is None or \
                bundled.stat().st_mtime > cached.stat().st_mtime else cached
        except OSError:
            return cached
    where = platform or sys.platform
    if where == "win32":
        return None
    return _newest(_bundled(env, "darwin" if where == "darwin" else "linux"))


def _windows_bundled(environ):
    """Store-installed Desktop resources, using only the supplied environment."""
    base = environ.get("ProgramW6432") or environ.get("ProgramFiles")
    if base:
        try:
            yield from pathlib.Path(base).glob(
                "WindowsApps/OpenAI.*/app/resources/codex.exe")
        except OSError:
            return


def codex_cli(environ=None):
    """The real codex executable, or None.

    `CONPACT_CODEX_REAL` wins, because it is the user saying which build to use
    and nothing should second-guess that. Then CODEX_CLI_PATH - Codex sets it in
    its own config for the tools it launches - then the newest of the
    per-version install folders, then whatever is on PATH; and each of those is
    resolved through the sidecar shim, so a machine where the shim is installed
    still hands our own tooling the real codex rather than the interposer.
    """
    env = os.environ if environ is None else environ
    pinned = env.get(REAL_CODEX_ENV)
    if isinstance(pinned, str) and pinned.strip() and pathlib.Path(pinned).is_file():
        return pathlib.Path(pinned)       # said outright; not resolved any further
    named = env.get(CLI_VAR)
    if isinstance(named, str) and named.strip() and pathlib.Path(named).is_file():
        resolved = _through_sidecar(pathlib.Path(named), env)
        if resolved is not None:
            return resolved
    newest = newest_build(env)
    if newest is not None:
        return _through_sidecar(newest, env)
    # Resolve against the supplied environment, not this process's PATH.  The
    # callers use an isolated environment to decide whether an app-server can
    # be started; borrowing the host PATH could select an unrelated CLI.
    found = shutil.which("codex", path=env.get("PATH"))
    return _through_sidecar(pathlib.Path(found), env) if found else None


class AppServer:
    """A JSON-RPC conversation with one `codex app-server` over stdio.

    Notifications (no `id`) stream in among the responses, so a reply is matched
    by id and everything else is dropped. Reading runs on its own thread because
    a pipe read on Windows cannot be given a timeout.
    """

    def __init__(self, process):
        self.process = process
        self.inbox: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.inbox.put(json.loads(line))
                except ValueError:
                    continue
        except (OSError, ValueError):
            pass
        finally:
            self.inbox.put(None)                     # the stream ended

    def request(self, method: str, params: dict, timeout: float) -> dict:
        """Send one request and return its reply, or raise TimeoutError."""
        request_id = str(uuid.uuid4())
        body = json.dumps({"id": request_id, "method": method, "params": params}) + "\n"
        self.process.stdin.write(body)
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"the app-server did not reply to {method} in time")
            message = self.inbox.get(timeout=remaining)
            if message is None:
                raise TimeoutError(f"the app-server closed its output during {method}")
            if isinstance(message, dict) and message.get("id") == request_id:
                return message

    def close(self):
        for shut in (self.process.stdin.close, self.process.terminate):
            try:
                shut()
            except OSError:
                pass


class WebSocketServer:
    """The same conversation as `AppServer`, over a localhost WebSocket.

    An app-server started with `--listen ws://IP:PORT` outlives the caller, so
    this is how a process reaches one it did not spawn. No reader thread is
    needed: a socket read can be given a deadline, which a Windows pipe read
    cannot.
    """

    def __init__(self, connection):
        self.connection = connection

    def request(self, method: str, params: dict, timeout: float) -> dict:
        request_id = str(uuid.uuid4())
        deadline = time.monotonic() + timeout
        self.connection.deadline = deadline
        self.connection.sock.settimeout(timeout)
        self.connection.send(json.dumps({"id": request_id, "method": method, "params": params}))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"the app-server did not reply to {method} in time")
            self.connection.sock.settimeout(remaining)
            message = json.loads(self.connection.recv())
            if isinstance(message, dict) and message.get("id") == request_id:
                return message

    def close(self):
        self.connection.close()


def connect_ws(host, port, token=None, timeout: float = HANDSHAKE_TIMEOUT,
               opener=None) -> WebSocketServer:
    """Open one conversation with an app-server that is already listening, and
    complete its handshake. Raises, like `connect`, so that each caller turns a
    failure into its own named outcome."""
    server = WebSocketServer(codex_ws.connect(host, port, RPC_PATH, token, timeout, opener))
    try:
        server.request(INITIALIZE, {"clientInfo": CLIENT, "capabilities": CAPABILITIES}, timeout)
    except BaseException:
        server.close()
        raise
    return server


def start_process(command, environ):
    """Start an app-server. Its stderr is discarded on purpose: the daemon logs
    to its own file, and a blocked stderr pipe would deadlock the reader."""
    return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            env=environ, bufsize=1)


def connect(cli, args=ARGS, environ=None, spawn=None,
            timeout: float = HANDSHAKE_TIMEOUT) -> AppServer:
    """Start one app-server on the given transport and complete its handshake.

    The handshake is part of connecting, not of the caller's work: a server that
    will not initialize is not a server, and every caller here would otherwise
    repeat the same two lines. Raises rather than returning a reason, because
    every caller already catches to turn a failure into its own named outcome.

    `spawn` defaults to None rather than to the real starter, so that the name is
    looked up on this module when the call is made: a default bound at import
    would sail straight past the conftest guard that stands for "no test starts
    a real app-server" (D-018).
    """
    starter = start_process if spawn is None else spawn
    server = AppServer(starter([str(cli), *args], environ))
    try:
        server.request(INITIALIZE, {"clientInfo": CLIENT, "capabilities": CAPABILITIES},
                       timeout)
    except BaseException:
        server.close()
        raise
    return server
