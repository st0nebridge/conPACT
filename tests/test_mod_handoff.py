"""Tests for conpact.mod_handoff: the beat, the ask and the answer the idle watcher shares with the mod."""
import json
import os

import pytest

from conpact import compaction, mod_handoff as mh

NOW = 1_800_000_000.0


def _beat(**fields):
    path = mh.beat_path("s1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": "s1", "at": NOW - 10, "ended": False, **fields}), encoding="utf-8")


def _answer(request_id, **fields):
    path = mh.answer_path("s1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": "s1", "request_id": request_id, "at": NOW + 1, **fields}),
                    encoding="utf-8")


class Clock:
    def __init__(self, t=NOW):
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


def test_timings_match_the_mods():
    assert (mh.BEAT_SECONDS, mh.POLL_SECONDS, mh.FRESH_SECONDS, mh.ASK_SECONDS, mh.GRACE_SECONDS) == (30, 2, 90, 10, 3)
    assert mh.KEEP_SECONDS == 7 * 24 * 3600


def test_paths_are_under_conpacts_own_folder():
    base = compaction.STATE_DIR / "mod"
    assert mh.beat_path("s1") == base / "beat" / "s1.json"
    assert mh.ask_path("s1") == base / "ask" / "s1.json"
    assert mh.answer_path("s1") == base / "answer" / "s1.json"


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "a b"])
def test_a_session_id_that_is_not_plain_is_refused(bad):
    for path in (mh.beat_path, mh.ask_path, mh.answer_path):
        with pytest.raises(ValueError):
            path(bad)


def test_no_beat_is_no_mod():
    assert mh.alive("s1", NOW) is False


@pytest.mark.parametrize("fields, now, expected", [
    ({}, NOW, True),
    ({"at": NOW - 90}, NOW, True),                  # three beats missed is the edge
    ({"at": NOW - 90.5}, NOW, False),
    ({"at": NOW}, NOW, True),
    ({"at": NOW + 1}, NOW, False),                  # a beat from the future is not trusted
    ({"ended": True}, NOW, False),
    ({"ended": None}, NOW, False),
    ({"session_id": "s2"}, NOW, False),
    ({"at": "1"}, NOW, False),
    ({"at": True}, NOW, False),
])
def test_a_fresh_beat_of_this_session_is_a_mod(fields, now, expected):
    _beat(**fields)
    assert mh.alive("s1", now) is expected


@pytest.mark.parametrize("text", ["", "not json", "[]", "null"])
def test_an_unreadable_beat_is_no_mod(text):
    path = mh.beat_path("s1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    assert mh.alive("s1", NOW) is False


def test_an_ask_names_the_session_its_own_id_and_its_lapse():
    _answer("old", action="compacted")
    request_id = mh.ask("s1", NOW)
    assert len(request_id) == 32 and request_id.isalnum()
    assert json.loads(mh.ask_path("s1").read_text(encoding="utf-8")) == {
        "session_id": "s1", "request_id": request_id, "requested_at": NOW, "expires_at": NOW + 10}
    assert not mh.answer_path("s1").exists()       # an older answer cannot be read as this one's
    assert not list(mh.ask_path("s1").parent.glob("*.tmp"))
    assert mh.ask("s1", NOW) != request_id


@pytest.mark.parametrize("action", ["claimed", "compacted", "skipped", "error"])
def test_the_answer_to_this_request_is_read(action):
    _answer("r1", action=action)
    assert mh.answer("s1", "r1")["action"] == action


@pytest.mark.parametrize("fields", [{"request_id": "r2"}, {"session_id": "s2"}, {"action": "other"}, {"action": None}])
def test_another_requests_answer_or_an_unknown_one_is_not(fields):
    _answer(fields.pop("request_id", "r1"), **{"action": "compacted", **fields})
    assert mh.answer("s1", "r1") is None


def test_no_answer_file_is_no_answer():
    assert mh.answer("s1", "r1") is None


def test_withdraw_removes_only_this_requests_ask():
    request_id = mh.ask("s1", NOW)
    mh.withdraw("s1", "other")
    assert mh.ask_path("s1").exists()
    mh.withdraw("s1", request_id)
    assert not mh.ask_path("s1").exists()
    mh.withdraw("s1", request_id)                   # gone already: nothing to do


def test_await_answer_returns_the_first_answer_and_removes_the_ask():
    clock = Clock()
    request_id = mh.ask("s1", NOW)
    clock.on_sleep = lambda t: _answer(request_id, action="claimed") if t >= NOW + 3 else None
    found = mh.await_answer("s1", request_id, NOW, clock, clock.sleep)
    assert found["action"] == "claimed"
    assert clock.slept == [1.0, 1.0, 1.0]
    assert not mh.ask_path("s1").exists()


def test_await_answer_gives_up_shortly_after_the_lapse_and_withdraws():
    clock = Clock()
    request_id = mh.ask("s1", NOW)
    assert mh.await_answer("s1", request_id, NOW, clock, clock.sleep) is None
    assert clock() == NOW + 13
    assert sum(clock.slept) == 13
    assert not mh.ask_path("s1").exists()


def test_await_answer_reads_an_answer_already_there_without_sleeping():
    clock = Clock()
    request_id = mh.ask("s1", NOW)
    _answer(request_id, action="error", reason="a turn is running")
    assert mh.await_answer("s1", request_id, NOW, clock, clock.sleep)["reason"] == "a turn is running"
    assert clock.slept == []


@pytest.mark.parametrize("found, text", [
    ({"action": "skipped", "reason": "not now"}, "the session's mod skipped the compaction: not now"),
    ({"action": "error", "reason": "a turn is running"}, "the session's mod failed the compaction: a turn is running"),
    ({"action": "error"}, "the session's mod failed the compaction"),
    ({"action": "error", "reason": ""}, "the session's mod failed the compaction"),
    ({"action": "skipped", "reason": 3}, "the session's mod skipped the compaction"),
])
def test_refusal(found, text):
    assert mh.refusal(found) == text


class Inner:
    def __init__(self, *states):
        self.states = list(states)
        self.checks = 0

    def check(self):
        self.checks += 1
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def test_the_tracker_follows_the_transcript_while_the_mod_says_nothing_else():
    inner = Inner({"state": "compacting", "elapsed": 1}, {"state": "compacted", "seconds": 4.0})
    _answer("r1", action="claimed")
    tracker = mh.Tracker(inner, "s1", "r1", NOW)
    assert tracker.check() == {"state": "compacting", "elapsed": 1}
    assert tracker.check() == {"state": "compacted", "seconds": 4.0}
    assert tracker.check() == {"state": "compacted", "seconds": 4.0}
    assert inner.checks == 2                        # a result is kept, not looked for again


@pytest.mark.parametrize("action, said", [("skipped", "skipped"), ("error", "failed")])
def test_the_tracker_ends_on_the_mods_refusal(action, said):
    inner = Inner({"state": "compacting", "elapsed": 1})
    _answer("r1", action=action, reason="why")
    tracker = mh.Tracker(inner, "s1", "r1", NOW)
    assert tracker.check() == {"state": "error", "detail": f"the session's mod {said} the compaction: why"}
    assert inner.checks == 0
    _answer("r1", action="compacted")
    assert tracker.check()["state"] == "error"


def test_without_a_transcript_the_mods_word_is_the_result():
    tracker = mh.Tracker(None, "s1", "r1", NOW)
    assert tracker.check() == {"state": "untracked"}
    _answer("r1", action="compacted", tokens_before=656_725, tokens_after=19_111, at=NOW + 7.25)
    assert tracker.check() == {"state": "compacted", "pre_tokens": 656_725, "post_tokens": 19_111,
                               "seconds": 7.2, "trigger": None, "at": None}


def test_without_a_transcript_a_compacted_answer_with_bad_numbers_still_ends():
    _answer("r1", action="compacted", tokens_before=-1, tokens_after=True, at="soon")
    assert mh.Tracker(None, "s1", "r1", NOW).check() == {
        "state": "compacted", "pre_tokens": None, "post_tokens": None, "seconds": 0.0, "trigger": None, "at": None}


def test_the_tracker_waits_until_the_compaction_is_over():
    clock = Clock()
    inner = Inner({"state": "compacting", "elapsed": 1}, {"state": "compacting", "elapsed": 6},
                  {"state": "compacted", "seconds": 9.0})
    assert mh.Tracker(inner, "s1", "r1", NOW).wait(clock.sleep, 5) == {"state": "compacted", "seconds": 9.0}
    assert clock.slept == [5, 5]


def test_prune_removes_only_what_is_a_week_old():
    _beat()
    old = mh.answer_path("s9")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("{}", encoding="utf-8")
    week = NOW - mh.KEEP_SECONDS
    os.utime(old, (week - 1, week - 1))
    os.utime(mh.beat_path("s1"), (week + 1, week + 1))
    mh.prune(NOW)
    assert not old.exists()
    assert mh.beat_path("s1").exists()


def test_prune_with_nothing_there_does_nothing():
    mh.prune(NOW)
    mh.prune()


def test_await_answer_sleeps_no_further_than_the_deadline():
    clock = Clock(NOW + 0.5)
    request_id = mh.ask("s1", NOW)
    assert mh.await_answer("s1", request_id, NOW, clock, clock.sleep) is None
    assert clock() == NOW + 13
    assert clock.slept == [1.0] * 12 + [0.5]


def test_prune_clears_all_three_folders():
    week = NOW - mh.KEEP_SECONDS
    for path in (mh.beat_path("s9"), mh.ask_path("s9"), mh.answer_path("s9")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (week - 1, week - 1))
    mh.prune(NOW)
    assert not any(p.exists() for p in (mh.beat_path("s9"), mh.ask_path("s9"), mh.answer_path("s9")))


def test_without_a_transcript_a_zero_count_is_a_count():
    _answer("r1", action="compacted", tokens_before=0, tokens_after=0, at=NOW)
    found = mh.Tracker(None, "s1", "r1", NOW).check()
    assert (found["pre_tokens"], found["post_tokens"]) == (0, 0)
