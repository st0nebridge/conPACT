"""
Regression test for CU-20260924-066 (the on-screen tests time the window, not
Tk's start-up).

On 2026-09-24, with the machine at 100% CPU, creating Tk in an on-screen test's
child took 7 to 16 seconds, and building the toast's card up to 15 more. Two
clocks counted that start-up against the window, and a third raced the
window's own slowness:

- `test_a_shown_toast_fades_in_fully_and_its_buttons_respond` closes its toast
  at the first poll after 10 seconds, so a click that never lands fails instead
  of hanging. Its clock was read when the child's controller class was defined,
  before `present()` created Tk. The toast's first poll, 500 ms after it was
  shown, came 11 seconds after the clock started and closed it before the
  test's click at 900 ms: the child printed "acted []".
- `tests/window_process.py` gave the child 30 seconds from its imports. Tk's
  start-up took up to 16 of them, and `test_a_real_toast_stays_up_while_
  compacting_then_shows_the_result` was stopped inside `mainloop()` with its
  window up.
- With the first clock fixed, the click test's click, 900 ms after show(), came
  before the fade's eight 16 ms steps had run: under the same load they took up
  to 1.7 seconds, and the child printed "alpha 0.61" and "alpha 0.73".

The contract:

  1. The click test's close clock starts when the toast is shown: however long
     Tk's start-up takes, the toast gets its 10 seconds. Its click comes 900 ms
     after the fade's last step, however long the fade took; a fade that never
     finishes still fails, because then no click comes.
  2. `window_process`'s limit starts again, whole, once the child's first Tk
     root exists; creating it is start-up, bounded by the start-up limit alone,
     and the start-up limit prints the child's stack as the window's does.
     Only the first root restarts the clock, and a window that never closes
     still fails within the limit.

The limit tests stand in for Tk with a class whose creation sleeps or returns
at once, so they put nothing on a screen and do not take the keyboard.
"""
import textwrap
import time

import pytest

import window_process


def _stand_in_tk(creation="pass"):
    """Start-up code that makes tkinter.Tk() run `creation` instead of creating Tk."""
    return textwrap.dedent(f"""
        import time
        import tkinter
        def creating_tk(self, *args, **kwargs):
            {creation}
        tkinter.Tk.__init__ = creating_tk
    """)


# --- 1. the click test times its toast ---------------------------------------

# Tk's start-up seems, to every clock the child reads, to take 11 seconds: past
# the click test's 10-second close clock. Faulthandler's limits keep real time.
SLOW_TK_START = textwrap.dedent("""
    import time
    import tkinter
    from conpact import toast_view
    _real_time, _create = time.time, tkinter.Tk.__init__
    def creating_tk_slowly(self, *args, **kwargs):
        _create(self, *args, **kwargs)
        time.time = lambda: _real_time() + 11
    tkinter.Tk.__init__ = creating_tk_slowly
""")


@pytest.mark.real_ui
def test_the_click_test_gives_its_toast_ten_seconds_however_long_tk_takes_to_start(tmp_path):
    pytest.importorskip("tkinter")
    from test_toast_view import CLICK_ON_SCREEN
    done = window_process.run(tmp_path, CLICK_ON_SCREEN, start=SLOW_TK_START)
    assert (done.returncode, done.stdout) == (0, "alpha 0.98\nacted ['compact']\n"), done.stderr


# Each step of the fade holds the event loop for 150 ms, as a starved process
# does: the eight steps take 1.3 seconds, past a click 900 ms after show().
SLOW_FADE = textwrap.dedent("""
    import time
    from conpact import toast_view
    _fade = toast_view.ToastView._fade
    def fading_slowly(self, step):
        time.sleep(0.15)
        _fade(self, step)
    toast_view.ToastView._fade = fading_slowly
""")


@pytest.mark.real_ui
def test_the_click_test_clicks_once_the_fade_has_finished_however_long_it_took(tmp_path):
    pytest.importorskip("tkinter")
    from test_toast_view import CLICK_ON_SCREEN
    done = window_process.run(tmp_path, CLICK_ON_SCREEN, start=SLOW_FADE)
    assert (done.returncode, done.stdout) == (0, "alpha 0.98\nacted ['compact']\n"), done.stderr


# --- 2. window_process's limit restarts once Tk exists --------------------------

def test_a_slow_tk_start_does_not_count_against_the_window(tmp_path):
    pytest.importorskip("tkinter")
    done = window_process.run(tmp_path, "import tkinter\ntkinter.Tk()\nprint('shown and closed')",
                              start=_stand_in_tk("time.sleep(4)"), window_seconds=2)
    assert (done.returncode, done.stdout) == (0, "shown and closed\n"), done.stderr


def test_a_window_that_never_closes_once_tk_exists_still_fails_in_time_with_its_stack(tmp_path):
    pytest.importorskip("tkinter")
    code = textwrap.dedent("""
        import time
        import tkinter
        tkinter.Tk()
        def a_window_nothing_closes():
            time.sleep(120)
        a_window_nothing_closes()
    """)
    began = time.monotonic()
    done = window_process.run(tmp_path, code, start=_stand_in_tk(), window_seconds=2)
    assert done.returncode != 0
    assert "a_window_nothing_closes" in done.stderr, done.stderr
    assert time.monotonic() - began < 60                         # the window's limit, not the start-up's


def test_only_the_first_tk_root_restarts_the_window_clock(tmp_path):
    pytest.importorskip("tkinter")
    code = textwrap.dedent("""
        import time
        import tkinter
        def a_root_every_second():
            while True:
                tkinter.Tk()
                time.sleep(1)
        a_root_every_second()
    """)
    began = time.monotonic()
    done = window_process.run(tmp_path, code, start=_stand_in_tk(), window_seconds=3)
    assert done.returncode != 0
    assert "a_root_every_second" in done.stderr, done.stderr
    assert time.monotonic() - began < 60


def test_a_tk_start_that_never_ends_fails_at_the_start_up_limit_with_its_stack(tmp_path):
    pytest.importorskip("tkinter")
    # 15 seconds of start-up, so a loaded machine still gets through Python's own
    # start-up in them; the window's 10 are what is left of the outer backstop.
    began = time.monotonic()
    done = window_process.run(tmp_path, "import tkinter\ntkinter.Tk()",
                              start=_stand_in_tk("time.sleep(120)"), window_seconds=10, start_seconds=15)
    assert done.returncode != 0
    assert "creating_tk" in done.stderr, done.stderr             # stuck creating Tk, and says so
    assert time.monotonic() - began < 60
