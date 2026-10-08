"""Tests for conpact.mcp_server: JSON-RPC 2.0 framing and MCP lifecycle over stdio."""
import io
import json

import pytest

from conpact import mcp_server as ms
from conpact import mcp_tools


@pytest.fixture
def ctx(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "4242.json").write_text(json.dumps(dict(
        name="Me", pid=4242, sessionId="sess-mcp", hostSessionId="local_mcp",
        bridgeSessionId="bridge_mcp")), encoding="utf-8")
    return mcp_tools.Context(environ={"CLAUDE_CODE_SESSION_ID": "sess-mcp"}, ppid=4242,
                             sessions_dir=sessions, requests_dir=tmp_path / "requests",
                             projects_dir=tmp_path / "projects")


def _req(method, params=None, id_=1):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


@pytest.mark.parametrize("asked,answered", [
    ("2025-11-25", "2025-11-25"),
    ("2025-06-18", "2025-06-18"),
    ("2025-03-26", "2025-11-25"),
    ("2099-01-01", "2025-11-25"),
    (None, "2025-11-25"),
])
def test_initialize_negotiates_the_version(ctx, asked, answered):
    reply = ms.handle_message(_req("initialize", {"protocolVersion": asked, "capabilities": {}}), ctx)
    result = reply["result"]
    assert result["protocolVersion"] == answered
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "conpact"
    from conpact import __version__
    assert result["serverInfo"]["version"] == __version__
    assert result["instructions"].startswith("Queue a real /compact")
    assert "hold_idle_toast" in result["instructions"]   # named where an agent will read it


def test_initialize_without_params(ctx):
    assert ms.handle_message(_req("initialize"), ctx)["result"]["protocolVersion"] == "2025-11-25"


def test_tools_list(ctx):
    tools = ms.handle_message(_req("tools/list"), ctx)["result"]["tools"]
    assert tools == mcp_tools.TOOLS


def test_agent_instructions_exclude_routine_read_only_answers(ctx):
    """Both MCP discovery surfaces must distinguish an answer from saved work."""
    initialized = ms.handle_message(_req("initialize"), ctx)["result"]
    tools = ms.handle_message(_req("tools/list"), ctx)["result"]["tools"]
    queue = next(tool for tool in tools if tool["name"] == "queue_compaction")
    for text in (initialized["instructions"], queue["description"]):
        assert "Do not queue after routine questions, read-only investigations" in text
        assert "even when the context is large" in text
        assert "user explicitly asks" in text
        assert "saved implementation work" in text
        assert "every overall piece of work" not in text
        assert "last step of a multi-step plan" not in text


def test_empty_capability_lists_and_ping(ctx):
    assert ms.handle_message(_req("resources/list"), ctx)["result"] == {"resources": []}
    assert ms.handle_message(_req("prompts/list"), ctx)["result"] == {"prompts": []}
    assert ms.handle_message(_req("ping"), ctx)["result"] == {}


def test_tools_call_runs_the_tool(ctx):
    reply = ms.handle_message(_req("tools/call", {"name": "compaction_status"}), ctx)
    assert reply["id"] == 1
    assert reply["result"]["isError"] is False


def test_tool_errors_are_results_not_protocol_errors(ctx):
    reply = ms.handle_message(_req("tools/call", {"name": "queue_compaction",
                                                  "arguments": {"min_context_tokens": -1}}), ctx)
    assert "error" not in reply
    assert reply["result"]["isError"] is True


@pytest.mark.parametrize("params", [
    {"name": "conpact_compact_now"},
    {},
    {"name": 5},
    {"name": "compaction_status", "arguments": "x"},
    "not an object",
])
def test_bad_tools_call_params_are_invalid_params(ctx, params):
    reply = ms.handle_message(_req("tools/call", params), ctx)
    assert reply["error"]["code"] == -32602


def test_an_internal_fault_does_not_leak_its_message(ctx, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("C:/secret/path details")

    monkeypatch.setattr(mcp_tools, "call_tool", explode)
    reply = ms.handle_message(_req("tools/call", {"name": "compaction_status"}), ctx)
    assert reply["error"] == {"code": -32603, "message": "Internal error"}


def test_unknown_method(ctx):
    assert ms.handle_message(_req("sampling/createMessage"), ctx)["error"]["code"] == -32601


@pytest.mark.parametrize("message", [
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
    {"jsonrpc": "2.0", "method": "tools/list"},  # a notification by shape: no id
    {"jsonrpc": "2.0", "id": 9, "result": {}},  # a response to us; we send no requests
])
def test_notifications_and_responses_get_no_reply(ctx, message):
    assert ms.handle_message(message, ctx) is None


def test_request_id_zero_is_a_request(ctx):
    assert ms.handle_message(_req("ping", id_=0), ctx) == {"jsonrpc": "2.0", "id": 0, "result": {}}


@pytest.mark.parametrize("message", [
    {"id": 1, "method": "ping"},
    {"jsonrpc": "1.0", "id": 1, "method": "ping"},
    {"jsonrpc": "2.0", "id": 1},
    {"jsonrpc": "2.0", "id": 1, "method": 7},
    {"jsonrpc": "2.0", "id": {"x": 1}, "method": "ping"},
])
def test_invalid_requests(ctx, message):
    reply = ms.handle_message(message, ctx)
    assert reply["error"]["code"] == -32600


def test_handle_line_parse_error(ctx):
    reply = ms.handle_line(b"{not json", ctx)
    assert reply == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}


def test_handle_line_refuses_batches_and_non_objects(ctx):
    assert ms.handle_line(b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]', ctx)["error"]["code"] == -32600
    assert ms.handle_line(b'"ping"', ctx)["error"]["code"] == -32600


def test_handle_line_ignores_blank_lines(ctx):
    assert ms.handle_line(b"   \r\n", ctx) is None


def test_serve_answers_each_request_on_its_own_line(ctx):
    lines = [
        json.dumps(_req("initialize", {"protocolVersion": "2025-06-18"}, id_=1)),
        "",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps(_req("ping", id_=2)) + "\r",
        "{broken",
    ]
    out = io.BytesIO()
    assert ms.serve(io.BytesIO(("\n".join(lines) + "\n").encode("utf-8")), out, ctx) == 0
    replies = [json.loads(line) for line in out.getvalue().decode("utf-8").split("\n") if line]
    assert [r.get("id") for r in replies] == [1, 2, None]
    assert replies[2]["error"]["code"] == -32700
    assert b"\r" not in out.getvalue()


def test_main_serves_stdin_to_stdout(monkeypatch):
    class _Std:
        def __init__(self, data=b""):
            self.buffer = io.BytesIO(data)

    stdin, stdout = _Std(json.dumps(_req("ping")).encode() + b"\n"), _Std()
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("sys.stdout", stdout)
    assert ms.main() == 0
    assert json.loads(stdout.buffer.getvalue()) == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_server_info_is_exact(ctx):
    from conpact import __version__
    info = ms.handle_message(_req("initialize", {"protocolVersion": "2025-11-25"}), ctx)["result"]["serverInfo"]
    assert info == {"name": "conpact", "title": "conPACT", "version": __version__}


@pytest.mark.parametrize("message,reply_id", [
    ({"id": 1, "method": "ping"}, 1),
    ({"jsonrpc": "1.0", "id": "a", "method": "ping"}, "a"),
    ({"jsonrpc": "1.0", "method": "ping"}, None),
    ({"jsonrpc": "2.0", "id": 5}, 5),
    ({"jsonrpc": "2.0", "id": {"x": 1}, "method": "ping"}, None),
])
def test_invalid_request_replies_are_exact(ctx, message, reply_id):
    assert ms.handle_message(message, ctx) == {
        "jsonrpc": "2.0", "id": reply_id, "error": {"code": -32600, "message": "Invalid Request"}}


def test_error_responses_from_the_client_are_ignored(ctx):
    assert ms.handle_message({"jsonrpc": "2.0", "id": 9, "error": {"code": 1, "message": "x"}}, ctx) is None


def test_a_request_with_a_stray_result_field_is_still_a_request(ctx):
    assert ms.handle_message({"jsonrpc": "2.0", "id": 3, "method": "ping", "result": {}}, ctx) == {
        "jsonrpc": "2.0", "id": 3, "result": {}}


@pytest.mark.parametrize("message,error", [
    (_req("tools/call", "x"), {"code": -32602, "message": "params must be an object"}),
    (_req("tools/call", {"name": 5}), {"code": -32602, "message": "tools/call needs a tool name and an arguments object"}),
    (_req("tools/call", {"name": "nope"}), {"code": -32602, "message": "Unknown tool: nope"}),
    (_req("sampling/createMessage"), {"code": -32601, "message": "Method not found: sampling/createMessage"}),
])
def test_error_bodies_are_exact(ctx, message, error):
    assert ms.handle_message(message, ctx)["error"] == error


def test_batches_and_non_objects_get_exact_errors(ctx):
    expected = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    assert ms.handle_line(b"[]", ctx) == expected
    assert ms.handle_line(b"5", ctx) == expected


def test_an_internal_fault_is_noted_on_stderr_without_detail(ctx, monkeypatch, capsys):
    def explode(*a, **k):
        raise RuntimeError("C:/secret/path details")

    monkeypatch.setattr(mcp_tools, "call_tool", explode)
    ms.handle_message(_req("tools/call", {"name": "compaction_status"}), ctx)
    assert capsys.readouterr().err == "[conpact.mcp_server] compaction_status failed: RuntimeError\n"


def test_serve_flushes_after_every_reply(ctx):
    class Recording(io.BytesIO):
        def __init__(self):
            super().__init__()
            self.events = []

        def write(self, data):
            self.events.append("write")
            return super().write(data)

        def flush(self):
            self.events.append("flush")

    out = Recording()
    ms.serve(io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'),
             out, ctx)
    assert out.events == ["write", "flush", "write", "flush"]
