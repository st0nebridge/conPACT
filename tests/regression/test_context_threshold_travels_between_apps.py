"""Regression: "big enough to be worth compacting" must mean the same thing in
both apps.

The idle notifier's minimum was an absolute token count, which is only
meaningful against a window. ChatGPT Desktop's window is 258,400 tokens, so a
minimum of 300,000 - an unremarkable size for a Claude session, which can hold
far more - silenced ChatGPT Desktop completely, including a session sitting at
94% full. A fraction is what the setting always meant.

Claude Code reports no window anywhere, so the absolute count is still the rule
there. That is the answer for an app that does not say, not a fallback that will
quietly stop being used.
"""
import pytest

from conpact import idle_arming, settings as st

CODEX_WINDOW = 258_400


def _settings(**over):
    return {**st.defaults(), **over}


def test_a_nearly_full_codex_session_is_never_silenced_by_a_claude_sized_minimum():
    """The exact failure: 94% full, and an absolute minimum refused it."""
    nearly_full = int(CODEX_WINDOW * 0.94)
    settings = _settings(min_context_tokens=300_000)

    assert idle_arming.too_small(nearly_full, CODEX_WINDOW, settings) is None
    assert idle_arming.too_small(nearly_full, None, settings) is not None, \
        "without a window there is nothing to take a fraction of"


@pytest.mark.parametrize("fill, wanted, refused", [
    (0.94, 50, False),
    (0.51, 50, False),
    (0.50, 50, False),
    (0.49, 50, True),
    (0.10, 50, True),
    (0.60, 75, True),
    (0.80, 75, False),
])
def test_the_fraction_is_measured_against_the_window(fill, wanted, refused):
    tokens = int(CODEX_WINDOW * fill)
    why = idle_arming.too_small(tokens, CODEX_WINDOW, _settings(min_context_fill=wanted))
    assert (why is not None) is refused, why


def test_the_refusal_says_the_fill_the_window_and_the_minimum():
    why = idle_arming.too_small(25_840, CODEX_WINDOW, _settings(min_context_fill=50))
    assert why is not None
    assert "10%" in why and "258,400" in why and "50%" in why


def test_an_app_with_no_window_still_uses_the_absolute_count():
    settings = _settings(min_context_tokens=100_000)
    assert idle_arming.too_small(99_999, None, settings) is not None
    assert idle_arming.too_small(100_000, None, settings) is None


@pytest.mark.parametrize("window", [0, None])
def test_a_missing_window_is_not_read_as_a_window_of_zero(window):
    """A zero would divide, or read as "0% full" and refuse everything."""
    assert idle_arming.too_small(500_000, window, _settings()) is None
