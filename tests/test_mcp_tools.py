"""Tests for conpact.mcp_tools: tool definitions, arguments, results and errors."""
import json

import jsonschema
import pytest

from conpact import compaction, idle_state, mcp_tools

_RECORD = dict(name="Me", pid=4242, status="busy",
               sessionId="sess-mcp", hostSessionId="local_mcp", bridgeSessionId="bridge_mcp")


@pytest.fixture
def ctx(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "4242.json").write_text(json.dumps(_RECORD), encoding="utf-8")
    return mcp_tools.Context(environ={"CLAUDE_CODE_SESSION_ID": "sess-mcp"}, ppid=4242,
                             sessions_dir=sessions, requests_dir=tmp_path / "requests",
                             projects_dir=tmp_path / "projects")


def _transcript(ctx, tokens):
    project = ctx.projects_dir / "C--proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "sess-mcp.jsonl").write_text(json.dumps({"type": "assistant", "message": {
        "model": "m", "usage": {"cache_read_input_tokens": tokens}}}) + "\n", encoding="utf-8")


def _tool(name):
    return next(t for t in mcp_tools.TOOLS if t["name"] == name)


def _check(result, name):
    """Every result is well formed, and a success matches the tool's outputSchema."""
    assert isinstance(result["content"], list) and result["content"][0]["type"] == "text"
    if not result["isError"]:
        jsonschema.validate(result["structuredContent"], _tool(name)["outputSchema"])
        assert json.loads(result["content"][-1]["text"]) == result["structuredContent"]
    return result


QUEUE, CANCEL, STATUS, HOLD = ("queue_compaction", "cancel_compaction",
                               "compaction_status", "hold_idle_toast")


def test_tool_metadata_is_complete():
    for tool in mcp_tools.TOOLS:
        assert tool["name"] in {QUEUE, CANCEL, STATUS, HOLD}
        # Claude Code exposes these as mcp__<server>__<name>, and the server is
        # already `conpact`; a name that repeats it reads twice over
        # (CU-20260922-042).
        assert not tool["name"].startswith("conpact"), tool["name"]
        assert tool["title"] and len(tool["description"]) > 40
        jsonschema.Draft202012Validator.check_schema(tool["inputSchema"])
        jsonschema.Draft202012Validator.check_schema(tool["outputSchema"])
        assert set(tool["annotations"]) == {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
    assert _tool(STATUS)["annotations"]["readOnlyHint"] is True
    assert _tool(QUEUE)["annotations"]["readOnlyHint"] is False
    assert _tool(QUEUE)["annotations"]["idempotentHint"] is True


def test_queue_reports_what_it_queued(ctx):
    _transcript(ctx, 120_000)
    result = _check(mcp_tools.call_tool(QUEUE, {"focus": "keep A\nand B", "min_context_tokens": 100_000}, ctx), QUEUE)
    data = result["structuredContent"]
    assert data == {"queued": True, "replaced": False, "session_id": "sess-mcp",
                    "focus": "keep A and B", "min_context_tokens": 100_000, "context_tokens": 120_000}
    text = result["content"][0]["text"]
    assert "end of this turn" in text and "100000" in text and "120000" in text


def test_queue_twice_replaces_rather_than_stacking(ctx):
    mcp_tools.call_tool(QUEUE, {"focus": "first"}, ctx)
    result = _check(mcp_tools.call_tool(QUEUE, {"focus": "second"}, ctx), QUEUE)
    assert result["structuredContent"]["replaced"] is True
    assert "replaced" in result["content"][0]["text"]
    assert compaction.pending_request("sess-mcp", requests_dir=ctx.requests_dir)["focus"] == "second"
    assert len(list(ctx.requests_dir.iterdir())) == 1


def _in_worktree(ctx, cwd=r"C:\src\conPACT\.claude\worktrees\angry-dirac-98738b"):
    """Put the bound session's record in a throwaway worktree checkout."""
    (ctx.sessions_dir / "4242.json").write_text(json.dumps({**_RECORD, "cwd": cwd}), encoding="utf-8")


def test_queue_refuses_in_a_throwaway_worktree_session(ctx):
    _transcript(ctx, 120_000)
    _in_worktree(ctx)
    result = _check(mcp_tools.call_tool(QUEUE, {"focus": "keep A"}, ctx), QUEUE)
    assert result["structuredContent"] == {"queued": False, "replaced": False, "session_id": "sess-mcp",
                                           "focus": "keep A", "min_context_tokens": None,
                                           "context_tokens": 120_000}
    # Nothing was written, so the Stop hook has nothing to fire.
    assert compaction.pending_request("sess-mcp", requests_dir=ctx.requests_dir) is None
    assert not ctx.requests_dir.exists() or not list(ctx.requests_dir.iterdir())


def test_the_refusal_is_an_answer_not_an_error_to_retry_around(ctx):
    _in_worktree(ctx)
    result = mcp_tools.call_tool(QUEUE, {}, ctx)
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert ".claude/worktrees" in text and "nothing to retry" in text


def test_a_worktree_session_may_still_compact_when_the_guard_is_turned_off(ctx):
    from conpact import settings, spin_off
    _in_worktree(ctx)
    settings.save({spin_off.SETTING: False})
    result = _check(mcp_tools.call_tool(QUEUE, {}, ctx), QUEUE)
    assert result["structuredContent"]["queued"] is True
    assert compaction.pending_request("sess-mcp", requests_dir=ctx.requests_dir) is not None


def test_the_guard_leaves_every_other_tool_alone(ctx):
    _in_worktree(ctx)
    for name in (STATUS, CANCEL, HOLD):
        assert _check(mcp_tools.call_tool(name, {}, ctx), name)["isError"] is False
    assert _check(mcp_tools.call_tool(STATUS, {}, ctx), STATUS)["structuredContent"]["pending"] is False


def test_a_session_outside_a_worktree_is_untouched_by_the_guard(ctx):
    _in_worktree(ctx, cwd=r"C:\src\conPACT")
    assert _check(mcp_tools.call_tool(QUEUE, {}, ctx), QUEUE)["structuredContent"]["queued"] is True


def test_queue_without_measurable_context(ctx):
    result = _check(mcp_tools.call_tool(QUEUE, {}, ctx), QUEUE)
    assert result["structuredContent"]["context_tokens"] is None
    assert result["structuredContent"]["min_context_tokens"] is None


@pytest.mark.parametrize("arguments", [
    {"focus": 5},
    {"focus": "x" * (compaction.MAX_FOCUS_CHARS + 1)},
    {"min_context_tokens": 0},
    {"min_context_tokens": "100k"},
    {"min_context_tokens": True},
    {"min_context_tokens": compaction.MAX_CONTEXT_TOKENS + 1},
    {"unexpected": 1},
])
def test_queue_argument_errors_are_tool_errors(ctx, arguments):
    result = mcp_tools.call_tool(QUEUE, arguments, ctx)
    assert result["isError"] is True
    assert "Nothing was queued" in result["content"][0]["text"]
    assert not ctx.requests_dir.exists()


def test_queue_refuses_a_session_without_remote_control(ctx):
    (ctx.sessions_dir / "4242.json").write_text(json.dumps(dict(_RECORD, bridgeSessionId=None)), encoding="utf-8")
    result = mcp_tools.call_tool(QUEUE, {}, ctx)
    assert result["isError"] is True
    assert "Remote Control is not connected" in result["content"][0]["text"]
    assert "do not retry" in result["content"][0]["text"]


def test_queue_refuses_an_unusable_session_id(ctx):
    bad = dict(_RECORD, sessionId="../x")
    (ctx.sessions_dir / "4242.json").write_text(json.dumps(bad), encoding="utf-8")
    ctx.environ["CLAUDE_CODE_SESSION_ID"] = "../x"
    result = mcp_tools.call_tool(QUEUE, {}, ctx)
    assert result["isError"] is True
    assert not ctx.requests_dir.exists()


def test_cancel_removes_a_queued_request(ctx):
    mcp_tools.call_tool(QUEUE, {}, ctx)
    result = _check(mcp_tools.call_tool(CANCEL, {}, ctx), CANCEL)
    assert result["structuredContent"] == {"cancelled": True, "session_id": "sess-mcp"}
    assert compaction.pending_request("sess-mcp", requests_dir=ctx.requests_dir) is None


def test_cancel_with_nothing_queued(ctx):
    result = _check(mcp_tools.call_tool(CANCEL, {}, ctx), CANCEL)
    assert result["structuredContent"]["cancelled"] is False
    assert "Nothing was queued" in result["content"][0]["text"]


def test_status_says_how_long_the_early_toast_is_held_for(ctx, monkeypatch):
    monkeypatch.setattr(mcp_tools.time, "time", lambda: 1000.0)
    _check(mcp_tools.call_tool(HOLD, {"minutes": 30}, ctx), HOLD)
    result = _check(mcp_tools.call_tool(STATUS, {}, ctx), STATUS)
    assert result["structuredContent"]["hold_minutes_left"] == 30
    assert "held for another 30 minutes" in result["content"][0]["text"]
    _check(mcp_tools.call_tool(HOLD, {"minutes": 0}, ctx), HOLD)
    assert _check(mcp_tools.call_tool(STATUS, {}, ctx), STATUS)["structuredContent"]["hold_minutes_left"] is None


def test_status_counts_a_hold_down_to_nothing_left_before_it_lapses(ctx, monkeypatch):
    """0 minutes left is a hold about to lapse, None is no hold at all: an agent
    deciding whether to hold again has to be able to tell those apart."""
    now = [1000.0]
    monkeypatch.setattr(mcp_tools.time, "time", lambda: now[0])
    longest = mcp_tools.MAX_HOLD_MINUTES

    def left():
        return _check(mcp_tools.call_tool(STATUS, {}, ctx), STATUS)["structuredContent"]["hold_minutes_left"]

    _check(mcp_tools.call_tool(HOLD, {"minutes": longest}, ctx), HOLD)
    assert left() == longest
    now[0] += longest * 60 - 0.5                      # half a second of it to go
    assert left() == 0                                # still held, with nothing left to round up to
    now[0] += 1
    assert left() is None                             # and now it is not held at all


def test_the_hold_names_its_session_and_says_what_it_does(ctx, monkeypatch):
    monkeypatch.setattr(mcp_tools.time, "time", lambda: 1000.0)
    result = _check(mcp_tools.call_tool(HOLD, {"minutes": 5, "reason": "waiting on the test suite"}, ctx), HOLD)
    assert result["structuredContent"] == {"held": True, "minutes": 5, "session_id": "sess-mcp",
                                           "reason": "waiting on the test suite"}
    assert idle_state.read_hold("sess-mcp") == {"until": 1300.0, "reason": "waiting on the test suite"}
    assert "before the prompt cache expires still comes" in result["content"][0]["text"]


def test_the_hold_defaults_to_half_an_hour(ctx, monkeypatch):
    monkeypatch.setattr(mcp_tools.time, "time", lambda: 1000.0)
    result = _check(mcp_tools.call_tool(HOLD, {}, ctx), HOLD)
    assert result["structuredContent"]["minutes"] == mcp_tools.DEFAULT_HOLD_MINUTES
    assert idle_state.read_hold("sess-mcp")["until"] == 1000.0 + mcp_tools.DEFAULT_HOLD_MINUTES * 60


def test_a_session_without_remote_control_can_still_quieten_its_toast(ctx, monkeypatch):
    """It sends nothing, and that session is the one that cannot be told any other way."""
    monkeypatch.setattr(mcp_tools.time, "time", lambda: 1000.0)
    record = {**_RECORD}
    del record["bridgeSessionId"]
    (ctx.sessions_dir / "4242.json").write_text(json.dumps(record), encoding="utf-8")
    assert mcp_tools.call_tool(QUEUE, {}, ctx)["isError"] is True          # queueing still refuses
    result = _check(mcp_tools.call_tool(HOLD, {"minutes": 10}, ctx), HOLD)
    assert result["structuredContent"]["held"] is True
    assert idle_state.read_hold("sess-mcp")["until"] == 1600.0


def test_a_refusal_from_the_hold_says_nothing_was_held(ctx):
    (ctx.sessions_dir / "4242.json").write_text(json.dumps({**_RECORD, "sessionId": "../evil"}),
                                                encoding="utf-8")
    result = mcp_tools.call_tool(HOLD, {}, ctx)
    assert result["isError"] is True
    text = result["content"][0]["text"]
    # The sentence with its neighbours, not a bare `in`: the mutation operator
    # wraps a string as "XX" + v + "XX", and a bare substring check passes for
    # that too, so it could never catch the message being replaced.
    assert " Nothing was held. If the session" in text
    assert "Nothing was queued" not in text


def test_releasing_a_hold_that_was_not_there_is_not_an_error(ctx):
    result = _check(mcp_tools.call_tool(HOLD, {"minutes": 0}, ctx), HOLD)
    assert result["structuredContent"] == {"held": False, "minutes": 0, "session_id": "sess-mcp", "reason": None}
    assert result["content"][0]["text"] == "The early idle toast was not held for this session."


def test_releasing_a_hold_that_was_there_says_so_and_leaves_no_minutes_on_it(ctx):
    _check(mcp_tools.call_tool(HOLD, {"minutes": 30}, ctx), HOLD)
    result = _check(mcp_tools.call_tool(HOLD, {"minutes": 0}, ctx), HOLD)
    assert result["structuredContent"] == {"held": False, "minutes": 0, "session_id": "sess-mcp", "reason": None}
    assert result["content"][0]["text"] == "The early idle toast is no longer held for this session."
    assert idle_state.read_hold("sess-mcp") is None


_MINUTES = "minutes must be a whole number from 0 to 120 (0 releases the hold). Nothing was held."
_REASON = "reason must be text of at most 200 characters. Nothing was held."
_TARGET = ("Unexpected argument(s): session_id. This tool never takes a target session - it always "
           "acts on the session that called it. Nothing was held.")


@pytest.mark.parametrize("arguments, complaint", [
    ({"minutes": -1}, _MINUTES),
    ({"minutes": 121}, _MINUTES),
    ({"minutes": "30"}, _MINUTES),
    ({"minutes": True}, _MINUTES),
    ({"minutes": 2.5}, _MINUTES),
    ({"reason": "x" * 201}, _REASON),
    ({"reason": 7}, _REASON),
    ({"session_id": "other"}, _TARGET),
])
def test_the_hold_refuses_what_it_cannot_do(ctx, arguments, complaint):
    # The whole message, not a substring of it: the mutation operator wraps a string
    # as "XX" + v + "XX", so only an expectation anchored at both ends can fail when
    # the message is replaced.
    result = mcp_tools.call_tool(HOLD, arguments, ctx)
    assert result["isError"] is True and result["content"][0]["text"] == complaint
    assert idle_state.read_hold("sess-mcp") is None


def test_status_reports_pending_request_and_context(ctx):
    _transcript(ctx, 90_000)
    mcp_tools.call_tool(QUEUE, {"focus": "keep A", "min_context_tokens": 50_000}, ctx)
    result = _check(mcp_tools.call_tool(STATUS, {}, ctx), STATUS)
    assert result["structuredContent"] == {"pending": True, "session_id": "sess-mcp", "focus": "keep A",
                                           "min_context_tokens": 50_000, "context_tokens": 90_000,
                                           "hold_minutes_left": None}


def test_status_with_nothing_pending(ctx):
    result = _check(mcp_tools.call_tool(STATUS, {}, ctx), STATUS)
    assert result["structuredContent"] == {"pending": False, "session_id": "sess-mcp", "focus": None,
                                           "min_context_tokens": None, "context_tokens": None,
                                           "hold_minutes_left": None}
    assert "Nothing is queued" in result["content"][0]["text"]


@pytest.mark.parametrize("name", [CANCEL, STATUS])
def test_argumentless_tools_refuse_arguments(ctx, name):
    assert mcp_tools.call_tool(name, {"x": 1}, ctx)["isError"] is True


def test_unknown_tool_is_a_lookup_error(ctx):
    with pytest.raises(mcp_tools.UnknownTool):
        mcp_tools.call_tool("conpact_compact_now", {}, ctx)


def test_context_from_runtime_uses_the_parent_process(monkeypatch):
    """The parent's command line is asked for by the parent's pid. How it is read
    (PowerShell or ps) is codex_caller's, tested there with a stand-in runner, so
    none is started here."""
    import os
    asked = []
    monkeypatch.setattr(mcp_tools.codex_caller, "process_command",
                        lambda pid: asked.append(pid) or "codex app-server")
    ctx = mcp_tools.Context.from_runtime()
    assert ctx.ppid == os.getppid()
    assert asked == [os.getppid()] and ctx.parent_command == "codex app-server"
    assert ctx.sessions_dir is None and ctx.requests_dir is None


# --- The tool contract clients rely on (everything except the prose) --------

_NULLABLE = {"type": ["integer", "null"]}
_EXPECTED_CONTRACT = {
    QUEUE: {
        "inputSchema": {"type": "object", "properties": {
            "focus": {"type": "string", "maxLength": 500},
            "min_context_tokens": {"type": "integer", "minimum": 1, "maximum": 10_000_000}},
            "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "queued": {"type": "boolean"}, "replaced": {"type": "boolean"}, "session_id": {"type": "string"},
            "focus": {"type": "string"}, "min_context_tokens": _NULLABLE, "context_tokens": _NULLABLE},
            "required": ["queued", "replaced", "session_id", "focus", "min_context_tokens", "context_tokens"],
            "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                        "openWorldHint": False},
    },
    CANCEL: {
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "cancelled": {"type": "boolean"}, "session_id": {"type": "string"}},
            "required": ["cancelled", "session_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": False},
    },
    HOLD: {
        "inputSchema": {"type": "object", "properties": {
            "minutes": {"type": "integer", "minimum": 0, "maximum": mcp_tools.MAX_HOLD_MINUTES},
            "reason": {"type": "string", "maxLength": 200}},
            "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "held": {"type": "boolean"}, "minutes": {"type": "integer"}, "session_id": {"type": "string"},
            "reason": {"type": ["string", "null"]}},
            "required": ["held", "minutes", "session_id", "reason"], "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": False},
    },
    STATUS: {
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "pending": {"type": "boolean"}, "session_id": {"type": "string"}, "focus": {"type": ["string", "null"]},
            "min_context_tokens": _NULLABLE, "context_tokens": _NULLABLE,
            "hold_minutes_left": _NULLABLE},
            "required": ["pending", "session_id", "focus", "min_context_tokens", "context_tokens",
                         "hold_minutes_left"],
            "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": False},
    },
}


def _without_prose(value):
    if isinstance(value, dict):
        return {k: _without_prose(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [_without_prose(v) for v in value]
    return value


def test_tool_contract_is_exact():
    assert [t["name"] for t in mcp_tools.TOOLS] == [QUEUE, CANCEL, HOLD, STATUS]
    for tool in mcp_tools.TOOLS:
        assert set(tool) == {"name", "title", "description", "inputSchema", "outputSchema", "annotations"}
        expected = _EXPECTED_CONTRACT[tool["name"]]
        assert _without_prose(tool["inputSchema"]) == expected["inputSchema"]
        assert _without_prose(tool["outputSchema"]) == expected["outputSchema"]
        assert tool["annotations"] == expected["annotations"]


# --- What the model reads -----------------------------------------------------

def _error_text(result):
    assert set(result) == {"content", "isError"} and result["isError"] is True
    assert len(result["content"]) == 1 and result["content"][0]["type"] == "text"
    return result["content"][0]["text"]


def test_queue_text_with_a_minimum_and_a_measured_context(ctx):
    _transcript(ctx, 120_000)
    result = mcp_tools.call_tool(QUEUE, {"min_context_tokens": 100_000}, ctx)
    assert result["content"][0] == {"type": "text", "text": (
        "Compaction queued for this session. It runs at the end of this turn, after your final answer, "
        "only if the context is then at least 100000 tokens. The context is about 120000 tokens now. "
        "Finish your answer normally; do not call this again.")}
    assert result["content"][1]["type"] == "text"
    assert result["structuredContent"]["focus"] == ""


def test_queue_text_when_replacing(ctx):
    mcp_tools.call_tool(QUEUE, {}, ctx)
    result = mcp_tools.call_tool(QUEUE, {}, ctx)
    assert result["content"][0]["text"] == (
        "Compaction queued for this session. It runs at the end of this turn, after your final answer. "
        "This replaced the request that was already queued. Finish your answer normally; do not call this again.")


def test_cancel_texts(ctx):
    assert mcp_tools.call_tool(CANCEL, {}, ctx)["content"][0]["text"] == "Nothing was queued for this session."
    mcp_tools.call_tool(QUEUE, {}, ctx)
    assert mcp_tools.call_tool(CANCEL, {}, ctx)["content"][0]["text"] == "Cancelled the queued compaction."


def test_status_texts(ctx):
    assert mcp_tools.call_tool(STATUS, {}, ctx)["content"][0]["text"] == "Nothing is queued for this session."
    _transcript(ctx, 90_000)
    mcp_tools.call_tool(QUEUE, {}, ctx)
    assert mcp_tools.call_tool(STATUS, {}, ctx)["content"][0]["text"] == (
        "A compaction is queued for the end of this turn. The context is about 90000 tokens.")


@pytest.mark.parametrize("arguments,text", [
    ({"b": 1, "a": 2}, "Unexpected argument(s): a, b. This tool never takes a target session - it always acts "
                       "on the session that called it. Nothing was queued."),
    ({"focus": 7}, "focus must be text of at most 500 characters. Nothing was queued."),
    ({"min_context_tokens": 0}, "min_context_tokens must be a whole number from 1 to 10000000. Nothing was queued."),
])
def test_argument_error_texts(ctx, arguments, text):
    assert _error_text(mcp_tools.call_tool(QUEUE, arguments, ctx)) == text


def test_binding_error_texts(ctx):
    (ctx.sessions_dir / "4242.json").write_text(json.dumps(dict(_RECORD, bridgeSessionId=None)), encoding="utf-8")
    assert _error_text(mcp_tools.call_tool(QUEUE, {}, ctx)) == (
        "Remote Control is not connected for this session, so a compaction could not be delivered. "
        "Nothing was queued. Tell the user; do not retry.")
    ctx.environ["CLAUDE_CODE_SESSION_ID"] = "sess-stale"
    (ctx.sessions_dir / "4242.json").write_text(json.dumps(_RECORD), encoding="utf-8")
    assert _error_text(mcp_tools.call_tool(STATUS, {}, ctx)) == (
        "Could not identify this session (no session record matched the current runtime identity). "
        "Nothing was queued. If the session was cleared or resumed after the conpact MCP server started, "
        "reconnect the server from /mcp and try again; otherwise tell the user and stop.")
    ctx.environ["CLAUDE_CODE_SESSION_ID"] = "../x"
    (ctx.sessions_dir / "4242.json").write_text(json.dumps(dict(_RECORD, sessionId="../x")), encoding="utf-8")
    assert _error_text(mcp_tools.call_tool(CANCEL, {}, ctx)) == (
        "This session's record has no usable session id ('../x'). Nothing was queued. Tell the user and stop.")
