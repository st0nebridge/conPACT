"""
@module tests.regression.test_toast_buttons_fit_the_card
@description The toast's button row was wider than the card it sits in, so Tk
             clipped whichever button was packed last - "Not now" was shown 37px
             wide of the 74px it asked for on the stage before the cache expires,
             and 19px short on a toast with no stage. Nothing measured the row, so
             every other test passed while half a button was cut off the card the
             user actually saw. Found by measuring while adding the early toast's
             fourth choice, which is why that one puts its standing choices on a
             second line instead (CU-20260920-028).
@input      conpact.toast_view, built on a real Tk root at the card's real width
@output     assertions that no button is narrower than it asked to be
@dependencies conpact.toast_view, tests.window_guard; stdlib: tkinter
"""
import pytest

tk = pytest.importorskip("tkinter")

from conpact import toast_view as tv  # noqa: E402
import window_guard  # noqa: E402

ASK = {"kind": "ask", "name": "conPACT", "context_tokens": 656_725, "last_call": 1000.0,
       "deadline": 4600.0, "span": 300.0}
STAGES = [None, "expiry", "early"]


class _Controller:
    def __init__(self, model):
        self._model = model

    def model(self):
        return self._model

    def poll(self):
        return None

    def act(self, action):
        return {"state": "closed"}

    def progress(self):
        return {"state": "untracked"}


@pytest.fixture
def root():
    yield from window_guard.root(tk, prepare=lambda window: window.overrideredirect(True))


@pytest.mark.parametrize("stage", STAGES)
def test_no_button_is_clipped_off_the_card(root, stage):
    model = {**ASK, **({"stage": stage, "expires_at": 6000.0} if stage else {})}
    view = tv.ToastView(root, _Controller(model), lambda: 4300.0, tv.PALETTES["dark"])
    # Exactly what show() does: the card's width is forced, never negotiated.
    root.geometry(f"{view.px(tv.WIDTH)}x{root.winfo_reqheight()}+-4000+-4000")
    root.update()
    rows = [view.row] if view.links is None else [view.row, view.links]
    clipped = [(button.cget("text"), button.winfo_reqwidth() - button.winfo_width())
               for row in rows for button in row.winfo_children()
               if button.winfo_width() < button.winfo_reqwidth()]
    assert clipped == [], f"clipped on stage {stage}: {clipped}"


@pytest.mark.parametrize("stage", STAGES)
def test_each_row_asks_for_no_more_than_the_card_can_give_it(root, stage):
    """The measurement behind the layout, so a longer label fails here and not on screen."""
    model = {**ASK, **({"stage": stage, "expires_at": 6000.0} if stage else {})}
    view = tv.ToastView(root, _Controller(model), lambda: 4300.0, tv.PALETTES["dark"])
    root.update()
    # The card less its 1px border, the accent stripe and the content padding.
    inner = view.px(tv.WIDTH) - 2 - view.px(4) - 2 * view.px(16)
    rows = [view.row] if view.links is None else [view.row, view.links]
    too_wide = [(row.winfo_reqwidth(), inner) for row in rows if row.winfo_reqwidth() > inner]
    assert too_wide == [], f"a row wants more than the card has on stage {stage}: {too_wide}"


def test_the_question_about_claude_codes_idle_compaction_fits_the_card(root):
    """Two long labels share its row; the third choice is a link underneath (CU-20261014-118)."""
    model = {"kind": "claude_idle", "deadline": None, "span": None}
    view = tv.ToastView(root, _Controller(model), lambda: 4300.0, tv.PALETTES["dark"])
    # As show() does: its longer text has to be wrapped before the height is read,
    # or the window is cut short and the buttons get no room at all.
    root.update_idletasks()
    root.geometry(f"{view.px(tv.WIDTH)}x{root.winfo_reqheight()}+-4000+-4000")
    root.update()
    clipped = [(button.cget("text"), button.winfo_reqwidth() - button.winfo_width())
               for row in (view.row, view.links) for button in row.winfo_children()
               if button.winfo_width() < button.winfo_reqwidth()]
    assert clipped == []
