"""
@module conpact.codex_cli_hook
@description Codex Stop-hook entry point for CLI tasks hosted by conPACT.
             Codex supplies the exact `session_id` on stdin. The hook acts only
             when its ancestor is the app-server recorded in
             `~/.conpact/codex-host.json`; the same global hook is therefore
             inert in ChatGPT Desktop and in ordinary `codex` sessions. A queued
             request is claimed and compacted at most once, otherwise the normal
             idle watch is armed for that CLI task. The hook never writes to
             stdout: Stop expects JSON there, and conPACT has no reason to
             continue or block the turn. Failures are logged by `run_one` and
             must never prevent Codex from finishing a response. Contributed by
             Lance Sandino.
@input      the Stop hook's JSON on stdin; the recorded app-server's pid
@output     at most one compaction, or an armed idle watch; nothing on stdout
@dependencies conpact.codex_arming, conpact.codex_host, conpact.codex_inject, conpact.compaction,
              conpact.detach, conpact.home;
              stdlib: json, os, pathlib, subprocess, sys, time
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

from . import codex_arming, codex_host, codex_inject, compaction, detach, home

STOP = "Stop"
MAX_ANCESTORS = 3
_READ_RECORD = object()


def _parent_pid(pid: int) -> int | None:
    """The parent of ``pid`` without a third-party process library."""
    try:
        if sys.platform == "win32":
            command = ("(Get-CimInstance Win32_Process -Filter \"ProcessId = "
                       f"{int(pid)}\").ParentProcessId")
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=3)
        else:
            done = subprocess.run(["ps", "-p", str(int(pid)), "-o", "ppid="],
                                  capture_output=True, text=True, timeout=3)
        parent = int((done.stdout or "").strip())
        return parent if parent > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def hosted_by_conpact(ppid: int | None = None, parent_reader=None, *, record=_READ_RECORD) -> bool:
    """Whether this hook descends from the one app-server conPACT recorded."""
    if record is _READ_RECORD:
        record = codex_host.read_record()
    target = record.get("pid") if record else None
    if not isinstance(target, int):
        return False
    current = os.getppid() if ppid is None else ppid
    parent = parent_reader or _parent_pid
    for _ in range(MAX_ANCESTORS):
        if current == target:
            return True
        current = parent(current)
        if current is None:
            break
    return False


def run(hook_input: dict, *, ppid: int | None = None, parent_reader=None, runner=None) -> dict:
    """Run the relevant Stop, returning a diagnostic for tests and logs."""
    if not isinstance(hook_input, dict) or hook_input.get("hook_event_name") != STOP:
        return {"action": "skip", "reason": "not a Stop hook"}
    if not hosted_by_conpact(ppid, parent_reader):
        return {"action": "skip", "reason": "not conPACT's app-server"}
    session_id = hook_input.get("session_id")
    if not compaction.is_valid_session_id(session_id):
        return {"action": "error", "reason": "Stop hook has no usable session id"}
    return (runner or codex_arming.run_one)(session_id, via="Codex Stop hook")


def main() -> int:
    try:
        home.migrate()
        payload = json.load(sys.stdin)
        detach_stop(payload)
    except Exception:
        pass
    return 0


def detach_stop(payload, spawner=None):
    """Return the Stop hook before the listener can start its next task.

    Waiting for compaction inside the Stop subprocess could hold the very turn
    whose completion allows that compaction to run. Ownership is checked here;
    the detached worker retains the ordinary exact-thread idle/generation checks.
    """
    if not isinstance(payload, dict) or payload.get("hook_event_name") != STOP:
        return {"action": "skip", "reason": "not a Stop hook"}
    record = codex_host.read_record()
    if not hosted_by_conpact(record=record):
        return {"action": "skip", "reason": "not conPACT's app-server"}
    session_id = payload.get("session_id")
    if not compaction.is_valid_session_id(session_id):
        return {"action": "error", "reason": "Stop hook has no usable session id"}
    env = dict(os.environ)
    env.pop(codex_inject.OWNER_ENV, None)
    if record is not None:
        env[codex_inject.OWNER_ENV] = str(record["pid"])
    root = str(pathlib.Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    argv = [detach.windowless_python(), "-m", "conpact.codex_arming", "--thread", session_id,
            "--ended-at-ns", str(time.time_ns()), "--after-stop"]
    try:
        pid = (spawner or detach.spawn)(argv, env=env)
        return {"action": "detached", "worker_pid": pid}
    except OSError as exc:
        return {"action": "error", "reason": str(exc)}


if __name__ == "__main__":
    raise SystemExit(main())
