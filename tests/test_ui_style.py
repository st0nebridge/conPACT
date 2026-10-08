"""Tests for conpact.ui_style: the look shared by the toast and the settings window."""
import re

import pytest

from conpact import ui_style as us
import window_guard

tk = pytest.importorskip("tkinter")


def test_fonts_and_palettes():
    assert (us.FONT, us.FONT_STRONG) == ("Segoe UI", "Segoe UI Semibold")
    assert set(us.PALETTES) == {"dark", "light"}
    assert set(us.PALETTES["dark"]) == set(us.PALETTES["light"])
    for palette in us.PALETTES.values():
        assert all(re.fullmatch(r"#[0-9a-f]{6}", color) for color in palette.values())


@pytest.fixture
def root():
    yield from window_guard.root(tk)


@pytest.mark.parametrize("style, bg, fg, hover_bg, hover_fg, font", [
    ("primary", "accent", "on_accent", "accent_hover", "on_accent", us.FONT_STRONG),
    ("secondary", "secondary", "text", "secondary_hover", "text", us.FONT_STRONG),
    ("ghost", "bg", "muted", "bg", "text", us.FONT),
])
def test_a_label_button_is_mouse_only_and_styled(root, style, bg, fg, hover_bg, hover_fg, font):
    p, clicks = us.PALETTES["light"], []
    button = us.label_button(root, "Go", style, p, lambda: clicks.append(True), px=lambda n: n * 2, pad=(3, 4))
    button.pack()
    root.update()
    assert isinstance(button, tk.Label) and str(button.cget("takefocus")) == "0"
    assert (button.cget("text"), button.cget("cursor")) == ("Go", "hand2")
    assert (int(str(button.cget("padx"))), int(str(button.cget("pady")))) == (6, 8)
    assert button.cget("font") == f"{{{font}}} 9"
    assert (button.cget("bg"), button.cget("fg")) == (p[bg], p[fg])
    button.event_generate("<Enter>")
    assert (button.cget("bg"), button.cget("fg")) == (p[hover_bg], p[hover_fg])
    button.event_generate("<Leave>")
    assert (button.cget("bg"), button.cget("fg")) == (p[bg], p[fg])
    assert button.bind("<Return>") == "" and button.bind("<space>") == ""
    button.event_generate("<ButtonRelease-1>")
    assert clicks == [True]
