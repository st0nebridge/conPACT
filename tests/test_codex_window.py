"""
@module tests.test_codex_window
@description When an idle Codex thread's prompt cache runs out: which records
             count as a call, that the kind is found wherever Codex puts it,
             that the context comes from the meter rather than being measured
             twice, and that the lifetime is the modelled one because Codex
             never states its own.
@input      conpact.codex_window, against written rollout files
@output     assertions on last_call, read_window and the TTL model
@dependencies conpact.codex_window, conpact.codex_meter; stdlib: json
"""
import json

import pytest

from conpact import cache_window, codex_meter, codex_window

WHEN = "2026-09-22T04:00:02.114Z"
LATER = "2026-09-22T05:30:00.000Z"


def rollout(tmp_path, *records):
    path = tmp_path / "rollout.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def usage_record(when=WHEN, total=187_170):
    """A `token_usage_record`, whose kind Codex puts at the TOP level."""
    return {"timestamp": when, "type": "token_usage_record",
            "payload": {"usage": {"input_tokens": total, "total_tokens": total}}}


def count_event(when=WHEN, total=13_083, window=258_400):
    """A `token_count`, which is an `event_msg` whose PAYLOAD carries the kind."""
    return {"timestamp": when, "type": "event_msg",
            "payload": {"type": "token_count",
                        "info": {"last_token_usage": {"total_tokens": total},
                                 "model_context_window": window}}}


class TestFindingTheKind:
    def test_a_usage_record_is_recognised_from_the_top_level(self):
        assert codex_window._kind(usage_record()) == "token_usage_record"

    def test_a_token_count_is_recognised_from_its_payload(self):
        """Reading only the payload finds the first of these and not the second;
        reading only the top level finds the second and not the first. This went
        wrong that way round the first time."""
        assert codex_window._kind(count_event()) == "token_count"

    @pytest.mark.parametrize("record", [
        {}, {"type": "compacted"}, {"payload": {"type": "task_complete"}},
        {"payload": "not a dict"}, {"type": None}])
    def test_anything_else_is_not_a_call(self, record):
        assert codex_window._kind(record) is None


class TestWhenTheThreadLastCalled:
    def test_the_newest_call_wins(self, tmp_path):
        path = rollout(tmp_path, usage_record(WHEN), usage_record(LATER))
        assert codex_window.last_call(path) == codex_window.parse_timestamp(LATER)

    def test_either_kind_counts_as_a_call(self, tmp_path):
        assert codex_window.last_call(rollout(tmp_path, count_event(LATER))) == \
            codex_window.parse_timestamp(LATER)

    def test_records_that_are_not_calls_are_passed_over(self, tmp_path):
        path = rollout(tmp_path, usage_record(WHEN),
                       {"timestamp": LATER, "type": "compacted", "payload": {}},
                       {"timestamp": LATER, "payload": {"type": "task_complete"}})
        assert codex_window.last_call(path) == codex_window.parse_timestamp(WHEN)

    def test_a_rollout_with_no_call_says_so(self, tmp_path):
        assert codex_window.last_call(rollout(tmp_path, {"type": "task_started"})) is None

    def test_a_missing_rollout_is_not_an_error(self, tmp_path):
        assert codex_window.last_call(tmp_path / "absent.jsonl") is None

    def test_a_call_with_no_usable_time_is_not_one(self, tmp_path):
        path = rollout(tmp_path, usage_record("not a timestamp"))
        assert codex_window.last_call(path) is None

    def test_it_gives_up_rather_than_reading_a_whole_rollout(self, tmp_path):
        """Rollouts reach hundreds of megabytes; the search is bounded. Records
        are read newest first, so the call being old is what puts it out of
        reach - putting it last in the file would be the first one seen."""
        path = rollout(tmp_path, usage_record(), *([{"type": "task_started"}] * 20))
        assert codex_window.last_call(path, max_records=5) is None
        assert codex_window.last_call(path, max_records=50) is not None


class TestTheWindow:
    def test_it_is_the_last_call_the_modelled_ttl_and_the_measured_context(self, tmp_path):
        path = rollout(tmp_path, usage_record(WHEN), count_event(WHEN, total=13_083))
        window = codex_window.read_window(path)
        assert isinstance(window, cache_window.CacheWindow)
        assert window.last_call == codex_window.parse_timestamp(WHEN)
        assert window.ttl == codex_window.TTL
        assert window.context_tokens == 13_083
        assert window.expires_at == window.last_call + codex_window.TTL

    def test_the_context_comes_from_the_meter_not_from_here(self, tmp_path, monkeypatch):
        """One module owns "how large is this thread", so a compaction and a
        toast can never disagree about the same thread."""
        asked = []
        monkeypatch.setattr(codex_meter, "current_context_tokens",
                            lambda path, max_records=2000: asked.append(path) or 4242)
        window = codex_window.read_window(rollout(tmp_path, usage_record()))
        assert window.context_tokens == 4242
        assert asked

    def test_no_call_means_no_window(self, tmp_path):
        assert codex_window.read_window(rollout(tmp_path, {"type": "task_started"})) is None

    def test_a_thread_the_meter_cannot_size_has_no_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(codex_meter, "current_context_tokens",
                            lambda path, max_records=2000: None)
        assert codex_window.read_window(rollout(tmp_path, usage_record())) is None


class TestTheLifetimeIsModelledNotRead:
    def test_codex_states_no_ttl_so_ours_is_marked_as_modelled(self):
        """Claude records `ephemeral_5m/1h_input_tokens` and cache_window reads
        it. Codex records only how much was cached, so this flag is what stops
        the toast implying the number came from the app."""
        assert codex_window.TTL_IS_MEASURED_NOT_DECLARED is True

    def test_the_lifetime_is_one_constant_in_one_place(self):
        assert codex_window.TTL == 3600

    def test_the_measurement_behind_it_is_written_down(self):
        """A modelled constant with no evidence beside it is a guess that looks
        like a fact."""
        doc = codex_window.__doc__
        assert "2,232" in doc and "hit cache" in doc and "45" in doc
