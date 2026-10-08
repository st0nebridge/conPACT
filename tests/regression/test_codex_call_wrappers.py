"""
@module tests.regression.test_codex_call_wrappers
@description Caller binding recognizes awaited batches and delayed call records.
@input Isolated rollouts, sidecar records and a scripted polling clock
@output Exact caller binding or refusal without queuing another thread
@dependencies conpact.codex_active, conpact.codex_caller, conpact.compaction,
              conpact.mcp_server, conpact.mcp_tools; stdlib: json; pytest
"""
import json

import pytest

from conpact import codex_active, codex_caller, compaction, mcp_server, mcp_tools

THREAD = "019d0000-0000-7000-a000-000000000003"
OTHER = "019d0000-0000-7000-a000-000000000004"


def test_refreshed_server_guidance_clears_a_past_refusal_for_later_closures():
    response = mcp_server.handle_message({"jsonrpc": "2.0", "id": 1,
        "method": "initialize", "params": {}}, context())
    assert "A binding refusal applies only to that call" in response["result"]["instructions"]
    assert "a fresh binding" in response["result"]["instructions"]


@pytest.mark.parametrize("batch", ["all", "allSettled"])
@pytest.mark.parametrize("position", ["first", "later"])
def test_literal_tool_calls_in_an_awaited_batch_identify_the_method(
        tmp_path, batch, position):
    calls = ["tools.mcp__conpact__compaction_status({})", "tools.other({})"]
    if position == "later":
        calls.reverse()
    source = "const r = await Promise." + batch + "([\n" + ",\n".join(calls) + "]);"
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps({"type": "response_item", "payload": {
        "type": "custom_tool_call", "name": "exec", "input": source}}) + "\n")
    assert codex_caller.rollout_is_calling_conpact(path, "compaction_status")
    assert not codex_caller.rollout_is_calling_conpact(path, "queue_compaction")


@pytest.mark.parametrize("source", [
    'text("await Promise.all([tools.mcp__conpact__queue_compaction({})])");',
    "// await Promise.all([tools.mcp__conpact__queue_compaction({})]);",
    "await Promise.all([() => tools.mcp__conpact__queue_compaction({})]);",
    "await Promise.all([async () => { await tools.mcp__conpact__queue_compaction({}); }]);",
    "await Promise.all([tools.other({callback: () => tools.mcp__conpact__queue_compaction({})})]);",
    "Promise.all([tools.mcp__conpact__queue_compaction({})]);",
    "await Promise.all([maybe && tools.mcp__conpact__queue_compaction({})]);",
    "async function later() { await tools.mcp__conpact__queue_compaction({}); }",
    "async function later() { text(1); await tools.mcp__conpact__queue_compaction({}); }",
    "async function later() { text(1); await Promise.all([tools.mcp__conpact__queue_compaction({})]); }",
    "async function later() { await Promise.all([tools.mcp__conpact__queue_compaction({})]); }",
    "await Promise.all([]);",
    "await Promise.all([); tools.mcp__conpact__queue_compaction({});",
    "await Promise.all([tools.other({]), tools.mcp__conpact__queue_compaction({})]);",
    ") await tools.mcp__conpact__queue_compaction({});",
])
def test_prose_comments_callbacks_and_unawaited_batches_are_not_call_identity(source):
    assert not codex_caller._invokes_conpact(source, "queue_compaction")


@pytest.mark.parametrize("definition", [
    "const later = async () => { await tools.other({}); };",
    "async function later() { await tools.other({}); }",
    "const matches = values.map(x => x.id);",
])
def test_unrelated_completed_function_definitions_do_not_hide_an_actual_call(definition):
    assert codex_caller._invokes_conpact(
        definition + "\ntext(await tools.mcp__conpact__compaction_status({}));",
        "compaction_status")


class PollClock:
    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.slept = []
        self.on_sleep = on_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep()


def context():
    return mcp_tools.Context(environ={"CODEX_HOME": "isolated"}, ppid=41,
                             parent_command="codex app-server")


def test_desktop_waits_for_its_exact_outstanding_call_before_queuing(monkeypatch):
    codex_active.publish([THREAD, OTHER], parent_pid=41)
    clock = PollClock(lambda: codex_active.publish(
        [THREAD, OTHER], calling=[THREAD], parent_pid=41,
        calling_tools={"queue_compaction": [THREAD]}))
    monkeypatch.setattr(codex_caller.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(codex_caller.time, "sleep", clock.sleep)
    monkeypatch.setattr(codex_caller, "recent_threads", lambda ctx: ([], [THREAD, OTHER]))
    result = mcp_tools.call_tool("queue_compaction", {}, context())
    assert result["isError"] is False
    assert result["structuredContent"]["session_id"] == THREAD
    assert compaction.pending_request(THREAD) is not None
    assert compaction.pending_request(OTHER) is None
    assert clock.slept == [codex_caller.CODEX_CALL_POLL_SECONDS]


def test_desktop_waits_for_rollout_persistence_without_accepting_running_identity(monkeypatch):
    codex_active.publish([THREAD, OTHER], parent_pid=41)
    clock = PollClock()
    monkeypatch.setattr(codex_caller.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(codex_caller.time, "sleep", clock.sleep)
    monkeypatch.setattr(codex_caller, "recent_threads", lambda ctx: (
        [THREAD] if clock.slept else [], [THREAD, OTHER]))
    assert codex_caller.bind_desktop(context()) == (THREAD, None)
    assert clock.slept == [codex_caller.CODEX_CALL_POLL_SECONDS]


def test_missing_identity_stops_at_deadline_and_refusal_is_only_for_this_call(monkeypatch):
    codex_active.publish([THREAD], parent_pid=41)
    clock = PollClock()
    monkeypatch.setattr(codex_caller.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(codex_caller.time, "sleep", clock.sleep)
    monkeypatch.setattr(codex_caller, "recent_threads", lambda ctx: ([], [THREAD]))
    result = mcp_tools.call_tool("queue_compaction", {}, context())
    assert result["isError"] is True
    assert clock.now == pytest.approx(codex_caller.CODEX_CALL_SETTLE_SECONDS)
    assert max(clock.slept) <= codex_caller.CODEX_CALL_POLL_SECONDS
    assert "this call only" in result["content"][0]["text"]
    assert compaction.pending_request(THREAD) is None
    codex_active.publish([THREAD], calling=[THREAD], parent_pid=41,
                         calling_tools={"queue_compaction": [THREAD]})
    later = mcp_tools.call_tool("queue_compaction", {}, context())
    assert later["structuredContent"]["session_id"] == THREAD
    assert len(clock.slept) > 0


@pytest.mark.parametrize("foreign", [False, True])
def test_ambiguous_or_foreign_owner_refuses_without_waiting(monkeypatch, foreign):
    codex_active.publish([THREAD, OTHER], calling=[THREAD, OTHER],
                         parent_pid=99 if foreign else 41,
                         calling_tools={"queue_compaction": [THREAD, OTHER]})
    clock = PollClock()
    monkeypatch.setattr(codex_caller.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(codex_caller.time, "sleep", clock.sleep)
    monkeypatch.setattr(codex_caller, "recent_threads", lambda ctx: ([THREAD], [THREAD]))
    assert mcp_tools.call_tool("queue_compaction", {}, context())["isError"] is True
    assert clock.slept == []
    assert compaction.pending_request(THREAD) is None
    assert compaction.pending_request(OTHER) is None


def test_ambiguity_that_arrives_during_settling_stops_without_queuing(monkeypatch):
    codex_active.publish([THREAD, OTHER], parent_pid=41)
    clock = PollClock(lambda: codex_active.publish(
        [THREAD, OTHER], calling=[THREAD, OTHER], parent_pid=41,
        calling_tools={"queue_compaction": [THREAD, OTHER]}))
    monkeypatch.setattr(codex_caller.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(codex_caller.time, "sleep", clock.sleep)
    monkeypatch.setattr(codex_caller, "recent_threads", lambda ctx: ([], [THREAD, OTHER]))
    assert mcp_tools.call_tool("queue_compaction", {}, context())["isError"] is True
    assert clock.slept == [codex_caller.CODEX_CALL_POLL_SECONDS]
    assert compaction.pending_request(THREAD) is None
    assert compaction.pending_request(OTHER) is None
