"""
Regression test for CU-20260919-009 (local MCP server that queues compaction).

  1. No tool takes a target. The session is bound from the runtime only: this
     server's parent process (the claude process, whose session record names the
     live session) corroborated by the CLAUDE_CODE_SESSION_ID Claude Code sets for
     every stdio MCP server. A stale or foreign identity is refused, not guessed.
  2. The tools never reach the bridge or the token; they only write, remove or
     read the request. Execution stays with the Stop hook.
  3. What the queue tool writes is exactly what the Stop hook claims and fires.
  4. Over real stdio, stdout carries nothing but JSON-RPC responses.
"""
import json
import os
import pathlib
import subprocess
import sys

from conpact import bridge_client, closure_hook, compaction, mcp_tools, token_store

ROOT = pathlib.Path(__file__).resolve().parents[2]
_RECORD = dict(name="Me", pid=4242, status="busy",
               sessionId="sess-mcp", hostSessionId="local_mcp", bridgeSessionId="bridge_mcp")


def _ctx(tmp_path, env_session="sess-mcp", ppid=4242, record=_RECORD):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    (sessions / f"{record['pid']}.json").write_text(json.dumps(record), encoding="utf-8")
    environ = {"CLAUDE_CODE_SESSION_ID": env_session} if env_session else {}
    return mcp_tools.Context(environ=environ, ppid=ppid, sessions_dir=sessions,
                             requests_dir=tmp_path / "requests", projects_dir=tmp_path / "projects")


def _forbid_execution(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("MCP tools must never send or touch the token")

    monkeypatch.setattr(bridge_client, "send_event", boom)
    monkeypatch.setattr(token_store, "get_access_token", boom)


def test_no_tool_takes_a_target():
    allowed = {"queue_compaction": {"focus", "min_context_tokens"},
               "cancel_compaction": set(),
               "hold_idle_toast": {"minutes", "reason"},
               "compaction_status": set()}
    assert {t["name"]: set(t["inputSchema"]["properties"]) for t in mcp_tools.TOOLS} == allowed
    for tool in mcp_tools.TOOLS:
        assert tool["inputSchema"]["additionalProperties"] is False


def test_queue_binds_to_the_parent_process_session(tmp_path, monkeypatch):
    _forbid_execution(monkeypatch)
    ctx = _ctx(tmp_path)
    result = mcp_tools.call_tool("queue_compaction", {"focus": "keep X"}, ctx)
    assert result["isError"] is False
    assert result["structuredContent"]["session_id"] == "sess-mcp"
    assert compaction.pending_request("sess-mcp", requests_dir=ctx.requests_dir)["focus"] == "keep X"


def test_a_target_argument_is_refused(tmp_path, monkeypatch):
    _forbid_execution(monkeypatch)
    ctx = _ctx(tmp_path)
    result = mcp_tools.call_tool("queue_compaction", {"session_id": "someone-else"}, ctx)
    assert result["isError"] is True
    assert not (tmp_path / "requests").exists()


def test_a_stale_session_id_is_refused_not_guessed(tmp_path, monkeypatch):
    # The server started before /clear: its CLAUDE_CODE_SESSION_ID no longer
    # matches the live record for its parent process.
    _forbid_execution(monkeypatch)
    ctx = _ctx(tmp_path, env_session="sess-before-clear")
    result = mcp_tools.call_tool("queue_compaction", {}, ctx)
    assert result["isError"] is True
    assert "reconnect" in result["content"][0]["text"]
    assert not (tmp_path / "requests").exists()


def test_a_foreign_parent_is_refused(tmp_path, monkeypatch):
    _forbid_execution(monkeypatch)
    ctx = _ctx(tmp_path, ppid=9999)
    result = mcp_tools.call_tool("queue_compaction", {}, ctx)
    assert result["isError"] is True
    assert not (tmp_path / "requests").exists()


def test_queued_request_is_what_the_stop_hook_fires(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    mcp_tools.call_tool("queue_compaction", {"focus": "keep X", "min_context_tokens": 10}, ctx)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "assistant", "message": {
        "model": "m", "usage": {"cache_read_input_tokens": 50}}}) + "\n", encoding="utf-8")
    seen = {}

    def fire(**kw):
        seen.update(kw)
        return {"sent": True, "http_status": 200}

    status = closure_hook.run({"session_id": "sess-mcp", "transcript_path": str(transcript)},
                              requests_dir=ctx.requests_dir, compactor=fire)
    assert status["action"] == "compacted"
    assert seen["focus"] == "keep X"
    assert status["min_context_tokens"] == 10


def test_stdio_server_speaks_only_json_rpc(tmp_path):
    home = tmp_path / "home"
    sessions = home / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    # The server's parent is this test process, so this is "its" session record.
    record = dict(_RECORD, pid=os.getpid())
    (sessions / f"{os.getpid()}.json").write_text(json.dumps(record), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("CLAUDE")}
    env.update(USERPROFILE=str(home), HOME=str(home), CLAUDE_CODE_SESSION_ID="sess-mcp")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "queue_compaction",
                    "arguments": {"focus": "keep the plan", "min_context_tokens": 1000}}},
    ]
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "mcp_server.py")],
        input="".join(json.dumps(m) + "\n" for m in messages).encode("utf-8"),
        capture_output=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    lines = proc.stdout.decode("utf-8").splitlines()
    replies = [json.loads(line) for line in lines]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["protocolVersion"] == "2025-11-25"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {t["name"] for t in mcp_tools.TOOLS}
    assert replies[2]["result"]["isError"] is False
    request = json.loads((home / ".conpact" / "requests" / "sess-mcp.json").read_text(encoding="utf-8"))
    assert (request["focus"], request["min_context_tokens"]) == ("keep the plan", 1000)
