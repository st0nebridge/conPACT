"""
@module conpact.runtime_parent
@description Resolve the MCP owner through verified Windows Python launchers.
@input OS process ancestry, this installation's interpreter and console entry
@output The immediate owner PID; unverified wrappers retain the direct parent
@dependencies stdlib: json, os, pathlib, re, subprocess, sys
"""
import json
import os
import pathlib
import re
import subprocess
import sys


def _command(command):
    """Split the executable token from its untouched Windows argument tail."""
    match = re.fullmatch(r'\s*(?:"([^"]+)"|(\S+))(.*)', command or '')
    return ((match[1] or match[2]), match[3].strip()) if match else ('', '')


def _path(value):
    return str(value or '').replace('\\', '/').casefold()


def _edge(child, parent):
    """An observed parent must predate its child, including the final owner."""
    if not child or not parent or child.get('ParentProcessId') != parent.get('ProcessId'):
        return False
    born, before = child.get('CreationDate'), parent.get('CreationDate')
    return isinstance(born, str) and isinstance(before, str) and bool(before) and before <= born


def resolve(rows, pid, ppid, python, entry):
    """Follow at most two known wrappers, never search for a matching session."""
    records = {r['ProcessId']: r for r in rows if isinstance(r, dict) and 'ProcessId' in r}
    current, parent = pid, ppid
    seen = {pid}
    for _ in range(2):
        child, wrapper = records.get(current), records.get(parent)
        if not _edge(child, wrapper):
            return ppid
        _, child_tail = _command(child.get('CommandLine'))
        wrapper_exe, wrapper_tail = _command(wrapper.get('CommandLine'))
        image = _path(wrapper.get('ExecutablePath'))
        if not image or image != _path(wrapper_exe):
            return parent
        if image == _path(python):
            transparent = bool(child_tail) and child_tail == wrapper_tail
        elif image == _path(entry):
            script, arguments = _command(child_tail)
            transparent = _path(script) == _path(entry) and arguments == wrapper_tail
        else:
            return parent
        if not transparent:
            return parent
        next_pid = wrapper.get('ParentProcessId')
        if not isinstance(next_pid, int) or next_pid <= 0 or next_pid in seen:
            return ppid
        seen.add(parent)
        current, parent = parent, next_pid
    return parent if _edge(records.get(current), records.get(parent)) else ppid


def _read():
    """Read only this process and three OS ancestors, without showing a window."""
    script = (f'$cursorPid={os.getpid()}; $rows=@(); '
              'for($i=0; $i -lt 4 -and $cursorPid -gt 0; $i++) {'
              '$p=Get-CimInstance Win32_Process -Filter "ProcessId=$cursorPid"; '
              'if(!$p){break}; $rows += $p | Select-Object ProcessId,ParentProcessId,'
              'ExecutablePath,CommandLine,@{Name="CreationDate";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}}; '
              '$cursorPid=$p.ParentProcessId }; ConvertTo-Json -InputObject @($rows) -Compress')
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, timeout=5,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        rows = json.loads(result.stdout)
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def owner(ppid, reader=None):
    """POSIX has no launcher intermediaries; Windows requires OS evidence."""
    if sys.platform != 'win32':
        return ppid
    entry = pathlib.Path(sys.prefix) / 'Scripts' / 'conpact-mcp.exe'
    redirector = sys.executable if sys.prefix != sys.base_prefix else ''
    return resolve((reader or _read)(), os.getpid(), ppid, redirector, str(entry))
