"""
@module conpact.codex_sidecar
@description The program ChatGPT Desktop runs instead of `codex`, so conPACT
             can reach the app-server that holds a *live* thread's writer lock.

             A Codex rollout may only be written by the app-server holding its
             per-thread lock, and the desktop holds that lock for every thread it
             has open - which is exactly the thread worth compacting. That
             app-server is a stdio child with no socket, so its stdin is the only
             way in, and the only supported way into that stdin is to be the
             executable the desktop launches: its own resolver takes
             `CODEX_CLI_PATH` ahead of the bundled binary.

             So: run the real codex with the arguments we were handed, proxy both
             pipes faithfully, and offer one control connection on which
             conPACT submits a JSON-RPC request. What we inject carries a
             per-process id tag; its reply is lifted out of the stream and handed
             back to the asker, so the desktop never sees a response to an id it
             did not send. Everything else is copied byte for byte, except an
             explicit HTTP provider opt-in selecting that provider on resumes
             and forks of known OpenAI histories (codex_transport).

             This is one implementation for all three platforms, which is why it
             is Python. The control channel is a loopback TCP socket guarded by a
             capability token rather than a named pipe or a Unix socket, because
             that is the one shape that behaves identically everywhere and it is
             the boundary this project already uses for its own app-server
             (D-20260922-034): the port is bound to 127.0.0.1, the token is read
             from a record in the user's home, and a connection that does not
             present it is closed before a byte of it is forwarded. On Windows
             the desktop can only launch a real executable, so a small native
             launcher (`src/sidecar/codex_launcher.c`) execs this module; it
             carries no logic of its own.

             It fails open wherever it can. Anything that is not the desktop's
             stdio app-server is run straight through and never proxied; a
             control socket that cannot be created is simply absent, and the
             proxy still runs; a control client that goes away is dropped without
             holding up the stream.
@input      argv (handed to the real codex verbatim), CONPACT_CODEX_REAL or
            real-codex.txt beside the shim, and one authenticated client
@output     the child's exit code, and a record naming the port, the token and
            the id tag
@dependencies conpact.codex_active, conpact.codex_appserver,
              conpact.codex_sidecar_log, conpact.codex_sidecar_control, conpact.codex_inject,
              conpact.codex_turns, conpact.codex_transport, conpact.detach (lazily), conpact.home;
              stdlib: hmac, json, os, pathlib,
              secrets, socket, subprocess, sys, threading, time, uuid
"""
from __future__ import annotations

import hmac
import json
import os
import pathlib
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid

from . import codex_active, codex_appserver, codex_inject, codex_sidecar_log, codex_turns, codex_transport, home
from .codex_appserver import REAL_CODEX_MARKER
from .codex_sidecar_control import Control, IO_SECONDS

REAL_ENV = codex_appserver.REAL_CODEX_ENV   # one name, one lever
# The variable the desktop resolves codex through, and which install points at
# this shim. The child must not inherit it still pointing here.
CLI_ENV = "CODEX_CLI_PATH"
# The launcher names its own folder here: started as `python -m`, argv[0] is this
# file inside the package, not the shim beside the marker.
DIR_ENV = "CONPACT_SIDECAR_DIR"
RECORD = "codex-sidecar.json"
HOST = "127.0.0.1"
CHUNK = 65536

# A sub-command of its own, or a listener, is not the desktop's stdio app-server
# and is never proxied - `--listen` is how conPACT starts one of its own.
NOT_OURS = ("proxy", "daemon")


def is_desktop_app_server(argv) -> bool:
    """`codex app-server` with no listener and no sub-command under it."""
    seen = False
    for arg in argv:
        if arg in ("--listen", "--stdio") or arg.startswith("--listen="):
            return False
        if seen and (arg in NOT_OURS or arg.startswith("generate-")):
            return False
        if arg == "app-server":
            seen = True
    return seen


def shim_dir(environ=None) -> pathlib.Path:
    """Where the marker naming the real codex lives: the folder the launcher
    names, else the folder we were started from."""
    env = os.environ if environ is None else environ
    named = env.get(DIR_ENV)
    if named:
        return pathlib.Path(named)
    return pathlib.Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] \
        else pathlib.Path.cwd()


def real_codex(environ=None, beside=None):
    """The explicit pin, newest installed build, then the marker as fallback.

    The marker is written once at install, so it must not hold the desktop on
    an older build which Codex may prune after this process has launched it.
    CODEX_CLI_PATH is never resolved here: it points at this shim.
    """
    env = os.environ if environ is None else environ
    marker = (beside or shim_dir(env)) / REAL_CODEX_MARKER
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    found = codex_appserver.selected_build(text, env)
    return str(found) if found is not None else None


def tag_for(pid: int) -> str:
    """The prefix every id we inject carries. It is the *value* prefix, not
    `"id":"..."`, so a reply matches whatever spacing the app-server writes."""
    return f"conpact-{pid}-"


def record_path(home=None) -> pathlib.Path:
    base = pathlib.Path(home) if home else pathlib.Path(os.path.expanduser("~"))
    return base / ".conpact" / RECORD


def write_record(port: int, token: str, pid: int, tag: str, home=None, parent_pid=None) -> None:
    """Where to reach us and what to say. Written with the parents created:
    the first conPACT file on a machine may well be this one."""
    path = record_path(home)
    record = {"address": f"{HOST}:{port}", "token": token, "pid": pid, "tag": tag}
    paths = [path]
    if parent_pid is not None:
        record["parent_pid"] = parent_pid
        paths.insert(0, path.parent / codex_inject.OWNERS / f"{parent_pid}.json")
    for target in paths:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(record), encoding="utf-8")
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


class Lifter:
    """The child's stdout, split into whole lines, each labelled with where it
    belongs: a line carrying our tag is a reply to something we injected and goes
    back to the control client; every other byte is the desktop's and is passed
    on untouched. Bytes are held only until the newline that ends their line."""

    def __init__(self, tag: str):
        self.tag = tag
        self.held = b""

    def feed(self, chunk: bytes):
        """[(ours, line)] for every complete line in `chunk`. A line keeps its
        newline when it is the desktop's, so the stream stays byte-faithful, and
        loses it when it is ours, because the client reads by line."""
        out = []
        self.held += chunk
        while b"\n" in self.held:
            line, _, self.held = self.held.partition(b"\n")
            try:
                message = json.loads(line)
                request_id = message.get("id") if isinstance(message, dict) else None
                ours = isinstance(request_id, str) and request_id.startswith(self.tag)
            except (ValueError, UnicodeDecodeError):
                ours = False
            out.append((True, line) if ours else (False, line + b"\n"))
        return out

    def rest(self) -> bytes:
        """Whatever never got its newline, at end of stream."""
        held, self.held = self.held, b""
        return held


def greet(token: str, first: bytes):
    """A client's first line is its token. Returns whatever it sent after that
    line, or None when it did not present the right one - compared in constant
    time, and nothing it sent is forwarded either way."""
    if b"\n" not in first:
        return None
    offered, _, rest = first.partition(b"\n")
    return rest if hmac.compare_digest(offered.strip(), token.encode("utf-8")) else None


def write_all(write, data: bytes) -> bool:
    """Write every byte, or say it could not.

    Both `os.write` and an unbuffered file object may take fewer bytes than
    offered and report how many; discarding that number truncates the message,
    and a truncated JSON-RPC line is not a slow reply but a broken one.
    """
    at = 0
    while at < len(data):
        try:
            wrote = write(data[at:])
        except (OSError, ValueError):
            return False
        if wrote is None:             # some file objects report nothing back
            return True               # and write everything they are given
        if wrote <= 0:                # took nothing: looping would never end
            return False
        at += wrote
    return True


def _write_child(child_stdin, lock, chunk) -> bool:
    with lock:
        try:
            if not write_all(child_stdin.write, chunk):
                return False
            child_stdin.flush()
            return True
        except (OSError, ValueError):
            return False


def _whole_lines(read, keep_tail=False):
    """Buffer one source until a complete JSON-RPC line can be written atomically."""
    held = b""
    while True:
        chunk = read(CHUNK)
        if not chunk:
            break
        held += chunk
        while b"\n" in held:
            line, _, held = held.partition(b"\n")
            yield line + b"\n"
    if keep_tail and held:
        yield held


def pump_to_child(read, child_stdin, lock, tap=None, transform=None) -> None:
    """The Desktop stream, with injection allowed only between whole lines."""
    for line in _whole_lines(read, keep_tail=True):
        if transform is not None:
            line = transform(line)
        if not _write_child(child_stdin, lock, line):
            return
        if tap is not None:                # after the write: the stream comes first
            tap.note(codex_sidecar_log.TO_CODEX, line)
    with lock:
        try:
            child_stdin.close()           # the desktop closed its side
        except (OSError, ValueError):
            pass


ARM_MODULE = "conpact.codex_arming"


def arm_on_turn_end(thread_id: str, spawner=None, environ=None, owner_pid=None) -> int | None:
    """Start the arming for one thread, detached, and return at once.

    Detached and out of process on purpose: this runs on the pump that carries
    the desktop's own traffic, so it must cost a spawn and nothing else. A
    failure to start is swallowed - the sweep is what makes that safe.
    """
    from . import detach
    env = dict(os.environ if environ is None else environ)
    env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1]) +         (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop(CLI_ENV, None)              # the arming must not re-enter the shim
    env.pop(codex_inject.OWNER_ENV, None)
    if owner_pid is not None:
        env[codex_inject.OWNER_ENV] = str(owner_pid)
    argv = [detach.windowless_python(), "-m", ARM_MODULE, "--thread", thread_id,
            "--ended-at-ns", str(time.time_ns())]
    try:
        return (spawner or detach.spawn)(argv, env=env)
    except Exception:
        return None


def pump_to_desktop(read, write, lifter, control, tap=None, turns=None, arm=None,
                    publish=None) -> None:
    """The real app-server -> the desktop, minus the replies we asked for.

    `publish` is told the in-flight set whenever it changes, and only then: it
    is how an MCP server started by Codex finds out which thread is asking,
    since Codex tells it nothing (`codex_active`).
    """
    published = None
    while True:
        chunk = read(CHUNK)
        if not chunk:
            break
        for ours, line in lifter.feed(chunk):
            if ours:
                control.give(line)
                if tap is not None:
                    tap.note(codex_sidecar_log.LIFTED, line + b"\n")
                continue
            if not write_all(write, line):
                return
            if tap is not None:
                tap.note(codex_sidecar_log.TO_DESKTOP, line)
            if turns is not None:
                # After the desktop's byte is out: the stream is never held up
                # for ours, and a turn that ended a millisecond ago is still a
                # turn that ended.
                ended = turns.note(line)
                if publish is not None:
                    state = (turns.in_flight(), turns.calling(), turns.calling_tools())
                    if state != published:
                        published = state
                        try:
                            publish(state[0], state[1])
                        except Exception:
                            pass        # knowing who is asking is not worth a pipe
                if ended is not None and arm is not None:
                    try:
                        arm(ended)
                    except Exception:
                        pass            # the notifier must not cost the desktop

    tail = lifter.rest()
    if tail:
        write_all(write, tail)


CONTROL_IO_SECONDS = IO_SECONDS
CONTROL_IDLE_SECONDS = 660.0   # includes the compaction client's 600-second wait


def serve_control(server, control, child_stdin, lock, token) -> None:
    """Accept one control client at a time, check its token, and forward what it
    writes into the app-server's stdin. A client that goes away is dropped; the
    stream is never held up for it."""
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        try:
            conn.settimeout(CONTROL_IO_SECONDS)
            opening = b""
            stop = time.monotonic() + CONTROL_IO_SECONDS
            while b"\n" not in opening and len(opening) < CHUNK:
                remaining = stop - time.monotonic()
                if remaining <= 0:
                    break
                conn.settimeout(remaining)
                chunk = conn.recv(CHUNK)
                if not chunk:
                    break
                opening += chunk
        except OSError:
            opening = b""
        rest = greet(token, opening)
        if rest is None:
            try:
                conn.close()
            except OSError:
                pass
            continue
        control.adopt(conn)
        idle_stop = time.monotonic() + CONTROL_IDLE_SECONDS

        def read_control(_):
            nonlocal rest, idle_stop
            if rest:
                chunk, rest = rest, b""
                return chunk
            while time.monotonic() < idle_stop:
                try:
                    chunk = conn.recv(CHUNK)
                    if chunk:
                        idle_stop = time.monotonic() + CONTROL_IDLE_SECONDS
                    return chunk
                except socket.timeout:
                    continue
                except OSError:
                    return b""
            return b""

        try:
            for line in _whole_lines(read_control):
                if not _write_child(child_stdin, lock, line):
                    return
        finally:
            control.release(conn)


def open_control():
    """A loopback listener on a port the system picks, or None - in which case
    the shim still proxies, it just cannot be injected into."""
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((HOST, 0))
        server.listen(1)
        return server
    except OSError:
        return None


def child_environment(exe: str, environ=None) -> dict:
    """The environment the real codex should run in.

    `CODEX_CLI_PATH` is how the desktop finds codex, and installing points it at
    this shim - so a child that inherited it unchanged would find the shim when
    it went looking for codex, and re-enter it. Codex spawns helpers of its own
    (the command runner, the code-mode host, bundled MCP servers), so this is
    not hypothetical. The child is handed the real path instead, which is both
    true and what it would have seen had the shim never been installed.
    """
    env = dict(os.environ if environ is None else environ)
    env[CLI_ENV] = exe
    return env


def passthrough(exe: str, args, environ=None) -> int:
    """Anything that is not the app-server: become the real codex. On POSIX that
    is an exec, so there is no extra process at all; on Windows, where there is
    no exec, it is a child we wait for and whose exit code we return."""
    argv = [exe] + list(args)
    env = child_environment(exe, environ)
    if hasattr(os, "execve") and os.name != "nt":
        try:
            os.execve(exe, argv, env)
        except OSError:
            pass
    return subprocess.call(argv, env=env)


def proxy(exe: str, args, home=None, read_in=None, write_out=None) -> int:
    """Run the real app-server under us and stand in its stdio path."""
    # Unbuffered by fd: a buffered read would hold a line back waiting for more.
    read = (lambda n: os.read(0, n)) if read_in is None else read_in
    write = (lambda data: os.write(1, data)) if write_out is None else write_out
    child = subprocess.Popen([exe] + list(args), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=None, bufsize=0,
                             env=child_environment(exe))
    pid = os.getpid()
    tag = tag_for(pid)
    lock = threading.Lock()
    control = Control()
    server = open_control()
    if server is not None:
        token = secrets.token_urlsafe(32)
        try:
            write_record(server.getsockname()[1], token, pid, tag, home, parent_pid=child.pid)
        except OSError:
            try:
                server.close()
            except OSError:
                pass
            server = None
    if server is not None:
        threading.Thread(target=serve_control,
                         args=(server, control, child.stdin, lock, token),
                         daemon=True).start()
    tapped = codex_sidecar_log.open_tap()
    to_codex, to_desktop, close_log = tapped if tapped else (None, None, None)
    turns = codex_turns.Turns()
    transport = codex_transport.load(args=args)
    threading.Thread(target=pump_to_child,
                     args=(read, child.stdin, lock, to_codex, transport), daemon=True).start()
    threading.Thread(target=pump_to_desktop,
                     args=(child.stdout.read, write, Lifter(tag), control, to_desktop,
                           turns, lambda tid: arm_on_turn_end(tid, owner_pid=child.pid),
                           lambda running, calling: codex_active.publish(
                               running, calling, home=home, parent_pid=child.pid,
                               calling_tools=turns.calling_tools())),
                     daemon=True).start()
    code = child.wait()
    for shut in (server.close if server is not None else None, close_log):
        if shut is not None:
            try:
                shut()
            except OSError:
                pass
    return code


def main(argv=None) -> int:
    home.migrate()
    args = list(sys.argv[1:] if argv is None else argv)
    exe = real_codex()
    if exe is None:
        sys.stderr.write("codex_sidecar: no real codex configured\n")
        return 1
    if not is_desktop_app_server(args):
        return passthrough(exe, args)
    return proxy(exe, args)


if __name__ == "__main__":       # pragma: no cover - the shim's entry point
    sys.exit(main())
