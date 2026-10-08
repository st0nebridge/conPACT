"""Tests for conpact.codex_active: which Codex thread is mid-turn.

This is an identity, so the interesting cases are all the ones where it must
refuse to give one.
"""
import json
import time

import pytest

from conpact import codex_active


class TestPublishing:
    def test_it_writes_the_in_flight_set(self, tmp_path):
        assert codex_active.publish(["b", "a"], home=tmp_path) is True
        data = json.loads(codex_active.record_path(tmp_path).read_text(encoding="utf-8"))
        assert data["threads"] == ["a", "b"], "sorted, so the file is stable"

    def test_it_creates_the_folder_on_a_machine_without_claude(self, tmp_path):
        assert codex_active.publish(["a"], home=tmp_path / "fresh") is True

    def test_it_never_raises_on_the_pump(self, tmp_path):
        wall = tmp_path / "file"
        wall.write_text("", encoding="utf-8")
        assert codex_active.publish(["a"], home=wall) is False

    def test_an_unserialisable_set_is_refused_not_raised(self, tmp_path):
        assert codex_active.publish([object()], home=tmp_path) is False


class TestBinding:
    def _publish(self, tmp_path, threads, at=None):
        codex_active.publish(threads, calling=threads, home=tmp_path,
                             clock=lambda: at or time.time())

    def test_exactly_one_tool_call_identifies_the_caller(self, tmp_path):
        self._publish(tmp_path, ["t-1"])
        assert codex_active.sole_thread(home=tmp_path) == ("t-1", None)

    def test_no_turn_in_flight_identifies_nobody(self, tmp_path):
        self._publish(tmp_path, [])
        thread, why = codex_active.sole_thread(home=tmp_path)
        assert thread is None and "no turn is in flight" in why

    def test_two_at_once_is_refused_rather_than_guessed(self, tmp_path):
        """The failure worth avoiding is acting on a thread that did not ask."""
        self._publish(tmp_path, ["t-1", "t-2"])
        thread, why = codex_active.sole_thread(home=tmp_path)
        assert thread is None and "will not guess" in why and "2 threads" in why

    def test_a_stale_record_is_not_evidence(self, tmp_path):
        """The sidecar writes on every turn boundary; an old file means it died
        mid-turn or the machine slept."""
        now = 10_000.0
        self._publish(tmp_path, ["t-1"], at=now - codex_active.MAX_AGE_SECONDS - 1)
        thread, why = codex_active.sole_thread(home=tmp_path, clock=lambda: now)
        assert thread is None and "last update was" in why

    def test_a_record_just_inside_the_window_still_counts(self, tmp_path):
        now = 10_000.0
        self._publish(tmp_path, ["t-1"], at=now - codex_active.MAX_AGE_SECONDS + 1)
        assert codex_active.sole_thread(home=tmp_path, clock=lambda: now)[0] == "t-1"

    def test_no_sidecar_at_all_says_so(self, tmp_path):
        thread, why = codex_active.sole_thread(home=tmp_path)
        assert thread is None and "sidecar is not running" in why

    @pytest.mark.parametrize("raw", ["", "not json", "[1,2]", "null",
                                     '{"threads":"a","at":1}', '{"threads":[]}'])
    def test_an_unusable_record_identifies_nobody(self, raw, tmp_path):
        path = codex_active.record_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        assert codex_active.sole_thread(home=tmp_path)[0] is None

    def test_blank_entries_are_not_threads(self, tmp_path):
        self._publish(tmp_path, ["  ", ""])
        assert codex_active.sole_thread(home=tmp_path)[0] is None
