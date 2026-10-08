"""
@module conpact.desktop
@description The few desktop facts and calls the toast needs. Two of them are
             asked of every desktop: the light/dark theme (the registry on
             Windows, `defaults` on macOS, `gsettings` on a Linux desktop) and
             handing a link to whatever registered its scheme (the shell on
             Windows, `open` on macOS, `xdg-open` on Linux). The rest are Windows
             refinements with a safe default elsewhere: per-monitor DPI awareness,
             the work area (the screen minus the taskbar), and showing a window
             without taking focus - a no-activate tool window with Windows 11
             rounded corners, handing the foreground back if showing it took it
             anyway - made while NoActivation refuses every activation of the
             thread's windows, which Tk would otherwise make on the first window
             a thread creates. Its clicks are answered without asking for
             activation (answer_clicks_without_activating): asked, the refusal
             would say no and Windows would drop the click. Every call takes the
             library or runner it uses as an argument, defaulting to the real
             one, so what this asks the desktop for is readable in a test
             instead of only on screen.
@input      a Tk root window; registry and user32 state; optionally the
            shcore / user32 / kernel32 / dwmapi / runner to call and the
            platform to behave as
@output     "light" / "dark"; a (left, top, right, bottom) rectangle; a shown
            window that takes clicks without being activated; a link handed on;
            NoActivation, a context manager with hand_back()
@dependencies stdlib: ctypes, os, subprocess, sys, winreg (Windows only)
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
SPI_GETWORKAREA = 0x0030
PER_MONITOR_AWARE = 2
WH_CBT = 5
HCBT_ACTIVATE = 5
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3
GWLP_WNDPROC = -4
_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def dpi_aware(shcore=None, os_name=None) -> bool:
    """Ask for per-monitor DPI awareness so text is crisp. True if granted."""
    if (os_name or os.name) != "nt":
        return False
    try:
        return (shcore or ctypes.windll.shcore).SetProcessDpiAwareness(PER_MONITOR_AWARE) == 0
    except (AttributeError, OSError):
        return False


MAC_THEME = ("defaults", "read", "-g", "AppleInterfaceStyle")
LINUX_THEME = ("gsettings", "get", "org.gnome.desktop.interface", "color-scheme")
QUERY_TIMEOUT = 5.0
MAC_OPENER, LINUX_OPENER = "open", "xdg-open"
OPEN_TIMEOUT = 10.0


def desktop_of(os_name=None, platform=None) -> str:
    """Which desktop to behave as: "win32", "darwin", or "linux" for anything else.

    `platform` is sys.platform's spelling. `os_name` is the older seam, kept so a
    caller saying "nt" still means Windows; any other os name means a POSIX
    desktop, which is macOS only when this really is a Mac.
    """
    if platform:
        return platform if platform in ("win32", "darwin") else "linux"
    if os_name is not None:
        if os_name == "nt":
            return "win32"
        return "darwin" if sys.platform == "darwin" else "linux"
    return desktop_of(platform=sys.platform)


def _ask(argv, run=None):
    """(exit code, stdout) of one short, read-only query - or None when it could
    not be run at all, which is a different answer from a non-zero exit."""
    try:
        done = (run or subprocess.run)(list(argv), capture_output=True, text=True, timeout=QUERY_TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.returncode, (done.stdout or "").strip()


def _apps_use_light_theme():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY) as key:
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0]


def theme(reader=None, os_name=None, platform=None, run=None) -> str:
    """The desktop's app theme; dark when it cannot be told.

    macOS writes AppleInterfaceStyle only in dark mode, so the key being absent
    (a non-zero exit) is an answer - light - while `defaults` failing to run is
    not. A Linux desktop is asked for the freedesktop colour-scheme preference
    through GNOME's settings, which other desktops that follow it answer too.
    """
    where = desktop_of(os_name, platform)
    if where == "win32":
        try:
            return "light" if (reader or _apps_use_light_theme)() == 1 else "dark"
        except (OSError, ImportError):
            return "dark"
    if where == "darwin":
        answer = _ask(MAC_THEME, run)
        if answer is None:
            return "dark"
        code, out = answer
        return "dark" if code == 0 and out.lower() == "dark" else "light"
    answer = _ask(LINUX_THEME, run)
    if answer is None or answer[0] != 0:
        return "dark"
    out = answer[1]
    if "prefer-light" in out or out.strip("'\"") == "default":
        return "light"
    return "dark"


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def work_area(fallback, user32=None, os_name=None):
    """The primary work area in pixels, or the fallback when it cannot be read."""
    if (os_name or os.name) != "nt":
        return fallback
    rect = _Rect()
    if not (user32 or ctypes.windll.user32).SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return fallback
    return (rect.left, rect.top, rect.right, rect.bottom)


def show_without_focus(root, user32=None, dwmapi=None, os_name=None, clicks=None) -> None:
    """Map a withdrawn Tk root as a no-activate, round-cornered tool window
    whose clicks never ask for it to be activated (`clicks`, below).

    The libraries are arguments for the same reason the theme's reader is: what
    this asks Windows for can then be read in a test, off screen.
    """
    if (os_name or os.name) != "nt":
        root.deiconify()
        return
    user32 = user32 or ctypes.windll.user32
    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id())
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    preference = ctypes.c_int(DWMWCP_ROUND)
    try:
        (dwmapi or ctypes.windll.dwmapi).DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(preference), ctypes.sizeof(preference))
    except (AttributeError, OSError):
        pass  # before Windows 11: square corners
    (clicks or answer_clicks_without_activating)(hwnd)
    previous = user32.GetForegroundWindow()
    root.deiconify()
    root.update()
    if previous and previous != hwnd and user32.GetForegroundWindow() == hwnd:
        user32.SetForegroundWindow(previous)


# Window procedures that must outlive every message sent to their windows. A
# toast process shows a handful of toasts at most, so these are simply kept.
_ANSWERING = []


def _window_api():
    """user32 of our own, typed for replacing a window procedure: the
    procedure and the one it replaces are pointers."""
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    wndproc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                 wintypes.LPARAM)
    get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)    # a 32-bit Python has only these
    put = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get.restype, get.argtypes = ctypes.c_void_p, [wintypes.HWND, ctypes.c_int]
    put.restype, put.argtypes = ctypes.c_void_p, [wintypes.HWND, ctypes.c_int, wndproc]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
    return get, put, user32.CallWindowProcW, wndproc


def answer_clicks_without_activating(hwnd, api=None) -> None:
    """Have a window answer every click's WM_MOUSEACTIVATE with MA_NOACTIVATE:
    take the click, never ask for activation. Everything else goes on to the
    window's own procedure.

    A click on a window that is not active first asks it whether to activate
    it. Tk leaves the answer to Windows, which says MA_ACTIVATE even for a
    no-activate tool window; Windows then tries to activate the toast,
    NoActivation refuses, and Windows drops the click. Measured on the real
    toast: 29 clicks on its close button in a row were all dropped, the press
    never reaching Tk. The answer MA_NOACTIVATE means activation is never
    asked for, so the refusal never meets a click.

    `api` is (get, put, call, wndproc): GetWindowLongPtrW, SetWindowLongPtrW,
    CallWindowProcW and the procedure's callback type, the real ones by
    default, as every call here takes what it calls.
    """
    get, put, call, wndproc = api or _window_api()
    previous = get(hwnd, GWLP_WNDPROC)

    def answer(window, message, wparam, lparam):
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        return call(previous, window, message, wparam, lparam)

    procedure = wndproc(answer)
    _ANSWERING.append(procedure)
    put(hwnd, GWLP_WNDPROC, procedure)


def _hook_api():
    """user32 and kernel32 of our own, typed for a hook: CallNextHookEx is
    passed pointers, which ctypes' default int conversion refuses on a 64-bit
    Python, and a private copy leaves everyone else's user32 as it was."""
    from ctypes import wintypes
    user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    hookproc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hookproc, wintypes.HINSTANCE, wintypes.DWORD]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    return user32, kernel32, hookproc


class NoActivation:
    """While open, no window of this thread can be activated, so none of them
    can take the keyboard from the window the user is typing in.

    Tk activates the first window a thread makes, shown or not (SetActiveWindow
    at the end of UpdateWrapper in tkWinWm.c), which is how the first toast a
    watcher showed took the keyboard for as long as it was up. A thread hook
    (WH_CBT) refuses every activation of this thread's windows. Refusing is not
    always enough: when this process may take the foreground, Windows moves it
    here before it asks the hook, and the user's window is left without the
    keyboard. So hand_back(), called as soon as Tk has made a window, gives the
    keyboard back to the window that had it when this opened - but only if this
    process, or nothing, has it now: a change of window the user made stands.

    The libraries and the hook's callback type are arguments, as for every call
    here; off Windows this does nothing.
    """

    def __init__(self, user32=None, kernel32=None, hookproc=None, os_name=None):
        self._windows = (os_name or os.name) == "nt"
        self._user32, self._kernel32, self._hookproc = user32, kernel32, hookproc
        self.previous = None
        self._hook = self._proc = None

    def __enter__(self):
        if not self._windows:
            return self
        if self._user32 is None:
            self._user32, self._kernel32, self._hookproc = _hook_api()
        self.previous = self._user32.GetForegroundWindow()
        self._proc = self._hookproc(self._refuse)   # kept alive for as long as it is hooked
        self._hook = self._user32.SetWindowsHookExW(WH_CBT, self._proc, None, self._kernel32.GetCurrentThreadId())
        return self

    def _refuse(self, code, wparam, lparam):
        if code == HCBT_ACTIVATE:
            return 1                                   # refused
        return self._user32.CallNextHookEx(None, code, wparam, lparam)

    def _ours(self, hwnd) -> bool:
        pid = ctypes.c_ulong()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == self._kernel32.GetCurrentProcessId()

    def hand_back(self) -> None:
        if not self._windows or not self.previous:
            return
        now = self._user32.GetForegroundWindow()
        if now != self.previous and (not now or self._ours(now)):
            self._user32.SetForegroundWindow(self.previous)

    def __exit__(self, *exc):
        if self._hook:
            self._user32.UnhookWindowsHookEx(self._hook)
        self._hook = self._proc = None


def open_url(url: str, starter=None, os_name=None, platform=None, run=None) -> None:
    """Hand a url to the desktop, which gives it to whatever registered the scheme.

    The one use is the app's own `claude://` link to a session: it brings that
    session up so the user can reach its Remote Control switch. Windows' shell
    takes it directly; macOS has `open` and a Linux desktop `xdg-open`, each
    given the url as one argument and never through a shell. Raises OSError when
    nothing handles it, which the caller reports on the toast. An opener still
    running when the timeout passes has handed the link on, so that is not a
    failure.
    """
    if starter is not None:
        starter(url)
        return
    where = desktop_of(os_name, platform)
    if where == "win32":
        os.startfile(url)
        return
    tool = MAC_OPENER if where == "darwin" else LINUX_OPENER
    try:
        done = (run or subprocess.run)([tool, url], capture_output=True, text=True, timeout=OPEN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return
    except OSError as exc:
        raise OSError(f"{tool} is not available to open the link") from exc
    if done.returncode != 0:
        raise OSError(f"{tool} could not open the link (exit {done.returncode})")
