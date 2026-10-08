"""Tests for conpact.toast_text: the toast's wording and number formats."""
import pytest

from conpact import toast_text as tt

ASK = {"kind": "ask", "name": "conPACT", "context_tokens": 656_725, "last_call": 1000.0,
       "deadline": 4600.0, "span": 300.0}
NOTICE = {"kind": "notice", "variant": "compacted", "compacting": True, "detail": None, "name": "conPACT",
          "context_tokens": 656_725, "last_call": 1000.0, "deadline": 4320.0, "span": 20}


@pytest.mark.parametrize("count, text", [
    (0, "0"), (950, "950"), (999, "999"), (1000, "1k"), (1499, "1k"), (1500, "2k"), (99_500, "100k"),
    (656_725, "657k"), (999_499, "999k"), (999_500, "1M"), (1_250_000, "1.2M"), (1_260_000, "1.3M"),
    (2_000_000, "2M"),
])
def test_tokens(count, text):
    assert tt.tokens(count) == text


@pytest.mark.parametrize("seconds, text", [
    (-5, "0 s"), (0, "0 s"), (45.9, "45 s"), (59, "59 s"), (60, "1 min"), (3300, "55 min"),
    (3599, "59 min"), (3600, "1 h"), (3900, "1 h 5 min"), (7260, "2 h 1 min"),
])
def test_duration(seconds, text):
    assert tt.duration(seconds) == text


@pytest.mark.parametrize("seconds, text", [
    (-3, "0:00"), (0, "0:00"), (0.2, "0:01"), (59, "0:59"), (60, "1:00"), (299.2, "5:00"), (3600, "60:00"),
])
def test_countdown(seconds, text):
    assert tt.countdown(seconds) == text


@pytest.mark.parametrize("seconds, text", [
    (-1, "0 s"), (0, "0 s"), (42.9, "42 s"), (59.99, "59 s"), (60, "1 min"), (101.8, "1 min 41 s"),
    (102, "1 min 42 s"), (600, "10 min"), (3725, "62 min 5 s"),
])
def test_elapsed(seconds, text):
    assert tt.elapsed(seconds) == text


@pytest.mark.parametrize("name, text", [
    ("conPACT", "conPACT"), ("  two\n words ", "two words"), (None, "this session"),
    ("   ", "this session"), (7, "this session"),
    ("x" * 40, "x" * 40), ("abcdefghij" * 5, "abcdefghij" * 3 + "abcdefghi" + "…"),
])
def test_session_name(name, text):
    assert tt.session_name(name) == text


def test_titles():
    assert tt.title(ASK) == "Compact “conPACT”?"
    assert tt.title({**ASK, "name": None}) == "Compact this session?"
    assert tt.title(ASK, "compacting") == "Compacting “conPACT”"
    assert tt.title({**ASK, "name": None}, "compacting") == "Compacting this session"
    assert tt.title(ASK, "compacted") == "Compacted “conPACT”"
    assert tt.title(NOTICE) == "Auto-compacting “conPACT”"
    assert tt.title(NOTICE, "compacting") == "Auto-compacting “conPACT”"
    assert tt.title(NOTICE, "compacted") == "Auto-compacted “conPACT”"
    assert tt.title({**NOTICE, "variant": "failed"}) == "Couldn't auto-compact “conPACT”"


def test_body_and_status():
    assert tt.body(ASK, 4300.0) == "657k tokens · idle 55 min"
    assert tt.status(ASK, 4300.0) == "Prompt cache expires in 5:00"
    assert tt.status(NOTICE, 4300.0) == "Compacting…"
    assert tt.status({**NOTICE, "variant": "failed", "detail": "bridge returned HTTP 401"}, 0) == (
        "Couldn't compact: bridge returned HTTP 401")


@pytest.mark.parametrize("state, text", [
    ({"state": "working"}, "Sending /compact…"),
    ({"state": "compacting", "elapsed": 0}, "Compacting… 0:00"),
    ({"state": "compacting", "elapsed": 65.9}, "Compacting… 1:05"),
    ({"state": "compacted", "pre_tokens": 459_517, "post_tokens": 23_498, "seconds": 101.8},
     "Done in 1 min 41 s: 460k → 23k tokens."),
    ({"state": "compacted", "pre_tokens": 459_517, "post_tokens": None, "seconds": 30.0}, "Done in 30 s."),
    ({"state": "compacted", "pre_tokens": None, "post_tokens": 0, "seconds": 30.0}, "Done in 30 s."),
    ({"state": "unconfirmed", "seconds": 600.0}, "No result after 10 min. Check the session."),
    ({"state": "untracked"}, "Compaction started. It can take a minute or two."),
    ({"state": "auto_off"}, "Auto-compact is off for this session."),
    ({"state": "deferred"}, "Compacting near expiry instead, unless you use this session first."),
    ({"state": "auto_expiry_set"}, "Compacting near expiry from now on."),
    ({"state": "error", "detail": "offline"}, "Couldn't compact: offline"),
])
def test_state_messages(state, text):
    assert tt.state_message(state) == text


def test_actions():
    assert tt.actions(ASK) == (("compact", "Compact now", "primary"),
                               ("auto", "Always compact", "secondary"),
                               ("dismiss", "Not now", "ghost"))
    assert tt.actions({**ASK, "stage": "expiry"})[1] == ("auto", "Always near expiry", "secondary")
    assert tt.actions(NOTICE) == (("turn_off_auto", "Turn off auto-compact", "secondary"),
                                  ("dismiss", "OK", "ghost"))
    assert tt.BRAND == "conPACT"


def test_only_the_early_toast_offers_to_wait_for_the_stage_before_expiry():
    """It is the only stage with a later one to hand the work to."""
    assert tt.actions({**ASK, "stage": "early"}) == (("compact", "Compact now", "primary"),
                                                     ("defer", "Near expiry", "secondary"),
                                                     ("dismiss", "Not now", "ghost"),
                                                     ("auto", "Always when idle", "link"),
                                                     ("auto_expiry", "Always near expiry", "link"))
    for model in (ASK, {**ASK, "stage": "expiry"}, NOTICE):
        offered = [action for action, _, _ in tt.actions(model)]
        assert "defer" not in offered and "auto_expiry" not in offered


def test_the_standing_choices_are_links_and_the_decisions_are_buttons():
    """The row holds three; a fourth would run past the card's edge, so the two
    "always" choices go on their own line underneath."""
    styles = {action: style for action, _, style in tt.actions({**ASK, "stage": "early"})}
    assert styles == {"compact": "primary", "defer": "secondary", "dismiss": "ghost",
                      "auto": "link", "auto_expiry": "link"}


def test_a_notice_for_a_one_off_deferral_offers_no_switch_to_turn_off():
    assert tt.actions({**NOTICE, "offer_auto_off": False}) == (("dismiss", "OK", "ghost"),)
    assert tt.actions({**NOTICE, "offer_auto_off": True}) == tt.actions(NOTICE)


@pytest.mark.parametrize("seconds, label", [
    (86_400, "Silence 24 h"), (900, "Silence 15 min"), (60, "Silence 1 min"), (None, "Silence"),
    ("lots", "Silence"),
])
def test_the_silence_link_says_how_long(seconds, label):
    assert tt.mute_label(seconds) == label


def test_an_early_toast_shows_how_long_the_cache_has_left_without_ticking():
    early = {**ASK, "stage": "early", "deadline": 1120.0, "expires_at": 4600.0}
    assert tt.status(early, 1060.0) == "Prompt cache expires in 59 min"
    assert tt.status({**ASK, "stage": "expiry"}, 4300.0) == "Prompt cache expires in 5:00"


def test_the_settings_link_and_its_failure():
    assert tt.SETTINGS_LINK == "Settings"
    assert tt.settings_failed(OSError("pythonw.exe not found")) == "Couldn't open the settings: pythonw.exe not found"


# --- the Remote Control toast ------------------------------------------------

REMOTE = {"kind": "remote", "name": "Lighthouse", "context_tokens": 200_000, "last_call": 1000.0,
          "deadline": 4600.0, "span": 300.0, "expires_at": 4600.0, "mute_seconds": 86_400, "stage": "expiry"}


def test_the_remote_toast_names_the_session_and_says_what_is_wrong():
    assert tt.title(REMOTE) == "Remote Control is off for “Lighthouse”"
    assert tt.body(REMOTE, 1300.0) == "200k tokens · idle 5 min"
    assert tt.status(REMOTE, 1300.0) == ("Nothing can be sent to it, so it cannot be compacted. "
                                         "The switch is in its toolbar.")


def test_the_remote_toast_offers_to_open_the_session_and_nothing_that_sends():
    assert tt.actions(REMOTE) == (("open_session", "Open the session", "primary"),
                                  ("dismiss", "Not now", "ghost"))
    assert not any(action in ("compact", "auto") for action, _, _ in tt.actions(REMOTE))


def test_the_always_on_offer_appears_only_when_the_setting_is_not_already_set():
    offered = {**REMOTE, "offer_always_on": True}
    assert tt.actions(offered) == (("open_session", "Open the session", "primary"),
                                   ("always_on", "Always on for new sessions", "secondary"),
                                   ("dismiss", "Not now", "ghost"))
    assert tt.status(offered, 1300.0) == ("Nothing can be sent to it. Open it for the switch, or turn "
                                          "Remote Control on for every new session.")


def test_the_setting_confirms_itself_and_says_when_it_could_not_be_changed():
    assert tt.state_message({"state": "startup_on"}) == "Remote Control will start with every new session."
    assert tt.state_message({"state": "startup_failed", "detail": "read-only"}) ==         "Couldn't change the setting: read-only"
    assert tt.state_message({"state": "remote_failed", "detail": "no handler"}) ==         "Couldn't open the session: no handler"
    assert tt.state_message({"state": "error", "detail": "HTTP 401"}) == "Couldn't compact: HTTP 401"


def test_the_remote_toast_keeps_its_wording_whatever_stage_it_is_at():
    """The auto-compact labels belong to the compact toast only."""
    assert tt.actions({**REMOTE, "stage": "early"}) == tt.actions(REMOTE)
    assert tt.title({**REMOTE, "stage": "early"}) == tt.title(REMOTE)
