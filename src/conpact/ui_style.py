"""
@module conpact.ui_style
@description The look shared by conPACT's windows (the toast and the settings
             window): fonts, the dark and light palettes that follow the Windows
             app theme, and the mouse-only label button, which acts on a click and
             never takes focus, so a stray Enter or Space never presses it.
@input      a parent widget, a palette, a click handler
@output     fonts, palettes, button widgets
@dependencies stdlib: tkinter (lazily)
"""
from __future__ import annotations

FONT = "Segoe UI"
FONT_STRONG = "Segoe UI Semibold"

PALETTES = {
    "dark": {"bg": "#262624", "border": "#3d3c38", "text": "#f5f4ef", "body": "#c3c0b6",
             "muted": "#8e8b82", "accent": "#d97757", "accent_hover": "#e3876a", "on_accent": "#ffffff",
             "secondary": "#35342f", "secondary_hover": "#42413b", "track": "#3a3935", "error": "#f2877d"},
    "light": {"bg": "#ffffff", "border": "#dedcd4", "text": "#1f1e1d", "body": "#3d3c38",
              "muted": "#76746c", "accent": "#c96442", "accent_hover": "#b4563a", "on_accent": "#ffffff",
              "secondary": "#f0eee6", "secondary_hover": "#e5e2d8", "track": "#ebe9e1", "error": "#b3261e"},
}


def label_button(parent, text, style, palette, on_click, px=round, pad=(12, 6)):
    """A mouse-only button: a label that acts on a click and never takes focus."""
    import tkinter as tk
    p = palette
    bg, fg, hover_bg, hover_fg = {
        "primary": (p["accent"], p["on_accent"], p["accent_hover"], p["on_accent"]),
        "secondary": (p["secondary"], p["text"], p["secondary_hover"], p["text"]),
        "ghost": (p["bg"], p["muted"], p["bg"], p["text"]),
        # A standing choice, offered beneath the buttons rather than beside them.
        "link": (p["bg"], p["accent"], p["bg"], p["accent_hover"]),
    }[style]
    label = tk.Label(parent, text=text, font=(FONT if style in ("ghost", "link") else FONT_STRONG, 9),
                     bg=bg, fg=fg, padx=px(pad[0]), pady=px(pad[1]), cursor="hand2", takefocus=0)
    label.bind("<Enter>", lambda event: label.configure(bg=hover_bg, fg=hover_fg))
    label.bind("<Leave>", lambda event: label.configure(bg=bg, fg=fg))
    label.bind("<ButtonRelease-1>", lambda event: on_click())
    return label
