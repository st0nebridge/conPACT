"""
@module conpact.session_ready
@description Why a live session cannot be compacted yet, and what to do about
             it. Three things have to be true, and they fail in different ways:
             the Stop hook (installed once, in ~/.claude/settings.json, and read
             at every turn end, so it reaches sessions that were already open);
             the MCP server (a child process of the session, started only when
             the session's own process starts, so a session whose process is
             older than the registration simply has no tools); and Remote
             Control (a per-session switch - without it the record has no
             bridgeSessionId and nothing can be sent at all). This module only
             looks: it never sends to a session, changes a setting, or touches
             another session's state. The running processes are read with one
             PowerShell query on Windows and one `ps` on macOS and Linux.
@input      the live session records, the running processes, our two logs
@output     one row per session - what it has, what it needs, what fixes it
@dependencies stdlib: json, pathlib, subprocess, sys; conpact.closure_hook,
              conpact.idle_state, conpact.session_registry
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from . import closure_hook, idle_state, session_registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVER_MARK = "mcp_server"

# One call, filtered in the query: every process whose command line mentions an
# MCP server, with the parent that started it.
POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%mcp_server%'\" | "
              "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"]

# The same question on macOS and Linux: every process, its parent and its whole
# command line, with no header. `-A`, `-o` and the `=` that drops a header are
# POSIX, so one spelling serves both procps and BSD ps. `ps` cannot filter on
# the command line, so that happens here.
PS = ["ps", "-A", "-o", "pid=,ppid=,args="]

REMOTE_CONTROL_FIX = ("Turn Remote Control on for this session (the switch in its toolbar), "
                      "so its record gets a bridgeSessionId.")
MCP_FIX = "Reopen the session so its process loads the MCP server."


def _path_text(value) -> str:
    return str(value).replace("\\", "/").lower()


def server_pids(processes, root=None) -> dict[int, int]:
    """Session pid -> the pid of *this* checkout's MCP server running under it.

    A server from another checkout is not the one this Stop hook and toast use,
    so it does not count. Where a session somehow has two, the last one listed
    wins; nothing here depends on which.
    """
    wanted = _path_text(root or ROOT)
    found: dict[int, int] = {}
    for process in processes:
        if not isinstance(process, dict):
            continue
        pid, parent, command = process.get("pid"), process.get("parent"), process.get("command")
        if not isinstance(pid, int) or not isinstance(parent, int) or not isinstance(command, str):
            continue
        text = _path_text(command)
        if SERVER_MARK in text and wanted in text:
            found[parent] = pid
    return found


def last_hook_run(session_id, entries) -> str | None:
    """The newest timestamp either log holds for that session, if any."""
    stamps = [entry.get("ts") for entry in entries
              if isinstance(entry, dict) and entry.get("session_id") == session_id
              and isinstance(entry.get("ts"), str) and entry.get("ts")]
    return max(stamps) if stamps else None


def readiness(records, processes, entries, root=None) -> list[dict]:
    """One row per live session record, in the order the records were read."""
    servers = server_pids(processes, root)
    rows = []
    for record in records:
        pid = record.get("pid")
        if not isinstance(pid, int):
            continue
        remote_control = bool(record.get("bridgeSessionId"))
        mcp = pid in servers
        actions = []
        if not remote_control:
            actions.append(REMOTE_CONTROL_FIX)   # first: nothing works without it
        if not mcp:
            actions.append(MCP_FIX)
        rows.append({"name": record.get("name"), "pid": pid, "session_id": record.get("sessionId"),
                     "remote_control": remote_control, "mcp": mcp,
                     "hook": last_hook_run(record.get("sessionId"), entries),
                     "actions": actions, "ready": not actions})
    return rows


def _mark(ok: bool) -> str:
    return "yes" if ok else "NO "


def lines(rows) -> list[str]:
    """The report, as printed."""
    if not rows:
        return ["conPACT readiness: no live sessions to check.",
                "A session appears here once its process is running and has written its record."]
    ready = sum(1 for row in rows if row["ready"])
    out = [f"conPACT readiness: {ready} of {len(rows)} sessions ready", "",
           f"  {'session':<30} {'pid':>7}  {'remote':<7}{'mcp':<5}hook last seen"]
    for row in rows:
        out.append(f"  {str(row['name'])[:30]:<30} {row['pid']:>7}  "
                   f"{_mark(row['remote_control']):<7}{_mark(row['mcp']):<5}{row['hook'] or '-'}")
    for row in rows:
        if row["actions"]:
            out.append("")
            out.append(f"  {row['name']}:")
            out.extend(f"    - {action}" for action in row["actions"])
    if ready < len(rows):
        out += ["", "  The Stop hook needs no action: it is read at every turn end, so it already",
                "  reaches sessions that were open before it was installed. A hook that has not",
                "  been seen yet has simply had nothing to say."]
    return out


def log_entries() -> list[dict]:
    """Every entry in our two logs: the idle notifier's and the Stop hook's."""
    out = []
    for path in (idle_state.log_path(), closure_hook.LOG_PATH):
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
    return out


def _capture(argv, run=subprocess.run) -> str:
    """One query's stdout. One shot, and bounded: a query that hangs must not hang the report."""
    return run(argv, capture_output=True, text=True, timeout=30).stdout


def parse_ps(text) -> list[dict]:
    """`ps -o pid=,ppid=,args=` output, reduced to the MCP servers in it."""
    found = []
    for line in (text or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or SERVER_MARK not in parts[2]:
            continue
        try:
            pid, parent = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        found.append({"pid": pid, "parent": parent, "command": parts[2]})
    return found


def list_processes(runner=None, platform=None) -> list[dict]:
    """The running MCP servers and who started them. Unreadable means none."""
    if (platform or sys.platform) != "win32":
        try:
            return parse_ps((runner or _capture)(PS))
        except (OSError, ValueError, subprocess.SubprocessError):
            return []
    try:
        raw = (runner or _capture)(POWERSHELL)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [{"pid": row.get("ProcessId"), "parent": row.get("ParentProcessId"),
             "command": row.get("CommandLine")} for row in data if isinstance(row, dict)]


def main() -> int:
    rows = readiness(session_registry.load_records(), list_processes(), log_entries())
    print("\n".join(lines(rows)))
    return 0 if all(row["ready"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
