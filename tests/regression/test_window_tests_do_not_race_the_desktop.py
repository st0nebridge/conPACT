"""
Regression test for CU-20260924-062 (the window tests do not race the desktop).

Two tests of the settings window failed now and then, most often while the
machine was busy, and passed when run again. Each was racing something outside
the code it tests.

`test_show_centres_the_window_in_the_work_area` put a real window on screen and
read back from Windows where it had landed. On 2026-09-23 it read (-1904, 16)
instead of (-4730, -4186): 16 pixels inside the corner of the user's left
monitor. PowerToys FancyZones, with "move newly created windows to the current
active monitor" on, moves every window a process shows onto the monitor under
the cursor. It does this from its own process, a moment after the window
appears. Replayed with the cursor on that monitor, each window the test showed
was moved to exactly (-1904, 16). Tk's own move normally lands after
FancyZones' and wins; under load FancyZones' lands last. The same test and its
neighbour also took the keyboard from whatever the user was doing.

`test_the_real_window_shows_saves_and_closes` gave its child process 30 seconds
to show, save and close the window. Under load, starting Python and importing
conpact took 13 to 15 of them and creating Tk 5 more, so the child was killed
before its window had finished.

The contract:

  1. What `show()` asks of the window manager is read in the test, as D-023
     sets out, not watched on a screen: the window is never mapped, and nothing
     it does depends on where a window manager puts a shown window. Run under a
     stand-in window manager that moves every window the process shows, as
     FancyZones does, the position tests still pass and it moves none of their
     windows; a control test that reads a mapped window back shows the
     stand-in bites.
  2. An on-screen test's time limit times the window, not Python's start-up: a
     slow start-up does not fail it, and a window that never closes still fails
     within the limit, with its stack printed.

The first stand-in moved a window from Tk's own <Map> binding, which runs
only when a test lets Tk handle its events. The position tests never do, so it
could not see that they still showed their window for a moment, until the
view was built on a withdrawn root (CU-20260924-063). It now watches Windows'
own "window shown" event, from a thread of its own, as FancyZones does from
its own process.
"""
import os
import pathlib
import subprocess
import sys
import textwrap
import time

import pytest

import window_process

REPO = pathlib.Path(__file__).resolve().parents[2]

# --- 1. a window manager cannot move what the position tests read ------------

STAND_IN = '''
"""A window manager that moves every window this process shows, as FancyZones
does: told by Windows that a window was shown, from a thread of its own, a
moment later. It moves each to a spot off every screen, so nothing appears."""
import ctypes
import os
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                  wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
EVENT_OBJECT_SHOW, GA_ROOT = 0x8002, 2
MOVED = []


@WINEVENTPROC
def _shown(hook, event, hwnd, id_object, id_child, thread, ms):
    if id_object == 0 and id_child == 0 and hwnd and user32.GetAncestor(hwnd, GA_ROOT) == hwnd:
        MOVED.append(hwnd)
        user32.SetWindowPos(hwnd, None, -7000, -7000, 0, 0, 0x0001 | 0x0004 | 0x0010)   # no size, z-order, activation


def _watch(ready):
    user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, _shown, os.getpid(), 0, 0)
    ready.set()
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.DispatchMessageW(ctypes.byref(message))


def pytest_configure(config):
    ready = threading.Event()
    threading.Thread(target=_watch, args=(ready,), daemon=True).start()
    ready.wait(10)


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(f"stand-in moved {len(MOVED)} window(s)")
'''

CONTROL = '''
import time
import tkinter


def test_stand_in_control_a_mapped_window_read_back():
    root = tkinter.Tk()
    try:
        root.wm_attributes("-toolwindow", True)    # which FancyZones leaves alone, as a test's root is
        root.geometry("+-4000+-4000")
        root.update()
        moved_by = time.monotonic() + 5            # a window manager acts a moment after the window appears
        while (root.winfo_x(), root.winfo_y()) == (-4000, -4000) and time.monotonic() < moved_by:
            time.sleep(0.01)
            root.update()
        assert (root.winfo_x(), root.winfo_y()) == (-4000, -4000)
    finally:
        root.destroy()
'''

# The control runs outside this suite's conftest, so it spends Tk's
# first-window activation the same way (window_guard), keeping the keyboard.
CONTROL_CONFTEST = '''
import tkinter

import window_guard


def pytest_sessionstart(session):
    window_guard.spend_first_activation(tkinter)
'''


def _under_the_stand_in(tmp_path, cwd, *args):
    (tmp_path / "stand_in.py").write_text(STAND_IN, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(tmp_path), str(REPO / "tests"))),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "stand_in", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    return done.stdout


@pytest.mark.skipif(os.name != "nt", reason="the stand-in moves a window through the Win32 API")
def test_the_position_tests_pass_while_a_window_manager_moves_every_shown_window(tmp_path):
    out = _under_the_stand_in(tmp_path, REPO, "-k", "show_centres or show_keeps", "tests/test_settings_window.py")
    assert "2 passed" in out and "failed" not in out, out
    assert "stand-in moved 0 window(s)" in out, out      # they never map one


@pytest.mark.skipif(os.name != "nt", reason="the stand-in moves a window through the Win32 API")
def test_the_stand_in_does_move_a_window_a_test_maps(tmp_path):
    # Its own root, so pytest never walks the shared temp folder to reach it: a
    # file outside the root makes pytest scan every folder above it, and a temp
    # folder another program deletes meanwhile ends the collection.
    control = tmp_path / "control"
    control.mkdir()
    (control / "pytest.ini").write_text("[pytest]\naddopts = --capture=sys\n", encoding="utf-8")
    (control / "test_control.py").write_text(CONTROL, encoding="utf-8")
    (control / "conftest.py").write_text(CONTROL_CONFTEST, encoding="utf-8")
    out = _under_the_stand_in(tmp_path, control, "test_control.py")
    assert "1 failed" in out and "test_stand_in_control_a_mapped_window_read_back" in out, out
    assert "stand-in moved 1 window(s)" in out, out


# --- 2. an on-screen test's limit times the window -----------------------------

def test_a_slow_start_does_not_count_against_the_window(tmp_path):
    done = window_process.run(tmp_path, "print('shown and closed')", start="import time; time.sleep(4)",
                              window_seconds=2)
    assert (done.returncode, done.stdout) == (0, "shown and closed\n"), done.stderr


def test_a_window_that_never_closes_still_fails_in_time_with_its_stack(tmp_path):
    code = textwrap.dedent("""
        import time
        def a_loop_nothing_ends():
            time.sleep(120)
        a_loop_nothing_ends()
    """)
    began = time.monotonic()
    done = window_process.run(tmp_path, code, start="pass", window_seconds=2)
    assert done.returncode != 0
    assert "a_loop_nothing_ends" in done.stderr, done.stderr     # where it was stuck, not just that it was
    assert time.monotonic() - began < 60                         # the window's limit, not the start-up's


def test_the_start_up_limit_is_a_backstop_well_past_what_was_measured():
    # Under load, starting Python, importing conpact and creating Tk took up to
    # 20 seconds; the backstop only has to end a child that never gets going.
    assert window_process.START_SECONDS >= 120
    assert window_process.WINDOW_SECONDS == 30   # the limit the tests always had, now for the window alone
