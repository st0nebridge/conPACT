"""
Regression test for CU-20261015-124: on a busy Windows machine the Codex CLI
Stop hook decided it was not below conPACT's app-server, and a Codex MCP server
could lose which surface started it.

Each read one process by starting PowerShell for a CIM query under a short
limit - 3 s for the hook's ancestor walk, 5 s for the MCP server's parent
command line - and gave up when it ran out. Measured 2026-10-15 on Windows 11
with 32 busy processes: the hook's read took 3.3-4.1 s and came back empty 4
times in 4, so hosted_by_conpact answered False; the command-line read took
3.8-5.4 s and came back empty once in 4, so surface() said unknown. Both now
read in-process through conpact.win_process. These tests make every process
start fail as a timeout - what load did to that PowerShell - and require the
right answer anyway.
"""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conpact import codex_caller, codex_cli_hook

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows process reads')


def _timed_out(*args, **kwargs):
    raise subprocess.TimeoutExpired('a process start', 5)


@pytest.fixture
def codex_child():
    """A child whose command line reads as Codex CLI's, started before starts are refused."""
    arguments = [sys.executable, '-c', 'import time; time.sleep(60)', 'codex', 'exec', '--json']
    child = subprocess.Popen(arguments, creationflags=subprocess.CREATE_NO_WINDOW)
    yield child, subprocess.list2cmdline(arguments)
    child.kill()
    child.wait()


def test_the_cli_hook_finds_the_recorded_app_server_when_no_process_can_start(monkeypatch, codex_child):
    child, _ = codex_child
    monkeypatch.setattr(subprocess, 'Popen', _timed_out)
    monkeypatch.setattr(subprocess, 'run', _timed_out)
    assert codex_cli_hook._parent_pid(child.pid) == os.getpid()
    assert codex_cli_hook.hosted_by_conpact(ppid=child.pid, record={'pid': os.getppid()}) is True


def test_the_mcp_server_reads_its_parents_command_when_no_process_can_start(monkeypatch, codex_child):
    child, command = codex_child
    monkeypatch.setattr(subprocess, 'Popen', _timed_out)
    monkeypatch.setattr(subprocess, 'run', _timed_out)
    parent_command = codex_caller.process_command(child.pid, runner=_timed_out)
    assert parent_command == command
    assert codex_caller.surface(SimpleNamespace(parent_command=parent_command, ppid=child.pid)) \
        == codex_caller.CODEX_CLI
