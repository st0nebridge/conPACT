"""
Regression test for CU-20260924-068 (the Stop-wrapper test times the hook
from its watcher, not from cmd.exe's launch).

`test_a_large_session_gets_a_detached_watcher_that_outlives_the_hook` runs the
real tools/stop_compact.cmd to show that the hook does not wait for the watcher
it starts. It checked that the wrapper returned within 15 seconds of being
launched, and on 2026-09-24, on a machine at 100% CPU, it failed in 16 of 24
copies of the suite ("assert 23.125 < 15"). Measured before changing it,
over 98 loaded runs: starting cmd.exe and Python took up to 19 seconds and
importing conpact up to 21, all before the hook had done anything; from the
moment the hook started its watcher to the moment the wrapper returned took a
median of 4 seconds, mostly starting the watcher and Python's and cmd.exe's
own exit, and past 15 once (21).

The contract:

  1. That test times the hook from `armed_at`, which the hook writes to the
     watch just before it starts the watcher, so a slow start-up does not fail
     it: run through a wrapper that spends 16 seconds before starting Python,
     it passes. Timed from the launch, it failed.
  2. A hook that does not return at once still fails it: run with a hook that
     waits 16 seconds after starting its watcher, it fails on its limit.

Both run the real test, with the real hook and a real detached watcher, through
a copy of the wrapper that differs only where it says.
"""
import os

import pytest

import test_stop_wrapper as wrapper_test

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the Stop-hook wrapper is a Windows .cmd")

HOOK_LINE = "python -m conpact.closure_hook"
SRC_LINK = "%~dp0..\\src"


def _wrapper_with(tmp_path, before_python="", python_line=HOOK_LINE):
    """A copy of stop_compact.cmd in tmp_path that runs `before_python` first and
    `python_line` in place of the hook's own; nothing else differs."""
    text = wrapper_test.WRAPPER.read_text(encoding="utf-8")
    assert text.count(HOOK_LINE) == 1 and text.count(SRC_LINK) == 1
    text = text.replace(SRC_LINK, str(wrapper_test.ROOT / "src")).replace(HOOK_LINE, before_python + python_line)
    copy = tmp_path / "stop_compact.cmd"
    copy.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))
    return copy


def _home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


def test_a_slow_start_up_does_not_fail_the_watcher_test(tmp_path, monkeypatch):
    # ping waits a second between its 17 echoes: 16 seconds before Python starts.
    slow = _wrapper_with(tmp_path, before_python="ping -n 17 127.0.0.1 >nul\n")
    monkeypatch.setattr(wrapper_test, "WRAPPER", slow)
    wrapper_test.test_a_large_session_gets_a_detached_watcher_that_outlives_the_hook(_home(tmp_path))


WAITING_HOOK = """
import sys
import time
from conpact import closure_hook, detach
_spawn = detach.spawn
def spawn_and_wait(*args, **kwargs):
    pid = _spawn(*args, **kwargs)
    time.sleep({seconds})  # a hook that waits on the watcher it has started
    return pid
detach.spawn = spawn_and_wait
sys.exit(closure_hook.main())
"""


def test_a_hook_that_waits_after_starting_its_watcher_still_fails_it(tmp_path, monkeypatch):
    shim = tmp_path / "waiting_hook.py"
    shim.write_text(WAITING_HOOK.format(seconds=wrapper_test.RETURNS_WITHIN + 1), encoding="utf-8")
    monkeypatch.setattr(wrapper_test, "WRAPPER", _wrapper_with(tmp_path, python_line=f'python "{shim}"'))
    with pytest.raises(AssertionError) as failed:
        wrapper_test.test_a_large_session_gets_a_detached_watcher_that_outlives_the_hook(_home(tmp_path))
    assert "RETURNS_WITHIN" in str(failed.traceback[-1].statement)     # its limit, not another check
