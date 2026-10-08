"""
@module conpact.mcp_server
@description A local stdio MCP server (JSON-RPC 2.0, one message per line) that
             exposes the compaction tools to the Claude Code session that starts
             it. Speaks the legacy-era lifecycle Claude Code 2.1.275 uses
             (initialize, then notifications/initialized): it answers
             2025-11-25 or 2025-06-18 as asked, else its latest. Tools only - no
             resources, prompts or server-initiated requests. stdout carries
             nothing but JSON-RPC responses; faults are never echoed to the
             client. Tool behaviour lives in mcp_tools.
@input      JSON-RPC messages on stdin, one per line
@output     JSON-RPC responses on stdout, one per line; exit code 0 at EOF
@dependencies conpact.home, conpact.mcp_tools, conpact (version); stdlib: json, sys
"""
from __future__ import annotations

import json
import sys

from . import __version__, home, mcp_tools

SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

INSTRUCTIONS = (
    "Queue a real /compact of the calling Claude Code or Codex session when the user explicitly asks, "
    "or at verified closure of saved implementation work: a finished feature, fix or build, "
    "a completed implementation multi-step plan, or an explicit wrap-up of the session. "
    "Do not queue after routine questions, read-only investigations, status reports or intermediate "
    "answers, even when the context is large. A finished answer is not an implementation closure. "
    "A binding refusal applies only to that call, not every future closure. "
    "After integration repair or at a later closure, check compaction_status for a fresh binding. "
    "Never guess another target or blindly resubmit a refused call. Once the work is "
    "verified and committed, call queue_compaction as your last action (discover it in the "
    "tool catalog if deferred), then give your final answer and say it is queued; the "
    "compaction runs after the turn ends. Optional: focus (what the summary should keep) and "
    "min_context_tokens (skip a context smaller than that). cancel_compaction withdraws it; "
    "compaction_status shows what is queued and the current context size. Queue at most "
    "once per closure. Do not queue one at all in a throwaway spin-off session - one working in a "
    ".claude/worktrees/... checkout, started from a suggestion card, a task chip, or an agent run "
    "isolated in a worktree. Those are merged and archived rather than resumed, so the summary is "
    "never read and the compaction spends a turn on nothing; say in one clause that you skipped it "
    "and why. If this session will sit idle mid-run - waiting on a build, a test suite or a "
    "review - call hold_idle_toast first, so the early idle toast does not offer to compact "
    "a session you are about to use again; the toast before the prompt cache expires still comes. "
    "These tools only ever act on the session that called them."
)


def _reply(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _initialize(params: dict) -> dict:
    asked = params.get("protocolVersion")
    version = asked if asked in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "conpact", "title": "conPACT", "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def _tools_call(id_, params: dict, ctx: mcp_tools.Context) -> dict:
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return _error(id_, INVALID_PARAMS, "tools/call needs a tool name and an arguments object")
    try:
        return _reply(id_, mcp_tools.call_tool(name, arguments, ctx))
    except mcp_tools.UnknownTool:
        return _error(id_, INVALID_PARAMS, f"Unknown tool: {name}")
    except Exception as exc:  # a fault: report it without its details
        sys.stderr.write(f"[conpact.mcp_server] {name} failed: {type(exc).__name__}\n")
        return _error(id_, INTERNAL_ERROR, "Internal error")


def handle_message(message: dict, ctx: mcp_tools.Context) -> dict | None:
    """Answer one decoded JSON-RPC message; None when no reply is due."""
    if message.get("jsonrpc") != "2.0":
        return _error(message.get("id") if "id" in message else None, INVALID_REQUEST, "Invalid Request")
    if "method" not in message and ("result" in message or "error" in message):
        return None  # a response to a request of ours; this server sends none
    is_request = "id" in message
    id_ = message.get("id")
    method = message.get("method")
    if not isinstance(method, str) or (is_request and not (id_ is None or isinstance(id_, (str, int)))):
        return _error(id_ if isinstance(id_, (str, int)) else None, INVALID_REQUEST, "Invalid Request")
    if not is_request:
        return None  # notifications (initialized, cancelled, ...) need no reply
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(id_, INVALID_PARAMS, "params must be an object")
    if method == "initialize":
        return _reply(id_, _initialize(params))
    if method == "ping":
        return _reply(id_, {})
    if method == "tools/list":
        return _reply(id_, {"tools": mcp_tools.TOOLS})
    if method == "tools/call":
        return _tools_call(id_, params, ctx)
    if method == "resources/list":
        return _reply(id_, {"resources": []})
    if method == "prompts/list":
        return _reply(id_, {"prompts": []})
    return _error(id_, METHOD_NOT_FOUND, f"Method not found: {method}")


def handle_line(raw: bytes, ctx: mcp_tools.Context) -> dict | None:
    """Decode one line and answer it. Blank lines are ignored."""
    if not raw.strip():
        return None
    try:
        message = json.loads(raw)
    except ValueError:
        return _error(None, PARSE_ERROR, "Parse error")
    if not isinstance(message, dict):
        # Batches were removed in 2025-06-18; anything else is not a message.
        return _error(None, INVALID_REQUEST, "Invalid Request")
    return handle_message(message, ctx)


def serve(instream, outstream, ctx: mcp_tools.Context) -> int:
    """Answer each line of instream on outstream until EOF."""
    for raw in instream:
        reply = handle_line(raw, ctx)
        if reply is not None:
            outstream.write(json.dumps(reply, separators=(",", ":")).encode("utf-8") + b"\n")
            outstream.flush()
    return 0


def main(argv=None) -> int:
    home.migrate()
    return serve(sys.stdin.buffer, sys.stdout.buffer, mcp_tools.Context.from_runtime())


if __name__ == "__main__":
    sys.exit(main())
