"""
Regression test for CU-20260924-064 (a toast never takes the keyboard, the
first one a process shows included).

D-015 says the toast is shown without taking focus. It was not, for the first
toast of each process. Measured on 2026-09-24 on Windows 11 with Tk 8.6.12, by
logging every change of the foreground window from outside:

- The real watcher, started the way the Stop hook starts it (a detached pythonw
  whose parent had already exited), showed its first toast 20 seconds later in
  one run and 10 minutes later in another. Each time its toast window became
  the foreground window while still hidden, at (0, 0), about 40 ms before it was
  shown, although the user had typed or clicked seconds earlier. It kept the
  foreground until the toast closed.
- Tk activates the first window a thread makes, shown or not (SetActiveWindow
  at the end of UpdateWrapper in tkWinWm.c). The hand-back in
  show_without_focus() read the foreground after that had happened, so the
  window it would have handed back to was the toast itself.
- A stand-in for the user's app, in a process of its own, was deactivated and
  lost the keyboard when the toast came up and got it back only when the toast
  closed.
- Refusing the activation with a thread hook is not enough on its own: in 2 of
  4 runs Windows had already moved the foreground to the toast's process before
  it asked the hook, and no window had the keyboard.

The contract:

  1. No window a toast's process makes is ever activated: at the first poll of
     each toast, the first and the next, its thread has no active window.
  2. No window of that process ever becomes the foreground window, as the
     user's desktop sees it from outside.
  3. The keyboard is never left with no window: if Windows empties the
     foreground before asking the hook, the keyboard goes back at once to the
     window that had it.

Each runs against real toasts in a fresh process, whose first window is the
one Tk activates.
"""
import ctypes
import json
import os
import threading

import pytest

import window_process

pytestmark = [pytest.mark.skipif(os.name != "nt", reason="Tk's first-window activation is a Windows call"),
              pytest.mark.real_ui]

EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT, WM_QUIT = 0x0003, 0x0000, 0x0012

TWO_TOASTS = """
import ctypes
import json
import os
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.GetActiveWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def owner(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


before = user32.GetForegroundWindow()
seen = []


class Toast:
    def model(self):
        return {"kind": "ask", "name": "x", "context_tokens": 1, "last_call": 0.0, "deadline": 1e12, "span": 1.0}

    def poll(self):
        now = user32.GetForegroundWindow()
        seen.append({"active": bool(user32.GetActiveWindow()), "ours": bool(now) and owner(now) == os.getpid(),
                     "emptied": bool(before) and not now})
        return "expired"

    def act(self, action):
        return {"state": "closed"}


toast_view.present(Toast(), clock=lambda: 1.0)
toast_view.present(Toast(), clock=lambda: 1.0)
print(json.dumps({"pid": os.getpid(), "toasts": seen}))
"""


class ForegroundLog:
    """The process behind every window that becomes the foreground while this
    is open, seen from outside the toast's process, as the user's desktop sees
    it, from a thread of its own."""

    def __enter__(self):
        self.owners = []
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        assert self._ready.wait(10), "the foreground log did not start"
        return self

    def _listen(self):
        from ctypes import wintypes
        user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        changed = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                     wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
        user32.SetWinEventHook.restype = wintypes.HANDLE
        user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, changed,
                                           wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
        user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                        wintypes.UINT, wintypes.UINT]

        def record(hook, event, hwnd, id_object, id_child, thread, ms):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            self.owners.append(pid.value)

        self._record = changed(record)   # kept alive while hooked
        hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._record,
                                      0, 0, WINEVENT_OUTOFCONTEXT)
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)   # the queue a quit is posted to
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWinEvent(hook)

    def __exit__(self, *exc):
        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(10)
        return False


def test_neither_the_first_toast_of_a_process_nor_the_next_takes_the_keyboard(tmp_path):
    with ForegroundLog() as foreground:
        proc = window_process.run(tmp_path, TWO_TOASTS, start="from conpact import toast_view")
    assert proc.returncode == 0, proc.stderr
    shown = json.loads(proc.stdout)
    assert len(shown["toasts"]) == 2
    for toast in shown["toasts"]:
        assert not toast["active"], "Tk's activation of the window it made was let through"
        assert not toast["ours"], "the toast's process has the keyboard"
        assert not toast["emptied"], "the keyboard was taken from the user's window and left with none"
    assert shown["pid"] not in foreground.owners, "a window of the toast's process became the foreground"
