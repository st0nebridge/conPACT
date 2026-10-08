"""
@module conpact.settings_window
@description The settings window: every setting with its label, what it does,
             its unit and default, in the toast's look and theme (stdlib Tk,
             D-015). The settings are on tabs, so the window fits a small screen
             (D-20260923-049): only the chosen tab's page is on screen, and the
             keyboard moves with it. Save checks every value and stores only what
             changed (so a change made elsewhere meanwhile is kept); a refused
             value is marked in place, its tab is brought forward and marked, and
             nothing is stored. Defaults fills the form in without saving. The form's logic (Form) has no Tk in it. The window runs in
             its own process: the toast's Settings link starts it with launch(),
             so it outlives the toast.
@input      the user's typing and clicks; the saved settings
@output     a window on screen until closed; settings saved through conpact.settings
@dependencies conpact.desktop, conpact.detach, conpact.home, conpact.settings,
              conpact.toast_text, conpact.ui_style; stdlib: os, pathlib, sys, tkinter
"""
from __future__ import annotations

import os
import pathlib
import sys

from . import desktop, detach, home, settings, toast_text, ui_style

MODULE = "conpact.settings_window"
SRC_ROOT = str(pathlib.Path(__file__).resolve().parents[1])
WIDTH = 460
# Every on/off setting has its own button, so the click carries which one it is.
TOGGLE_ACTION = "toggle:"
# The tabs, in order, and the settings on each. Every setting is on exactly one;
# all on one page, the window was taller than a 1080-pixel screen (D-20260923-049).
TABS = (
    ("Idle toast", (settings.TOGGLE, "lead_seconds", "mute_seconds", "result_seconds")),
    ("Session size", ("min_context_fill", "min_context_tokens")),
    ("Early toast", ("idle_seconds", "early_toast_seconds")),
    ("Agent", ("closure_min_context_tokens", settings.GUARD_SPIN_OFF)),
)
TAB_ACTION = "tab:"
NEXT_TAB, PREVIOUS_TAB = "<<NextTab>>", "<<PreviousTab>>"  # Ctrl+Tab, Ctrl+Shift+Tab


def text_of(value) -> str:
    """A number as the form shows it: "100,000", or empty for off."""
    return "" if value is None else f"{value:,}"


def _short(key: str, exc: Exception) -> str:
    """A refusal without the key, as a sentence: "Must be from 10 to 86,400 seconds."."""
    text = str(exc).removeprefix(f"{key} ")
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")


class Form:
    """What the window edits: the typed text of each number, and each on/off setting."""

    def __init__(self):
        self.errors, self.message = {}, ""
        self._fill(settings.load())

    def _fill(self, values: dict) -> None:
        self.values = values
        self.text = {s.key: text_of(values[s.key]) for s in settings.SETTINGS if s.unit}
        self.on = {s.key: values[s.key] for s in settings.SETTINGS if s.unit is None}

    def set_text(self, key: str, text: str) -> None:
        self.text[key] = text

    def toggle(self, key: str) -> None:
        self.on[key] = not self.on[key]

    def fill_defaults(self) -> None:
        defaults = settings.defaults()
        self.text = {key: text_of(defaults[key]) for key in self.text}
        self.on = {key: defaults[key] for key in self.on}
        self.errors = {}
        self.message = "Defaults filled in. Save to keep them."

    def save(self) -> bool:
        """Store what changed; False (nothing stored) if any value is refused or the write fails."""
        values, self.errors = dict(self.on), {}
        for key, text in self.text.items():
            try:
                values[key] = settings.parse(key, text)
            except ValueError as exc:
                self.errors[key] = _short(key, exc)
        if self.errors:
            self.message = "Not saved: fix the marked values."
            return False
        changes = {key: value for key, value in values.items() if value != self.values[key]}
        if not changes:
            self.message = "Nothing changed."
            return True
        try:
            saved = settings.save(changes)
        except (OSError, ValueError) as exc:
            self.message = f"Not saved: {exc}"
            return False
        self._fill(saved)
        self.message = f"Saved. {settings.APPLIES}"
        return True


class SettingsView:
    """The window's widgets, on an existing Tk root."""

    def __init__(self, root, form: Form, palette: dict, scale: float = 1.0):
        self.root, self.form, self.p, self.scale = root, form, palette, scale
        self.closed = False
        self.entries, self.labels, self.units, self.error_labels = {}, {}, {}, {}
        self.buttons, self.toggle_buttons = {}, {}
        self.tabs, self.marks, self.pages, self.tab = {}, {}, {}, TABS[0][0]
        self._build()
        self.refresh()

    def px(self, n: float) -> int:
        return max(1, round(n * self.scale))

    def _build(self) -> None:
        import tkinter as tk
        p, root = self.p, self.root
        root.title("conPACT settings")
        root.configure(bg=p["bg"])
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Return>", lambda event: self.save())
        root.bind("<Escape>", lambda event: self.close())
        root.event_add(NEXT_TAB, "<Control-Tab>")
        for back in ("<Control-Shift-Tab>", "<Control-ISO_Left_Tab>"):  # Windows and macOS; X11
            try:
                root.event_add(PREVIOUS_TAB, back)
            except tk.TclError:
                pass  # a key this platform has no name for
        root.bind(NEXT_TAB, lambda event: self.step(1))
        root.bind(PREVIOUS_TAB, lambda event: self.step(-1))
        outer = tk.Frame(root, bg=p["bg"])
        outer.pack(fill="both", expand=True)
        tk.Frame(outer, bg=p["accent"], width=self.px(4)).pack(side="left", fill="y")
        content = tk.Frame(outer, bg=p["bg"], padx=self.px(20), pady=self.px(16))
        content.pack(side="left", fill="both", expand=True)
        tk.Label(content, text="✳  " + toast_text.BRAND, font=(ui_style.FONT_STRONG, 8), fg=p["accent"],
                 bg=p["bg"], anchor="w").pack(fill="x")
        tk.Label(content, text="Settings", font=(ui_style.FONT_STRONG, 13), fg=p["text"], bg=p["bg"],
                 anchor="w").pack(fill="x", pady=(self.px(4), self.px(4)))
        self._tab_strip(content)
        book = tk.Frame(content, bg=p["bg"])
        book.pack(fill="x")
        book.grid_columnconfigure(0, weight=1)
        for name, keys in TABS:
            self.pages[name] = tk.Frame(book, bg=p["bg"])
            self.pages[name].grid(row=0, column=0, sticky="nsew")
            for key in keys:
                self._row(self.pages[name], settings.get(key))
        # Every page is as tall as the tallest, so changing tab never moves the buttons.
        book.update_idletasks()
        book.grid_rowconfigure(0, minsize=max(page.winfo_reqheight() for page in self.pages.values()))
        self.select(self.tab, focus=False)
        self.status = self._text(content, "", 9, p["muted"])
        self.status.pack(fill="x", pady=(self.px(12), self.px(8)))
        row = tk.Frame(content, bg=p["bg"])
        row.pack(fill="x")
        for action, label, style in (("save", "Save", "primary"), ("defaults", "Defaults", "secondary"),
                                     ("close", "Close", "ghost")):
            button = self._button(row, label, style, action)
            button.pack(side="right" if style == "ghost" else "left", padx=(0, self.px(8)))
            self.buttons[action] = button

    def _tab_strip(self, parent) -> None:
        import tkinter as tk
        p = self.p
        strip = tk.Frame(parent, bg=p["bg"])
        strip.pack(fill="x", pady=(self.px(8), 0))
        for name, _ in TABS:
            cell = tk.Frame(strip, bg=p["bg"])
            cell.pack(side="left", padx=(0, self.px(18)))
            tab = tk.Label(cell, text=name, font=(ui_style.FONT_STRONG, 9), fg=p["muted"], bg=p["bg"],
                           padx=0, pady=self.px(4), cursor="hand2", takefocus=0)
            tab.pack(fill="x")
            tab.bind("<Enter>", lambda event, tab=tab: tab.configure(fg=self.p["text"]))
            tab.bind("<Leave>", lambda event: self._paint_tabs())
            tab.bind("<ButtonRelease-1>", lambda event, name=name: self.click(TAB_ACTION + name))
            self.tabs[name] = tab
            self.marks[name] = tk.Frame(cell, bg=p["bg"], height=self.px(2))
            self.marks[name].pack(fill="x")
        tk.Frame(parent, bg=p["border"], height=1).pack(fill="x")

    def _text(self, parent, text, size, color):
        import tkinter as tk
        return tk.Label(parent, text=text, font=(ui_style.FONT, size), fg=color, bg=self.p["bg"], anchor="w",
                        justify="left", wraplength=self.px(WIDTH - 44))

    def _button(self, parent, text, style, action, pad=(12, 6)):
        return ui_style.label_button(parent, text, style, self.p, lambda: self.click(action), self.px, pad)

    def _row(self, parent, setting) -> None:
        import tkinter as tk
        p, key = self.p, setting.key
        frame = tk.Frame(parent, bg=p["bg"])
        frame.pack(fill="x", pady=(self.px(10), 0))
        self.labels[key] = tk.Label(frame, text=setting.label, font=(ui_style.FONT_STRONG, 9), fg=p["text"],
                                    bg=p["bg"], anchor="w")
        self.labels[key].pack(fill="x")
        line = tk.Frame(frame, bg=p["bg"])
        line.pack(fill="x", pady=(self.px(3), 0))
        if setting.unit is None:
            self.toggle_buttons[key] = self._button(line, "On", "secondary", TOGGLE_ACTION + key, pad=(16, 4))
            self.toggle_buttons[key].pack(side="left")
        else:
            entry = tk.Entry(line, width=12, font=(ui_style.FONT, 10), bg=p["secondary"], fg=p["text"],
                             insertbackground=p["text"], relief="flat", highlightthickness=1,
                             highlightbackground=p["border"], highlightcolor=p["accent"])
            entry.pack(side="left", ipady=self.px(3))
            self.entries[key] = entry
            default = text_of(setting.default) or "off"
            self.units[key] = tk.Label(line, text=f"{setting.unit}   default {default}", font=(ui_style.FONT, 9),
                                       fg=p["muted"], bg=p["bg"])
            self.units[key].pack(side="left", padx=(self.px(8), 0))
        self._text(frame, setting.help, 8, p["muted"]).pack(fill="x", pady=(self.px(2), 0))
        self.error_labels[key] = self._text(frame, "", 8, p["error"])

    # --- behaviour -------------------------------------------------------

    def click(self, action: str) -> None:
        if self.closed:
            return
        if action.startswith(TOGGLE_ACTION):
            self.toggle(action[len(TOGGLE_ACTION):])
        elif action.startswith(TAB_ACTION):
            self.select(action[len(TAB_ACTION):])
        else:
            {"save": self.save, "defaults": self.defaults, "close": self.close}[action]()

    def refresh(self) -> None:
        form = self.form
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, form.text[key])
        for key, button in self.toggle_buttons.items():
            button.configure(text="On" if form.on[key] else "Off")
        for key, label in self.error_labels.items():
            message = form.errors.get(key, "")
            label.configure(text=message)
            if message:
                label.pack(fill="x")
            else:
                label.pack_forget()
        not_saved = form.message.startswith("Not saved")
        self.status.configure(text=form.message, fg=self.p["error"] if not_saved else self.p["muted"])
        marked = [name for name, keys in TABS if form.errors.keys() & set(keys)]
        if marked and self.tab not in marked:
            self.select(marked[0])  # a refusal on a page that is not showing would go unseen
        self._paint_tabs()

    def select(self, name: str, focus: bool = True) -> None:
        """Show one tab's page, and take the keyboard to it, so nothing is typed into a hidden one."""
        self.tab = name
        for other, page in self.pages.items():
            if other == name:
                page.grid()
            else:
                page.grid_remove()
        self._paint_tabs()
        if focus:
            self._first_box().focus_set()

    def step(self, by: int) -> str:
        names = [name for name, _ in TABS]
        self.select(names[(names.index(self.tab) + by) % len(names)])
        return "break"  # or Tk's own Tab binding moves the focus on again

    def _first_box(self):
        """The first box on the page that is showing, or the window when it has none."""
        return next((self.entries[key] for key in dict(TABS)[self.tab] if key in self.entries), self.root)

    def _paint_tabs(self) -> None:
        p, refused = self.p, self.form.errors.keys()
        for name, keys in TABS:
            chosen = name == self.tab
            self.tabs[name].configure(fg=p["error"] if refused & set(keys) else p["text"] if chosen else p["muted"])
            self.marks[name].configure(bg=p["accent"] if chosen else p["bg"])

    def save(self) -> None:
        for key, entry in self.entries.items():
            self.form.set_text(key, entry.get())
        self.form.save()
        self.refresh()

    def defaults(self) -> None:
        self.form.fill_defaults()
        self.refresh()

    def toggle(self, key: str) -> None:
        self.form.toggle(key)
        self.toggle_buttons[key].configure(text="On" if self.form.on[key] else "Off")

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.root.withdraw()
            self.root.after(0, self.root.quit)

    def show(self) -> None:
        """Centre the window in the work area and give it focus."""
        root = self.root
        root.update_idletasks()
        width, height = root.winfo_reqwidth(), root.winfo_reqheight()
        left, top, right, bottom = desktop.work_area((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))
        root.geometry(f"+{left + max(0, (right - left - width) // 2)}+{top + max(0, (bottom - top - height) // 3)}")
        root.deiconify()
        root.lift()
        root.focus_force()
        self._first_box().focus_set()


def run() -> None:
    """Show the window and return once it is closed."""
    import tkinter as tk
    desktop.dpi_aware()
    root = tk.Tk()
    root.withdraw()
    try:
        view = SettingsView(root, Form(), ui_style.PALETTES[desktop.theme()], root.winfo_fpixels("1i") / 96)
        view.show()
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def launch(spawn=None, environ=None) -> int:
    """Start the window as its own process (from a toast's Settings link); returns its pid."""
    argv = [detach.windowless_python(), "-m", MODULE]
    env = {**(os.environ if environ is None else environ), "PYTHONPATH": SRC_ROOT}
    return (spawn or detach.spawn)(argv, env=env)


def main(argv=None) -> int:
    home.migrate()
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
