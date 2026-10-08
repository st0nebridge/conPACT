"""
@module conpact.toast_view
@description The idle toast window (D-015): a small styled card in the
             bottom-right corner of the work area, stacked by screen slot, drawn
             with stdlib Tk in the shared look (ui_style). Its buttons are
             mouse-only labels, so a stray Enter or Space never presses one; it
             appears without taking focus (the first toast a process shows
             included: its windows are made with activation refused), fades
             in, follows the Windows light/dark app theme and has rounded corners
             on Windows 11. It knows nothing about sessions: it renders a
             controller's model(), calls poll() twice a second (closing on any
             reason), runs act(action) on a worker thread when a button is
             clicked and shows the resulting state. Choices styled "link" go on
             a second line under the buttons, because the card is only as wide
             as WIDTH and a fourth button in the row is clipped off its edge. Once a compaction was sent
             it stays up and shows progress() twice a second (elapsed time, then
             the tokens before and after) instead of polling. Its Settings link
             starts the settings window as its own process; how long a result
             stays up comes from the user's settings. `--demo` shows a sample
             that sends nothing. Dismissing a pending action hides the window
             immediately while its event loop retains the worker's result;
             dismissal never cancels or resubmits a compaction.
@input      a controller with model() / poll() / act(action) / progress()
@output     a window on screen until the controller or the user closes it
@dependencies conpact.desktop, conpact.detach, conpact.idle_state,
              conpact.toast_text, conpact.ui_style, conpact.settings and
              conpact.settings_window (lazily); stdlib: argparse, os, queue,
              sys, threading, time, tkinter
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time

from . import desktop, detach, idle_state, toast_text
from .ui_style import FONT, FONT_STRONG, PALETTES, label_button  # noqa: F401 (PALETTES: the toast's theme)

WIDTH = 380
TICK_MS = 500
FADE_STEPS = 8
ALPHA = 0.98
CLOSE_AFTER = {"compacted": 8000, "untracked": 4000, "auto_off": 2500, "startup_on": 2500,
               "deferred": 3000, "auto_expiry_set": 3000}
# other results stay until closed
DEMO_COMPACT_SECONDS = 4.0


def act_into(controller, action: str, results: queue.Queue) -> None:
    """Run controller.act(action) (on a worker thread) and queue the resulting state."""
    try:
        state = controller.act(action)
    except Exception as exc:  # shown to the user rather than lost in a thread
        state = {"state": "error", "detail": f"{type(exc).__name__}: {exc}"}
    results.put(state)


class ToastView:
    """The card's widgets and behaviour, on an existing (withdrawn) Tk root."""

    def __init__(self, root, controller, clock=time.time, palette=None, scale: float = 1.0,
                 close_after=None, open_settings=None):
        self.root, self.controller, self.clock = root, controller, clock
        self.close_after = CLOSE_AFTER if close_after is None else close_after
        self.open_settings = open_settings
        self.p = palette or PALETTES["dark"]
        self.scale = scale
        self.model = controller.model()
        self.results = queue.Queue()
        self.busy = self.final = self.closed = False
        self.dismissed = False
        self.tracking = bool(self.model.get("compacting"))  # an auto-compaction is already under way
        self.fraction = 1.0
        self._build()

    def px(self, n: float) -> int:
        return max(1, round(n * self.scale))

    def _build(self) -> None:
        import tkinter as tk
        p, root, now = self.p, self.root, self.clock()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=p["border"])
        card = tk.Frame(root, bg=p["bg"])
        card.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(card, bg=p["accent"], width=self.px(4)).pack(side="left", fill="y")
        content = tk.Frame(card, bg=p["bg"], padx=self.px(16), pady=self.px(14))
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=p["bg"])
        header.pack(fill="x")
        tk.Label(header, text="✳  " + toast_text.BRAND, font=(FONT_STRONG, 8), fg=p["accent"],
                 bg=p["bg"]).pack(side="left")
        self.close_button = self._button(header, "✕", "ghost", "dismiss", pad=(6, 0))
        self.close_button.pack(side="right")
        self.mute_button = None
        if self.model["kind"] in ("ask", "remote"):
            self.mute_button = self._button(header, toast_text.mute_label(self.model.get("mute_seconds")),
                                            "ghost", "mute", pad=(6, 0))
            self.mute_button.pack(side="right")
        self.settings_button = None
        if self.open_settings is not None:
            self.settings_button = self._button(header, toast_text.SETTINGS_LINK, "ghost", "settings", pad=(6, 0))
            self.settings_button.pack(side="right")

        wrap = self.px(WIDTH - 44)
        self.title = self._text(content, toast_text.title(self.model), (FONT_STRONG, 11), p["text"], wrap)
        self.title.pack(fill="x", pady=(self.px(8), 0))
        self.body = self._text(content, toast_text.body(self.model, now), (FONT, 9), p["body"], wrap)
        self.body.pack(fill="x", pady=(self.px(3), 0))
        self.status = self._text(content, toast_text.status(self.model, now), (FONT, 9), p["muted"], wrap)
        self.status.pack(fill="x", pady=(self.px(1), 0))

        self.bar = tk.Canvas(content, height=self.px(3), bg=p["track"], highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(self.px(10), self.px(12)))
        self.bar_fill = self.bar.create_rectangle(0, 0, 0, self.px(3), fill=p["accent"], width=0)

        self.row = tk.Frame(content, bg=p["bg"])
        self.row.pack(fill="x")
        # The standing choices go on their own line: three buttons already fill
        # the row, and a fourth would run past the card's edge. A toast without
        # any is built exactly as it was, down to the widget tree.
        found = toast_text.actions(self.model)
        self.links = tk.Frame(content, bg=p["bg"]) if any(s == "link" for _, _, s in found) else None
        self.buttons = {}
        for action, label, style in found:
            if style == "link":
                button = self._button(self.links, label, style, action, pad=(0, 2))
                button.pack(side="left", padx=(0, self.px(14)))
            elif style == "ghost":
                button = self._button(self.row, label, style, action)
                button.pack(side="right")
            else:
                button = self._button(self.row, label, style, action)
                button.pack(side="left", padx=(0, self.px(8)))
            self.buttons[action] = button
        if self.links is not None:
            self.links.pack(fill="x", pady=(self.px(10), 0))

    def _text(self, parent, text, font, color, wrap):
        import tkinter as tk
        return tk.Label(parent, text=text, font=font, fg=color, bg=self.p["bg"], anchor="w",
                        justify="left", wraplength=wrap)

    def _button(self, parent, text, style, action, pad=(12, 6)):
        return label_button(parent, text, style, self.p, lambda: self.click(action), self.px, pad)

    # --- behaviour -------------------------------------------------------

    def click(self, action: str) -> None:
        if self.closed:
            return
        if action == "settings":
            self._open_settings()  # any time: it changes nothing on this toast
            return
        if action == "dismiss" and (self.tracking or self.final):
            self.close()  # nothing is left to decide; a sent compaction goes on regardless
            return
        if action == "dismiss" and self.busy:
            # Codex's send waits for recorded completion. Hide immediately, but
            # retain the event loop until _drain receives the worker's outcome
            # so the watcher cannot exit and abandon an in-flight operation.
            self.dismissed = True
            self.root.withdraw()
            return
        if self.busy:
            return
        self.busy = True
        if action in ("compact", "auto"):
            self._say(toast_text.state_message({"state": "working"}), self.p["body"])
            self._hide_actions()
        elif action in ("defer", "auto_expiry"):
            self._hide_actions()  # nothing is sent, so nothing says it is sending
        # The worker gets the controller and the queue only - never the view or
        # a Tk object, which must not be touched (or freed) off the main thread.
        threading.Thread(target=act_into, args=(self.controller, action, self.results), daemon=True).start()
        self.root.after(50, self._drain)

    def _open_settings(self) -> None:
        if self.open_settings is None:
            return
        try:
            self.open_settings()
        except OSError as exc:
            self._say(toast_text.settings_failed(exc), self.p["error"])

    def _drain(self) -> None:
        if self.closed:
            return
        try:
            state = self.results.get_nowait()
        except queue.Empty:
            self.root.after(50, self._drain)
            return
        if self.dismissed:
            self.close()
        else:
            self.show_state(state)

    def show_state(self, state: dict) -> None:
        """Show a click's result or a sent compaction's progress."""
        kind = state.get("state")
        if kind == "closed":
            self.close()
            return
        if kind == "sent":
            self.tracking = True
            self._hide_actions()
            self.title.configure(text=toast_text.title(self.model, "compacting"))
            state = {"state": "compacting", "elapsed": 0}
        if state["state"] == "compacting":
            self._say(toast_text.state_message(state), self.p["text"])
            return
        self.tracking, self.final = False, True
        self._hide_actions()
        if kind == "compacted":
            self.title.configure(text=toast_text.title(self.model, "compacted"))
        stays = kind not in self.close_after
        self._say(toast_text.state_message(state), self.p["error"] if stays else self.p["text"])
        if stays:
            self.busy = False  # only the close button is left
        else:
            self.root.after(self.close_after[kind], self.close)

    def _hide_actions(self) -> None:
        """Take away every row: once a choice is made there is nothing left to choose."""
        self.row.pack_forget()
        if self.links is not None:
            self.links.pack_forget()

    def _say(self, text: str, color: str) -> None:
        self.status.configure(text=text, fg=color)

    def tick(self) -> None:
        if self.closed:
            return
        if self.tracking:
            self._fill(1.0)
            self.show_state(self.controller.progress())
        elif not (self.busy or self.final):
            if self.controller.poll():
                self.close()
                return
            now = self.clock()
            self.status.configure(text=toast_text.status(self.model, now))
            self.body.configure(text=toast_text.body(self.model, now))
            span = self.model["span"] or 1
            self._fill(min(1.0, max(0.0, (self.model["deadline"] - now) / span)))
        self.root.after(TICK_MS, self.tick)

    def _fill(self, fraction: float) -> None:
        self.fraction = fraction
        self.bar.coords(self.bar_fill, 0, 0, self.bar.winfo_width() * fraction, self.px(3))

    def close(self) -> None:
        """Hide at once; end the event loop from inside it (a quit issued before
        mainloop() starts is lost, which would leave a dead window on screen)."""
        if not self.closed:
            self.closed = True
            self.root.withdraw()
            self.root.after(0, self.root.quit)

    def show(self, slot: int) -> None:
        """Place the card in the bottom-right corner (stacked by slot), fade it in, start ticking."""
        root = self.root
        root.update_idletasks()
        width, height = self.px(WIDTH), root.winfo_reqheight()
        _, _, right, bottom = desktop.work_area((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))
        margin, gap = self.px(16), self.px(10)
        x = right - width - margin
        y = bottom - margin - height - slot * (height + gap)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.attributes("-alpha", 0.0)
        desktop.show_without_focus(root)
        self._fade(0)
        root.after(TICK_MS, self.tick)  # polled from inside the event loop, never before it runs

    def _fade(self, step: int) -> None:
        if self.closed:
            return
        self.root.attributes("-alpha", ALPHA * (step + 1) / FADE_STEPS)
        if step + 1 < FADE_STEPS:
            self.root.after(16, self._fade, step + 1)


def options() -> dict:
    """The toast's options from the user's settings: how long a result stays up, and the Settings link."""
    from . import settings, settings_window
    return {"close_after": {**CLOSE_AFTER, "compacted": settings.load()["result_seconds"] * 1000},
            "open_settings": settings_window.launch}


def present(controller, clock=None) -> None:
    """Show the toast for a controller and return once it has closed.

    None of it may take the keyboard, the first toast a process shows included:
    Tk activates the first window a thread makes, so every window here is made
    with activation refused, and the keyboard is handed back the moment Tk has
    made the toast's window, in case Windows moved it anyway (D-20260924-054).
    """
    import tkinter as tk
    desktop.dpi_aware()
    with desktop.NoActivation() as keyboard:   # before Tk makes any window
        root = tk.Tk()
        root.withdraw()
        slot = idle_state.claim_slot(os.getpid(), detach.pid_alive)
        try:
            view = ToastView(root, controller, clock or getattr(controller, "clock", time.time),
                             PALETTES[desktop.theme()], root.winfo_fpixels("1i") / 96, **options())
            root.update_idletasks()   # Tk makes the window here, and asks for it to be activated
            keyboard.hand_back()
            view.show(slot or 0)
            root.mainloop()
        finally:
            idle_state.release_slot(slot)
            try:
                root.destroy()
            except tk.TclError:
                pass


class DemoController:
    """A sample for --demo: realistic numbers, and nothing is ever sent."""

    def __init__(self, kind: str, seconds: float, clock=time.time):
        self.clock = clock
        self.opened = clock()
        self.seconds = seconds
        self.kind = kind
        self.actions = []
        self.sent_at = self.opened  # a notice is shown once its compaction has started

    def model(self) -> dict:
        now = self.opened
        if self.kind in ("ask", "early", "remote"):
            return {"kind": "remote" if self.kind == "remote" else "ask",
                    **({"stage": "early"} if self.kind == "early" else {}),
                    "name": "conPACT", "context_tokens": 656_725,
                    "last_call": now - 3300, "deadline": now + 300, "span": 300,
                    "expires_at": now + 300, "mute_seconds": 86_400,
                    **({"offer_always_on": True} if self.kind == "remote" else {})}
        return {"kind": "notice", "variant": "failed" if self.kind == "failed" else "compacted",
                "compacting": self.kind != "failed",
                "detail": "bridge returned HTTP 401" if self.kind == "failed" else None,
                "name": "conPACT", "context_tokens": 656_725, "last_call": now - 3300,
                "deadline": now + self.seconds, "span": self.seconds}

    def poll(self):
        return "timeout" if self.clock() >= self.opened + self.seconds else None

    def act(self, action: str) -> dict:
        self.actions.append(action)
        if action in ("dismiss", "mute", "open_session"):
            return {"state": "closed"}   # the demo opens nothing and silences nothing
        if action in ("defer", "auto_expiry"):
            return {"state": "deferred" if action == "defer" else "auto_expiry_set"}
        if action == "always_on":
            return {"state": "startup_on"}   # and changes no setting
        time.sleep(0.6)  # stands in for the bridge call
        if action == "turn_off_auto":
            return {"state": "auto_off"}
        self.sent_at = self.clock()
        return {"state": "sent"}

    def progress(self) -> dict:
        elapsed = self.clock() - self.sent_at
        if elapsed < DEMO_COMPACT_SECONDS:
            return {"state": "compacting", "elapsed": elapsed}
        return {"state": "compacted", "pre_tokens": 656_725, "post_tokens": 19_111, "seconds": 78.0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m conpact.toast_view",
                                     description="Show a sample idle toast. Nothing is sent.")
    parser.add_argument("--demo", choices=("ask", "early", "notice", "failed", "remote"), required=True)
    parser.add_argument("--seconds", type=float, default=30.0, help="close after this long")
    args = parser.parse_args(argv)
    controller = DemoController(args.demo, args.seconds)
    present(controller)
    print(f"closed; clicked: {', '.join(controller.actions) or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
