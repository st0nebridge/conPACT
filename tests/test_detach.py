"""Tests for conpact.detach: starting a background process that outlives the hook."""
import os
import subprocess
import sys
import types

import pytest

from conpact import detach as dt

pytestmark = pytest.mark.real_spawn


def test_windowless_python_prefers_pythonw_next_to_the_interpreter(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    assert dt.windowless_python(str(exe)) == str(tmp_path / "pythonw.exe")


def test_windowless_python_falls_back_to_the_interpreter(tmp_path):
    exe = tmp_path / "python.exe"
    assert dt.windowless_python(str(exe)) == str(exe)
    assert dt.windowless_python() in (sys.executable, os.path.join(os.path.dirname(sys.executable), "pythonw.exe"))


def _recorder(fail_when=lambda kw: False):
    calls = []

    def popen(argv, **kw):
        calls.append((argv, kw))
        if fail_when(kw):
            raise OSError("access denied")
        return types.SimpleNamespace(pid=42)
    return calls, popen


def test_flags():
    assert (dt.DETACHED_PROCESS, dt.CREATE_NEW_PROCESS_GROUP, dt.CREATE_BREAKAWAY_FROM_JOB) == (
        0x00000008, 0x00000200, 0x01000000)


def test_spawn_on_windows_detaches_breaks_away_and_holds_no_std_handles():
    calls, popen = _recorder()
    assert dt.spawn(["prog", "arg"], env={"X": "1"}, popen=popen, os_name="nt") == 42
    [(argv, kw)] = calls
    assert argv == ["prog", "arg"]
    assert kw == {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "close_fds": True, "env": {"X": "1"},
                  "creationflags": 0x00000008 | 0x00000200 | 0x01000000}


def test_spawn_retries_without_breakaway_when_the_job_forbids_it():
    calls, popen = _recorder(lambda kw: kw["creationflags"] & 0x01000000)
    assert dt.spawn(["prog"], popen=popen, os_name="nt") == 42
    assert [kw["creationflags"] for _, kw in calls] == [0x01000208, 0x00000208]


def test_spawn_raises_when_it_cannot_start_at_all():
    calls, popen = _recorder(lambda kw: True)
    with pytest.raises(OSError):
        dt.spawn(["prog"], popen=popen, os_name="nt")
    assert len(calls) == 2


def test_spawn_elsewhere_starts_a_new_session():
    calls, popen = _recorder()
    assert dt.spawn(["prog"], popen=popen, os_name="posix") == 42
    [(_, kw)] = calls
    assert kw["start_new_session"] is True and "creationflags" not in kw
    assert kw["stdout"] is subprocess.DEVNULL and kw["close_fds"] is True


@pytest.mark.parametrize("outcome, alive", [(None, True), (PermissionError(), True),
                                            (ProcessLookupError(), False), (OSError(), False)])
def test_pid_alive_elsewhere_probes_with_signal_zero(outcome, alive):
    calls = []

    def kill(pid, sig):
        calls.append((pid, sig))
        if outcome is not None:
            raise outcome
    assert dt.pid_alive(123, os_name="posix", kill=kill) is alive
    assert calls == [(123, 0)]


def test_pid_alive_for_this_process_and_not_for_a_finished_one():
    assert dt.pid_alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert dt.pid_alive(proc.pid) is False
    assert dt.pid_alive(0) is False
    assert dt.pid_alive(-5) is False
