"""
Regression test for CU-20261015-123: on a busy machine a Windows MCP server
bound its venv launcher instead of the process that started it.

The server's owner was read by starting PowerShell for four CIM queries, under
a 5-second limit, and a read that ran out of time returned nothing, so the
direct parent - the venv redirector - was kept. Measured 2026-10-15 on
Windows 11: 2.8-5.3 s idle, 5.0-6.5 s with 32 busy processes, every slow read
empty; test_real_venv_redirector_resolves_the_process_that_started_it failed
1 run in 4. The read is now made in-process, so it no longer waits for a
process to start. These tests make every process start fail as a timeout - what
load did to that PowerShell - and require the owner to be found anyway.
"""
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from conpact import runtime_parent as rp

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows launcher ancestry')

CHILD = '''\
import os
import subprocess


def timed_out(*args, **kwargs):
    raise subprocess.TimeoutExpired('a process start', 5)


subprocess.Popen = subprocess.run = timed_out
from conpact.mcp_tools import Context

print(Context.from_runtime().ppid, os.getppid())
'''


def _timed_out(*args, **kwargs):
    raise subprocess.TimeoutExpired('a process start', 5)


def test_the_ancestry_read_needs_no_process_to_start(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', _timed_out)
    monkeypatch.setattr(subprocess, 'run', _timed_out)
    rows = rp._read()
    assert [row['ProcessId'] for row in rows[:2]] == [os.getpid(), os.getppid()]
    assert rp._edge(rows[0], rows[1])


def test_a_venv_server_binds_its_starter_when_no_process_can_start(tmp_path):
    folder = tmp_path / 'environment with spaces'
    venv.EnvBuilder(with_pip=False).create(folder)
    script = folder / 'mcp child.py'
    script.write_text(CHILD, encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(Path(rp.__file__).resolve().parents[1]))
    done = subprocess.run([str(folder / 'Scripts' / 'python.exe'), str(script)],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    owner, redirector = map(int, done.stdout.split())
    assert redirector != os.getpid()
    assert owner == os.getpid()
