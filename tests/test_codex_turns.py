"""Tests for conpact.codex_turns: turn-end events out of the app-server stream.

Two properties carry the design. It must not fire on the wrong thing - acting
on a mis-read event arms a watch against a session that is still working - and
it must never raise, because it runs inside the sidecar's pump.
"""
import json

import pytest

from conpact import codex_turns


def line(obj):
    return json.dumps(obj).encode("utf-8")


class TestWhatCountsAsATurnEnding:
    def test_a_turn_completed_notification_names_its_thread(self):
        assert codex_turns.turn_ended(
            {"method": "turn/completed", "params": {"threadId": "t-1"}}) == "t-1"

    @pytest.mark.parametrize("key", ["threadId", "thread_id", "conversationId"])
    def test_the_id_is_read_wherever_it_travels(self, key):
        assert codex_turns.turn_ended(
            {"method": "turn/completed", "params": {key: "t-9"}}) == "t-9"

    def test_a_nested_thread_object_also_names_it(self):
        assert codex_turns.turn_ended(
            {"method": "turn/completed", "params": {"thread": {"id": "t-2"}}}) == "t-2"

    @pytest.mark.parametrize("method", [
        "turn/started", "item/completed", "item/started",
        "thread/tokenUsage/updated", "thread/status/changed", "hook/completed",
    ])
    def test_nothing_else_is_a_turn_ending(self, method):
        """`turn/started` is its opposite and an item is one step inside a turn.
        A sweep still catches whatever this misses; a false fire arms a watch
        against a session that is still working."""
        assert codex_turns.turn_ended({"method": method, "params": {"threadId": "t"}}) is None

    def test_a_reply_is_never_an_event_whatever_it_is_called(self):
        """Anything with an id answers somebody's request."""
        assert codex_turns.turn_ended(
            {"id": "7", "method": "turn/completed", "params": {"threadId": "t"}}) is None

    @pytest.mark.parametrize("params", [None, {}, [1, 2], "text", {"threadId": ""},
                                        {"threadId": "   "}, {"threadId": 7}])
    def test_an_event_that_names_no_usable_thread_is_not_actionable(self, params):
        assert codex_turns.turn_ended({"method": "turn/completed", "params": params}) is None

    @pytest.mark.parametrize("message", [None, [], "s", 7, {"method": None}])
    def test_anything_that_is_not_a_message_is_not_an_event(self, message):
        assert codex_turns.turn_ended(message) is None


class TestItNeverBreaksThePump:
    @pytest.mark.parametrize("raw", [b"", b"not json", b"[1,2,3]", b"null",
                                     b"\xff\xfe binary", b'{"method":'])
    def test_unparseable_bytes_are_simply_not_events(self, raw):
        assert codex_turns.Turns().note(raw) is None

    def test_a_clock_that_explodes_does_not_escape(self):
        def boom():
            raise RuntimeError("no clock")
        turns = codex_turns.Turns(clock=boom)
        assert turns.note(line({"method": "turn/completed",
                                "params": {"threadId": "t"}})) is None


class TestOneArmingPerTurn:
    def _turns(self):
        self.now = 1000.0
        return codex_turns.Turns(clock=lambda: self.now, settle=2.0)

    def test_the_first_turn_end_reports_its_thread(self):
        turns = self._turns()
        assert turns.note(line({"method": "turn/completed",
                                "params": {"threadId": "t-1"}})) == "t-1"

    def test_a_repeat_inside_the_settling_window_is_swallowed(self):
        """Re-arming retires the live watcher and restarts its timer, so a
        burst must not become several armings."""
        turns = self._turns()
        msg = line({"method": "turn/completed", "params": {"threadId": "t-1"}})
        assert turns.note(msg) == "t-1"
        self.now += 0.5
        assert turns.note(msg) is None
        self.now += 0.5
        assert turns.note(msg) is None

    def test_once_it_has_settled_the_next_turn_reports_again(self):
        turns = self._turns()
        msg = line({"method": "turn/completed", "params": {"threadId": "t-1"}})
        assert turns.note(msg) == "t-1"
        self.now += 5.0
        assert turns.note(msg) == "t-1"

    def test_two_threads_settle_independently(self):
        turns = self._turns()
        a = line({"method": "turn/completed", "params": {"threadId": "a"}})
        b = line({"method": "turn/completed", "params": {"threadId": "b"}})
        assert turns.note(a) == "a"
        assert turns.note(b) == "b", "one thread's burst must not silence another"
        self.now += 0.2
        assert turns.note(a) is None and turns.note(b) is None
