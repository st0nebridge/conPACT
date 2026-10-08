"""
@module tests.test_codex_meter
@description What a Codex rollout says about its thread right now: how large the
             context is, how large the window is, and whether a turn is running.
@input      conpact.codex_meter, against hand-written rollout files
@output     assertions on both token record shapes, the cumulative-counter trap,
            turn state and the tail bound
@dependencies conpact.codex_meter; stdlib: json
"""
import json

import pytest

from conpact import codex_meter


def rollout(tmp_path, *records, name="r.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def token_count(total, window=258400):
    """The `event_msg`/`token_count` shape."""
    return {"type": "event_msg", "payload": {
        "type": "token_count",
        "info": {"total_token_usage": {"total_tokens": 414284594},
                 "last_token_usage": {"input_tokens": total - 1, "output_tokens": 1,
                                      "total_tokens": total},
                 "model_context_window": window}}}


def usage_record(total):
    """The `token_usage_record` shape, which carries a cumulative counter beside
    the per-call one."""
    return {"type": "token_usage_record", "payload": {
        "usage": {"total_tokens": total},
        "turn_token_usage": {"total_tokens": 2799281},
        "thread_token_usage": {"total_tokens": 419896175}}}


def marker(kind, turn="t1"):
    return {"type": "event_msg", "payload": {"type": kind, "turn_id": turn,
                                             "model_context_window": 258400}}


class TestContextSize:
    def test_it_reads_the_per_call_total_from_a_token_count_event(self, tmp_path):
        path = rollout(tmp_path, token_count(150504))
        assert codex_meter.current_context_tokens(path) == 150504

    def test_it_reads_the_per_call_total_from_a_token_usage_record(self, tmp_path):
        path = rollout(tmp_path, usage_record(177573))
        assert codex_meter.current_context_tokens(path) == 177573

    def test_the_cumulative_counters_are_never_mistaken_for_the_context(self, tmp_path):
        """The trap this module exists to avoid: `thread_token_usage` on the same
        record read 419,896,175 on this machine against a real context of 177,573
        - out by three orders of magnitude. `tokens_used` in the state store is
        the same cumulative number."""
        path = rollout(tmp_path, usage_record(177573))
        assert codex_meter.current_context_tokens(path) == 177573

    def test_the_newest_record_wins(self, tmp_path):
        path = rollout(tmp_path, usage_record(1000), token_count(2000), usage_record(3000))
        assert codex_meter.current_context_tokens(path) == 3000

    def test_records_that_carry_no_usage_are_skipped_to_reach_one_that_does(self, tmp_path):
        path = rollout(tmp_path, usage_record(4242),
                       {"type": "response_item", "payload": {"x": 1}},
                       {"type": "event_msg", "payload": {"type": "item_completed"}})
        assert codex_meter.current_context_tokens(path) == 4242

    def test_a_rollout_with_no_usage_at_all_cannot_be_measured(self, tmp_path):
        path = rollout(tmp_path, {"type": "response_item", "payload": {}})
        assert codex_meter.current_context_tokens(path) is None

    def test_a_missing_rollout_cannot_be_measured(self, tmp_path):
        assert codex_meter.current_context_tokens(tmp_path / "absent.jsonl") is None

    @pytest.mark.parametrize("path", [None, "", 0])
    def test_no_path_at_all_cannot_be_measured(self, path):
        assert codex_meter.current_context_tokens(path) is None

    @pytest.mark.parametrize("bad", [{"total_tokens": 0}, {"total_tokens": -5},
                                     {"total_tokens": True}, {"total_tokens": "150k"}, {}, None])
    def test_a_total_that_is_not_a_positive_whole_number_says_nothing(self, tmp_path, bad):
        path = rollout(tmp_path, {"type": "token_usage_record", "payload": {"usage": bad}})
        assert codex_meter.current_context_tokens(path) is None

    def test_a_truncated_last_line_does_not_stop_the_reader(self, tmp_path):
        """Codex appends to this file while we read it, so the last line is
        routinely half-written."""
        path = rollout(tmp_path, usage_record(555))
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"type": "token_usage_record", "payl')
        assert codex_meter.current_context_tokens(path) == 555


class TestContextWindow:
    def test_it_reads_the_window_from_a_token_count_event(self, tmp_path):
        path = rollout(tmp_path, token_count(150504, window=258400))
        assert codex_meter.context_window(path) == 258400

    def test_a_turn_marker_also_carries_the_window(self, tmp_path):
        """Useful on a thread whose turn has started but produced no usage yet."""
        path = rollout(tmp_path, marker("task_started"))
        assert codex_meter.context_window(path) == 258400

    def test_a_rollout_that_never_says_has_no_window(self, tmp_path):
        assert codex_meter.context_window(rollout(tmp_path, usage_record(10))) is None


class TestTurnState:
    def test_a_thread_whose_last_marker_is_a_completion_is_idle(self, tmp_path):
        path = rollout(tmp_path, marker("task_started"), marker("task_complete"))
        assert codex_meter.turn_state(path) == codex_meter.IDLE

    def test_a_thread_whose_last_marker_is_a_start_is_still_running(self, tmp_path):
        path = rollout(tmp_path, marker("task_complete", "t1"), marker("task_started", "t2"))
        assert codex_meter.turn_state(path) == codex_meter.RUNNING

    def test_records_after_the_marker_do_not_change_the_answer(self, tmp_path):
        """A completed turn is still followed by trailing records."""
        path = rollout(tmp_path, marker("task_complete"),
                       {"type": "response_item", "payload": {}}, usage_record(10))
        assert codex_meter.turn_state(path) == codex_meter.IDLE

    def test_a_rollout_with_no_markers_says_nothing(self, tmp_path):
        assert codex_meter.turn_state(rollout(tmp_path, usage_record(10))) is None

    def test_a_missing_rollout_says_nothing(self, tmp_path):
        assert codex_meter.turn_state(tmp_path / "absent.jsonl") is None


class TestTheTailBound:
    def test_it_gives_up_rather_than_reading_a_whole_rollout_backwards(self, tmp_path):
        """Rollouts reach 158 MB on this machine. A thread whose tail carries no
        usage must read as unmeasurable in bounded time, not walk to byte zero."""
        filler = [{"type": "response_item", "payload": {"n": n}} for n in range(400)]
        path = rollout(tmp_path, usage_record(99), *filler)
        assert codex_meter.current_context_tokens(path, max_records=50) is None
        assert codex_meter.current_context_tokens(path, max_records=500) == 99


class TestTheNames:
    def test_the_two_turn_states_are_named_as_literals(self):
        """Callers branch on these and the CLI prints them."""
        assert codex_meter.IDLE == "idle"
        assert codex_meter.RUNNING == "running"

    def test_the_rollout_markers_are_the_ones_codex_writes(self):
        assert codex_meter.STARTED == "task_started"
        assert codex_meter.COMPLETE == "task_complete"
        assert codex_meter.WINDOW == "model_context_window"

    def test_a_context_of_a_single_token_still_counts_as_a_measurement(self, tmp_path):
        """`> 0` is the guard; `> 1` would read a real one-token context as
        unmeasurable, and "unmeasurable" makes the closure hook fail closed."""
        path = rollout(tmp_path, usage_record(1))
        assert codex_meter.current_context_tokens(path) == 1
