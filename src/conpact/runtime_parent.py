"""
@module conpact.runtime_parent
@description Resolve the MCP owner through verified Windows Python launchers.
@input OS process ancestry, this installation's interpreter and console entry
@output The immediate owner PID; unverified wrappers retain the direct parent
@dependencies conpact.win_process; stdlib: os, pathlib, re, sys
"""
import os
import pathlib
import re
import sys

from . import win_process


def _command(command):
    """Split the executable token from its untouched Windows argument tail."""
    match = re.fullmatch(r'\s*(?:"([^"]+)"|(\S+))(.*)', command or '')
    return ((match[1] or match[2]), match[3].strip()) if match else ('', '')


def _path(value):
    return str(value or '').replace('\\', '/').casefold()


def _same(one, other):
    """One executable: the same path, or two names for one file. The OS names an
    image by its real path; a launcher may be started through a junction."""
    if not (isinstance(one, str) and isinstance(other, str) and one and other):
        return False
    if _path(one) == _path(other):
        return True
    try:
        return os.path.samefile(one, other)
    except (OSError, ValueError):
        return False


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
        image = wrapper.get('ExecutablePath')
        if not _same(image, wrapper_exe):
            return parent
        if _same(image, python):
            transparent = bool(child_tail) and child_tail == wrapper_tail
        elif _same(image, entry):
            script, arguments = _command(child_tail)
            transparent = _same(script, entry) and arguments == wrapper_tail
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


def _read(snapshot=None):
    """This process and up to three OS ancestors, read in-process: nothing is
    started, so no window is shown and a busy machine cannot run it out of time."""
    snapshot = snapshot or win_process.snapshot
    rows, pid = [], os.getpid()
    while len(rows) < 4 and isinstance(pid, int) and pid > 0:
        row = snapshot(pid)
        if not row:
            break
        rows.append(row)
        pid = row['ParentProcessId']
    return rows


def owner(ppid, reader=None):
    """POSIX has no launcher intermediaries; Windows requires OS evidence."""
    if sys.platform != 'win32':
        return ppid
    entry = pathlib.Path(sys.prefix) / 'Scripts' / 'conpact-mcp.exe'
    redirector = sys.executable if sys.prefix != sys.base_prefix else ''
    return resolve((reader or _read)(), os.getpid(), ppid, redirector, str(entry))
