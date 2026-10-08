"""
@module tests.regression.test_codex_current_call_binding
@description Bind current calls without scanning a long turn's older history.
@input Isolated fresh rollouts and a method-specific MCP context
@output Exact callers, rejection of closed calls, and bounded history reads
@dependencies conpact.codex_caller, conpact.codex_meter, conpact.codex_threads,
              conpact.mcp_tools; stdlib: json; pytest
"""
import json

import pytest

from conpact import codex_caller, codex_meter, codex_threads, mcp_tools

THREAD = "019d0000-0000-7000-a000-000000000003"
OTHER = "019d0000-0000-7000-a000-000000000004"
CALL = {"type": "response_item", "payload": {"type": "custom_tool_call",
        "name": "exec", "input": "await tools.mcp__conpact__queue_compaction({});"}}


def rollout(tmp_path, *records, thread=THREAD):
    path = tmp_path / (thread + ".jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return {"id": thread, "rollout_path": str(path), "kind": "user", "archived": False}


def context():
    return mcp_tools.Context(environ={"CODEX_HOME": "isolated"}, ppid=41,
                             tool_name="queue_compaction")


def test_current_call_binds_when_turn_start_is_beyond_the_history_limit(tmp_path, monkeypatch):
    row = rollout(tmp_path, {"type": "event_msg", "payload": {"type": "task_started"}},
                  *[{"type": "event_msg", "payload": {"type": "token_count"}}]
                  * codex_meter.MAX_RECORDS, CALL)
    monkeypatch.setattr(codex_threads, "threads", lambda env: [row])
    assert codex_meter.turn_state(row["rollout_path"]) is None
    assert codex_caller.recent_threads(context()) == ([THREAD], [THREAD])


def test_method_binding_does_not_spend_its_settle_window_scanning_old_turns(tmp_path, monkeypatch):
    row = rollout(tmp_path, CALL)
    other = rollout(tmp_path, {"type": "event_msg", "payload": {"type": "task_started"}},
                    thread=OTHER)
    monkeypatch.setattr(codex_threads, "threads", lambda env: [other, row])
    reads = []
    monkeypatch.setattr(codex_meter, "turn_state", lambda path: reads.append(path))
    assert codex_caller.recent_threads(context()) == ([THREAD], [THREAD])
    assert reads == []


@pytest.mark.parametrize("boundary", ["task_complete", "turn_aborted", "task_started"])
def test_turn_boundaries_clear_an_earlier_unreturned_call(tmp_path, monkeypatch, boundary):
    row = rollout(tmp_path, CALL, {"type": "event_msg", "payload": {"type": boundary}})
    monkeypatch.setattr(codex_threads, "threads", lambda env: [row])
    assert not codex_caller.rollout_is_calling_conpact(row["rollout_path"], "queue_compaction")
    assert codex_caller.recent_threads(context()) == ([], [])


@pytest.mark.parametrize("field,value", [("phase", "final_answer"), ("channel", "final")])
def test_a_final_answer_clears_an_unreturned_call(tmp_path, field, value):
    row = rollout(tmp_path, CALL, {"type": "response_item", "payload": {
        "type": "message", "role": "assistant", field: value, "content": []}})
    assert not codex_caller.rollout_is_calling_conpact(row["rollout_path"], "queue_compaction")


def test_call_diagnostics_preserve_the_marker_time_without_its_input(tmp_path):
    record = {**CALL, "timestamp": "2026-10-03T15:46:59.214Z"}
    row = rollout(tmp_path, record)
    evidence = {}
    assert codex_caller.rollout_is_calling_conpact(row["rollout_path"], "queue_compaction", evidence)
    assert evidence == {"marker": "custom_tool_call", "marker_at": record["timestamp"]}


def test_refusal_saves_evidence_without_mutating_a_shared_context(monkeypatch):
    from conpact import codex_active, codex_caller_log
    ctx = context()
    ctx.binding_trace = {"retained": "original"}
    captured = []
    monkeypatch.setattr(codex_active, "sole_thread", lambda **kwargs: (None, codex_active.FOREIGN_PROCESS))
    monkeypatch.setattr(codex_caller_log, "record", lambda *args: captured.append(args))
    result = mcp_tools.call_tool("queue_compaction", {}, ctx)
    assert result["isError"]
    assert captured[0][:3] == (41, "queue_compaction", codex_active.FOREIGN_PROCESS)
    assert captured[0][3]["attempts"] == 1
    assert ctx.binding_trace == {"retained": "original"}


def test_two_current_calls_remain_ambiguous_even_without_recent_turn_markers(tmp_path, monkeypatch):
    rows = [rollout(tmp_path, CALL), rollout(tmp_path, CALL, thread=OTHER)]
    monkeypatch.setattr(codex_threads, "threads", lambda env: rows)
    assert codex_caller.recent_threads(context()) == ([THREAD, OTHER], [THREAD, OTHER])


def test_a_running_turn_without_the_current_method_is_never_a_caller(tmp_path, monkeypatch):
    row = rollout(tmp_path, {"type": "event_msg", "payload": {"type": "task_started"}},
                  {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                   "input": "await tools.mcp__conpact__compaction_status({});"}})
    monkeypatch.setattr(codex_threads, "threads", lambda env: [row])
    assert codex_caller.recent_threads(context()) == ([], [])
