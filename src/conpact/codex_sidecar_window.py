"""
@module conpact.codex_sidecar_window
@description The one click. A small window that says whether the Codex sidecar
             is installed and offers the single action that is available: Install
             when it is not, Uninstall when it is. Everything the install needs -
             building the shim, finding the real codex, writing the user's
             environment - happens behind that one button, so there is no
             sequence for the user to get right and no compiler step to remember.

             The window's logic (`Panel`) has no Tk in it: it holds the status,
             the action that applies, and the sentence to show after acting, and
             is tested directly. The Tk half only draws it. The look is the
             toast's (stdlib Tk, D-015), and the window runs in its own process
             so it outlives whatever started it.
@input      the user's click; what `codex_sidecar_install.status` reads
@output     a window on screen until closed; the sidecar installed or removed
@dependencies conpact.codex_sidecar_install, conpact.desktop,
              conpact.detach, conpact.ui_style; stdlib: os, pathlib, sys,
              tkinter
"""
from __future__ import annotations

import os
import pathlib
import sys

from . import codex_sidecar_install as install_module
from . import desktop, detach, ui_style

MODULE = "conpact.codex_sidecar_window"
SRC_ROOT = str(pathlib.Path(__file__).resolve().parents[1])
WIDTH = 460

TITLE = "Codex sidecar"
BLURB = ("Lets conPACT compact a ChatGPT Desktop thread while the app is "
         "still holding it open. It stands in front of the app-server ChatGPT "
         "starts, and passes everything else straight through.")

INSTALL = "install"
UNINSTALL = "uninstall"


class Panel:
    """What the window shows and what its button does. No Tk in here."""

    def __init__(self, reader=None, installer=None, remover=None):
        self._read = reader or install_module.status
        self._install = installer or install_module.install
        self._remove = remover or install_module.uninstall
        self.message = ""
        self.failed = False
        self.refresh()

    def refresh(self) -> None:
        self.status = self._read()

    @property
    def installed(self) -> bool:
        return bool(self.status.get("installed"))

    @property
    def action(self) -> str:
        """The one thing worth offering, which is never both."""
        return UNINSTALL if self.installed else INSTALL

    @property
    def action_text(self) -> str:
        return "Uninstall" if self.installed else "Install"

    @property
    def headline(self) -> str:
        if self.installed:
            return "Installed and ready." if self.status.get("sidecar_running") \
                else "Installed. Restart ChatGPT Desktop to start using it."
        return "Not installed."

    def detail(self) -> str:
        """What the user would otherwise have to go and look up."""
        lines = [f"Shim: {self.status.get('exe')}"]
        if self.status.get("env_value"):
            lines.append(f"CODEX_CLI_PATH: {self.status['env_value']}")
        lines.append(self.status.get("store_note", ""))
        return "\n".join(line for line in lines if line)

    def click(self) -> None:
        """Do the one action, then say what happened. A refusal is a sentence in
        the window, never an exception out of it."""
        act = self._remove if self.installed else self._install
        try:
            outcome = act()
        except Exception as problem:               # a window must never die on a click
            self.message, self.failed = f"{type(problem).__name__}: {problem}", True
            return
        self.message = outcome.get("message") or ""
        self.failed = not outcome.get("done")
        self.refresh()


class SidecarView:
    """The window itself."""

    def __init__(self, root, panel: Panel, palette: dict, scale: float = 1.0):
        self.root, self.panel, self.p, self.scale = root, panel, palette, scale
        self.build()

    def px(self, n: float) -> int:
        return max(1, round(n * self.scale))

    def build(self) -> None:
        import tkinter as tk
        p = self.p
        self.root.title(TITLE)
        self.root.configure(bg=p["bg"])
        outer = tk.Frame(self.root, bg=p["bg"])
        outer.pack(fill="both", expand=True)
        tk.Frame(outer, bg=p["accent"], width=self.px(4)).pack(side="left", fill="y")
        content = tk.Frame(outer, bg=p["bg"], padx=self.px(20), pady=self.px(16))
        content.pack(side="left", fill="both", expand=True)

        self._text(content, TITLE, 11, p["text"], ui_style.FONT_STRONG).pack(
            fill="x", pady=(0, self.px(4)))
        self._text(content, BLURB, 9, p["body"]).pack(fill="x", pady=(0, self.px(12)))

        self.headline = self._text(content, "", 9, p["text"], ui_style.FONT_STRONG)
        self.headline.pack(fill="x")
        self.detail = self._text(content, "", 8, p["muted"])
        self.detail.pack(fill="x", pady=(self.px(4), self.px(12)))

        row = tk.Frame(content, bg=p["bg"])
        row.pack(fill="x")
        self.button = ui_style.label_button(row, "", "primary", p, self.click, self.px)
        self.button.pack(side="left")
        ui_style.label_button(row, "Close", "ghost", p, self.root.destroy,
                              self.px).pack(side="right")

        self.message = self._text(content, "", 8, p["muted"])
        self.message.pack(fill="x", pady=(self.px(10), 0))
        self.show()

    def _text(self, parent, text, size, colour, font=None):
        import tkinter as tk
        return tk.Label(parent, text=text, font=(font or ui_style.FONT, size),
                        bg=self.p["bg"], fg=colour, anchor="w", justify="left",
                        wraplength=self.px(WIDTH - 44))

    def show(self) -> None:
        self.button.configure(text=self.panel.action_text)
        self.headline.configure(text=self.panel.headline)
        self.detail.configure(text=self.panel.detail())
        self.message.configure(
            text=self.panel.message,
            fg=self.p["error"] if self.panel.failed else self.p["muted"])

    def click(self) -> None:
        self.button.configure(text="Working...")
        self.root.update_idletasks()
        self.panel.click()
        self.show()


def run() -> None:                     # pragma: no cover - exercised as -m
    import tkinter as tk
    root = tk.Tk()
    try:
        SidecarView(root, Panel(), ui_style.PALETTES[desktop.theme()],
                    root.winfo_fpixels("1i") / 96)
        root.resizable(False, False)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def launch(spawn=None, environ=None) -> int:
    """Open the window in its own process, so it outlives whatever asked for it."""
    argv = [detach.windowless_python(), "-m", MODULE]
    env = {**(os.environ if environ is None else environ), "PYTHONPATH": SRC_ROOT}
    return (spawn or detach.spawn)(argv, env=env)


def main(argv=None) -> int:
    run()
    return 0


if __name__ == "__main__":             # pragma: no cover - the window's entry point
    sys.exit(main())
