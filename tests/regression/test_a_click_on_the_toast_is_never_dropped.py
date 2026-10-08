"""
Regression test for CU-20260924-076 (a click on the toast is never dropped).

CU-20260924-064 made every window of a toast with activation refused, so that
Tk's first-window activation could not take the keyboard. That broke the
buttons. A click on a window that is not active first asks it, with
WM_MOUSEACTIVATE, whether to activate it; Tk leaves the answer to Windows,
which says MA_ACTIVATE even for a no-activate tool window. Windows then asked
to activate the toast, the refusal said no, and Windows dropped the click.
Measured on 2026-09-24 on a real toast with the user clicking: 29 clicks on its
close button in a row reached the toast's thread, and each was followed by
MA_ACTIVATE, a mouse-caused activation request refused, and no press reaching
Tk. The user saw "nothing, click again".

The contract:

  1. A click on a shown toast - its close button, its buttons - is answered
     MA_NOACTIVATE: take the click, never ask for activation, so the refusal
     never meets a click.

Run against a real toast in a fresh process, shown by present(), which is
where both the refusal and the answer are in force. A real mouse cannot be
used here without taking the user's; the live check, with the user clicking,
is recorded in the change entry.
"""
import json
import os

import pytest

import window_process

pytestmark = [pytest.mark.skipif(os.name != "nt", reason="WM_MOUSEACTIVATE is a Windows message"),
              pytest.mark.real_ui]

ASK_EACH_BUTTON = """
import ctypes
import json
from ctypes import wintypes

user32 = ctypes.WinDLL("user32")
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
WM_MOUSEACTIVATE, A_LEFT_CLICK = 0x0021, (0x0201 << 16) | 1
asked = {}
shown = toast_view.ToastView.show


def show(self, slot):
    shown(self, slot)
    frame = user32.GetParent(self.root.winfo_id())
    for name, button in [("close", self.close_button), *self.buttons.items()]:
        asked[name] = user32.SendMessageW(button.winfo_id(), WM_MOUSEACTIVATE, frame, A_LEFT_CLICK)


toast_view.ToastView.show = show


class Toast:
    def model(self):
        return {"kind": "ask", "name": "x", "context_tokens": 1, "last_call": 0.0, "deadline": 1e12, "span": 1.0}

    def poll(self):
        return "expired"

    def act(self, action):
        return {"state": "closed"}


toast_view.present(Toast(), clock=lambda: 1.0)
print(json.dumps(asked))
"""

MA_NOACTIVATE = 3


def test_a_click_on_any_of_the_toasts_buttons_asks_for_no_activation(tmp_path):
    proc = window_process.run(tmp_path, ASK_EACH_BUTTON, start="from conpact import toast_view")
    assert proc.returncode == 0, proc.stderr
    asked = json.loads(proc.stdout)
    assert set(asked) == {"close", "compact", "auto", "dismiss"}
    assert asked == {name: MA_NOACTIVATE for name in asked}, "a click would ask for activation, and be dropped"
