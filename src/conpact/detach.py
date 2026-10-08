"""
@module conpact.detach
@description Start a background process that outlives its parent and holds none
             of the parent's standard handles. The Stop hook must return at once:
             Claude Code waits for a hook's stdout/stderr to close, so a child
             that inherited them would hold the turn end open. On Windows the
             child is detached from the console, put in its own process group and
             broken away from any job object when the job allows it, and pythonw
             is preferred so no console window appears. Also answers whether a
             process is still running.
@input      an argv list and an environment
@output     the child's pid; a liveness answer for a pid
@dependencies stdlib: ctypes, os, subprocess, sys
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_TIMEOUT = 0x102


def windowless_python(executable: str | None = None) -> str:
    """pythonw.exe beside the interpreter if there is one, else the interpreter."""
    executable = executable or sys.executable
    candidate = os.path.join(os.path.dirname(executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else executable


def spawn(argv, env=None, popen=None, os_name=None) -> int:
    """Start argv detached and return its pid. Raises OSError if it cannot start."""
    popen = popen or subprocess.Popen
    common = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "close_fds": True, "env": env}
    if (os_name or os.name) != "nt":
        return popen(argv, start_new_session=True, **common).pid
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return popen(argv, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **common).pid
    except OSError:
        # A job that does not allow breakaway refuses the flag; start inside it.
        return popen(argv, creationflags=flags, **common).pid


def pid_alive(pid, os_name=None, kill=None) -> bool:
    """Whether a process with this pid is running. (Never probe with os.kill on
    Windows: there it terminates the process.)"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if (os_name or os.name) != "nt":
        try:
            (kill or os.kill)(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)
