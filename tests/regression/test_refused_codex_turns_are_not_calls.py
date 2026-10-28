"""
@module tests.regression.test_refused_codex_turns_are_not_calls
@description Regression test for CU-20261028-128. A Codex automation heartbeat
             that is refused for a spent usage limit still writes a `token_count`
             record, every few minutes. `last_call` read it as a model call, so
             the thread looked freshly used: "Silence" (which ends when the
             thread is used) was cleared and "Not now" re-armed the toast.
@input      conpact.codex_window, conpact.idle_arming, conpact.idle_state
@output     assertions that a refused turn moves neither the window nor the mute
@dependencies conpact.codex_window, conpact.idle_arming, conpact.idle_state; stdlib: json
"""
import json

from conpact import codex_window, idle_arming, idle_state

CALL = "2026-10-28T00:00:00.000Z"
HEARTBEAT = "2026-10-28T00:52:44.000Z"


def _rollout(tmp_path, *records):
    path = tmp_path / "rollout.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _count(when):
    return {"timestamp": when, "type": "event_msg",
            "payload": {"type": "token_count",
                        "info": {"last_token_usage": {"total_tokens": 265_656},
                                 "model_context_window": 475_000}}}


def _started(when):
    return {"timestamp": when, "type": "event_msg", "payload": {"type": "task_started"}}


def _done(when, error=None):
    return {"timestamp": when, "type": "event_msg",
            "payload": {"type": "task_complete", "error": error}}


REFUSED = {"message": "You've hit your usage limit.", "codex_error_info": "usage_limit_exceeded"}


def test_a_turn_refused_for_the_usage_limit_is_not_a_call(tmp_path):
    path = _rollout(tmp_path, _started(CALL), _count(CALL), _done(CALL),
                    _started(HEARTBEAT), _count(HEARTBEAT), _done(HEARTBEAT, REFUSED))
    assert codex_window.last_call(path) == codex_window.parse_timestamp(CALL)


def test_a_completed_turn_after_it_still_counts(tmp_path):
    later = "2026-10-28T01:30:00.000Z"
    path = _rollout(tmp_path, _started(CALL), _count(CALL), _done(CALL, REFUSED),
                    _started(later), _count(later), _done(later))
    assert codex_window.last_call(path) == codex_window.parse_timestamp(later)


def test_other_errors_still_count_their_calls(tmp_path):
    other = {"message": "stream closed", "codex_error_info": "other"}
    path = _rollout(tmp_path, _started(CALL), _count(CALL), _done(CALL, other))
    assert codex_window.last_call(path) == codex_window.parse_timestamp(CALL)


def test_a_refused_heartbeat_does_not_end_a_silence(tmp_path, monkeypatch):
    monkeypatch.setenv("CONPACT_HOME", str(tmp_path / "home"))
    path = _rollout(tmp_path, _started(CALL), _count(CALL), _done(CALL),
                    _started(HEARTBEAT), _count(HEARTBEAT), _done(HEARTBEAT, REFUSED))
    window = codex_window.read_window(path)
    silenced_at = codex_window.parse_timestamp(CALL) + 600
    idle_state.set_mute("thread-1", silenced_at + 86_400,
                        after_call=codex_window.parse_timestamp(CALL))
    assert idle_arming.mute_left("thread-1", window, silenced_at + 3_000) is not None
