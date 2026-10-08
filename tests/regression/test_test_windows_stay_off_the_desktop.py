"""
Regression test for CU-20260924-063 (a test's windows stay off the user's
screens and away from their keyboard).

Measured on 2026-09-24 by logging, from outside the test process, every window
a python process showed and every change of the foreground window, across a run
of the window test files:

- The first Tk window each test process created took the keyboard from the
  window the user was typing in, shown or not: Tk activates the first window a
  thread creates (SetActiveWindow in tkWinWm.c's UpdateWrapper). In that run the
  user's keyboard went to an off-screen test window for 33 seconds.
- 32 test roots were ordinary windows, which PowerToys FancyZones moves onto the
  monitor under the cursor ("move newly created windows to the current active
  monitor"). With the cursor parked on the left monitor, one was moved to
  (-1904, 16), on that screen. FancyZones leaves tool windows alone, and the
  toast tests' borderless roots, which are tool windows, were not moved.
- One test that is not `real_ui` put the settings window in the middle of the
  user's screen: it called show(), which centres the window in the real work
  area.
- The position tests of CU-20260924-062 showed their window for a moment,
  because the view was built before the root was withdrawn.

The contract:

  1. A window test's root is a tool window, placed off every screen, and Tk
     shows it without activating it.
  2. Tk's first-window activation is spent before any test: in a fresh process
     Tk activates its first window, and once it has been spent it activates
     none.
  3. Every test that is not `real_ui` runs under a guard that refuses any
     activation of its windows and records it, and records any of its windows
     that is shown without being a tool window, or that lands on a screen, so
     the test fails. Each is shown biting on a window that cannot be seen: the
     controls are transparent.
"""
import ctypes
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

import window_guard

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the guard reads what Windows does with a window")
TESTS = pathlib.Path(__file__).resolve().parents[1]


def _frame(window):
    return ctypes.windll.user32.GetParent(window.winfo_id())


def _on_a_screen(window):
    from ctypes import wintypes
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(_frame(window), ctypes.byref(rect))
    return bool(ctypes.windll.user32.MonitorFromRect(ctypes.byref(rect), 0))


@pytest.fixture
def invisible_root():
    """A test root that cannot be seen even on a screen, for the controls."""
    yield from window_guard.root(tk, prepare=lambda window: window.attributes("-alpha", 0.0))


# --- 1. the root every window test builds on ----------------------------------

@pytest.mark.parametrize("borderless", [False, True])
def test_a_test_root_is_an_unactivated_tool_window_off_every_screen(borderless, _isolate_user_state):
    for window in window_guard.root(tk, prepare=(lambda w: w.overrideredirect(True)) if borderless else None):
        window.update()
        style = ctypes.windll.user32.GetWindowLongW(_frame(window), window_guard.GWL_EXSTYLE)
        assert window.winfo_ismapped()
        assert style & window_guard.WS_EX_TOOLWINDOW       # which FancyZones never moves
        assert not _on_a_screen(window)
        assert _isolate_user_state == []                  # shown without being activated


# --- 2. Tk's first-window activation ------------------------------------------

FIRST_WINDOW = """
import tkinter
import window_guard
if SPEND:
    window_guard.spend_first_activation(tkinter)
seen = []
with window_guard.Guard(record=seen.append):
    for root in window_guard.root(tkinter):
        root.update()
print(seen)
"""


def _first_window(spend):
    code = textwrap.dedent(FIRST_WINDOW).replace("SPEND", str(spend))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                          env={**os.environ, "PYTHONPATH": str(TESTS)})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_tk_activates_the_first_window_of_a_fresh_process():
    assert _first_window(spend=False) == str([window_guard.TAKE_THE_KEYBOARD])


def test_once_the_first_activation_is_spent_a_test_window_takes_nothing():
    assert _first_window(spend=True) == "[]"


# --- 3. the guard around every test -------------------------------------------

def test_a_test_window_that_takes_the_keyboard_fails_its_test(invisible_root, _isolate_user_state):
    invisible_root.update()
    invisible_root.focus_force()
    invisible_root.update()
    assert window_guard.TAKE_THE_KEYBOARD in _isolate_user_state
    assert ctypes.windll.user32.GetForegroundWindow() != _frame(invisible_root)   # it was refused
    _isolate_user_state.clear()  # this breach was the point of the test


def test_a_test_window_a_window_manager_would_move_fails_its_test(invisible_root, _isolate_user_state):
    invisible_root.wm_attributes("-toolwindow", False)
    invisible_root.update()
    assert window_guard.SHOW_A_WINDOW_MANAGERS_MOVE in _isolate_user_state
    _isolate_user_state.clear()  # this breach was the point of the test


def test_a_test_window_on_a_screen_fails_its_test(invisible_root, _isolate_user_state):
    invisible_root.geometry("1x1+0+0")          # the primary monitor's corner, and transparent
    invisible_root.update()
    assert _isolate_user_state == ["put a window on a screen, at (0, 0)"]
    _isolate_user_state.clear()  # this breach was the point of the test
