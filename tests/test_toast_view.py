"""Tests for conpact.toast_view: the toast window, driven through real Tk events."""
import os
import pathlib
import queue
import re
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from conpact import desktop, idle_state, toast_text, toast_view as tv  # noqa: E402
from tk_reading import font as _font, packing as _packing  # noqa: E402
import window_guard  # noqa: E402
import window_process  # noqa: E402

ASK = {"kind": "ask", "name": "conPACT", "context_tokens": 656_725, "last_call": 1000.0,
       "deadline": 4600.0, "span": 300.0}
EARLY = {**ASK, "stage": "early", "expires_at": 6000.0}   # the only stage with a later one
NOTICE = {"kind": "notice", "variant": "compacted", "compacting": True, "detail": None, "name": "conPACT",
          "context_tokens": 656_725, "last_call": 1000.0, "deadline": 4320.0, "span": 20}
DONE = {"state": "compacted", "pre_tokens": 656_725, "post_tokens": 19_111, "seconds": 78.0}


class Controller:
    def __init__(self, model, results=None, reason=None, state=None):
        self._model = model
        self.results = results or {}
        self.reason = reason
        self.state = state or {"state": "compacting", "elapsed": 0}
        self.acts = []
        self.threads = []
        self.polls = 0
        self.checks = 0

    def model(self):
        return self._model

    def poll(self):
        self.polls += 1
        return self.reason

    def act(self, action):
        self.acts.append(action)
        self.threads.append(threading.current_thread())
        result = self.results.get(action, {"state": "closed"})
        return result() if callable(result) else result

    def progress(self):
        self.checks += 1
        return self.state


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def root():
    # Mapped (Tk drops events sent to unmapped widgets) but far off screen, and
    # borderless, as the card is.
    yield from window_guard.root(tk, prepare=lambda window: window.overrideredirect(True))


def _pump(root, until, timeout=3.0):
    end = time.monotonic() + timeout
    while not until() and time.monotonic() < end:
        root.update()
        time.sleep(0.01)
    return until()


def _view(root, controller, now=4300.0):
    view = tv.ToastView(root, controller, Clock(now), tv.PALETTES["dark"])
    root.update()
    return view


def test_constants_and_palettes():
    assert (tv.WIDTH, tv.TICK_MS, tv.FADE_STEPS, tv.ALPHA) == (380, 500, 8, 0.98)
    assert tv.CLOSE_AFTER == {"compacted": 8000, "untracked": 4000, "auto_off": 2500, "startup_on": 2500,
                              "deferred": 3000, "auto_expiry_set": 3000}
    assert set(tv.PALETTES) == {"dark", "light"}
    assert set(tv.PALETTES["dark"]) == set(tv.PALETTES["light"])
    for palette in tv.PALETTES.values():
        assert all(re.fullmatch(r"#[0-9a-f]{6}", color) for color in palette.values())


def test_the_ask_toast_renders_its_model(root):
    view = _view(root, Controller(ASK))
    assert view.title.cget("text") == "Compact “conPACT”?"
    assert view.body.cget("text") == "657k tokens · idle 55 min"
    assert view.status.cget("text") == "Prompt cache expires in 5:00"
    assert {a: b.cget("text") for a, b in view.buttons.items()} == {
        "compact": "Compact now", "auto": "Always compact", "dismiss": "Not now"}
    assert view.buttons["compact"].cget("bg") == tv.PALETTES["dark"]["accent"]
    assert view.close_button.cget("text") == "✕"


def test_the_notice_renders_its_model(root):
    view = _view(root, Controller(NOTICE))
    assert view.title.cget("text") == "Auto-compacting “conPACT”"
    assert view.status.cget("text") == "Compacting…"
    assert list(view.buttons) == ["turn_off_auto", "dismiss"]
    assert view.tracking is True
    assert _view(root, Controller({**NOTICE, "variant": "failed", "compacting": False})).tracking is False


def test_buttons_are_mouse_only(root):
    controller = Controller(ASK)
    view = _view(root, controller)
    for button in [*view.buttons.values(), view.close_button]:
        assert isinstance(button, tk.Label)
        assert str(button.cget("takefocus")) == "0"
        assert button.bind("<Return>") == "" and button.bind("<space>") == ""
    root.event_generate("<Return>")
    root.event_generate("<space>")
    root.update()
    assert controller.acts == []


def test_hover_changes_a_buttons_colours(root):
    view = _view(root, Controller(ASK))
    button, dark = view.buttons["compact"], tv.PALETTES["dark"]
    button.event_generate("<Enter>")
    assert button.cget("bg") == dark["accent_hover"]
    button.event_generate("<Leave>")
    assert button.cget("bg") == dark["accent"]
    ghost = view.buttons["dismiss"]
    ghost.event_generate("<Enter>")
    assert ghost.cget("fg") == dark["text"]


def test_a_click_acts_off_the_ui_thread_then_follows_the_compaction_to_its_result(root, monkeypatch):
    monkeypatch.setattr(tv, "CLOSE_AFTER", {"compacted": 10, "untracked": 10, "auto_off": 10})
    controller = Controller(ASK, results={"compact": {"state": "sent"}})
    view = _view(root, controller)
    view.buttons["compact"].event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.tracking)
    assert view.title.cget("text") == "Compacting “conPACT”"
    assert view.status.cget("text") == "Compacting… 0:00"
    assert controller.acts == ["compact"]
    assert controller.threads[0] is not threading.main_thread()
    assert controller.threads[0].daemon is True   # a stuck bridge call must not hold the process open
    assert view.row.winfo_manager() == ""
    controller.state = DONE
    view.tick()
    assert view.title.cget("text") == "Compacted “conPACT”"
    assert view.status.cget("text") == "Done in 1 min 18 s: 657k → 19k tokens."
    assert (view.tracking, view.final) == (False, True)
    assert _pump(root, lambda: view.closed)


def test_while_compacting_it_shows_the_elapsed_time_and_stops_asking(root):
    controller = Controller(ASK, results={"compact": {"state": "sent"}})
    view = _view(root, controller)
    view.click("compact")
    assert _pump(root, lambda: view.tracking)
    polls = controller.polls
    controller.state = {"state": "compacting", "elapsed": 65.9}
    view.tick()
    assert view.status.cget("text") == "Compacting… 1:05"
    assert view.fraction == 1.0
    assert (controller.polls, view.closed) == (polls, False)


def test_no_result_in_time_keeps_the_toast_open_with_only_close(root):
    controller = Controller(ASK, results={"compact": {"state": "sent"}},
                            state={"state": "unconfirmed", "seconds": 600.0})
    view = _view(root, controller)
    view.click("compact")
    assert _pump(root, lambda: view.tracking)
    view.tick()
    assert view.final
    assert view.status.cget("text") == "No result after 10 min. Check the session."
    assert view.status.cget("fg") == tv.PALETTES["dark"]["error"]
    root.update()
    assert not view.closed
    view.close_button.event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.closed)
    assert controller.acts == ["compact"]


def test_an_untracked_compaction_says_it_started_then_closes(root, monkeypatch):
    monkeypatch.setattr(tv, "CLOSE_AFTER", {"compacted": 10, "untracked": 10, "auto_off": 10})
    controller = Controller(ASK, results={"compact": {"state": "sent"}}, state={"state": "untracked"})
    view = _view(root, controller)
    view.click("compact")
    assert _pump(root, lambda: view.tracking)
    view.tick()
    assert view.status.cget("text") == "Compaction started. It can take a minute or two."
    assert _pump(root, lambda: view.closed)


def _linked(root, controller, opener):
    view = tv.ToastView(root, controller, Clock(4300.0), tv.PALETTES["dark"], open_settings=opener)
    root.update()
    return view


def test_the_settings_link_opens_the_settings_and_leaves_the_toast_as_it_is(root):
    opened, controller = [], Controller(ASK)
    view = _linked(root, controller, lambda: opened.append(True))
    assert view.settings_button.cget("text") == "Settings"
    assert str(view.settings_button.cget("takefocus")) == "0"
    view.settings_button.event_generate("<ButtonRelease-1>")
    root.update()
    assert opened == [True]
    assert (controller.acts, view.closed, view.busy) == ([], False, False)
    assert view.status.cget("text") == "Prompt cache expires in 5:00"


def test_the_settings_link_works_while_compacting(root):
    opened, controller = [], Controller(ASK, results={"compact": {"state": "sent"}})
    view = _linked(root, controller, lambda: opened.append(True))
    view.click("compact")
    assert _pump(root, lambda: view.tracking)
    view.click("settings")
    assert opened == [True] and view.tracking and controller.acts == ["compact"]


def test_a_settings_window_that_cannot_start_is_reported_on_the_toast(root):
    def broken():
        raise OSError("pythonw.exe not found")
    view = _linked(root, Controller(ASK), broken)
    view.click("settings")
    assert view.status.cget("text") == "Couldn't open the settings: pythonw.exe not found"
    assert view.status.cget("fg") == tv.PALETTES["dark"]["error"]
    assert not view.closed


def test_without_an_opener_there_is_no_settings_link(root):
    view = _view(root, Controller(ASK))
    assert view.settings_button is None
    view.click("settings")
    assert not view.closed


def test_a_result_stays_up_as_long_as_the_view_is_told(root):
    controller = Controller(ASK, results={"compact": {"state": "sent"}}, state=DONE)
    view = tv.ToastView(root, controller, Clock(4300.0), tv.PALETTES["dark"],
                        close_after={"compacted": 10, "untracked": 4000, "auto_off": 2500})
    root.update()
    view.click("compact")
    assert _pump(root, lambda: view.tracking)
    view.tick()
    assert _pump(root, lambda: view.closed, timeout=1.0)


def test_the_toasts_options_come_from_the_settings():
    from conpact import settings, settings_window
    assert tv.options() == {"close_after": tv.CLOSE_AFTER, "open_settings": settings_window.launch}
    settings.save({"result_seconds": 20})
    assert tv.options()["close_after"] == {**tv.CLOSE_AFTER, "compacted": 20_000}


def test_close_while_compacting_just_closes(root):
    controller = Controller(ASK, results={"compact": {"state": "sent"}})
    view = _view(root, controller)
    view.click("compact")
    assert _pump(root, lambda: view.tracking)
    view.close_button.event_generate("<ButtonRelease-1>")
    root.update()
    assert view.closed
    assert controller.acts == ["compact"]


def test_the_notice_follows_its_compaction_from_the_start(root, monkeypatch):
    monkeypatch.setattr(tv, "CLOSE_AFTER", {"compacted": 10, "untracked": 10, "auto_off": 10})
    controller = Controller(NOTICE, state=DONE)
    view = tv.ToastView(root, controller, Clock(4300.0))
    view.tick()
    assert view.title.cget("text") == "Auto-compacted “conPACT”"
    assert view.status.cget("text") == "Done in 1 min 18 s: 657k → 19k tokens."
    assert view.row.winfo_manager() == ""    # nothing left to answer, so nothing left to click
    assert controller.polls == 0
    assert _pump(root, lambda: view.closed)


def test_while_working_it_says_so_and_ignores_more_clicks(root):
    release = threading.Event()

    def slow():
        release.wait(3)
        return {"state": "sent"}
    controller = Controller(ASK, results={"auto": slow})
    view = _view(root, controller)
    view.click("auto")
    assert view.status.cget("text") == "Sending /compact…"
    view.click("compact")
    release.set()
    assert _pump(root, lambda: view.tracking)
    assert controller.acts == ["auto"]


@pytest.mark.parametrize("action", ["compact", "auto"])
@pytest.mark.parametrize("state", [{"state": "sent"}, {"state": "error", "detail": "timed out"}])
def test_close_hides_a_pending_send_without_abandoning_its_result(root, action, state):
    entered, release = threading.Event(), threading.Event()
    finished = []

    def slow():
        entered.set()
        release.wait(3)
        finished.append(state)
        return state

    controller = Controller(ASK, results={action: slow})
    view = _view(root, controller)
    view.click(action)
    try:
        assert entered.wait(1)
        view.close_button.event_generate("<ButtonRelease-1>")
        root.update()
        assert not root.winfo_viewable()
        assert not view.closed  # the event loop retains the outstanding operation
        assert finished == []
        view.click("compact")
        assert controller.acts == [action]
        release.set()
        assert _pump(root, lambda: view.closed)
        assert finished == [state]
        assert not root.winfo_viewable()
        assert controller.acts == [action]
    finally:
        release.set()


def test_a_closed_view_never_reschedules_its_worker_drain(root, monkeypatch):
    view = _view(root, Controller(ASK))
    scheduled = _held_timers(root, monkeypatch)
    view.close()
    scheduled.clear()
    view._drain()
    assert scheduled == []


def test_an_error_keeps_the_toast_open_with_only_close(root):
    controller = Controller(ASK, results={"compact": {"state": "error", "detail": "bridge returned HTTP 401"}})
    view = _view(root, controller)
    view.click("compact")
    assert _pump(root, lambda: view.final)
    assert view.status.cget("text") == "Couldn't compact: bridge returned HTTP 401"
    assert view.status.cget("fg") == tv.PALETTES["dark"]["error"]
    assert not view.closed and not view.busy
    view.close_button.event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.closed)
    assert controller.acts == ["compact"]  # nothing left to decide: close just closes


def test_a_failing_controller_is_shown_not_lost(root):
    def boom():
        raise RuntimeError("boom")
    view = _view(root, Controller(ASK, results={"compact": boom}))
    view.click("compact")
    assert _pump(root, lambda: view.final)
    assert view.status.cget("text") == "Couldn't compact: RuntimeError: boom"


def test_a_worker_that_raises_queues_the_failure_as_a_state():
    """act_into is all that stands between an exception on a worker thread and a
    toast that waits for a result which is never coming."""
    results = queue.Queue()

    class Boom:
        def act(self, action):
            raise RuntimeError("boom")

    assert tv.act_into(Boom(), "compact", results) is None
    assert results.get_nowait() == {"state": "error", "detail": "RuntimeError: boom"}


def test_sending_a_compaction_hides_the_answers_and_goes_looking_for_the_result(root, monkeypatch):
    """The two things a click does before the worker has answered: say what is
    happening in place of the question, and book the look at the queue."""
    view = _view(root, Controller(ASK, results={"compact": {"state": "sent"}}))
    scheduled = _held_timers(root, monkeypatch)
    view.click("compact")
    assert view.status.cget("text") == "Sending /compact…"
    assert view.row.winfo_manager() == ""
    assert scheduled == [(50, view._drain)]


def test_dismiss_closes(root):
    controller = Controller(ASK)
    view = _view(root, controller)
    view.buttons["dismiss"].event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.closed)
    assert controller.acts == ["dismiss"]
    view.click("compact")
    assert controller.acts == ["dismiss"]


def test_turning_auto_off_confirms_then_closes(root, monkeypatch):
    monkeypatch.setattr(tv, "CLOSE_AFTER", {"compacted": 10, "untracked": 10, "auto_off": 10})
    view = _view(root, Controller(NOTICE, results={"turn_off_auto": {"state": "auto_off"}}))
    view.click("turn_off_auto")
    assert _pump(root, lambda: view.status.cget("text") == "Auto-compact is off for this session.")
    assert _pump(root, lambda: view.closed)


def test_tick_counts_down_and_closes_on_any_reason(root):
    controller = Controller(ASK)
    clock = Clock(4300.0)
    view = tv.ToastView(root, controller, clock)
    clock.t = 4450.0
    view.tick()
    assert view.status.cget("text") == "Prompt cache expires in 2:30"
    assert view.body.cget("text") == "657k tokens · idle 57 min"
    assert view.fraction == 0.5
    clock.t = 4700.0
    view.tick()
    assert view.fraction == 0.0
    controller.reason = "expired"
    view.tick()
    assert view.closed
    polls = controller.polls
    view.tick()
    assert controller.polls == polls


def test_tick_caps_the_bar_and_stops_polling_once_busy(root):
    controller = Controller(ASK)
    view = tv.ToastView(root, controller, Clock(0.0))
    view.tick()
    assert view.fraction == 1.0
    view.busy = True
    polls = controller.polls
    view.tick()
    assert controller.polls == polls


def test_a_compaction_reported_as_sent_takes_the_answers_away_and_starts_tracking(root):
    """A click's own result arrives through _drain, which has already hidden the
    row - but show_state is the door the tracking path comes through too, and it
    must never leave a question on screen that has already been answered."""
    view = _view(root, Controller(ASK))
    view.show_state({"state": "sent"})
    assert view.tracking is True
    assert view.row.winfo_manager() == ""
    assert view.title.cget("text") == "Compacting “conPACT”"
    assert view.status.cget("text") == "Compacting… 0:00"


def test_the_countdown_books_its_own_next_tick(root, monkeypatch):
    """Nothing else does. A tick that forgets stops the clock, the bar and the
    polling for good, and the toast sits there showing a time that never moves."""
    view = _view(root, Controller(ASK))
    scheduled = _held_timers(root, monkeypatch)
    view.tick()
    assert scheduled == [(tv.TICK_MS, view.tick)]


def test_a_deadline_with_no_span_behind_it_does_not_divide_by_zero(root):
    """span is how long the countdown runs for; a model without one still has to
    draw a bar rather than raise on the first tick."""
    view = tv.ToastView(root, Controller(dict(ASK, span=0, deadline=4301.0)), Clock(4300.0))
    view.tick()
    assert view.fraction == 1.0


def test_a_sent_compaction_fills_the_bar_and_asks_for_progress_instead_of_polling(root):
    """Once it is tracking there is no deadline left to count down to, so the bar
    goes full and stays there for as long as the compaction runs."""
    controller = Controller(NOTICE, state={"state": "compacting", "elapsed": 3})
    view = _view(root, controller)
    assert view.tracking is True
    view.fraction = 0.0
    view.bar.coords(view.bar_fill, 0, 0, 0, view.px(3))
    view.tick()
    assert (view.fraction, controller.checks, controller.polls) == (1.0, 1, 0)
    width = view.bar.winfo_width()
    assert width > 1 and view.bar.coords(view.bar_fill) == [0.0, 0.0, float(width), float(view.px(3))]


def test_the_card_is_a_borderless_topmost_window_in_the_palettes_colours(root):
    """The chrome the card depends on: no title bar, above other windows, and a
    one-pixel border showing round the edge of the content."""
    window = tk.Toplevel(root)      # a fresh one: the fixture's root is already borderless
    window.withdraw()
    palette = tv.PALETTES["light"]
    view = tv.ToastView(window, Controller(ASK), Clock(4300.0), palette)
    window.update()
    assert bool(window.overrideredirect()) is True
    assert bool(window.attributes("-topmost")) is True
    assert window.cget("bg") == palette["border"]
    card, = window.winfo_children()
    assert card.cget("bg") == palette["bg"]
    stripe, _content = card.winfo_children()
    assert (stripe.cget("bg"), int(stripe.cget("width"))) == (palette["accent"], view.px(4))


def test_the_card_is_laid_out_the_way_it_is(root):
    """Every widget the card is built from, where it sits, and the size it was given.

    Layout is most of what a toast is; a mutation run showed almost none of it was
    checked. A padding, a font size, the accent stripe's width, or an entire
    `.pack()` call could change or vanish and every other test still passed.
    """
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0), tv.PALETTES["dark"],
                        open_settings=lambda: None)
    root.update()
    px = view.px

    card, = root.winfo_children()
    assert _packing(card) == ("top", "both", 1, px(1), px(1))
    stripe, content = card.winfo_children()
    assert _packing(stripe) == ("left", "y", 0, 0, 0)
    assert int(stripe.cget("width")) == px(4)
    assert _packing(content) == ("left", "both", 1, 0, 0)
    assert (int(content.cget("padx")), int(content.cget("pady"))) == (px(16), px(14))

    header, title, body, status, bar, row = content.winfo_children()
    assert _packing(header) == ("top", "x", 0, 0, 0)
    brand, close, mute, settings = header.winfo_children()
    assert brand.cget("text") == "✳  " + toast_text.BRAND
    assert (_font(brand), _packing(brand)[0]) == ((tv.FONT_STRONG, 8), "left")
    for button in (close, mute, settings):
        assert _packing(button)[0] == "right"      # they stack in from the right-hand edge
        # A literal 1, not px(0): px clamps to 1, so pad=(6, 0) and pad=(6, 1) build
        # the same widget and no assertion can tell them apart.
        assert (int(button.cget("padx")), int(button.cget("pady"))) == (px(6), 1)

    wrap = px(tv.WIDTH - 44)                       # the card's width less the stripe and the padding
    for line, gap, size in ((title, 8, 11), (body, 3, 9), (status, 1, 9)):
        assert _packing(line) == ("top", "x", 0, 0, (px(gap), 0))
        assert (_font(line), int(line.cget("wraplength"))) == ((tv.FONT_STRONG if line is title else tv.FONT,
                                                                size), wrap)

    assert _packing(bar) == ("top", "x", 0, 0, (px(10), px(12)))
    assert (int(bar.cget("height")), int(bar.cget("highlightthickness")), int(bar.cget("bd"))) == (px(3), 0, 0)
    assert bar.coords(view.bar_fill) == [0.0, 0.0, 0.0, float(px(3))]   # empty until the first tick
    assert float(bar.itemcget(view.bar_fill, "width")) == 0             # a solid fill, not an outline

    assert _packing(row) == ("top", "x", 0, 0, 0)
    primary, secondary, ghost = row.winfo_children()
    assert [_packing(button)[0] for button in (primary, secondary, ghost)] == ["left", "left", "right"]
    assert _packing(primary)[3] == (0, px(8))      # the gap between the two answer buttons
    for button in (primary, secondary, ghost):     # an answer button is bigger than a header link
        assert (int(button.cget("padx")), int(button.cget("pady"))) == (px(12), px(6))


def test_the_early_toast_puts_the_standing_choices_on_a_line_of_their_own(root):
    """Four choices do not fit one row at 380px wide, so the two "always" ones
    go underneath as links - accent-coloured text, not a button's block."""
    view = tv.ToastView(root, Controller(EARLY), Clock(4300.0), tv.PALETTES["dark"])
    root.update()
    px = view.px

    content = root.winfo_children()[0].winfo_children()[1]
    header, title, body, status, bar, row, links = content.winfo_children()
    assert _packing(links) == ("top", "x", 0, 0, (px(10), 0))

    primary, secondary, ghost = row.winfo_children()
    assert [button.cget("text") for button in (primary, secondary, ghost)] == [
        "Compact now", "Near expiry", "Not now"]
    assert [_packing(button)[0] for button in (primary, secondary, ghost)] == ["left", "left", "right"]

    when_idle, near_expiry = links.winfo_children()
    assert [button.cget("text") for button in (when_idle, near_expiry)] == [
        "Always when idle", "Always near expiry"]
    for button in (when_idle, near_expiry):
        assert _packing(button)[0] == "left"
        assert _packing(button)[3] == (0, px(14))   # the gap between the two links
        # A literal 1 for padx: px clamps 0 to 1, so pad=(0, n) and pad=(1, n)
        # build the same widget, exactly as for the header links above.
        assert (int(button.cget("padx")), int(button.cget("pady"))) == (1, px(2))
        assert _font(button) == (tv.FONT, 9)       # a link's weight, not a button's
        assert button.cget("fg") == tv.PALETTES["dark"]["accent"]


def test_a_toast_with_no_standing_choices_is_built_exactly_as_it_was(root):
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0), tv.PALETTES["dark"])
    root.update()
    assert view.links is None
    content = root.winfo_children()[0].winfo_children()[1]
    assert len(content.winfo_children()) == 6   # header, title, body, status, bar, row


@pytest.mark.parametrize("action, state, text", [
    ("defer", "deferred", "Compacting near expiry instead, unless you use this session first."),
    ("auto_expiry", "auto_expiry_set", "Compacting near expiry from now on."),
])
def test_choosing_to_wait_takes_both_rows_away_and_never_claims_a_send(root, action, state, text):
    controller = Controller(EARLY, results={action: {"state": state}})
    view = _view(root, controller)
    view.click(action)
    assert _pump(root, lambda: view.final)
    assert controller.acts == [action]
    # Not "Sending /compact…": nothing was sent, and the toast must not say it was.
    assert view.status.cget("text") == text
    assert view.status.cget("fg") == tv.PALETTES["dark"]["text"]
    assert not view.row.winfo_ismapped() and not view.links.winfo_ismapped()
    assert _pump(root, lambda: view.closed, timeout=5.0)


@pytest.mark.parametrize("action", ["defer", "auto_expiry"])
def test_choosing_to_wait_takes_the_rows_away_before_the_answer_comes_back(root, monkeypatch, action):
    """The click takes the choices away itself, as it does for a compaction. The
    worker's answer would take them too, but only once it has been drained, and
    until then the rows would sit there offering choices that no longer do
    anything. Nothing is sent, so the status goes on saying what it said."""
    view = _view(root, Controller(EARLY, results={action: {"state": "deferred"}}))
    assert (view.row.winfo_manager(), view.links.winfo_manager()) == ("pack", "pack")
    status = view.status.cget("text")
    scheduled = _held_timers(root, monkeypatch)
    view.click(action)
    assert (view.row.winfo_manager(), view.links.winfo_manager()) == ("", "")
    assert (view.busy, view.final) == (True, False)   # the answer has not been shown
    assert view.status.cget("text") == status
    assert scheduled == [(50, view._drain)]


def test_every_size_is_scaled_to_the_screen_and_none_of_them_vanishes(root):
    """px() is what makes the card the same size on a 4K screen as on a laptop."""
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0), tv.PALETTES["dark"], scale=1.5)
    assert (view.px(16), view.px(10), view.px(4)) == (24, 15, 6)
    assert view.px(0.1) == 1                 # a hairline is still a line
    assert view.px(0) == 1


def test_the_toast_waits_for_a_result_that_is_not_there_yet(root, monkeypatch):
    """The worker thread is still running: look again in 50 ms rather than lose the click."""
    view = _view(root, Controller(ASK))
    scheduled = _held_timers(root, monkeypatch)
    view._drain()
    assert scheduled == [(50, view._drain)]


def test_closing_a_closed_toast_does_nothing_twice(root, monkeypatch):
    view = _view(root, Controller(ASK))
    withdrawn = []
    monkeypatch.setattr(root, "withdraw", lambda: withdrawn.append("withdrawn"))
    scheduled = _held_timers(root, monkeypatch)
    view.close()
    view.close()
    assert withdrawn == ["withdrawn"] and view.closed is True
    assert scheduled == [(0, root.quit)]   # at once, but from inside the loop it is ending


# --- placing and fading in --------------------------------------------------
#
# show() used to be provable only on screen, because it hands the window to the
# desktop. With that call and the work area injected, the arithmetic it exists
# for is read off the geometry it asks for, and no window is ever mapped.

RIGHT, BOTTOM = -3000, -3000


def _off_screen_desktop(monkeypatch):
    monkeypatch.setattr(desktop, "work_area",
                        lambda fallback: (RIGHT - 1920, BOTTOM - 1040, RIGHT, BOTTOM))
    handed = []
    monkeypatch.setattr(desktop, "show_without_focus", handed.append)
    return handed


def _held_timers(root, monkeypatch):
    """Take show()'s `after` calls instead of running them: the test reads what
    was scheduled, and no timer is left to fire against a destroyed window."""
    scheduled = []
    monkeypatch.setattr(root, "after", lambda ms, *args: scheduled.append((ms, *args)))
    return scheduled


def test_show_places_the_card_bottom_right_by_slot(root, monkeypatch):
    _off_screen_desktop(monkeypatch)
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    root.update_idletasks()
    height = root.winfo_reqheight()
    placed = []
    monkeypatch.setattr(root, "geometry", placed.append)
    _held_timers(root, monkeypatch)
    for slot in (0, 1, 2):
        view.show(slot)
    assert placed == [f"380x{height}+{RIGHT - 380 - 16}+{BOTTOM - 16 - height - slot * (height + 10)}"
                      for slot in (0, 1, 2)]


def test_show_starts_the_countdown_from_inside_the_event_loop(root, monkeypatch):
    """Never before it runs: a first poll that closed the toast before mainloop()
    started used to lose its quit and leave a dead window on screen."""
    _off_screen_desktop(monkeypatch)
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    monkeypatch.setattr(root, "geometry", lambda spec: None)
    scheduled = _held_timers(root, monkeypatch)
    view.show(0)
    assert scheduled[-1] == (tv.TICK_MS, view.tick)


def test_show_hands_the_window_to_the_desktop_only_once_it_is_invisible(root, monkeypatch):
    """Alpha 0 first, then the desktop maps it, then the fade: any other order
    and the card appears at full opacity before it has been placed."""
    events = []
    monkeypatch.setattr(desktop, "work_area", lambda fallback: (RIGHT - 1920, BOTTOM - 1040, RIGHT, BOTTOM))
    monkeypatch.setattr(desktop, "show_without_focus", lambda window: events.append(("shown", window is root)))
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    real_attributes = root.attributes

    def attributes(*args):
        if len(args) > 1 and args[0] == "-alpha":
            events.append(("alpha", round(float(args[1]), 4)))
        return real_attributes(*args)

    monkeypatch.setattr(root, "geometry", lambda spec: None)
    monkeypatch.setattr(root, "attributes", attributes)
    _held_timers(root, monkeypatch)
    view.show(0)
    assert events == [("alpha", 0.0), ("shown", True), ("alpha", round(tv.ALPHA / tv.FADE_STEPS, 4))]


def test_the_card_fades_in_step_by_step_to_full_opacity(root, monkeypatch):
    _off_screen_desktop(monkeypatch)
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    view._fade(0)
    assert float(root.attributes("-alpha")) == pytest.approx(tv.ALPHA / tv.FADE_STEPS)
    assert _pump(root, lambda: float(root.attributes("-alpha")) >= tv.ALPHA)
    assert float(root.attributes("-alpha")) == pytest.approx(tv.ALPHA)


def test_the_fade_runs_its_steps_once_each_and_then_lets_go(root, monkeypatch):
    """Each step books the next, so the one that reaches full opacity must book
    nothing: a fade that keeps going wakes the event loop every frame, forever."""
    _off_screen_desktop(monkeypatch)
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    scheduled = _held_timers(root, monkeypatch)
    for step in range(tv.FADE_STEPS):
        view._fade(step)
    assert scheduled == [(16, view._fade, step + 1) for step in range(tv.FADE_STEPS - 1)]
    assert float(root.attributes("-alpha")) == pytest.approx(tv.ALPHA)


def test_with_no_work_area_the_card_sits_in_the_corner_of_the_screen(root, monkeypatch):
    """When Windows will not say where the taskbar is, the whole screen is the
    work area - the card is placed against the screen's own edges instead."""
    monkeypatch.setattr(desktop, "work_area", lambda fallback: fallback)
    monkeypatch.setattr(desktop, "show_without_focus", lambda window: None)
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    root.update_idletasks()
    height = root.winfo_reqheight()
    placed = []
    monkeypatch.setattr(root, "geometry", placed.append)
    _held_timers(root, monkeypatch)
    view.show(0)
    assert placed == [f"380x{height}+{root.winfo_screenwidth() - 380 - 16}"
                      f"+{root.winfo_screenheight() - 16 - height}"]


def test_a_fade_stops_as_soon_as_the_toast_is_closed(root, monkeypatch):
    _off_screen_desktop(monkeypatch)
    view = tv.ToastView(root, Controller(ASK), Clock(4300.0))
    root.attributes("-alpha", 0.0)
    view.closed = True
    view._fade(0)
    assert float(root.attributes("-alpha")) == 0.0


def _run_isolated(tmp_path, code):
    """Run a real toast in its own process with a throwaway home: if it hangs,
    the test fails and the window is killed instead of staying on screen. The
    time limit starts once toast_view is imported, and again once Tk exists
    (see window_process)."""
    return window_process.run(tmp_path, code, start="from conpact import toast_view")


PRESENT_AND_CLOSE_AT_ONCE = """
from conpact import toast_view
class C:
    polls = 0
    def model(self):
        return {"kind": "ask", "name": "x", "context_tokens": 1, "last_call": 0.0, "deadline": 1e12, "span": 1.0}
    def poll(self):
        C.polls += 1
        return "expired"
    def act(self, action):
        return {"state": "closed"}
toast_view.present(C(), clock=lambda: 1.0)
print("returned after", C.polls, "poll")
"""


@pytest.mark.real_ui
def test_a_toast_closed_by_its_first_poll_does_not_stay_on_screen(tmp_path):
    # Regression: the first poll ran before mainloop() started, so its quit was
    # lost and a faint, unclickable window stayed up (seen 2026-09-19).
    proc = _run_isolated(tmp_path, PRESENT_AND_CLOSE_AT_ONCE)
    assert (proc.returncode, proc.stdout) == (0, "returned after 1 poll\n"), proc.stderr
    assert not (tmp_path / ".conpact" / "idle" / "toasts" / "slot-0").exists()


CLICK_ON_SCREEN = """
import time
from conpact import toast_view
shown = toast_view.ToastView.show
def show(self, slot):
    C.opened = time.time()   # the close clock times the window, not Tk's start-up
    shown(self, slot)
toast_view.ToastView.show = show
faded = toast_view.ToastView._fade
def fade(self, step):
    faded(self, step)
    if step == toast_view.FADE_STEPS - 1:   # the click follows the fade, however long load made it
        self.root.after(900, click, self)
toast_view.ToastView._fade = fade
def click(self):
    print("alpha", round(float(self.root.attributes("-alpha")), 2))
    button = self.buttons["compact"]
    button.event_generate("<ButtonPress-1>", x=5, y=5)
    button.event_generate("<ButtonRelease-1>", x=5, y=5)
class C:
    acts = []
    opened = None
    def model(self):
        return {"kind": "ask", "name": "x", "context_tokens": 1, "last_call": 0.0, "deadline": 1e12, "span": 1.0}
    def poll(self):
        return "timeout" if time.time() > C.opened + 10 else None
    def act(self, action):
        C.acts.append(action)
        return {"state": "closed"}
toast_view.present(C())
print("acted", C.acts)
"""


@pytest.mark.real_ui
def test_a_shown_toast_fades_in_fully_and_its_buttons_respond(tmp_path):
    # Regression: the user saw a faint toast whose buttons did nothing (2026-09-19).
    # Its clocks time the toast: under load, Tk's start-up took 16 s and the
    # fade 1.7 s, so a close clock started before Tk, or a click at a fixed time
    # after show(), failed a toast that worked (CU-20260924-066).
    proc = _run_isolated(tmp_path, CLICK_ON_SCREEN)
    assert (proc.returncode, proc.stdout) == (0, "alpha 0.98\nacted ['compact']\n"), proc.stderr


FOLLOW_ON_SCREEN = """
import time
from conpact import toast_view
toast_view.CLOSE_AFTER["compacted"] = 200
seen = []
say = toast_view.ToastView._say
def spy(self, text, color):
    seen.append(text)
    say(self, text, color)
toast_view.ToastView._say = spy
shown = toast_view.ToastView.show
def show(self, slot):
    shown(self, slot)
    self.root.after(600, lambda: self.click("compact"))
toast_view.ToastView.show = show
class C:
    sent = None
    def model(self):
        return {"kind": "ask", "name": "x", "context_tokens": 500_000, "last_call": 0.0, "deadline": 1e12,
                "span": 1.0}
    def poll(self):
        return None
    def act(self, action):
        C.sent = time.time()
        return {"state": "sent"}
    def progress(self):
        elapsed = time.time() - C.sent
        if elapsed < 1.5:
            return {"state": "compacting", "elapsed": elapsed}
        return {"state": "compacted", "pre_tokens": 500_000, "post_tokens": 20_000, "seconds": 1.5}
toast_view.present(C())
print(seen[0], "|", any(text.startswith("Compacting… 0:0") for text in seen), "|", seen[-1])
"""


@pytest.mark.real_ui
def test_a_real_toast_stays_up_while_compacting_then_shows_the_result(tmp_path):
    # Regression: the toast said "Compaction started" and closed after 3 s, so
    # nothing showed that a 100-second compaction was running (2026-09-19).
    proc = _run_isolated(tmp_path, FOLLOW_ON_SCREEN)
    assert (proc.returncode, proc.stdout) == (
        0, "Sending /compact… | True | Done in 1 s: 500k → 20k tokens.\n"), proc.stderr


@pytest.mark.real_ui
def test_the_demo_shows_and_closes_by_itself(tmp_path):
    proc = _run_isolated(tmp_path, "from conpact import toast_view; "
                                   "toast_view.main(['--demo', 'failed', '--seconds', '0.5'])")
    assert (proc.returncode, proc.stdout) == (0, "closed; clicked: nothing\n"), proc.stderr


# --- present(): the whole window, with none on screen ------------------------
#
# The three tests above run a real toast in its own process, which is what they
# are for - but coverage is not collected in a subprocess, so a mutation run
# sees every line of present() as untested. These call it here, faking only the
# two desktop calls that would put a window on screen.

class ClosingController:
    """Closes itself at the first poll, so mainloop() ends as soon as it starts."""

    def __init__(self, clock=None):
        self.polls = 0
        if clock is not None:
            self.clock = clock

    def model(self):
        return {"kind": "ask", "name": "x", "context_tokens": 1, "last_call": 0.0,
                "deadline": 1e12, "span": 1.0}

    def poll(self):
        self.polls += 1
        return "expired"

    def act(self, action):
        return {"state": "closed"}


@pytest.fixture
def unmapped(monkeypatch):
    """present() builds its own root; only the calls that would show it are faked."""
    monkeypatch.setattr(desktop, "work_area", lambda fallback: (RIGHT - 1920, BOTTOM - 1040, RIGHT, BOTTOM))
    monkeypatch.setattr(desktop, "show_without_focus", lambda window: None)
    monkeypatch.setattr(tv, "TICK_MS", 10)  # the first poll closes it; no need to wait half a second

    class Watched(tk.Tk):
        """A root that gives up after five seconds. What ends present()'s loop is the
        ticking that show() starts, so a mutant that drops the call to show() leaves
        the loop with nothing scheduled to end it, and the test hangs instead of
        failing. A hang is not a detection (D-20260920-025)."""

        def __init__(self):
            super().__init__()
            self.after(5000, self.quit)

    monkeypatch.setattr(tk, "Tk", Watched)


def _spy_on_the_view(monkeypatch):
    """What present() dressed the toast with, and the root it built."""
    built = {}
    real = tv.ToastView

    def spy(window, controller, clock, palette, scale, **kwargs):
        built.update(root=window, clock=clock, palette=palette, scale=scale,
                     state_when_built=window.state(), dpi=window.winfo_fpixels("1i"), **kwargs)
        return real(window, controller, clock, palette, scale, **kwargs)

    monkeypatch.setattr(tv, "ToastView", spy)
    return built


@pytest.mark.real_present
def test_present_returns_once_the_toast_has_closed_itself(unmapped):
    controller = ClosingController()
    assert tv.present(controller, clock=lambda: 1.0) is None
    assert controller.polls == 1


@pytest.mark.real_present
def test_present_takes_a_screen_slot_and_always_gives_it_back(unmapped, monkeypatch):
    seen = []
    claim, release = idle_state.claim_slot, idle_state.release_slot
    monkeypatch.setattr(idle_state, "claim_slot",
                        lambda pid, alive: seen.append(("claim", pid)) or claim(pid, alive))
    monkeypatch.setattr(idle_state, "release_slot",
                        lambda slot: seen.append(("release", slot)) or release(slot))
    tv.present(ClosingController())
    assert seen == [("claim", os.getpid()), ("release", 0)]
    assert not idle_state.slot_path(0).exists()


@pytest.mark.real_present
def test_a_toast_with_no_slot_left_is_still_shown_at_the_bottom(unmapped, monkeypatch):
    monkeypatch.setattr(idle_state, "claim_slot", lambda pid, alive: None)
    slots = []
    show = tv.ToastView.show
    monkeypatch.setattr(tv.ToastView, "show", lambda self, slot: slots.append(slot) or show(self, slot))
    tv.present(ClosingController())
    assert slots == [0]


@pytest.mark.real_present
def test_present_dresses_the_toast_from_the_desktop_and_the_settings(unmapped, monkeypatch):
    from conpact import settings, settings_window
    monkeypatch.setattr(desktop, "theme", lambda: "light")
    built = _spy_on_the_view(monkeypatch)
    tv.present(ClosingController())
    assert built["palette"] is tv.PALETTES["light"]
    # The screen's own dpi against the 96 Windows calls 100%: every size on the
    # card is multiplied by this, so a card built at the wrong scale is unusable.
    assert built["scale"] == pytest.approx(built["dpi"] / 96)
    assert built["close_after"]["compacted"] == settings.load()["result_seconds"] * 1000
    assert built["open_settings"] is settings_window.launch


@pytest.mark.real_present
def test_present_asks_for_dpi_awareness_and_builds_the_window_hidden(unmapped, monkeypatch):
    """Crisp text, and nothing on screen until show() has placed the card:
    a window built visible appears in the corner of the screen first."""
    asked = []
    monkeypatch.setattr(desktop, "dpi_aware", lambda: asked.append("dpi"))
    built = _spy_on_the_view(monkeypatch)
    tv.present(ClosingController())
    assert asked == ["dpi"]
    assert built["state_when_built"] == "withdrawn"


@pytest.mark.real_present
def test_the_window_present_built_is_destroyed_on_the_way_out(unmapped, monkeypatch):
    built = _spy_on_the_view(monkeypatch)
    tv.present(ClosingController())
    with pytest.raises(tk.TclError):
        built["root"].winfo_exists()


@pytest.mark.real_present
def test_every_window_is_made_with_activation_refused_and_the_keyboard_handed_back_at_once(
        unmapped, monkeypatch):
    """Tk activates the first window a thread makes, which took the keyboard
    for as long as a watcher's first toast was up. So the refusal is in force
    before Tk makes anything, the keyboard goes back as soon as Tk has made the
    toast's window - before it is placed or shown, so that nothing the user
    types in between is lost - and the refusal lasts until the window is gone."""
    events = []

    class Recorded:
        def __enter__(self):
            events.append("refusing")
            return self

        def hand_back(self):
            events.append("handed back")

        def __exit__(self, *exc):
            events.append("no longer refusing")
            return False

    monkeypatch.setattr(desktop, "NoActivation", Recorded)
    made = tk.Tk

    class Made(made):
        def __init__(self):
            events.append("Tk")
            super().__init__()

        def update_idletasks(self):
            if "made the window" not in events:
                events.append("made the window")
            super().update_idletasks()

        def destroy(self):
            events.append("destroyed")
            super().destroy()

    monkeypatch.setattr(tk, "Tk", Made)
    show = tv.ToastView.show
    monkeypatch.setattr(tv.ToastView, "show", lambda self, slot: events.append("shown") or show(self, slot))
    tv.present(ClosingController())
    assert events == ["refusing", "Tk", "made the window", "handed back", "shown", "destroyed",
                      "no longer refusing"]


@pytest.mark.real_present
def test_the_clock_is_the_callers_then_the_controllers_then_the_wall(unmapped, monkeypatch):
    given, own = Clock(1.0), Clock(2.0)
    built = _spy_on_the_view(monkeypatch)
    tv.present(ClosingController(clock=own), clock=given)
    assert built["clock"] is given
    tv.present(ClosingController(clock=own))
    assert built["clock"] is own
    tv.present(ClosingController())
    assert built["clock"] is time.time


# --- the demo, without a window ----------------------------------------------

def test_main_shows_a_demo_and_says_what_was_clicked(monkeypatch, capsys):
    shown = []
    monkeypatch.setattr(tv, "present", lambda controller, clock=None: shown.append(controller))
    assert tv.main(["--demo", "remote", "--seconds", "12"]) == 0
    [controller] = shown
    assert (controller.kind, controller.seconds) == ("remote", 12.0)
    assert capsys.readouterr().out == "closed; clicked: nothing\n"


def test_main_lists_every_button_the_user_pressed(monkeypatch, capsys):
    def present(controller, clock=None):
        controller.act("dismiss")
        controller.act("always_on")
    monkeypatch.setattr(tv, "present", present)
    assert tv.main(["--demo", "ask"]) == 0
    assert capsys.readouterr().out == "closed; clicked: dismiss, always_on\n"


def test_a_demo_runs_for_half_a_minute_unless_told_otherwise(monkeypatch):
    shown = []
    monkeypatch.setattr(tv, "present", lambda controller, clock=None: shown.append(controller))
    tv.main(["--demo", "notice"])
    assert shown[0].seconds == 30.0


def test_the_demo_must_name_which_toast_to_show(monkeypatch):
    shown = []
    monkeypatch.setattr(tv, "present", lambda controller, clock=None: shown.append(controller.kind))
    for argv in ([], ["--demo", "nonesuch"]):
        with pytest.raises(SystemExit) as raised:
            tv.main(argv)
        assert raised.value.code == 2
    for kind in ("ask", "early", "notice", "failed", "remote"):
        tv.main(["--demo", kind])          # every sample it offers is one it can show
    assert shown == ["ask", "early", "notice", "failed", "remote"]


@pytest.mark.real_present
def test_the_module_run_as_a_command_is_what_shows_the_demo(unmapped, monkeypatch, capsys):
    """`python -m conpact.toast_view --demo ...` is the only way in, so the guard
    at the bottom of the module is the whole of what that command does. Break it and
    the documented demo becomes a process that prints nothing and exits 0.

    runpy gives the module a fresh namespace, so the fakes have to be ones it picks
    up itself: `desktop` and `tkinter` come out of sys.modules already patched, and
    a Tk that declines to map itself keeps the card off the screen.
    """
    import runpy
    import warnings

    class Unmapped(tk.Tk):
        def __init__(self):
            super().__init__()
            self.after(0, self.quit)         # end the loop the moment it starts

        def deiconify(self):
            pass                             # never mapped, so it never appears in the corner

    monkeypatch.setattr(desktop, "dpi_aware", lambda: None)
    monkeypatch.setattr(tk, "Tk", Unmapped)
    monkeypatch.setattr("sys.argv", ["conpact.toast_view", "--demo", "notice", "--seconds", "0"])
    with warnings.catch_warnings(), pytest.raises(SystemExit) as stopped:
        warnings.filterwarnings("ignore", "'conpact.toast_view' found in sys.modules", RuntimeWarning)
        runpy.run_module("conpact.toast_view", run_name="__main__")
    assert stopped.value.code == 0
    assert capsys.readouterr().out == "closed; clicked: nothing\n"


def test_the_demo_models_are_the_ones_a_real_session_would_have_produced():
    """--demo is the only way to see a toast without waiting for an idle session,
    so what it shows has to be a whole model with realistic numbers in it."""
    now = 100.0
    ask = tv.DemoController("ask", 5, Clock(now)).model()
    assert ask == {"kind": "ask", "name": "conPACT", "context_tokens": 656_725,
                   "last_call": now - 3300, "deadline": now + 300, "span": 300,
                   "expires_at": now + 300, "mute_seconds": 86_400}
    assert tv.DemoController("remote", 5, Clock(now)).model() == dict(ask, kind="remote",
                                                                     offer_always_on=True)
    # The early stage is the ask toast at its first stage, the only one that
    # offers to wait for expiry instead.
    early = tv.DemoController("early", 5, Clock(now)).model()
    assert early == dict(ask, stage="early")
    assert [action for action, _, _ in toast_text.actions(early)] == [
        "compact", "defer", "dismiss", "auto", "auto_expiry"]
    notice = {"kind": "notice", "variant": "compacted", "compacting": True, "detail": None,
              "name": "conPACT", "context_tokens": 656_725, "last_call": now - 3300,
              "deadline": now + 20, "span": 20}
    assert tv.DemoController("notice", 20, Clock(now)).model() == notice
    assert tv.DemoController("failed", 20, Clock(now)).model() == dict(
        notice, variant="failed", compacting=False, detail="bridge returned HTTP 401")


def test_the_demo_compaction_takes_a_moment_like_a_real_one(monkeypatch):
    """Without the pause the demo jumps straight to "Compacting…" and nobody
    ever sees the "Sending /compact…" the real toast shows first."""
    slept = []
    monkeypatch.setattr(tv.time, "sleep", slept.append)
    tv.DemoController("ask", 5, Clock(100.0)).act("compact")
    assert slept == [0.6]


def test_the_demo_controller_sends_nothing():
    clock = Clock(100.0)
    demo = tv.DemoController("ask", 5, clock)
    assert demo.model()["kind"] == "ask" and demo.model()["deadline"] == 400.0
    assert demo.poll() is None
    clock.t = 105.0
    assert demo.poll() == "timeout"
    assert demo.act("dismiss") == {"state": "closed"}
    assert demo.act("mute") == {"state": "closed"}      # a sample silences nothing either
    assert tv.DemoController("failed", 5, clock).model()["detail"] == "bridge returned HTTP 401"
    assert tv.DemoController("failed", 5, clock).model()["compacting"] is False
    notice = tv.DemoController("notice", 5, clock)
    assert (notice.model()["variant"], notice.model()["compacting"]) == ("compacted", True)
    assert notice.progress() == {"state": "compacting", "elapsed": 0.0}
    clock.t += tv.DEMO_COMPACT_SECONDS
    assert notice.progress() == {"state": "compacted", "pre_tokens": 656_725, "post_tokens": 19_111,
                                 "seconds": 78.0}


def test_the_demo_remote_toast_shows_the_same_words_and_opens_nothing():
    demo = tv.DemoController("remote", 5, Clock(100.0))
    assert demo.model()["kind"] == "remote"
    assert toast_text.title(demo.model()).startswith("Remote Control is off")
    assert demo.model()["offer_always_on"] is True
    assert demo.act("open_session") == {"state": "closed"}   # a sample never opens anything
    assert demo.act("always_on") == {"state": "startup_on"}  # and changes no setting
    assert demo.actions == ["open_session", "always_on"]


@pytest.mark.parametrize("kind, action, answer", [
    ("early", "defer", {"state": "deferred"}),
    ("early", "auto_expiry", {"state": "auto_expiry_set"}),
    ("remote", "always_on", {"state": "startup_on"}),
])
def test_the_demo_answers_a_choice_that_sends_nothing_at_once(monkeypatch, kind, action, answer):
    """Waiting for expiry and turning Remote Control on for new sessions send no
    compaction, so the demo answers them at once, with no pause standing in for
    a bridge call, in the state the toast shows for each, and starts no
    compaction for the toast to follow."""
    slept = []
    monkeypatch.setattr(tv.time, "sleep", slept.append)
    clock = Clock(100.0)
    demo = tv.DemoController(kind, 5, clock)
    clock.t = 110.0
    assert demo.act(action) == answer
    assert (slept, demo.actions, demo.sent_at) == ([], [action], 100.0)


def test_the_demo_compaction_starts_when_clicked(monkeypatch):
    monkeypatch.setattr(tv.time, "sleep", lambda s: None)
    clock = Clock(100.0)
    demo = tv.DemoController("ask", 5, clock)
    clock.t = 110.0
    assert demo.act("compact") == {"state": "sent"}
    clock.t = 111.0
    assert demo.progress() == {"state": "compacting", "elapsed": 1.0}
    assert demo.act("turn_off_auto") == {"state": "auto_off"}
    assert demo.actions == ["compact", "turn_off_auto"]


# --- silencing a session ----------------------------------------------------

def test_the_silence_link_says_how_long_and_closes_the_toast(root):
    controller = Controller({**ASK, "mute_seconds": 86_400}, results={"mute": {"state": "closed"}})
    view = _view(root, controller)
    assert view.mute_button.cget("text") == "Silence 24 h"
    view.mute_button.event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.closed)
    assert controller.acts == ["mute"]


def test_the_silence_link_falls_back_to_a_plain_label(root):
    view = _view(root, Controller(ASK))
    assert view.mute_button.cget("text") == "Silence"


def test_a_notice_has_no_silence_link(root):
    view = _view(root, Controller(NOTICE))
    assert view.mute_button is None


REMOTE = {"kind": "remote", "name": "Lighthouse", "context_tokens": 200_000, "last_call": 1000.0,
          "deadline": 4600.0, "span": 300.0, "expires_at": 4600.0, "mute_seconds": 86_400, "stage": "expiry"}


def test_the_remote_control_toast_offers_the_setting_and_confirms_it(root):
    model = {**REMOTE, "offer_always_on": True}
    controller = Controller(model, results={"always_on": {"state": "startup_on"}})
    view = tv.ToastView(root, controller, Clock(4300.0), tv.PALETTES["dark"],
                        close_after={**tv.CLOSE_AFTER, "startup_on": 10})
    root.update()
    assert set(view.buttons) == {"open_session", "always_on", "dismiss"}
    assert view.buttons["always_on"].cget("text") == "Always on for new sessions"
    view.buttons["always_on"].event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.status.cget("text").startswith("Remote Control will start"))
    assert _pump(root, lambda: view.closed)          # the confirmation closes itself
    assert controller.acts == ["always_on"]


def test_a_setting_that_could_not_be_changed_stays_on_screen(root):
    controller = Controller({**REMOTE, "offer_always_on": True},
                            results={"always_on": {"state": "startup_failed", "detail": "read-only"}})
    view = _view(root, controller)
    view.buttons["always_on"].event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.status.cget("text") == "Couldn't change the setting: read-only")
    assert not view.closed


def test_the_remote_control_toast_can_be_silenced_and_opens_the_session(root):
    controller = Controller(REMOTE, results={"open_session": {"state": "closed"}})
    view = _view(root, controller)
    assert view.mute_button.cget("text") == "Silence 24 h"
    assert set(view.buttons) == {"open_session", "dismiss"}
    assert view.title.cget("text") == "Remote Control is off for “Lighthouse”"
    view.buttons["open_session"].event_generate("<ButtonRelease-1>")
    assert _pump(root, lambda: view.closed)
    assert controller.acts == ["open_session"]


def test_an_early_toast_names_the_stage_on_its_auto_button(root):
    view = _view(root, Controller({**ASK, "stage": "early", "expires_at": 7600.0}))
    assert view.buttons["auto"].cget("text") == "Always when idle"
    assert view.buttons["auto_expiry"].cget("text") == "Always near expiry"
    assert view.status.cget("text") == "Prompt cache expires in 55 min"  # not a ticking 55:00
