"""
@module conpact.codex_remote
@description Codex's own Remote Control, which is the ChatGPT Desktop
             counterpart of the switch Claude Code puts in a session's toolbar.
             The shape differs in a way that decides the whole design: on Claude
             a session offers *itself* over the bridge, while on Codex the thing
             offered is an **app-server**, which enrols with the backend as a
             *server* and is then driven by paired clients. So conPACT runs
             an app-server of its own (`codex_host`) and offers that, rather than
             depending on Codex's shared daemon - which will not start from the
             CLI ChatGPT Desktop installs, and listens on a socket Python on
             Windows cannot open.

             Everything here is one of two things: a read of state that changes
             nothing, or an action something explicitly asked for (D-019, D-021).
             Nothing runs from a hook or a watcher on its own, and nothing
             connects to the relay as a *client* - that half is a device-keyed
             credential behind a step-up authorisation, and D-032 stands.

             One fact is reported rather than worked around: the desktop app
             never shares an app-server with us on Windows. Its own launcher
             takes the shared socket only when `process.platform !== "win32"`, so
             a thread the desktop holds stays out of reach exactly as D-031 says,
             and enabling remote control here offers *our* threads, not its.
@input      the process environment, and (injected) the ways to reach our
            app-server
@output     a read-only status dict, and one outcome dict per action saying
            whether it was done and, when it was not, which named reason applies
@dependencies conpact.codex_appserver, conpact.codex_home,
              conpact.codex_host; stdlib: pathlib, sys
"""
from __future__ import annotations

import pathlib
import sys

from . import codex_appserver, codex_home, codex_host

# Codex's own shared daemon. We do not use it - see the module docstring - but
# `show` reports what is there, because "there is no socket" is the first thing
# anyone looking for one will check.
CONTROL_DIR = "app-server-control"
SOCKET = "app-server-control.sock"

# The daemon runs only from a *packaged* CLI - one whose folder carries this
# manifest. The copy ChatGPT Desktop installs does not, and says so: "this CLI
# has no complete local package; install a packaged Codex CLI or use the
# standalone installer". A listener of our own has no such requirement.
PACKAGE_MANIFEST = "codex-package.json"

# Served by the app-server itself. There is a CLI for some of these, but only on
# the daemon, so every one of them goes over our own listener instead.
STATUS_READ = "remoteControl/status/read"
ENABLE = "remoteControl/enable"
DISABLE = "remoteControl/disable"
PAIRING_START = "remoteControl/pairing/start"
PAIRING_STATUS = "remoteControl/pairing/status"
CLIENT_LIST = "remoteControl/client/list"
CLIENT_REVOKE = "remoteControl/client/revoke"

# Only the columns that say whether remote control is on and what this machine
# is called. The account and server ids in this table are credentials-adjacent
# and are never read, let alone logged; `environment_id` is, because
# `client/list` and `client/revoke` are refused without it - a scope, not a
# secret.
ENROLLMENT_SQL = (
    "select app_server_client_name, server_name, remote_control_enabled, "
    "updated_at, websocket_url, environment_id from remote_control_enrollments "
    "order by updated_at desc"
)

# Measured from the app-server's own refusals: "remote control client list
# requires environmentId", "limit must be between 1 and 100".
CLIENT_LIMIT = 100

# Why the desktop app does not share an app-server with us.
WINDOWS_STDIO = ("the desktop app takes the shared daemon's socket only when "
                 "platform is not win32, so on Windows it always runs its own "
                 "app-server as a stdio child")
SHARED = "the desktop app may share the daemon's socket when it is configured to"

# What `remoteControl/status/read` calls a server that is offering itself.
ENABLED = "enabled"

RPC_TIMEOUT = 60.0
ENROL_TIMEOUT = 180.0

NO_CLI = codex_host.NO_CLI
NO_HOST = codex_host.NOT_RUNNING
NOT_ENROLLED = "not_enrolled"
FAILED = codex_host.FAILED

NOT_DONE = {
    NO_CLI: codex_host.NOT_DONE[NO_CLI],
    NO_HOST: codex_host.NOT_DONE[NO_HOST],
    NOT_ENROLLED: "this machine has never enrolled for remote control, so it has no environment",
    FAILED: "the app-server refused or did not answer",
}


def control_dir(environ=None) -> pathlib.Path:
    return codex_home.home(environ) / CONTROL_DIR


def socket_path(environ=None) -> pathlib.Path:
    """Where Codex's shared daemon would listen. AF_UNIX, which Python on Windows
    cannot open - one of the two reasons we run our own listener instead."""
    return control_dir(environ) / SOCKET


def desktop_shares_daemon(platform=None) -> tuple[bool, str]:
    """Whether ChatGPT Desktop would share an app-server with us, and why not.

    Measured from the app's own launcher, not assumed: the first conjunct of the
    condition that picks the shared socket is `process.platform !== "win32"`.
    """
    name = sys.platform if platform is None else platform
    if str(name).startswith("win"):
        return False, WINDOWS_STDIO
    return True, SHARED


def packaged(environ=None) -> bool:
    """Whether the codex executable we found is a packaged CLI, which is what
    Codex's own daemon requires. Read from the manifest beside it rather than by
    running the daemon and watching it refuse."""
    cli = codex_appserver.codex_cli(environ)
    if cli is None:
        return False
    try:
        return (pathlib.Path(cli).parent / PACKAGE_MANIFEST).is_file()
    except OSError:
        return False


def enrollment(environ=None):
    """What the backend knows this machine as, or None when it has never
    enrolled. Read `mode=ro` from Codex's own state store (D-030)."""
    rows = codex_home.rows(codex_home.state_db(environ), ENROLLMENT_SQL)
    if not rows:
        return None
    row = rows[0]
    url = row.get("websocket_url") or ""
    return {
        "client_name": row.get("app_server_client_name") or "",
        "server_name": row.get("server_name") or "",
        "enabled": bool(row.get("remote_control_enabled")),
        "updated_at": row.get("updated_at"),
        "host": url.split("/")[2] if "//" in url else "",
        "environment_id": row.get("environment_id") or "",
    }


def _outcome(done: bool, reason=None, detail=None) -> dict:
    return {"done": done, "reason": reason, "detail": detail,
            "message": None if done else (NOT_DONE.get(reason) or "not done")}


def _exists(path) -> bool:
    try:
        return pathlib.Path(path).exists()
    except OSError:
        return False


def status(environ=None, asker=None, platform=None, opener=None) -> dict:
    """Everything about remote control on this machine that can be read without
    changing it - the Codex counterpart of the readiness report's "remote NO" for
    a Claude session. `needs` is the list a caller shows: what is still missing
    before this machine can be driven remotely."""
    cli = codex_appserver.codex_cli(environ)
    enrolled = enrollment(environ)
    ours = codex_host.running(environ, asker)
    shares, why = desktop_shares_daemon(platform)
    # The enrolment row is what the *machine* has registered - it is the
    # desktop's, not ours - so whether remote control is on is asked of our own
    # server whenever it is up, and only guessed from the row when it is not.
    mine = remote_status(environ, opener) if ours["ready"] else None
    said = mine["detail"] if (mine and mine["done"] and isinstance(mine["detail"], dict)) else None
    offered = said.get("status") if said else None
    needs = []
    if cli is None:
        needs.append(NO_CLI)
    if not ours["ready"]:
        needs.append("host")
    # A server that is up but will not say counts as not offering: reporting
    # "ready" from the enrolment row is exactly the mistake this replaced.
    offers = (offered == ENABLED) if ours["ready"] else bool(enrolled and enrolled["enabled"])
    if not offers:
        needs.append("remote_control")
    return {
        "offered": offered,
        "cli": str(cli) if cli is not None else None,
        "packaged": packaged(environ),
        "host": ours,
        "record": str(codex_host.record_path()),
        "daemon_socket": str(socket_path(environ)),
        "daemon_socket_present": _exists(socket_path(environ)),
        "enrolled": enrolled is not None,
        "enabled": bool(enrolled and enrolled["enabled"]),
        "server_name": (enrolled or {}).get("server_name") or None,
        "client_name": (enrolled or {}).get("client_name") or None,
        "remote_host": (enrolled or {}).get("host") or None,
        "desktop_shares_daemon": shares,
        "desktop_detail": why,
        "needs": needs,
        "ready": not needs,
    }


def start(environ=None, **how) -> dict:
    """Start our own app-server. It listens on loopback only and refuses every
    caller that does not hold the token it was started with."""
    return codex_host.start(environ, **how)


def stop(environ=None, **how) -> dict:
    return codex_host.stop(environ, **how)


def _ask(server, method, params, timeout=RPC_TIMEOUT) -> dict:
    """One call on an open server, as an outcome."""
    try:
        reply = server.request(method, params, timeout)
    except (OSError, ValueError, TimeoutError) as problem:
        return _outcome(False, FAILED, f"{type(problem).__name__}: {problem}")
    if "error" in reply:
        return _outcome(False, FAILED, reply["error"])
    return _outcome(True, detail=reply.get("result"))


def _call(method, params, environ, opener, timeout=RPC_TIMEOUT) -> dict:
    """Open our app-server, make one call, close it."""
    server, refused = codex_host.open_server(environ, opener)
    if refused is not None:
        return _outcome(False, refused["reason"], refused["detail"])
    try:
        return _ask(server, method, params, timeout)
    finally:
        server.close()


def remote_status(environ=None, opener=None) -> dict:
    """What our app-server says about its own remote control - not the same
    question as `status`, which describes the machine."""
    return _call(STATUS_READ, {}, environ, opener)


def enable(environ=None, opener=None) -> dict:
    """Offer this app-server for remote control. It enrols with the backend under
    the user's ChatGPT account, so nothing calls this without an explicit
    action."""
    return _call(ENABLE, {}, environ, opener, ENROL_TIMEOUT)


def disable(environ=None, opener=None) -> dict:
    return _call(DISABLE, {}, environ, opener, ENROL_TIMEOUT)


def pairing_code(environ=None, opener=None) -> dict:
    """A short-lived code that pairs one client to this app-server. The code is
    the user's to type into their own client; it is returned, never stored."""
    return _call(PAIRING_START, {}, environ, opener, ENROL_TIMEOUT)


def pairing_status(code, manual=False, environ=None, opener=None) -> dict:
    """Has a code been claimed yet? The app-server takes one of the two kinds and
    refuses both at once."""
    key = "manualPairingCode" if manual else "pairingCode"
    return _call(PAIRING_STATUS, {key: code}, environ, opener)


def _environment_of(server, environ):
    """The environment the paired clients live in, or a named refusal.

    The server we are talking to knows its own, and that is the one its client
    list is scoped to; the enrolment row is the fallback for a server that has
    not settled one yet. Asking without it only earns "missing field
    `environmentId`", so a machine that has neither is told so instead.
    """
    asked = _ask(server, STATUS_READ, {})
    if not asked["done"]:
        # The connection is the same one the next call would use, so a server
        # that cannot answer this is not a machine with no environment.
        return None, asked
    live = asked["detail"].get("environmentId") if isinstance(asked["detail"], dict) else None
    if isinstance(live, str) and live:
        return live, None
    enrolled = enrollment(environ)
    if enrolled and enrolled["environment_id"]:
        return enrolled["environment_id"], None
    return None, _outcome(False, NOT_ENROLLED)


def _scoped(method, params, environ, opener) -> dict:
    """One call that has to name an environment, on one connection with the call
    that finds out which one."""
    server, refused = codex_host.open_server(environ, opener)
    if refused is not None:
        return _outcome(False, refused["reason"], refused["detail"])
    try:
        where, denied = _environment_of(server, environ)
        if denied is not None:
            return denied
        return _ask(server, method, {**params, "environmentId": where})
    finally:
        server.close()


def clients(environ=None, opener=None, limit: int = CLIENT_LIMIT) -> dict:
    """Every client paired to our app-server."""
    return _scoped(CLIENT_LIST, {"limit": limit}, environ, opener)


def revoke(client_id, environ=None, opener=None) -> dict:
    """Unpair one client, by the id `clients` reports."""
    return _scoped(CLIENT_REVOKE, {"clientId": client_id}, environ, opener)
