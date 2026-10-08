"""
@module tests.window_guard
@description What keeps the Tk windows of a test off the user's screens and
             away from their keyboard, on Windows. Tests share a desktop they do
             not control, and two things on it act on any window a test shows
             (measured 2026-09-24, CU-20260924-063):
             - A window manager. PowerToys FancyZones moves every newly shown
               window onto the monitor under the cursor, unless it is a tool
               window or a popup without a sizing frame. A test's root is
               therefore a tool window, placed off every screen (`root`).
             - Tk itself. The first window a thread creates is activated, shown
               or not (SetActiveWindow in tkWinWm.c's UpdateWrapper), which
               takes the keyboard from whatever the user is typing in.
               `spend_first_activation` has that happen once, before any test,
               on a window that is never shown, and hands the keyboard back.
             `Guard` holds every test that is not `real_ui` to both. It refuses
             any activation of the test's windows, records it, and records any
             window of the test that is shown without being a tool window, or
             lands on a screen. Elsewhere than Windows all of these do nothing.
@input      the tkinter module, passed in
@output     root(): a fixture body yielding a Tk root; spend_first_activation();
            hand_back(before); Guard(record): a context manager calling
            record(what) per breach
@dependencies stdlib: ctypes, gc, os; pytest (to skip where there is no display)
"""
import ctypes
import gc
import os

import pytest

OFF_SCREEN = "+-4000+-4000"
WINDOWS = os.name == "nt"
WH_CBT, WH_CALLWNDPROCRET, HCBT_ACTIVATE, WM_WINDOWPOSCHANGED = 5, 12, 5, 0x0047
GWL_STYLE, GWL_EXSTYLE, WS_CHILD, WS_EX_TOOLWINDOW = -16, -20, 0x40000000, 0x00000080
TAKE_THE_KEYBOARD = "take the keyboard"
SHOW_A_WINDOW_MANAGERS_MOVE = "show a window that is not a tool window, which a window manager may move"

if WINDOWS:
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.MonitorFromRect.restype = wintypes.HANDLE
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]

    class _Returned(ctypes.Structure):
        """CWPRETSTRUCT: a message a window of this thread has just handled."""
        _fields_ = [("lResult", LRESULT), ("lParam", wintypes.LPARAM), ("wParam", wintypes.WPARAM),
                    ("message", wintypes.UINT), ("hwnd", wintypes.HWND)]

_spent = []


def root(tk, prepare=None):
    """The whole body of a window test's `root` fixture: a new Tk root, a tool
    window placed off every screen, which Tk maps at its first update without
    activating it; `prepare(window)` runs before that. Destroyed afterwards."""
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        if WINDOWS:
            raise  # Windows always has a display: a failure here is a real fault
        pytest.skip(f"no display: {exc}")
    if WINDOWS:
        window.wm_attributes("-toolwindow", True)
    window.geometry(OFF_SCREEN)
    if prepare is not None:
        prepare(window)
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass
    # Precaution: free the destroyed interpreter here, on the main thread, never
    # later on whichever thread the cycle collector happens to run.
    del window
    gc.collect()


def spend_first_activation(tk):
    """Have Tk activate the first window of this thread now, on one that is
    never shown, with the activation refused and the keyboard handed back if
    Windows moved it anyway. Tk does this once per thread, and every test runs
    its Tk on the main thread, so once per process is enough."""
    if not WINDOWS or _spent:
        return
    _spent.append(True)
    before = user32.GetForegroundWindow()
    with Guard(record=lambda what: None):
        window = tk.Tk()
        window.withdraw()
        window.update_idletasks()   # Tk creates the window's frame here, and activates it
        window.destroy()
    hand_back(before)
    del window
    gc.collect()


def _ours(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == kernel32.GetCurrentProcessId()


def hand_back(before):
    """Give the keyboard back to the window that had it, but only if this
    process is what took it: never undo a change of window the user made."""
    now = user32.GetForegroundWindow()
    if before and now != before and (not now or _ours(now)):
        user32.SetForegroundWindow(before)


class Guard:
    """Around a test: refuses and records every activation of this thread's
    windows, and records each of its top-level windows that is shown without
    being a tool window, or that lands on a screen (once per window each)."""

    def __init__(self, record):
        self.record = record
        self._seen = set()
        self._hooks = []

    def _activation(self, code, wparam, lparam):
        if code == HCBT_ACTIVATE:
            self.record(TAKE_THE_KEYBOARD)
            return 1                                      # refused
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _handled(self, code, wparam, lparam):
        try:
            if code >= 0:
                done = ctypes.cast(lparam, ctypes.POINTER(_Returned)).contents
                if done.message == WM_WINDOWPOSCHANGED:
                    self._look_at(done.hwnd)
        except Exception as exc:  # noqa: BLE001 - a hook must return, and the test must still hear of it
            self.record(f"check a window's place ({exc!r})")
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _look_at(self, hwnd):
        if user32.GetWindowLongW(hwnd, GWL_STYLE) & WS_CHILD or not user32.IsWindowVisible(hwnd):
            return
        if not user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW and (hwnd, "tool") not in self._seen:
            self._seen.add((hwnd, "tool"))
            self.record(SHOW_A_WINDOW_MANAGERS_MOVE)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if user32.MonitorFromRect(ctypes.byref(rect), 0) and (hwnd, "screen") not in self._seen:   # 0: no monitor
            self._seen.add((hwnd, "screen"))
            self.record(f"put a window on a screen, at ({rect.left}, {rect.top})")

    def __enter__(self):
        if WINDOWS:
            self.before = user32.GetForegroundWindow()
            thread = kernel32.GetCurrentThreadId()
            self._procs = (HOOKPROC(self._activation), HOOKPROC(self._handled))   # kept alive while hooked
            for kind, proc in zip((WH_CBT, WH_CALLWNDPROCRET), self._procs):
                hook = user32.SetWindowsHookExW(kind, proc, None, thread)
                if not hook:
                    raise ctypes.WinError()
                self._hooks.append(hook)
        return self

    def __exit__(self, *exc):
        while self._hooks:
            user32.UnhookWindowsHookEx(self._hooks.pop())
        if WINDOWS:
            hand_back(self.before)
        return False
