"""
@module tests.window_process
@description Running a real window in a process of its own, with a throwaway
             home, for the on-screen tests (`real_ui`) of both window modules.
             Its limits time the window, not the start-up. The window's own
             limit starts once the child has imported what it needs, and starts
             again, whole, once the child's first Tk root exists: creating Tk
             is start-up too, bounded only by the start-up limit, counted from
             the child's launch. Past either limit the child prints every
             thread's stack and exits, so a window that never closes fails the
             test and says where it was stuck. Under load, starting Python and
             importing conpact took 13 to 15 seconds (2026-09-23), and creating
             Tk 7 to 16 (2026-09-24), so a limit counting either made a healthy
             window fail (CU-20260924-062, CU-20260924-066).
@input      the test's tmp_path, the child's code, and the start-up code to run
            before the window's clock starts
@output     subprocess.CompletedProcess, text, with stdout and stderr captured
@dependencies stdlib: os, pathlib, subprocess, sys, time
"""
import os
import pathlib
import subprocess
import sys
import time

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
WINDOW_SECONDS = 30
START_SECONDS = 120

# Run in the child after its start-up code. Tk's first root restarts the
# window's clock; while it is being created only the start-up limit applies.
CLOCK = """
import faulthandler as _faulthandler
import time as _time
_faulthandler.dump_traceback_later({window}, exit=True)
try:
    import tkinter as _tkinter
except ImportError:
    _tkinter = None
if _tkinter is not None:
    _create_tk = _tkinter.Tk.__init__
    _tk_made = []
    def _tk_with_the_window_clock(self, *args, **kwargs):
        if _tk_made:
            return _create_tk(self, *args, **kwargs)
        _tk_made.append(True)
        _faulthandler.dump_traceback_later(max(1.0, {start_ends} - _time.time()), exit=True)
        try:
            return _create_tk(self, *args, **kwargs)
        finally:
            _faulthandler.dump_traceback_later({window}, exit=True)
    _tkinter.Tk.__init__ = _tk_with_the_window_clock
"""


def run(tmp_path, code, start, window_seconds=WINDOW_SECONDS, start_seconds=START_SECONDS):
    """Run `start`, then give `code` window_seconds to finish, counted again
    from its first Tk root, in a child whose home is tmp_path. If it hangs the
    child ends itself, so the window cannot stay on screen."""
    env = {**os.environ, "USERPROFILE": str(tmp_path), "HOME": str(tmp_path), "PYTHONPATH": SRC,
           "PYTHONIOENCODING": "utf-8"}
    clock = CLOCK.format(window=window_seconds, start_ends=repr(time.time() + start_seconds))
    return subprocess.run([sys.executable, "-c", f"{start}\n{clock}\n{code}"], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=start_seconds + window_seconds)
