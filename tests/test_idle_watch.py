"""Tests for conpact.idle_watch: the detached watcher, its toast controllers and main."""
import json
import os
import sys
import time

import pytest

from conpact import (compact_progress, compaction, idle_state, idle_watch as iw, mod_handoff, session_registry,
                        toast_text, token_store)

ARMED = 1_800_000_000.0
FIRE = ARMED + 150
EXPIRES = ARMED + 450
FINISHED = "2027-01-15T08:06:40.000Z"  # ARMED + 400: after any send these tests make
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "timestamp": FINISHED,
            "compactMetadata": {"trigger": "manual", "preTokens": 656_725, "postTokens": 19_111, "durationMs": 78_000}}
DONE = {"state": "compacted", "pre_tokens": 656_725, "post_tokens": 19_111, "seconds": 78.0,
        "trigger": "manual", "at": FINISHED}


class Clock:
    def __init__(self, t=ARMED):
        self.t = t
        self.slept = []
        self.on_sleep = None

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds
        if self.on_sleep:
            self.on_sleep(self.t)


def _record(status="idle", changed=ARMED + 0.5, **fields):
    record = {"pid": 4242, "sessionId": "s1", "bridgeSessionId": "session_x", "name": "conPACT",
              "status": status, "statusUpdatedAt": None if changed is None else int(changed * 1000), **fields}
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / "4242.json").write_text(json.dumps(record), encoding="utf-8")
    return record


def _arm(**fields):
    marker = {"session_id": "s1", "armed_at": ARMED, "last_call": ARMED - 2, "ttl": 3600,
              "context_tokens": 656_725, "fire_at": FIRE, "expires_at": EXPIRES, "name": "conPACT",
              "pid": 4242, **fields}
    generation = idle_state.write_marker("s1", marker)
    return generation, idle_state.read_marker("s1")


def _transcript(tmp_path, *entries):
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in [{"type": "user"}, *entries]), encoding="utf-8")
    return path


def _finish(path, entry=BOUNDARY):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


_BREACHES = []  # the watcher swallows what a fake raises, so record it too and fail at teardown


@pytest.fixture(autouse=True)
def _nothing_unexpected_happened():
    _BREACHES.clear()
    yield
    assert _BREACHES == []


def _never_send(record, **kw):
    _BREACHES.append("sent")
    raise AssertionError("must not send")


def _never_present(controller):
    _BREACHES.append("presented")
    raise AssertionError("must not show a toast")


def _sender(calls, status=200):
    def send(record, **kw):
        calls.append((record, kw))
        return {"sent": True, "http_status": status, "token_refreshed": False}
    return send


def _never_open(url):
    _BREACHES.append("opened")
    raise AssertionError("must not open anything")


def _deps(clock, compactor=_never_send, present=_never_present, opener=_never_open):
    return iw.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None,
                   compactor=compactor, present=present, opener=opener)


def test_constants():
    assert (iw.POLL_SECONDS, iw.SETTLE_SECONDS, iw.NOTICE_SECONDS) == (5, 120, 20)


def test_default_deps(monkeypatch):
    from conpact import toast_view
    deps = iw.default_deps()
    from conpact import desktop
    assert (deps.clock, deps.sleep, deps.environ, deps.sessions_dir, deps.compactor, deps.present,
            deps.opener) == (time.time, time.sleep, os.environ, None, compaction.compact_record,
                             toast_view.present, desktop.open_url)


# --- activity -------------------------------------------------------------

MARKER = {"armed_at": ARMED}


@pytest.mark.parametrize("record, now, strict, reason", [
    ({"status": "idle", "statusUpdatedAt": int((ARMED + 1) * 1000)}, ARMED + 500, False, None),
    ({"status": "idle", "statusUpdatedAt": int((ARMED + 120) * 1000)}, ARMED + 500, False, None),
    ({"status": "idle", "statusUpdatedAt": int((ARMED + 121) * 1000)}, ARMED + 500, False, "resumed"),
    ({"status": "busy", "statusUpdatedAt": int(ARMED * 1000)}, ARMED + 119, False, None),
    ({"status": "busy", "statusUpdatedAt": int(ARMED * 1000)}, ARMED + 120, False, "resumed"),
    ({"status": "busy", "statusUpdatedAt": int(ARMED * 1000)}, ARMED + 5, True, "resumed"),
    ({"statusUpdatedAt": int(ARMED * 1000)}, ARMED + 500, False, "resumed"),
    ({"status": "idle", "statusUpdatedAt": True}, ARMED + 500, False, None),
    ({"status": "idle", "statusUpdatedAt": "later"}, ARMED + 500, False, None),
])
def test_activity(record, now, strict, reason):
    assert iw.activity(record, MARKER, now, strict=strict) == reason


def test_interruption_reasons():
    clock = Clock(ARMED + 500)
    deps = _deps(clock)
    generation, marker = _arm()
    assert iw.interruption("s1", generation, marker, deps) == "closed"
    _record()
    assert iw.interruption("s1", generation, marker, deps) is None
    _record(status="busy", changed=ARMED + 400)
    assert iw.interruption("s1", generation, marker, deps) == "resumed"
    _arm()
    assert iw.interruption("s1", generation, marker, deps) == "superseded"
    idle_state.watch_path("s1").unlink()
    assert iw.interruption("s1", generation, marker, deps) == "cancelled"


def test_find_record_matches_the_session_id_only():
    _record()
    assert iw.find_record("s1", None)["pid"] == 4242
    assert iw.find_record("s2", None) is None


# --- waiting --------------------------------------------------------------

def test_wait_for_sleeps_in_polls_until_the_deadline():
    clock = Clock(100)
    checks = []
    assert iw.wait_for(112, lambda: checks.append(clock()) and None, _deps(clock)) is None
    assert clock.slept == [5, 5, 2]
    assert checks == [105, 110, 112]


def test_wait_for_returns_at_once_when_the_deadline_has_passed():
    clock = Clock(100)
    assert iw.wait_for(100, lambda: "never", _deps(clock)) is None
    assert clock.slept == []


def test_wait_for_stops_at_the_first_interruption():
    clock = Clock(100)
    assert iw.wait_for(200, lambda: "resumed" if clock() >= 110 else None, _deps(clock)) == "resumed"
    assert clock.slept == [5, 5]


# --- watch ----------------------------------------------------------------

def test_watch_stands_down_for_a_newer_generation():
    clock = Clock()
    _arm()
    assert iw.watch("s1", "old", _deps(clock)) == {"event": "superseded"}
    assert clock.slept == []


def test_watch_stands_down_when_its_watch_was_cancelled_before_it_started():
    clock = Clock()
    assert iw.watch("s1", "any", _deps(clock)) == {"event": "cancelled"}
    assert clock.slept == []


def test_watch_stands_down_when_the_session_is_used_again():
    _record()
    generation, _ = _arm()
    clock = Clock()
    clock.on_sleep = lambda t: _record(status="busy", changed=t) if t >= ARMED + 130 else None
    outcome = iw.watch("s1", generation, _deps(clock))
    assert outcome == {"event": "resumed", "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}
    assert idle_state.read_marker("s1") is None


def test_watch_leaves_a_newer_marker_alone():
    _record()
    generation, _ = _arm()
    clock = Clock()
    clock.on_sleep = lambda t: _arm() if t >= ARMED + 30 and idle_state.read_marker("s1")["generation"] == generation else None
    assert iw.watch("s1", generation, _deps(clock))["event"] == "superseded"
    assert idle_state.read_marker("s1")["generation"] != generation


def test_watch_shows_the_toast_at_the_notify_time():
    _record()
    generation, _ = _arm()
    clock = Clock()
    shown = []

    def present(controller):  # the watcher swallows what present() raises: assert outside it
        shown.append((clock(), controller, controller.poll(), controller.act("dismiss")))
    outcome = iw.watch("s1", generation, _deps(clock, present=present))
    [(when, controller, polled, state)] = shown
    assert when == FIRE
    assert isinstance(controller, iw.AskPrompt)
    assert polled is None and state == {"state": "closed"}
    assert outcome == {"event": "dismissed", "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}
    assert idle_state.read_marker("s1") is None


def test_watch_asks_for_remote_control_when_the_session_is_not_bound_at_the_notify_time():
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")
    shown = []
    outcome = iw.watch("s1", generation, _deps(Clock(), present=shown.append))
    [prompt] = shown
    assert isinstance(prompt, iw.RemotePrompt) and prompt.model()["kind"] == "remote"
    assert outcome == {"event": "closed", "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}


def test_remote_control_switched_off_between_the_check_and_the_send_is_reported(monkeypatch):
    """A race, not a path the watcher takes: bound() said yes, the send found no bridge."""
    _record(bridgeSessionId=None)
    generation, _ = _arm()
    monkeypatch.setattr(iw, "bound", lambda session_id, deps: True)
    outcome = iw.watch("s1", generation, _deps(Clock()))
    assert outcome["event"] == "error"
    assert "no bridgeSessionId" in outcome["reason"]


def test_the_remote_toast_opens_that_session_in_the_app_and_sends_nothing():
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")
    opened = []
    outcome = iw.watch("s1", generation, _deps(Clock(), present=lambda c: c.act("open_session"), opener=opened.append))
    assert opened == ["claude://claude.ai/epitaxy/local_a"]
    assert outcome["event"] == "remote_opened" and outcome["link"] == opened[0]


def test_the_remote_toast_says_so_when_the_app_has_no_link_for_the_session():
    _record(bridgeSessionId=None)
    generation, _ = _arm()                      # a marker with no host_session_id
    states = []
    iw.watch("s1", generation, _deps(Clock(), present=lambda c: states.append(c.act("open_session"))))
    assert states == [{"state": "remote_failed", "detail": "the app has no link for this session"}]
    assert toast_text.state_message(states[0]) == "Couldn't open the session: the app has no link for this session"


def test_the_remote_toast_reports_a_link_that_will_not_open():
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")

    def refuse(url):
        raise OSError("no handler for claude://")
    outcome = iw.watch("s1", generation, _deps(Clock(), present=lambda c: c.act("open_session"), opener=refuse))
    assert outcome["event"] == "remote_open_failed" and "no handler" in outcome["reason"]


def test_the_remote_toast_offers_to_turn_it_on_for_every_new_session():
    from conpact import remote_startup
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")
    shown, states = [], []
    outcome = iw.watch("s1", generation, _deps(Clock(), present=lambda c: (
        shown.append(c.model()["offer_always_on"]), states.append(c.act("always_on")))))
    assert shown == [True]
    assert states == [{"state": "startup_on"}]
    assert remote_startup.is_on() is True
    assert outcome["event"] == "remote_startup_on" and outcome["changed"] is True


def test_the_offer_is_not_made_when_the_setting_is_already_on():
    from conpact import remote_startup
    remote_startup.turn_on()
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")
    shown = []
    iw.watch("s1", generation, _deps(Clock(), present=lambda c: shown.append(c.model())))
    assert shown[0]["offer_always_on"] is False
    assert not any(action == "always_on" for action, _, _ in toast_text.actions(shown[0]))


def test_a_setting_that_cannot_be_written_is_reported_on_the_toast(monkeypatch):
    from conpact import remote_startup
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")

    def refuse():
        raise OSError("read-only file system")
    monkeypatch.setattr(remote_startup, "turn_on", refuse)
    states = []
    outcome = iw.watch("s1", generation, _deps(Clock(), present=lambda c: states.append(c.act("always_on"))))
    assert states == [{"state": "startup_failed", "detail": "read-only file system"}]
    assert outcome["event"] == "remote_startup_failed"
    assert toast_text.state_message(states[0]) == "Couldn't change the setting: read-only file system"


def _remote_prompt(clock=None, host="local_a", **deps_kw):
    _record(bridgeSessionId=None)
    generation, marker = _arm(host_session_id=host)
    return iw.RemotePrompt("s1", generation, marker, EXPIRY_STAGE, _deps(clock or Clock(FIRE), **deps_kw))


def test_every_answer_the_remote_toast_can_give_is_pinned():
    """Each (state, outcome) pair, so a changed word in either is a failing test."""
    opened = []
    prompt = _remote_prompt(opener=opened.append)
    assert prompt.act("open_session") == {"state": "closed"}
    assert prompt.outcome == {"event": "remote_opened", "link": "claude://claude.ai/epitaxy/local_a"}
    assert opened == ["claude://claude.ai/epitaxy/local_a"]

    def refuse(url):
        raise OSError("no handler")
    prompt = _remote_prompt(opener=refuse)
    assert prompt.act("open_session") == {"state": "remote_failed", "detail": "no handler"}
    assert prompt.outcome == {"event": "remote_open_failed", "reason": "OSError: no handler"}

    prompt = _remote_prompt(host=None)
    assert prompt.act("open_session") == {"state": "remote_failed",
                                          "detail": "the app has no link for this session"}
    assert prompt.outcome == {"event": "remote_no_link"}

    prompt = _remote_prompt()
    assert prompt.act("dismiss") == {"state": "closed"}       # straight through to AskPrompt
    assert prompt.outcome == {"event": "dismissed"}


def test_the_remote_toast_answers_once_and_then_only_closes():
    opened = []
    prompt = _remote_prompt(opener=opened.append)
    assert prompt.act("open_session") == {"state": "closed"}
    assert prompt.act("open_session") == {"state": "closed"}  # already answered
    assert prompt.act("always_on") == {"state": "closed"}
    assert opened == ["claude://claude.ai/epitaxy/local_a"]   # opened once
    assert prompt.outcome["event"] == "remote_opened"


def test_the_remote_toast_can_be_silenced_like_any_other():
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")
    outcome = iw.watch("s1", generation, _deps(Clock(), present=lambda c: c.act("mute")))
    assert outcome["event"] == "muted"
    assert idle_state.read_mute("s1") is not None


@pytest.mark.parametrize("action", ["compact", "auto", "turn_off_auto", "launch"])
def test_the_remote_toast_never_sends_whatever_it_is_asked(action):
    _record(bridgeSessionId=None)
    generation, _ = _arm(host_session_id="local_a")
    states = []
    outcome = iw.watch("s1", generation, _deps(Clock(), present=lambda c: states.append(c.act(action))))
    assert states == [{"state": "closed"}]          # and _never_send was not called
    assert outcome["event"] == "closed" and idle_state.auto_mode("s1") is None


def test_watch_does_not_ask_a_session_that_is_busy_when_the_toast_is_due():
    # With a short idle delay the notify time falls inside the settle window,
    # where the wait tolerates "busy"; the check before asking does not.
    _record(status="busy")
    generation, _ = _arm(fire_at=ARMED + 10)
    outcome = iw.watch("s1", generation, _deps(Clock()))
    assert outcome == {"event": "resumed", "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}


def test_watch_reports_a_toast_that_fails():
    _record()
    generation, _ = _arm()

    def present(controller):
        raise RuntimeError("no display")
    outcome = iw.watch("s1", generation, _deps(Clock(), present=present))
    assert outcome == {"event": "error", "reason": "toast failed: RuntimeError: no display",
                       "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}


@pytest.mark.parametrize("make_it, reason", [
    (lambda clock: setattr(clock, "t", EXPIRES), "expired"),
    (lambda clock: _record(status="busy", changed=FIRE + 30), "resumed"),  # e.g. a background task woke it
])
def test_a_toast_closed_by_its_poll_logs_why(make_it, reason):
    _record()
    generation, _ = _arm()
    clock = Clock()
    polls = []

    def present(prompt):  # the watcher swallows what present() raises: assert outside it
        polls.append(prompt.poll())
        make_it(clock)
        polls.extend([prompt.poll(), prompt.poll()])
    outcome = iw.watch("s1", generation, _deps(clock, present=present))
    assert polls == [None, reason, reason]  # and it keeps saying so once it has
    assert outcome == {"event": reason, "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}


def test_a_toast_closed_without_a_choice_is_reported_as_closed():
    _record()
    generation, _ = _arm()
    assert iw.watch("s1", generation, _deps(Clock(), present=lambda c: None))["event"] == "closed"


# --- the ask prompt -------------------------------------------------------

EXPIRY_STAGE = {"kind": "expiry", "at": FIRE, "until": EXPIRES}
EARLY_STAGE = {"kind": "early", "at": ARMED + 30, "until": ARMED + 90}


def _prompt(clock, compactor=_never_send, stage=None):
    generation, marker = _arm()
    return iw.AskPrompt("s1", generation, marker, stage or EXPIRY_STAGE, _deps(clock, compactor=compactor))


def test_ask_model():
    _record()
    prompt = _prompt(Clock(FIRE))
    assert prompt.model() == {"kind": "ask", "stage": "expiry", "name": "conPACT", "context_tokens": 656_725,
                              "last_call": ARMED - 2, "deadline": EXPIRES, "span": EXPIRES - FIRE,
                              "expires_at": EXPIRES, "mute_seconds": 86_400,
                              # A Claude marker names no platform, so the toast
                              # calls it a session and its TTL is read, not modelled.
                              "platform": None, "ttl_is_modelled": None}
    early = _prompt(Clock(ARMED + 30), stage=EARLY_STAGE)
    assert early.model() == {**prompt.model(), "stage": "early", "deadline": ARMED + 90, "span": 60}


def test_ask_poll_closes_at_the_cache_expiry_or_on_activity():
    _record()
    clock = Clock(FIRE)
    prompt = _prompt(clock)
    assert prompt.poll() is None
    clock.t = EXPIRES
    assert prompt.poll() == "expired"
    clock.t = FIRE
    _record(status="busy", changed=FIRE)
    assert prompt.poll() == "resumed"


def test_compact_now_sends_plain_compact_to_the_bound_session():
    _record()
    calls = []
    prompt = _prompt(Clock(FIRE), compactor=_sender(calls))
    assert prompt.act("compact") == {"state": "sent"}
    [(record, kw)] = calls
    assert (record["sessionId"], record["bridgeSessionId"], kw) == ("s1", "session_x", {})
    assert prompt.outcome == {"event": "compacted", "http_status": 200, "token_refreshed": False, "sent_at": FIRE}
    assert idle_state.auto_mode("s1") is None


def test_auto_compact_switches_on_for_this_session_only_and_compacts_now():
    _record()
    calls = []
    prompt = _prompt(Clock(FIRE), compactor=_sender(calls))
    assert prompt.act("auto") == {"state": "sent"}
    assert (idle_state.auto_mode("s1"), idle_state.auto_mode("s2")) == ("expiry", None)
    assert len(calls) == 1
    assert prompt.outcome["event"] == "compacted_auto_on"


def test_the_auto_button_remembers_the_stage_it_was_pressed_at():
    _record()
    prompt = _prompt(Clock(ARMED + 30), compactor=_sender([]), stage=EARLY_STAGE)
    assert prompt.act("auto") == {"state": "sent"}
    assert idle_state.auto_mode("s1") == "early"


def test_auto_from_a_stage_that_does_not_name_itself_is_remembered_as_before_expiry():
    _record()
    prompt = _prompt(Clock(FIRE), compactor=_sender([]), stage={"at": FIRE, "until": EXPIRES})
    assert prompt.act("auto") == {"state": "sent"}
    assert idle_state.auto_mode("s1") == "expiry"


def test_nothing_is_sent_to_a_session_that_is_busy_when_clicked():
    _record(status="busy", changed=FIRE)
    prompt = _prompt(Clock(FIRE))
    assert prompt.act("compact") == {"state": "closed"}
    assert prompt.outcome == {"event": "resumed"}


def test_nothing_is_sent_when_the_watch_was_superseded():
    _record()
    prompt = _prompt(Clock(FIRE))
    _arm()
    assert prompt.act("auto") == {"state": "closed"}
    assert prompt.outcome == {"event": "superseded"}
    assert idle_state.auto_mode("s1") is None


def test_a_refused_send_is_reported():
    _record()
    prompt = _prompt(Clock(FIRE), compactor=_sender([], status=401))
    assert prompt.act("compact") == {"state": "error", "detail": "bridge returned HTTP 401"}
    assert prompt.outcome == {"event": "failed", "http_status": 401, "token_refreshed": False, "sent_at": FIRE}
    assert (prompt.sent, prompt.progress()) == (False, {"state": "untracked"})


@pytest.mark.parametrize("exc", [token_store.TokenError("no login"), OSError("offline"),
                                 session_registry.TargetError("gone")])
def test_a_send_that_cannot_happen_is_reported(exc):
    _record()

    def fail(record, **kw):
        raise exc
    prompt = _prompt(Clock(FIRE), compactor=fail)
    assert prompt.act("compact") == {"state": "error", "detail": str(exc)}
    assert prompt.outcome == {"event": "error", "reason": f"{type(exc).__name__}: {exc}"}


def test_nothing_more_is_sent_after_a_send():
    _record()
    calls = []
    prompt = _prompt(Clock(FIRE), compactor=_sender(calls))
    prompt.act("compact")
    assert prompt.act("compact") == {"state": "closed"}
    assert prompt.act("dismiss") == {"state": "closed"}
    assert len(calls) == 1
    assert prompt.outcome["event"] == "compacted"


def test_an_unknown_action_sends_nothing():
    _record()
    prompt = _prompt(Clock(FIRE))
    assert prompt.act("launch") == {"state": "closed"}
    assert prompt.outcome is None


# --- following a sent compaction -------------------------------------------

def test_compact_now_follows_the_compaction_until_the_transcript_shows_it_done(tmp_path):
    _record()
    path = _transcript(tmp_path, BOUNDARY)  # an earlier compaction must not count
    generation, marker = _arm(transcript_path=str(path))
    clock = Clock(FIRE)
    prompt = iw.AskPrompt("s1", generation, marker, EXPIRY_STAGE, _deps(clock, compactor=_sender([])))
    assert prompt.progress() == {"state": "untracked"}  # nothing sent yet
    assert prompt.act("compact") == {"state": "sent"}
    assert prompt.sent is True
    clock.t = FIRE + 30
    assert prompt.progress() == {"state": "compacting", "elapsed": 30}
    _finish(path)
    assert prompt.progress() == DONE


def test_the_tracker_starts_at_the_transcript_size_before_the_send(tmp_path):
    _record()
    path = _transcript(tmp_path)
    generation, marker = _arm(transcript_path=str(path))

    def send_and_finish_at_once(record, **kw):
        _finish(path)
        return {"sent": True, "http_status": 200, "token_refreshed": False}
    prompt = iw.AskPrompt("s1", generation, marker, EXPIRY_STAGE, _deps(Clock(FIRE), compactor=send_and_finish_at_once))
    prompt.act("compact")
    assert prompt.progress() == DONE
    assert prompt.tracker.started == FIRE


def test_the_log_gets_the_result_even_when_the_toast_was_closed_first(tmp_path):
    _record()
    path = _transcript(tmp_path)
    generation, _ = _arm(transcript_path=str(path))
    clock = Clock()

    clicked = []

    def click_and_close(prompt):  # the watcher swallows what this raises: assert outside it
        clicked.append(prompt.act("compact"))
        clock.on_sleep = lambda t: _finish(path) if t >= FIRE + 60 else None
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender([]), present=click_and_close))
    assert clicked == [{"state": "sent"}]
    assert outcome == {"event": "compacted", "http_status": 200, "token_refreshed": False, "sent_at": FIRE,
                       "result": DONE, "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}
    assert clock() == FIRE + 60
    assert idle_state.read_marker("s1") is None


def test_the_log_says_so_when_no_result_appears_in_time(tmp_path):
    _record()
    generation, _ = _arm(transcript_path=str(_transcript(tmp_path)))
    clock = Clock()
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender([]), present=lambda p: p.act("auto")))
    assert outcome["event"] == "compacted_auto_on"
    assert outcome["result"] == {"state": "unconfirmed", "seconds": float(compact_progress.TRACK_SECONDS)}


def test_a_compaction_without_a_transcript_is_untracked():
    _record()
    generation, _ = _arm()
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender([]), present=lambda p: p.act("compact")))
    assert outcome["result"] == {"state": "untracked"}


def test_nothing_is_followed_when_nothing_was_sent(tmp_path):
    _record()
    generation, _ = _arm(transcript_path=str(_transcript(tmp_path)))
    clock = Clock()
    outcome = iw.watch("s1", generation, _deps(clock, present=lambda p: p.act("dismiss")))
    assert "result" not in outcome
    assert clock() == FIRE


def test_a_failing_toast_after_a_send_still_logs_the_result(tmp_path):
    _record()
    path = _transcript(tmp_path)
    generation, _ = _arm(transcript_path=str(path))

    def send_then_fail(prompt):
        prompt.act("compact")
        _finish(path)
        raise RuntimeError("display lost")
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender([]), present=send_then_fail))
    assert (outcome["event"], outcome["result"]) == ("compacted", DONE)


def test_the_auto_notice_follows_the_compaction_too(tmp_path):
    _record()
    idle_state.set_auto("s1", "expiry")
    path = _transcript(tmp_path)
    generation, _ = _arm(transcript_path=str(path))
    seen = []

    def present(notice):
        seen.append(notice.progress()["state"])
        _finish(path)
        seen.append(notice.progress()["state"])
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender([]), present=present))
    assert seen == ["compacting", "compacted"]
    assert (outcome["event"], outcome["result"]) == ("auto_compacted", DONE)


# --- auto mode and its notice ----------------------------------------------

def test_auto_mode_compacts_without_asking_and_shows_a_notice():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm()
    calls, shown = [], []
    clock = Clock()
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender(calls), present=shown.append))
    assert len(calls) == 1 and calls[0][0]["sessionId"] == "s1"
    [notice] = shown
    assert isinstance(notice, iw.Notice)
    assert notice.model() == {"kind": "notice", "stage": "expiry", "variant": "compacted", "compacting": True,
                              "detail": None, "name": "conPACT", "context_tokens": 656_725,
                              "last_call": ARMED - 2, "deadline": FIRE + 20, "span": 20,
                              "offer_auto_off": True}
    assert outcome == {"event": "auto_compacted", "http_status": 200, "token_refreshed": False, "sent_at": FIRE,
                       "result": {"state": "untracked"}, "stage": "expiry", "context_tokens": 656_725,
                       "ttl": 3600}


def test_the_notice_can_turn_auto_off_for_its_session():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm()

    states = []

    def present(notice):  # the watcher swallows what present() raises: assert outside it
        states.append(notice.act("turn_off_auto"))
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender([]), present=present))
    assert states == [{"state": "auto_off"}]
    assert idle_state.auto_mode("s1") is None
    assert outcome["event"] == "auto_compacted" and outcome["auto_off"] is True


def test_auto_mode_says_nothing_when_the_session_woke_just_before_the_send(monkeypatch):
    """The send binds the session strictly. One that woke after the last poll is
    left alone - and with nothing sent there is nothing to show a notice about."""
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm()

    def wake_then_fire(deadline, check, deps):
        _record(status="busy", changed=ARMED + 300)  # a new turn started since the last poll
        return None
    monkeypatch.setattr(iw, "wait_for", wake_then_fire)
    outcome = iw.watch("s1", generation, _deps(Clock(FIRE)))  # must neither send nor show
    assert outcome == {"event": "resumed", "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}


def test_the_notice_closes_after_its_display_time():
    notice = iw.Notice({"name": "n", "context_tokens": 1, "last_call": 0, "session_id": "s1"},
                       Clock(1000), "compacted")
    assert notice.progress() == {"state": "untracked"}
    assert notice.poll() is None
    notice.clock.t = 1019.9
    assert notice.poll() is None
    notice.clock.t = 1020
    assert notice.poll() == "timeout"
    assert notice.act("dismiss") == {"state": "closed"}
    assert notice.act("launch") == {"state": "closed"}


def test_auto_mode_reports_a_refused_send_in_the_notice():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm()
    shown = []
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender([], status=503), present=shown.append))
    assert shown[0].model()["variant"] == "failed"
    assert shown[0].model()["compacting"] is False
    assert shown[0].model()["detail"] == "bridge returned HTTP 503"
    assert outcome["event"] == "failed" and outcome["http_status"] == 503
    assert "result" not in outcome


def test_auto_mode_reports_a_send_that_cannot_happen():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm()

    def fail(record, **kw):
        raise token_store.TokenError("no login")
    shown = []
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=fail, present=shown.append))
    assert shown[0].model()["detail"] == "no login"
    assert outcome["event"] == "error" and outcome["reason"] == "TokenError: no login"


def test_auto_mode_never_sends_to_a_busy_session():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm(fire_at=ARMED + 10)
    clock = Clock()
    clock.on_sleep = lambda t: _record(status="busy", changed=ARMED + 0.5) if t >= ARMED + 10 else None
    outcome = iw.watch("s1", generation, _deps(clock))
    assert outcome["event"] == "resumed"


def test_a_notice_that_fails_to_show_does_not_hide_the_send():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _arm()

    def present(notice):
        raise RuntimeError("no display")
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender([]), present=present))
    assert outcome["event"] == "auto_compacted"
    assert outcome["notice_error"] == "RuntimeError: no display"


# --- main -----------------------------------------------------------------

def _log():
    path = idle_state.log_path()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.mark.parametrize("argv", [[], ["s1"], ["../x", "g"], ["s1", "g", "extra"]])
def test_main_rejects_bad_arguments(argv, monkeypatch):
    monkeypatch.setattr(iw, "watch", lambda *a: pytest.fail("must not watch"))
    assert iw.main(argv) == 2
    assert _log() == []


def test_main_logs_the_outcome(monkeypatch):
    seen = []
    monkeypatch.setattr(iw, "watch", lambda sid, gen, deps: seen.append((sid, gen, deps)) or {"event": "expired"})
    assert iw.main(["s1", "gen1"]) == 0
    [(sid, gen, deps)] = seen
    assert (sid, gen, deps.compactor) == ("s1", "gen1", compaction.compact_record)
    [entry] = _log()
    assert {k: v for k, v in entry.items() if k != "ts"} == {"session_id": "s1", "event": "expired"}


def test_main_reads_the_arguments_the_watcher_was_started_with(monkeypatch):
    seen = []
    monkeypatch.setattr(iw, "watch", lambda sid, gen, deps: seen.append((sid, gen)) or {"event": "expired"})
    monkeypatch.setattr(sys, "argv", ["idle_watch.py", "s1", "gen1"])
    assert iw.main() == 0
    assert seen == [("s1", "gen1")]


def test_main_never_raises(monkeypatch):
    def boom(*a):
        raise RuntimeError("bad")
    monkeypatch.setattr(iw, "watch", boom)
    assert iw.main(["s1", "gen1"]) == 0
    assert _log()[0]["event"] == "error" and _log()[0]["reason"] == "RuntimeError: bad"


def test_the_module_run_as_a_command_is_what_starts_the_watcher(monkeypatch):
    """`idle_arming` arms a session by spawning `python -m conpact.idle_watch`,
    so the guard at the bottom of the module is the whole of that process. Break it
    and every armed session gets a watcher that exits 0 having watched nothing.

    Run with no arguments, so main() refuses at the door and nothing is watched:
    what is under test is that the guard calls main at all, and exits on its code.
    """
    import runpy
    import warnings
    # No patch stands in for watch(): runpy builds a fresh namespace that would not
    # see one. Nothing is watched because main() refuses the arguments, and the
    # empty log below is what proves it got no further.
    monkeypatch.setattr(sys, "argv", ["conpact.idle_watch"])
    with warnings.catch_warnings(), pytest.raises(SystemExit) as stopped:
        warnings.filterwarnings("ignore", "'conpact.idle_watch' found in sys.modules", RuntimeWarning)
        runpy.run_module("conpact.idle_watch", run_name="__main__")
    assert stopped.value.code == 2            # the refusal, carried out of the process
    assert _log() == []


# --- two stages -------------------------------------------------------------

def _two_stage(**fields):
    return _arm(stages=[EARLY_STAGE, EXPIRY_STAGE], fire_at=EARLY_STAGE["at"], **fields)


def _answer(clock, answers):
    """present() that answers each toast in turn; "timeout" lets the toast run out."""
    seen = []

    def present(controller):
        stage = controller.model().get("stage")
        seen.append(stage)
        action = answers.pop(0)
        if action == "timeout":
            clock.t = controller.model()["deadline"]
            controller.poll()
        else:
            controller.act(action)
    return present, seen


def test_stage_list_falls_back_for_a_marker_without_stages():
    _, marker = _arm()
    assert iw.stage_list(marker) == [{"kind": "expiry", "at": FIRE, "until": EXPIRES}]
    _, marker = _arm(stages=[{"kind": "early", "at": 1, "until": "soon"}])
    assert iw.stage_list(marker) == [{"kind": "expiry", "at": FIRE, "until": EXPIRES}]
    _, marker = _two_stage()
    assert iw.stage_list(marker) == [EARLY_STAGE, EXPIRY_STAGE]


def test_dismissing_the_early_toast_still_leaves_the_one_before_the_cache_expires():
    _record()
    generation, _ = _two_stage()
    clock = Clock()
    present, seen = _answer(clock, ["dismiss", "dismiss"])
    outcome = iw.watch("s1", generation, _deps(clock, present=present))
    assert seen == ["early", "expiry"]
    assert outcome == {"event": "dismissed", "stage": "expiry",
                       "earlier": [{"stage": "early", "event": "dismissed"}],
                       "context_tokens": 656_725, "ttl": 3600}


def test_an_early_toast_left_alone_times_out_and_the_later_one_comes():
    _record()
    generation, _ = _two_stage()
    clock = Clock()
    present, seen = _answer(clock, ["timeout", "dismiss"])
    outcome = iw.watch("s1", generation, _deps(clock, present=present))
    assert seen == ["early", "expiry"]
    assert outcome["earlier"] == [{"stage": "early", "event": "timeout"}]


def test_compacting_from_the_early_toast_ends_the_watch():
    _record()
    generation, _ = _two_stage()
    clock, calls = Clock(), []
    present, seen = _answer(clock, ["compact"])
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender(calls), present=present))
    assert seen == ["early"] and len(calls) == 1
    assert outcome["event"] == "compacted" and outcome["stage"] == "early"
    assert "earlier" not in outcome


def _answer_kinds(clock, answers):
    """present() that answers each toast in turn and records what kind it was,
    so an ask and the notice an automatic compaction shows are told apart."""
    seen = []

    def present(controller):
        model = controller.model()
        seen.append((model["kind"], model.get("stage")))
        action = answers.pop(0)
        if action == "timeout":
            clock.t = model["deadline"]
            controller.poll()
        else:
            controller.act(action)
    return present, seen


def test_deferring_the_early_toast_compacts_near_expiry_without_asking_again():
    _record()
    generation, _ = _two_stage()
    clock, calls = Clock(), []
    present, seen = _answer_kinds(clock, ["defer", "dismiss"])
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender(calls), present=present))
    # The early stage asked; the expiry stage compacted and only said so afterwards.
    assert seen == [("ask", "early"), ("notice", "expiry")]
    assert len(calls) == 1 and calls[0][0]["sessionId"] == "s1"
    assert outcome["event"] == "auto_compacted" and outcome["stage"] == "expiry"
    assert outcome["earlier"] == [{"stage": "early", "event": "deferred"}]
    # One idle only: nothing was written down, so the next idle asks again.
    assert idle_state.auto_mode("s1") is None


def test_a_deferred_compaction_is_void_once_the_session_is_used_again():
    """The whole point of deferring is that it is still conditional: the stage
    before the cache expires re-checks, and a session back at work is not compacted."""
    _record()
    generation, _ = _two_stage()
    clock = Clock()

    def present(controller):
        controller.act("defer")
        _record(status="busy", changed=ARMED + 200)  # the user came back to it

    outcome = iw.watch("s1", generation, _deps(clock, present=present))  # _never_send: a send fails the test
    assert outcome["event"] == "resumed" and outcome["stage"] == "expiry"
    assert outcome["earlier"] == [{"stage": "early", "event": "deferred"}]


def test_always_near_expiry_writes_the_switch_and_compacts_there():
    _record()
    generation, _ = _two_stage()
    clock, calls = Clock(), []
    present, seen = _answer_kinds(clock, ["auto_expiry", "dismiss"])
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender(calls), present=present))
    assert seen == [("ask", "early"), ("notice", "expiry")]
    assert len(calls) == 1
    assert outcome["earlier"] == [{"stage": "early", "event": "auto_expiry_set"}]
    # Unlike a deferral, this one outlives the watch.
    assert idle_state.auto_mode("s1") == "expiry"


def test_only_a_standing_switch_is_offered_back_to_be_turned_off():
    _record()
    notices = []

    def present(controller):
        if controller.model()["kind"] == "notice":
            notices.append(controller.model()["offer_auto_off"])
            return
        controller.act(answer)

    for answer, offered in (("defer", False), ("auto_expiry", True)):
        idle_state.clear_auto("s1")
        generation, _ = _two_stage()
        iw.watch("s1", generation, _deps(Clock(), compactor=_sender([]), present=present))
    assert notices == [False, True]


def test_waiting_is_not_offered_where_there_is_nothing_left_to_wait_for():
    """Only the early stage has a later one; idle_arming never puts an early
    stage last, so "defer" on the expiry toast is not a choice that exists."""
    _record()
    prompt = _prompt(Clock(FIRE))  # the expiry stage
    for action in ("defer", "auto_expiry"):
        assert prompt.act(action) == {"state": "closed"}
    assert prompt.outcome is None
    assert idle_state.auto_mode("s1") is None


def test_waiting_sends_nothing_at_the_moment_it_is_clicked():
    _record()
    generation, marker = _two_stage()
    for action, state, event in (("defer", "deferred", "deferred"),
                                 ("auto_expiry", "auto_expiry_set", "auto_expiry_set")):
        idle_state.clear_auto("s1")
        prompt = iw.AskPrompt("s1", generation, marker, EARLY_STAGE, _deps(Clock()))
        assert prompt.act(action) == {"state": state}   # _never_send: a send fails the test
        assert prompt.outcome == {"event": event}
        assert prompt.sent is False


def test_a_session_with_remote_control_off_cannot_defer_either():
    """Nothing can be sent to it now and nothing could be sent later (D-020)."""
    prompt = _remote_prompt()
    for action in ("defer", "auto_expiry"):
        assert prompt.act(action) == {"state": "closed"}
    assert prompt.outcome is None


def test_silencing_the_session_ends_the_watch_and_records_the_mute():
    _record()
    generation, _ = _two_stage()
    clock = Clock()
    present, seen = _answer(clock, ["mute"])
    outcome = iw.watch("s1", generation, _deps(clock, present=present))
    assert seen == ["early"]
    assert outcome == {"event": "muted", "for_seconds": 86_400, "stage": "early",
                       "context_tokens": 656_725, "ttl": 3600}
    assert idle_state.read_mute("s1") == {"until": EARLY_STAGE["at"] + 86_400, "after_call": ARMED - 2}


def test_the_mute_lasts_as_long_as_the_setting_says():
    from conpact import settings
    settings.save({"mute_seconds": 900})
    _record()
    generation, marker = _arm()
    prompt = _prompt(Clock(FIRE))
    assert prompt.act("mute") == {"state": "closed"}
    assert idle_state.read_mute("s1")["until"] == FIRE + 900


def test_a_session_the_user_archived_is_left_alone(tmp_path):
    _record(hostSessionId="local_a")
    store = tmp_path / "Claude" / "claude-code-sessions" / "i" / "p"
    store.mkdir(parents=True)
    (store / "archived-sessions.idx").write_text(json.dumps({"v": 1, "archived": ["local_a"]}), encoding="utf-8")
    generation, _ = _arm()
    deps = iw.Deps(clock=Clock(), sleep=Clock().sleep, environ={"APPDATA": str(tmp_path)}, sessions_dir=None,
                   compactor=_never_send, present=_never_present)
    outcome = iw.watch("s1", generation, deps)
    assert outcome == {"event": "archived", "stage": "expiry", "context_tokens": 656_725, "ttl": 3600}


def test_auto_stage_picks_the_stage_the_user_chose():
    stages = [EARLY_STAGE, EXPIRY_STAGE]
    assert iw.auto_stage(None, stages) is None
    assert iw.auto_stage("early", stages) is EARLY_STAGE
    assert iw.auto_stage("expiry", stages) is EXPIRY_STAGE
    assert iw.auto_stage("early", [EXPIRY_STAGE]) is EXPIRY_STAGE  # no early stage in this watch


def test_auto_at_idle_compacts_at_the_early_stage_and_the_later_one_stays_quiet():
    _record()
    idle_state.set_auto("s1", "early")
    generation, _ = _two_stage()
    calls, shown = [], []
    outcome = iw.watch("s1", generation, _deps(Clock(), compactor=_sender(calls), present=shown.append))
    assert len(calls) == 1 and len(shown) == 1
    assert shown[0].model()["stage"] == "early"
    assert outcome["event"] == "auto_compacted" and outcome["stage"] == "early"


def test_auto_near_expiry_shows_nothing_early_and_compacts_at_the_later_stage():
    _record()
    idle_state.set_auto("s1", "expiry")
    generation, _ = _two_stage()
    calls, shown = [], []
    clock = Clock()
    outcome = iw.watch("s1", generation, _deps(clock, compactor=_sender(calls), present=shown.append))
    assert len(calls) == 1 and len(shown) == 1
    assert shown[0].model()["stage"] == "expiry"
    assert outcome["stage"] == "expiry" and clock.t >= EXPIRY_STAGE["at"]


# --- the mod's route ------------------------------------------------------
# Where the session's mod beats, the toast reaches the session through it:
# no Remote Control needed, and nothing sent over the bridge.

def _beat(at=FIRE - 10, **fields):
    path = mod_handoff.beat_path("s1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": "s1", "at": at, "ended": False, **fields}), encoding="utf-8")


def _the_mod_answers(clock, *answers, after=1):
    """Stand in for the mod: `after` seconds into the watcher's wait, answer its
    ask - each further answer one sleep later. Returns the asks it saw."""
    seen, pending = [], list(answers)

    def on_sleep(t):
        path = mod_handoff.ask_path("s1")
        if path.exists():
            ask = json.loads(path.read_text(encoding="utf-8"))
            if not seen or seen[-1] != ask:
                seen.append(ask)
        if seen and pending and t >= seen[-1]["requested_at"] + after:
            answer = mod_handoff.answer_path("s1")
            answer.parent.mkdir(parents=True, exist_ok=True)
            answer.write_text(json.dumps({"session_id": "s1", "request_id": seen[-1]["request_id"], "at": t,
                                          **pending.pop(0)}), encoding="utf-8")
    clock.on_sleep = on_sleep
    return seen


def test_a_session_whose_mod_beats_is_reachable_without_remote_control():
    _record(bridgeSessionId=None)
    deps = _deps(Clock(FIRE))
    _beat()
    assert iw.claude_platform().reachable("s1", deps) is True
    _beat(at=FIRE - 91)
    assert iw.claude_platform().reachable("s1", deps) is False
    _beat(ended=True)
    assert iw.claude_platform().reachable("s1", deps) is False
    _record()
    assert iw.claude_platform().reachable("s1", deps) is True     # the bridge, as before


def test_the_toast_offers_to_compact_a_session_with_remote_control_off_when_its_mod_beats():
    _record(bridgeSessionId=None)
    _beat(at=FIRE)
    generation, _ = _arm()
    shown = []
    iw.watch("s1", generation, _deps(Clock(), present=shown.append))
    [prompt] = shown
    assert type(prompt) is iw.AskPrompt


def test_compact_now_hands_the_compaction_to_the_mod_and_sends_nothing_over_the_bridge(tmp_path):
    _record(bridgeSessionId=None)
    _beat()
    path = _transcript(tmp_path)
    generation, marker = _arm(transcript_path=str(path))
    clock = Clock(FIRE)
    seen = _the_mod_answers(clock, {"action": "claimed"})
    prompt = iw.AskPrompt("s1", generation, marker, EXPIRY_STAGE, _deps(clock))
    assert prompt.act("compact") == {"state": "sent"}
    [ask] = seen
    assert (ask["session_id"], ask["requested_at"], ask["expires_at"]) == ("s1", FIRE, FIRE + mod_handoff.ASK_SECONDS)
    assert prompt.outcome == {"event": "compacted", "transport": "mod", "request_id": ask["request_id"],
                              "sent_at": FIRE}
    assert prompt.sent is True
    assert not mod_handoff.ask_path("s1").exists()                # answered: the watcher takes it away
    assert prompt.progress() == {"state": "compacting", "elapsed": 1}
    _finish(path)
    assert prompt.progress() == DONE


def test_the_mod_is_preferred_where_remote_control_is_on_too():
    _record()
    _beat()
    clock = Clock(FIRE)
    _the_mod_answers(clock, {"action": "claimed"})
    prompt = _prompt(clock)                                       # _never_send: the bridge is not used
    assert prompt.act("compact") == {"state": "sent"}
    assert prompt.outcome["transport"] == "mod"


def test_without_a_beat_the_bridge_is_used_as_before():
    _record()
    calls = []
    prompt = _prompt(Clock(FIRE), compactor=_sender(calls))
    assert prompt.act("compact") == {"state": "sent"}
    assert len(calls) == 1 and "transport" not in prompt.outcome
    assert not mod_handoff.ask_path("s1").exists()


@pytest.mark.parametrize("action, said", [("error", "failed"), ("skipped", "skipped")])
def test_a_compaction_the_mod_refuses_is_reported(action, said):
    _record(bridgeSessionId=None)
    _beat()
    clock = Clock(FIRE)
    _the_mod_answers(clock, {"action": action, "reason": "a turn is running"})
    prompt = _prompt(clock)
    detail = f"the session's mod {said} the compaction: a turn is running"
    assert prompt.act("compact") == {"state": "error", "detail": detail}
    assert prompt.outcome["event"] == "failed" and prompt.outcome["reason"] == detail
    assert prompt.outcome["transport"] == "mod"
    assert prompt.sent is False


def test_a_request_the_mod_does_not_take_lapses_and_nothing_is_sent_instead():
    _record()                                                     # the bridge is there, and still not used
    _beat()
    clock = Clock(FIRE)
    prompt = _prompt(clock)
    detail = "the session's mod did not take the compaction"
    assert prompt.act("compact") == {"state": "error", "detail": detail}
    assert prompt.outcome["event"] == "failed"
    assert clock() == FIRE + mod_handoff.ASK_SECONDS + mod_handoff.GRACE_SECONDS
    assert not mod_handoff.ask_path("s1").exists()                # withdrawn: the mod will not take it now


def test_the_mods_later_refusal_ends_the_toasts_progress(tmp_path):
    _record(bridgeSessionId=None)
    _beat()
    generation, marker = _arm(transcript_path=str(_transcript(tmp_path)))
    clock = Clock(FIRE)
    _the_mod_answers(clock, {"action": "claimed"})
    prompt = iw.AskPrompt("s1", generation, marker, EXPIRY_STAGE, _deps(clock))
    assert prompt.act("compact") == {"state": "sent"}
    answer = mod_handoff.answer_path("s1")
    answer.write_text(json.dumps({**json.loads(answer.read_text(encoding="utf-8")), "action": "error",
                                  "reason": "boom"}), encoding="utf-8")
    assert prompt.progress() == {"state": "error", "detail": "the session's mod failed the compaction: boom"}


def test_nothing_is_handed_over_for_a_session_that_is_busy_when_clicked():
    _record(status="busy", changed=FIRE, bridgeSessionId=None)
    _beat()
    prompt = _prompt(Clock(FIRE))
    assert prompt.act("compact") == {"state": "closed"}
    assert prompt.outcome == {"event": "resumed"}
    assert not mod_handoff.ask_path("s1").exists()


def test_a_session_that_cannot_be_bound_is_not_handed_over(monkeypatch):
    _record(bridgeSessionId=None)
    _beat()

    def unbound(**kw):
        raise session_registry.TargetError("no session record matched")
    monkeypatch.setattr(session_registry, "resolve_self_unbound", unbound)
    prompt = _prompt(Clock(FIRE))
    assert prompt.act("compact") == {"state": "error", "detail": "no session record matched"}
    assert prompt.outcome == {"event": "error", "reason": "TargetError: no session record matched"}
    assert not mod_handoff.ask_path("s1").exists()


def test_a_request_that_cannot_be_written_is_reported(monkeypatch):
    _record(bridgeSessionId=None)
    _beat()

    def cannot(session_id, now):
        raise OSError("disk full")
    monkeypatch.setattr(mod_handoff, "ask", cannot)
    prompt = _prompt(Clock(FIRE))
    assert prompt.act("compact") == {"state": "error", "detail": "disk full"}
    assert prompt.outcome == {"event": "error", "reason": "OSError: disk full"}


def test_auto_compact_through_the_mod_shows_the_notice_and_logs_the_result(tmp_path):
    _record(bridgeSessionId=None)
    _beat(at=FIRE)                                                # the mod beats on through the wait
    path = _transcript(tmp_path)
    generation, _ = _arm(transcript_path=str(path))
    idle_state.set_auto("s1", "expiry")
    clock = Clock()
    notices = []

    def present(notice):
        notices.append(notice.model()["variant"])
        _finish(path)
    _the_mod_answers(clock, {"action": "claimed"})
    outcome = iw.watch("s1", generation, _deps(clock, present=present))
    assert notices == ["compacted"]
    assert outcome["event"] == "auto_compacted" and outcome["transport"] == "mod"
    assert outcome["result"] == DONE


def test_the_watcher_clears_what_old_sessions_left_for_the_mod(monkeypatch):
    pruned = []
    monkeypatch.setattr(mod_handoff, "prune", lambda now=None: pruned.append(now))
    monkeypatch.setattr(iw, "watch", lambda session_id, generation, deps: {"event": "cancelled"})
    monkeypatch.setattr(iw, "default_deps", lambda platform=None: None)
    assert iw.main(["s1", "g1"]) == 0
    assert pruned == [None]


def test_a_send_over_the_bridge_still_needs_remote_control():
    """Only the mod's route binds without a bridge; the bridge's own send never does."""
    _record(bridgeSessionId=None)
    _, marker = _arm()
    sent = iw._send("s1", marker, _deps(Clock(FIRE)))              # _never_send: nothing may go out
    assert sent["outcome"]["event"] == "error" and "no bridgeSessionId" in sent["outcome"]["reason"]
    assert sent["state"]["state"] == "error"


def test_the_mods_route_hands_nothing_over_for_a_session_found_busy_at_the_send():
    """Auto-compact sends without the toast's own check first: the route checks again."""
    _record(status="busy", changed=FIRE, bridgeSessionId=None)
    _beat()
    _, marker = _arm()
    sent = iw.claude_platform().send("s1", marker, _deps(Clock(FIRE)))
    assert sent == {"outcome": {"event": "resumed"}, "state": {"state": "closed"}}
    assert not mod_handoff.ask_path("s1").exists()
