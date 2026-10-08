"""
@module conpact.codex_active
@description Which Codex threads are mid-turn right now, written by the sidecar
             and read by anything that needs to know who is asking.

             It exists because Codex tells an MCP server nothing about who
             called it. A Claude session's MCP server binds to its own session
             through the environment (`CLAUDE_CODE_SESSION_ID`) and the parent
             pid (D-20260919-012); a Codex MCP server is handed neither - three
             live MCP children were read on 2026-09-22 and none carried a thread
             id of any kind. So the identity has to come from the one process
             that can see it: the sidecar, which watches `turn/started` and
             `turn/completed` go past.

             A running turn alone cannot identify a tool caller. Only an open
             conPACT call observed on the owning app-server identifies one;
             absent or ambiguous calls refuse. Fail closed is the whole point - the failure
             worth avoiding is acting on a thread that did not ask, not
             declining one that did.

             A file rather than a new control verb, deliberately: the sidecar's
             control port exists to inject into an app-server's stdin, and a
             question answered by reading a file needs no port, no token and no
             new way in.

             A sidecar started before conPACT's state moved to ~/.conpact/
             (D-20260923-048) keeps writing to the old folder until ChatGPT
             Desktop restarts, so the default read takes whichever of the two
             records is fresher.
@input      the in-flight thread ids (from the sidecar), and a clock
@output     a small JSON record; and the one thread that may be bound, or a
            refusal saying why not
@dependencies conpact.compaction, conpact.home; stdlib: json, os, pathlib, time
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from . import compaction
from . import home as state_home

RECORD = "codex-active.json"

# A record older than this is not evidence of anything: the sidecar writes on
# every turn boundary, so a stale file means it died mid-turn or the machine
# slept. Binding to a turn that "started" an hour ago would be a guess.
MAX_AGE_SECONDS = 900.0
FOREIGN_PROCESS = ("conPACT cannot identify this caller from a sidecar owned "
                   "by another app-server process.")


def record_path(home=None) -> pathlib.Path:
    """Beside the rest of conPACT's state, not in Codex's own folders."""
    if home is not None:
        return pathlib.Path(home) / ".conpact" / RECORD
    return compaction.STATE_DIR / RECORD


def publish(threads, calling=(), home=None, clock=time.time, parent_pid=None,
            calling_tools=None) -> bool:
    """Write who is mid-turn and who is calling *us*.

    `calling` is the exact answer; `threads` is diagnostic only: the app-server
    names the thread on an `mcpToolCall` to our server, so when it is there the
    caller is stated rather than inferred. Returns whether it was written; never
    raises, because this runs on the sidecar's pump.
    """
    temporary = None
    try:
        path = record_path(home)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"threads": sorted(set(threads)),
                           "calling": sorted(set(calling)), "at": clock(),
                           "pid": os.getpid(), "parent_pid": parent_pid,
                           "calling_tools": calling_tools or {}})
        # Readers run in MCP processes while this writer runs in the sidecar.
        # Replacing a complete file keeps them from observing an empty or
        # partly-written JSON document between truncate and write.
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, path)
        return True
    except (OSError, ValueError, TypeError):
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _read_one(path: pathlib.Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("threads"), list):
        return None
    if not isinstance(data.get("at"), (int, float)):
        return None
    return data


def read(home=None) -> dict | None:
    """The record, or None when there is not a usable one. With no home named,
    the fresher of the current record and one a pre-move sidecar still writes."""
    if home is not None:
        return _read_one(record_path(home))
    found = [r for r in (_read_one(record_path()), _read_one(state_home.PREVIOUS / RECORD)) if r]
    return max(found, key=lambda r: r["at"]) if found else None


def sole_thread(home=None, clock=time.time, max_age: float = MAX_AGE_SECONDS,
                parent_pid=None, tool_name=None):
    """Bind one observed conPACT call, optionally requiring its owning process.

    The refusal text is what a tool shows the agent, so it says what is true
    rather than "unavailable".
    """
    data = read(home)
    if data is None:
        return None, ("conPACT cannot tell which Codex thread is asking: the "
                      "sidecar is not running, or has not seen a turn yet.")
    age = clock() - data["at"]
    if age > max_age:
        return None, (f"conPACT cannot tell which Codex thread is asking: the "
                      f"sidecar's last update was {round(age)} s ago.")
    if parent_pid is not None and data.get("parent_pid") != parent_pid:
        if data.get("parent_pid") is not None:
            return None, FOREIGN_PROCESS
        return None, "conPACT cannot identify this caller from an unrecorded app-server process."
    calls = data.get("calling", [])
    if tool_name:
        methods = data.get("calling_tools", {})
        calls = methods.get(tool_name, []) if isinstance(methods, dict) else []
    calling = [t for t in calls
               if isinstance(t, str) and t.strip()]
    if len(calling) == 1:
        return calling[0], None        # stated by the app-server, not inferred
    if len(calling) > 1:
        return None, (f"conPACT will not guess which of {len(calling)} threads "
                      f"calling it at once is asking.")
    threads = [t for t in data["threads"] if isinstance(t, str) and t.strip()]
    if not threads:
        return None, ("conPACT cannot tell which Codex thread is asking: no turn "
                      "is in flight, so nothing identifies the caller.")
    return None, ("conPACT cannot identify the caller: running turns do not "
                  "identify a conPACT tool call.")
