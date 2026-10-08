"""Tests for conpact.desktop: theme, work area, DPI and focus-free showing."""
import ctypes
import gc
import os

import pytest

import window_guard
from conpact import desktop as dk

windows = pytest.mark.skipif(os.name != "nt", reason="Windows desktop calls")


def test_constants():
    assert (dk.GWL_EXSTYLE, dk.WS_EX_TOOLWINDOW, dk.WS_EX_NOACTIVATE) == (-20, 0x80, 0x08000000)
    assert (dk.DWMWA_WINDOW_CORNER_PREFERENCE, dk.DWMWCP_ROUND, dk.SPI_GETWORKAREA) == (33, 2, 0x30)
    assert dk.PER_MONITOR_AWARE == 2
    assert (dk.WH_CBT, dk.HCBT_ACTIVATE) == (5, 5)
    assert (dk.WM_MOUSEACTIVATE, dk.MA_NOACTIVATE, dk.GWLP_WNDPROC) == (0x0021, 3, -4)


@pytest.mark.parametrize("value, theme", [(1, "light"), (0, "dark"), (2, "dark")])
def test_theme_follows_the_app_theme(value, theme):
    assert dk.theme(reader=lambda: value, os_name="nt") == theme


def test_theme_is_dark_when_unknown():
    def missing():
        raise OSError("no such value")
    assert dk.theme(reader=missing, os_name="nt") == "dark"
    unrunnable, _ = _runner_that_fails()
    assert dk.theme(reader=lambda: 1, os_name="posix", run=unrunnable) == "dark"


def _runner_that_fails():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        raise FileNotFoundError(argv[0])
    return run, calls


@pytest.mark.parametrize("code, out, expected", [
    (0, "Dark", "dark"),
    (1, "", "light"),            # the key exists only in dark mode
    (0, "Light", "light"),
])
def test_on_macos_the_theme_is_read_from_the_global_defaults(code, out, expected):
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return type("Done", (), {"returncode": code, "stdout": out})()
    assert dk.theme(platform="darwin", run=run) == expected
    assert seen == [["defaults", "read", "-g", "AppleInterfaceStyle"]]


@pytest.mark.parametrize("code, out, expected", [
    (0, "'prefer-dark'", "dark"),
    (0, "'prefer-light'", "light"),
    (0, "'default'", "light"),
    (0, '"default"', "light"),   # either quote comes off
    (0, "'Xdefault'", "dark"),   # but only a quote: this is not 'default'
    (1, "", "dark"),             # no such schema: cannot tell
])
def test_on_linux_the_theme_is_the_colour_scheme_preference(code, out, expected):
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return type("Done", (), {"returncode": code, "stdout": out})()
    assert dk.theme(platform="linux", run=run) == expected
    assert seen == [["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_a_theme_query_that_cannot_run_reads_as_dark(platform):
    run, calls = _runner_that_fails()
    assert dk.theme(platform=platform, run=run) == "dark"
    assert len(calls) == 1


@pytest.mark.parametrize("platform, argv", [("darwin", list(dk.MAC_THEME)), ("linux", list(dk.LINUX_THEME))])
def test_a_theme_query_is_read_from_its_own_output_as_text_within_a_time_limit(platform, argv):
    """Without capture_output there is no stdout to read, and without text it is
    bytes, which never equal "dark": either way every desktop reads as one theme."""
    run, calls = _runner(_Done(0, "Dark"))
    dk.theme(platform=platform, run=run)
    [(asked, kwargs)] = calls
    assert asked == argv
    assert kwargs == {"capture_output": True, "text": True, "timeout": dk.QUERY_TIMEOUT}


def test_a_query_that_printed_nothing_answers_with_empty_output():
    """A run can come back with no stdout at all (None, which is what subprocess
    gives when nothing was captured): that is an empty answer, not a missing one."""
    run, _ = _runner(_Done(0, None))
    assert dk._ask(("anything",), run) == (0, "")
    run, _ = _runner(_Done(1, "  Dark\n"))
    assert dk._ask(("anything",), run) == (1, "Dark")


@pytest.mark.parametrize("os_name, platform, expected", [
    (None, "win32", "win32"), (None, "darwin", "darwin"), (None, "linux", "linux"),
    (None, "freebsd14", "linux"), ("nt", None, "win32"),
])
def test_which_desktop_to_behave_as(os_name, platform, expected):
    assert dk.desktop_of(os_name, platform) == expected


@pytest.mark.parametrize("really, told_nothing, told_posix", [
    ("win32", "win32", "linux"),      # a POSIX os name means a POSIX desktop, even here
    ("darwin", "darwin", "darwin"),
    ("linux", "linux", "linux"),
    ("freebsd14", "linux", "linux"),
])
def test_with_no_platform_given_what_this_really_is_decides(monkeypatch, really, told_nothing, told_posix):
    """Given no platform, desktop_of reads sys.platform: for everything when told
    nothing, and for Mac-or-not when told only a POSIX os name. That read has no
    argument, so the module's own sys is stood in for; the interpreter's stays as it is."""
    monkeypatch.setattr(dk, "sys", type("Sys", (), {"platform": really}))
    assert dk.desktop_of() == told_nothing
    assert dk.desktop_of(os_name="posix") == told_posix
    assert dk.desktop_of(os_name="nt") == "win32"


@windows
def test_theme_reads_the_registry():
    assert dk.theme() in ("light", "dark")


def test_elsewhere_the_work_area_is_the_fallback_and_dpi_is_untouched():
    assert dk.work_area((0, 0, 800, 600), os_name="posix") == (0, 0, 800, 600)
    assert dk.dpi_aware(os_name="posix") is False


@windows
def test_the_work_area_is_a_real_rectangle():
    left, top, right, bottom = dk.work_area(None)
    assert right > left and bottom > top


@windows
def test_dpi_awareness_can_be_requested():
    assert dk.dpi_aware() in (True, False)


@windows
def test_the_theme_is_read_from_the_documented_registry_value():
    """Not any value that happens to be there: this exact one, under this key."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
        expected = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
    assert dk._apps_use_light_theme() == expected
    assert dk.theme() == ("light" if expected == 1 else "dark")


# --- what the two library calls are actually asked for -----------------------

class FakeShcore:
    def __init__(self, result=0, raises=None):
        self.result, self.raises = result, raises
        self.calls = []

    def SetProcessDpiAwareness(self, level):
        self.calls.append(level)
        if self.raises is not None:
            raise self.raises
        return self.result


def test_dpi_awareness_asks_for_per_monitor_and_reports_the_answer():
    granted = FakeShcore(result=0)
    assert dk.dpi_aware(shcore=granted, os_name="nt") is True
    assert granted.calls == [2]                      # per-monitor, not system-wide
    assert dk.dpi_aware(shcore=FakeShcore(result=-2147024891), os_name="nt") is False


@pytest.mark.parametrize("failure", [AttributeError("no shcore"), OSError("refused")])
def test_a_windows_that_cannot_be_asked_leaves_the_scaling_alone(failure):
    assert dk.dpi_aware(shcore=FakeShcore(raises=failure), os_name="nt") is False


class FakeSpi:
    """SystemParametersInfoW fills the caller's rectangle and returns non-zero."""

    def __init__(self, rect=(1, 2, 1920, 1040), answers=True):
        self.rect, self.answers = rect, answers
        self.calls = []

    def SystemParametersInfoW(self, action, ui_param, ref, win_ini):
        self.calls.append((action, ui_param, win_ini))
        if not self.answers:
            return 0
        ref._obj.left, ref._obj.top, ref._obj.right, ref._obj.bottom = self.rect
        return 1


def test_the_work_area_is_the_rectangle_windows_filled_in():
    spi = FakeSpi(rect=(1, 2, 1920, 1040))
    assert dk.work_area((0, 0, 800, 600), user32=spi, os_name="nt") == (1, 2, 1920, 1040)
    assert spi.calls == [(dk.SPI_GETWORKAREA, 0, 0)]


def test_a_work_area_windows_will_not_give_falls_back():
    assert dk.work_area((0, 0, 800, 600), user32=FakeSpi(answers=False), os_name="nt") == (0, 0, 800, 600)


@windows
@pytest.mark.real_ui
def test_show_without_focus_maps_a_no_activate_tool_window():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    user32 = ctypes.windll.user32
    users = user32.GetForegroundWindow()   # the user's window, which gets the keyboard back at the end
    other = None
    try:
        # The window under test is withdrawn before Tk first shows anything, so
        # it is never on a screen until show_without_focus shows it, off them all.
        root.withdraw()
        root.overrideredirect(True)
        root.geometry("40x20+-4000+-4000")
        # A window of ours holds the focus first, standing in for the user's app:
        # a tool window off every screen, which no window manager moves into view.
        other = tk.Toplevel(root)
        other.wm_attributes("-toolwindow", True)
        other.geometry("40x20+-4000+-4000")
        other.update()
        other_hwnd = user32.GetParent(other.winfo_id())
        if not user32.SetForegroundWindow(other_hwnd) or user32.GetForegroundWindow() != other_hwnd:
            pytest.skip("this process may not set the foreground window")
        dk.show_without_focus(root)
        assert root.winfo_ismapped()
        hwnd = user32.GetParent(root.winfo_id())
        style = user32.GetWindowLongW(hwnd, dk.GWL_EXSTYLE)
        assert style & dk.WS_EX_NOACTIVATE and style & dk.WS_EX_TOOLWINDOW
        assert user32.GetForegroundWindow() == other_hwnd  # the focus stayed where it was
    finally:
        root.destroy()
        window_guard.hand_back(users)
        del root, other
        gc.collect()  # precaution: free the interpreter on the main thread


# --- the same window, without a window --------------------------------------
#
# The test above proves show_without_focus against a real Tk window, which is
# what it is for; it can only run on screen, so a mutation run never executes a
# line of it. These drive the same function through injected win32 calls, so
# what it asks Windows for is measured rather than assumed.

class FakeRoot:
    def __init__(self, ident=4321):
        self.ident = ident
        self.calls = []

    def winfo_id(self):
        self.calls.append("winfo_id")
        return self.ident

    def update_idletasks(self):
        self.calls.append("update_idletasks")

    def deiconify(self):
        self.calls.append("deiconify")

    def update(self):
        self.calls.append("update")


class FakeUser32:
    """Records every call. GetForegroundWindow answers from a script, so a test
    says what the desktop did while the window was being shown."""

    def __init__(self, style=0x10000, hwnd=777, foreground=(555, 777)):
        self.style, self.hwnd = style, hwnd
        self.foreground = list(foreground)
        self.calls = []

    def GetParent(self, ident):
        self.calls.append(("GetParent", ident))
        return self.hwnd

    def GetWindowLongW(self, hwnd, index):
        self.calls.append(("GetWindowLongW", hwnd, index))
        return self.style

    def SetWindowLongW(self, hwnd, index, value):
        self.calls.append(("SetWindowLongW", hwnd, index, value))

    def GetForegroundWindow(self):
        self.calls.append(("GetForegroundWindow",))
        return self.foreground.pop(0)

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))


class FakeDwm:
    def __init__(self, raises=None):
        self.raises = raises
        self.calls = []

    def DwmSetWindowAttribute(self, hwnd, attribute, value, size):
        if self.raises is not None:
            raise self.raises
        self.calls.append((hwnd, attribute, value._obj.value, size))


def _show(root=None, user32=None, dwmapi=None, **kwargs):
    root, user32, dwmapi = root or FakeRoot(), user32 or FakeUser32(), dwmapi or FakeDwm()
    clicks = kwargs.pop("clicks", lambda hwnd: root.calls.append(("clicks answered", hwnd)))
    dk.show_without_focus(root, user32=user32, dwmapi=dwmapi, os_name="nt", clicks=clicks, **kwargs)
    return root, user32, dwmapi


def test_the_window_is_made_a_no_activate_tool_window_without_losing_its_other_styles():
    root, user32, _ = _show(user32=FakeUser32(style=0x10000))
    assert ("GetParent", root.ident) in user32.calls
    [set_style] = [c for c in user32.calls if c[0] == "SetWindowLongW"]
    assert set_style == ("SetWindowLongW", 777, dk.GWL_EXSTYLE,
                         0x10000 | dk.WS_EX_NOACTIVATE | dk.WS_EX_TOOLWINDOW)


def test_the_corners_are_asked_to_be_round():
    _, _, dwm = _show()
    assert dwm.calls == [(777, dk.DWMWA_WINDOW_CORNER_PREFERENCE, dk.DWMWCP_ROUND, ctypes.sizeof(ctypes.c_int))]


@pytest.mark.parametrize("failure", [AttributeError("no dwmapi"), OSError("not supported")])
def test_a_windows_without_rounded_corners_is_shown_all_the_same(failure):
    """Before Windows 11 the call is missing or refused: square corners, no crash."""
    root, user32, _ = _show(dwmapi=FakeDwm(raises=failure))
    assert "deiconify" in root.calls
    assert ("SetForegroundWindow", 555) in user32.calls


def test_the_window_is_mapped_and_drawn_in_order():
    """Its clicks are answered before it is shown: a click on it must never be dropped."""
    root, _, _ = _show()
    assert root.calls == ["update_idletasks", "winfo_id", ("clicks answered", 777), "deiconify", "update"]


def test_the_foreground_is_handed_back_when_showing_took_it():
    _, user32, _ = _show(user32=FakeUser32(hwnd=777, foreground=(555, 777)))
    assert ("SetForegroundWindow", 555) in user32.calls


@pytest.mark.parametrize("foreground, why", [
    ((555, 555), "the toast never took the foreground"),
    ((0, 777), "nothing held it beforehand"),
    ((777, 777), "the toast already held it"),
])
def test_the_foreground_is_left_alone_otherwise(foreground, why):
    _, user32, _ = _show(user32=FakeUser32(hwnd=777, foreground=foreground))
    assert not [c for c in user32.calls if c[0] == "SetForegroundWindow"], why


def test_off_windows_it_is_only_deiconified():
    root, user32 = FakeRoot(), FakeUser32()
    dk.show_without_focus(root, user32=user32, dwmapi=FakeDwm(), os_name="posix",
                          clicks=lambda hwnd: root.calls.append("clicks answered"))
    assert root.calls == ["deiconify"] and user32.calls == []


# --- a click that never asks for the window to be activated ------------------
#
# A click on a window that is not active first asks it, with WM_MOUSEACTIVATE,
# whether to activate it. Tk leaves that to Windows, which says MA_ACTIVATE
# even for a no-activate tool window; NoActivation then refuses the activation
# and Windows drops the click. So the toast's frame answers MA_NOACTIVATE itself.

def _answering(previous=0xABC, returned=42):
    calls, installed = [], []

    def get(hwnd, index):
        calls.append(("get", hwnd, index))
        return previous

    def put(hwnd, index, procedure):
        installed.append((hwnd, index, procedure))

    def call(replaced, hwnd, message, wparam, lparam):
        calls.append(("call", replaced, hwnd, message, wparam, lparam))
        return returned

    dk.answer_clicks_without_activating(777, api=(get, put, call, lambda answer: answer))
    [(hwnd, index, procedure)] = installed
    return hwnd, index, procedure, calls


def test_a_click_is_answered_take_it_and_do_not_activate():
    hwnd, index, procedure, calls = _answering()
    assert (hwnd, index) == (777, dk.GWLP_WNDPROC)
    assert procedure(777, dk.WM_MOUSEACTIVATE, 555, (0x0201 << 16) | 1) == dk.MA_NOACTIVATE
    assert not [c for c in calls if c[0] == "call"], "the answer is not Tk's, which would be MA_ACTIVATE"


def test_every_other_message_goes_on_to_the_windows_own_procedure():
    _, _, procedure, calls = _answering(previous=0xABC, returned=42)
    assert calls == [("get", 777, dk.GWLP_WNDPROC)], "the procedure it replaces is read first"
    assert procedure(777, 0x000F, 1, 2) == 42
    assert calls[-1] == ("call", 0xABC, 777, 0x000F, 1, 2)


def test_the_answering_procedure_outlives_the_call_that_installed_it():
    """Windows calls it for as long as the window lives; a freed one would crash the toast."""
    before = len(dk._ANSWERING)
    _, _, procedure, _ = _answering()
    assert dk._ANSWERING[before:] == [procedure]


@windows
def test_the_real_window_api_is_a_private_typed_copy():
    from ctypes import wintypes
    get, put, call, wndproc = dk._window_api()
    assert get.restype is ctypes.c_void_p and get.argtypes == [wintypes.HWND, ctypes.c_int]
    assert put.restype is ctypes.c_void_p and put.argtypes == [wintypes.HWND, ctypes.c_int, wndproc]
    assert call.restype is ctypes.c_ssize_t
    assert call.argtypes == [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    assert wndproc._restype_ is ctypes.c_ssize_t
    assert call is not ctypes.windll.user32.CallWindowProcW


@windows
def test_a_real_toast_window_takes_a_click_without_asking_to_be_activated():
    """On a real Tk window, off every screen: the question a click asks is
    answered MA_NOACTIVATE, and everything else still reaches Tk."""
    from ctypes import wintypes
    tk = pytest.importorskip("tkinter")
    user32 = ctypes.WinDLL("user32")
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    for root in window_guard.root(tk, prepare=lambda window: window.overrideredirect(True)):
        label = tk.Label(root, text="x")
        label.pack()
        root.geometry("60x30+-4000+-4000")
        dk.show_without_focus(root)
        frame = user32.GetParent(root.winfo_id())
        asked = user32.SendMessageW(label.winfo_id(), dk.WM_MOUSEACTIVATE, frame, (0x0201 << 16) | 1)
        assert asked == dk.MA_NOACTIVATE
        root.geometry("70x40+-4000+-4000")
        root.update()
        assert (root.winfo_width(), root.winfo_height()) == (70, 40)   # Tk still hears its frame move


# --- refusing activation, Tk's first window included -------------------------
#
# Tk activates the first window a thread makes, which is how a watcher's first
# toast took the keyboard. NoActivation refuses every activation through a
# thread hook and hands the keyboard back if Windows moved it anyway. What it
# asks Windows for is read here through injected calls; the on-screen anchor
# (tests/regression/test_the_first_toast_leaves_the_keyboard_alone.py) shows it
# against a real toast in a fresh process.

USERS, OURS, OTHER_APPS = 555, 777, 888


class HookUser32:
    """Records every call. GetForegroundWindow answers from a script (the last
    answer repeats); each window belongs to a process from a table."""

    def __init__(self, foreground=(USERS,), hook=4242):
        self.foreground = list(foreground)
        self.hook = hook
        self.owners = {OURS: FakeKernel32.PID, OTHER_APPS: 5000, USERS: 6000}
        self.calls = []
        self.procs = []

    def GetForegroundWindow(self):
        self.calls.append(("GetForegroundWindow",))
        return self.foreground.pop(0) if len(self.foreground) > 1 else self.foreground[0]

    def SetWindowsHookExW(self, kind, proc, module, thread):
        self.calls.append(("SetWindowsHookExW", kind, module, thread))
        self.procs.append(proc)
        return self.hook

    def CallNextHookEx(self, hook, code, wparam, lparam):
        self.calls.append(("CallNextHookEx", hook, code, wparam, lparam))
        return 77

    def UnhookWindowsHookEx(self, hook):
        self.calls.append(("UnhookWindowsHookEx", hook))

    def GetWindowThreadProcessId(self, hwnd, pid):
        pid._obj.value = self.owners[hwnd]
        return 1

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))


class FakeKernel32:
    PID, THREAD = 4000, 31

    def GetCurrentThreadId(self):
        return self.THREAD

    def GetCurrentProcessId(self):
        return self.PID


def _no_activation(user32, os_name="nt"):
    return dk.NoActivation(user32=user32, kernel32=FakeKernel32(), hookproc=lambda refuse: refuse,
                           os_name=os_name)


def test_the_hook_is_a_cbt_hook_on_this_thread_alone_and_is_removed_on_leaving():
    user32 = HookUser32()
    with _no_activation(user32):
        assert user32.calls[-1] == ("SetWindowsHookExW", dk.WH_CBT, None, FakeKernel32.THREAD)
    assert user32.calls[-1] == ("UnhookWindowsHookEx", 4242)


def test_every_activation_is_refused_and_everything_else_passes_on():
    user32 = HookUser32()
    with _no_activation(user32):
        [refuse] = user32.procs
        assert refuse(dk.HCBT_ACTIVATE, OURS, 0) == 1
        assert not [c for c in user32.calls if c[0] == "CallNextHookEx"], "a refused activation goes no further"
        assert refuse(3, OURS, 2 ** 40) == 77   # HCBT_CREATEWND, whose lparam is a pointer
    assert ("CallNextHookEx", None, 3, OURS, 2 ** 40) in user32.calls


def test_the_window_that_had_the_keyboard_is_read_before_anything_is_hooked():
    user32 = HookUser32(foreground=(USERS,))
    with _no_activation(user32) as keyboard:
        assert keyboard.previous == USERS
    names = [c[0] for c in user32.calls]
    assert names.index("GetForegroundWindow") < names.index("SetWindowsHookExW")


@pytest.mark.parametrize("now, why", [
    (0, "Windows moved the foreground here before asking the hook, and no window has it"),
    (OURS, "a window of this process has it"),
])
def test_the_keyboard_is_handed_back_when_this_process_took_it(now, why):
    user32 = HookUser32(foreground=(USERS, now))
    with _no_activation(user32) as keyboard:
        keyboard.hand_back()
    assert ("SetForegroundWindow", USERS) in user32.calls, why


@pytest.mark.parametrize("foreground, why", [
    ((USERS, USERS), "the user's window still has it"),
    ((USERS, OTHER_APPS), "the user moved to another app: that stands"),
    ((0, 0), "no window had it to begin with"),
    ((0, OURS), "no window had it to begin with, so there is none to give it back to"),
])
def test_the_keyboard_is_left_alone_otherwise(foreground, why):
    user32 = HookUser32(foreground=foreground)
    with _no_activation(user32) as keyboard:
        keyboard.hand_back()
    assert not [c for c in user32.calls if c[0] == "SetForegroundWindow"], why


def test_an_error_inside_is_not_swallowed_and_the_hook_still_comes_off():
    """A toast that fails must fail where the watcher can log it, not vanish here."""
    user32 = HookUser32()
    with pytest.raises(RuntimeError, match="the toast failed"):
        with _no_activation(user32):
            raise RuntimeError("the toast failed")
    assert user32.calls[-1] == ("UnhookWindowsHookEx", 4242)


def test_leaving_does_not_hand_back_on_its_own():
    """Minutes may have passed: by then a window without the keyboard is the user's doing."""
    user32 = HookUser32(foreground=(USERS, 0))
    with _no_activation(user32):
        pass
    assert not [c for c in user32.calls if c[0] == "SetForegroundWindow"]


def test_a_hook_windows_would_not_install_is_not_removed_and_the_hand_back_still_works():
    user32 = HookUser32(foreground=(USERS, OURS), hook=None)
    with _no_activation(user32) as keyboard:
        keyboard.hand_back()
    assert not [c for c in user32.calls if c[0] == "UnhookWindowsHookEx"]
    assert ("SetForegroundWindow", USERS) in user32.calls


def test_off_windows_nothing_is_asked_of_the_desktop():
    user32 = HookUser32()
    with _no_activation(user32, os_name="posix") as keyboard:
        keyboard.hand_back()
    assert user32.calls == [] and keyboard.previous is None


@windows
def test_the_real_hook_library_is_a_private_typed_copy():
    """CallNextHookEx is handed pointers: without its types, ctypes refuses one
    wider than an int. The copy is private, so no one else's user32 changes."""
    from ctypes import wintypes
    user32, kernel32, hookproc = dk._hook_api()
    assert user32 is not ctypes.windll.user32 and kernel32 is not ctypes.windll.kernel32
    assert user32.CallNextHookEx.argtypes == [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    assert user32.CallNextHookEx.restype is ctypes.c_ssize_t
    assert user32.SetWindowsHookExW.argtypes == [ctypes.c_int, hookproc, wintypes.HINSTANCE, wintypes.DWORD]
    assert user32.SetWindowsHookExW.restype is wintypes.HHOOK
    assert user32.UnhookWindowsHookEx.argtypes == [wintypes.HHOOK]
    assert user32.GetForegroundWindow.restype is wintypes.HWND
    assert user32.SetForegroundWindow.argtypes == [wintypes.HWND]
    assert user32.GetWindowThreadProcessId.argtypes == [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    assert hookproc._restype_ is ctypes.c_ssize_t
    assert hookproc._argtypes_ == (ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


@windows
def test_the_real_hook_goes_on_and_comes_off():
    with dk.NoActivation() as keyboard:
        assert keyboard._hook and keyboard._proc is not None
    assert keyboard._hook is None and keyboard._proc is None


# --- handing a url to the shell ---------------------------------------------

@pytest.mark.real_open
def test_a_url_goes_to_whatever_registered_the_scheme():
    seen = []
    assert dk.open_url("claude://claude.ai/epitaxy/local_a", starter=seen.append) is None
    assert seen == ["claude://claude.ai/epitaxy/local_a"]


@pytest.mark.real_open
def test_the_real_starter_is_the_shells_own():
    """os.startfile is what hands a claude:// link to the desktop app."""
    assert dk.open_url.__defaults__ == (None, None, None, None)
    assert hasattr(os, "startfile") == (os.name == "nt")


class _Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout = returncode, stdout


def _runner(result=None, raises=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if raises is not None:
            raise raises
        return result or _Done()
    return run, calls


@pytest.mark.real_open
@pytest.mark.parametrize("platform, tool", [("darwin", "open"), ("linux", "xdg-open")])
def test_off_windows_the_desktops_own_opener_gets_the_url_as_one_argument(platform, tool):
    """Never through a shell: the url is one argv entry, so nothing in it is parsed."""
    run, calls = _runner()
    assert dk.open_url("claude://claude.ai/epitaxy/local_a", platform=platform, run=run) is None
    [(argv, kwargs)] = calls
    assert argv == [tool, "claude://claude.ai/epitaxy/local_a"]
    assert kwargs == {"capture_output": True, "text": True, "timeout": dk.OPEN_TIMEOUT}
    assert "shell" not in kwargs


@pytest.mark.real_open
def test_an_opener_that_fails_is_reported_not_swallowed():
    run, _ = _runner(_Done(returncode=4))
    with pytest.raises(OSError) as raised:
        dk.open_url("claude://x", platform="linux", run=run)
    assert str(raised.value) == "xdg-open could not open the link (exit 4)"


@pytest.mark.real_open
def test_a_missing_opener_is_reported_by_name():
    run, _ = _runner(raises=FileNotFoundError("open"))
    with pytest.raises(OSError) as raised:
        dk.open_url("claude://x", platform="darwin", run=run)
    assert str(raised.value) == "open is not available to open the link"


@pytest.mark.real_open
def test_an_opener_still_running_at_the_timeout_has_handed_the_link_on():
    import subprocess
    run, _ = _runner(raises=subprocess.TimeoutExpired("xdg-open", dk.OPEN_TIMEOUT))
    assert dk.open_url("claude://x", platform="linux", run=run) is None


@pytest.mark.real_open
def test_on_windows_the_shell_opens_the_url_with_nothing_handed_in(monkeypatch):
    """The refusal is for the platforms that have no os.startfile, not for the
    one that does: there, a caller passes a url and nothing else."""
    seen = []
    monkeypatch.setattr(os, "startfile", seen.append, raising=False)
    assert dk.open_url("claude://x", os_name="nt") is None
    assert seen == ["claude://x"]


@pytest.mark.real_open
def test_a_starter_that_was_given_is_used_wherever_we_are():
    """Only the *shell* is Windows-only: a caller that brings its own opener is
    never refused, which is what the tests themselves rely on."""
    seen = []
    dk.open_url("claude://x", starter=seen.append, os_name="posix")
    assert seen == ["claude://x"]
