"""
@module conpact.mcp_tools
@description The MCP tools: queue, cancel or inspect a compaction request for the
             session that started this server - a Claude Code session, or the
             Codex thread whose turn is in flight. The target is never an
             argument. It is bound from the runtime only: this process's parent
             (the claude process, whose ~/.claude/sessions/<pid>.json record names
             the live session) corroborated by the CLAUDE_CODE_SESSION_ID Claude
             Code sets for every stdio MCP server. Nothing here talks to the
             bridge or reads the token - the Stop hook fires the request at the
             end of the turn. Transport (JSON-RPC framing) lives in mcp_server.
@input      a tool name, its arguments, and a runtime Context
@output     MCP tool results: text content, structuredContent, isError
@dependencies conpact.codex_caller, conpact.codex_caller_log, conpact.compaction, conpact.context_meter,
              conpact.idle_state, conpact.session_registry, conpact.spin_off, and
              lazily conpact.codex_meter, conpact.codex_threads; stdlib:
              dataclasses, json, os, pathlib, time
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import time

from . import (codex_caller, compaction, context_meter, idle_state,
               session_registry, spin_off)

QUEUE = "queue_compaction"
CANCEL = "cancel_compaction"
STATUS = "compaction_status"
HOLD = "hold_idle_toast"

DEFAULT_HOLD_MINUTES = 30
MAX_HOLD_MINUTES = 120

_NULLABLE_TOKENS = {"type": ["integer", "null"]}
_NO_ARGUMENTS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS = [
    {
        "name": QUEUE,
        "title": "Queue compaction of this session",
        "description": (
            "Queue a real compaction of THIS session - the one you are running in, Claude Code or "
            "Codex - to run after your final answer, when this "
            "turn ends. Use it when the user explicitly asks, or at verified closure of saved "
            "implementation work (a finished feature, fix or build, a completed implementation "
            "multi-step plan, or an explicit wrap-up of the session). "
            "Do not queue after routine questions, read-only investigations, status reports or "
            "intermediate answers, even when the context is large. A finished answer is not an "
            "implementation closure. Eligible implementation work must be verifiably complete and "
            "checkpointed (tests run, changes committed, open threads written down) - as your last action, "
            "once per closure. Then finish your answer normally; do not call it again. Optional focus: one line "
            "of facts telling the summary what to keep - what is done and what is open. Word your own "
            "choices and offers as yours: never attribute them to the user (\"the user's call\", \"the user "
            "runs X\") unless you quote the user, because the summary carries them forward as the user's "
            "rules. Optional min_context_tokens: compact only if the context is "
            "at least that large when the turn ends; otherwise nothing happens. Queuing again replaces the "
            "earlier request. Use cancel_compaction to withdraw it. It answers queued=false, "
            "without queuing anything, in a throwaway spin-off session - one working in a "
            ".claude/worktrees/... checkout - because those are merged and archived rather than resumed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "maxLength": compaction.MAX_FOCUS_CHARS,
                          "description": "The state the summary should keep, as facts (one line). Never word "
                                         "your own choices as the user's decisions."},
                "min_context_tokens": {"type": "integer", "minimum": 1,
                                       "maximum": compaction.MAX_CONTEXT_TOKENS,
                                       "description": "Compact only if the context is at least this many "
                                                      "tokens when the turn ends."},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "queued": {"type": "boolean"},
                "replaced": {"type": "boolean"},
                "session_id": {"type": "string"},
                "focus": {"type": "string"},
                "min_context_tokens": _NULLABLE_TOKENS,
                "context_tokens": _NULLABLE_TOKENS,
            },
            "required": ["queued", "replaced", "session_id", "focus", "min_context_tokens", "context_tokens"],
            "additionalProperties": False,
        },
        # Compaction summarizes the live context: lossy and not undoable once it runs.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": CANCEL,
        "title": "Cancel queued compaction",
        "description": (
            "Withdraw the compaction queued for this session with queue_compaction, before the "
            "turn ends. Safe to call when nothing is queued."
        ),
        "inputSchema": _NO_ARGUMENTS,
        "outputSchema": {
            "type": "object",
            "properties": {"cancelled": {"type": "boolean"}, "session_id": {"type": "string"}},
            "required": ["cancelled", "session_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": HOLD,
        "title": "Hold this session's early idle toast",
        "description": (
            "Stop THIS session's *early* idle toast for a while, because you are mid-run rather than "
            "finished: a long build, a test suite, a review you are waiting on. Between such steps the "
            "session looks idle at every turn end, and the early toast (the one at the idle_seconds "
            "setting) would offer to compact a session you are about to use again. The toast before the "
            "prompt cache expires is NOT held: that one is still worth having, because the context really "
            "is about to go cold. Give minutes (default 30, at most 120); 0 releases the hold. Optional "
            "reason: one line saying what you are waiting on, for the log. It holds only the session that "
            "calls it, it expires by itself, and unlike the toast's own Silence it is not spent by using "
            "the session again. It never sends anything and never compacts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "minimum": 0, "maximum": MAX_HOLD_MINUTES,
                            "description": f"How long to hold the early toast for (0 releases it, "
                                           f"default {DEFAULT_HOLD_MINUTES}, at most {MAX_HOLD_MINUTES})."},
                "reason": {"type": "string", "maxLength": 200,
                           "description": "One line: what this run is waiting on."},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "held": {"type": "boolean"},
                "minutes": {"type": "integer"},
                "session_id": {"type": "string"},
                "reason": {"type": ["string", "null"]},
            },
            "required": ["held", "minutes", "session_id", "reason"],
            "additionalProperties": False,
        },
        # It only ever silences a prompt: it cannot cause a compaction or a send.
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": STATUS,
        "title": "Compaction status",
        "description": (
            "Show whether a compaction is queued for this session (with its focus and minimum), how large "
            "the session's context currently is, in tokens, and how many minutes the early idle toast is "
            "held for. Use it to decide on a min_context_tokens value."
        ),
        "inputSchema": _NO_ARGUMENTS,
        "outputSchema": {
            "type": "object",
            "properties": {
                "pending": {"type": "boolean"},
                "session_id": {"type": "string"},
                "focus": {"type": ["string", "null"]},
                "min_context_tokens": _NULLABLE_TOKENS,
                "context_tokens": _NULLABLE_TOKENS,
                "hold_minutes_left": {"type": ["integer", "null"]},
            },
            "required": ["pending", "session_id", "focus", "min_context_tokens", "context_tokens",
                         "hold_minutes_left"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
]


class UnknownTool(LookupError):
    """No tool by that name - a protocol error, not a tool result."""


class ToolFailure(Exception):
    """A tool could not do its job; the message tells the model what to do next."""


@dataclasses.dataclass
class Context:
    """Where the server looks for its session. Defaults are the live runtime."""

    environ: dict
    ppid: int
    sessions_dir: pathlib.Path | None = None
    requests_dir: pathlib.Path | None = None
    projects_dir: pathlib.Path | None = None
    parent_command: str | None = None
    tool_name: str | None = None
    binding_trace: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def from_runtime(cls) -> "Context":
        from . import runtime_parent
        ppid = runtime_parent.owner(os.getppid())
        return cls(environ=dict(os.environ), ppid=ppid,
                   parent_command=codex_caller.process_command(ppid))


# How this server tells which app started it. Decided from its own environment,
# never by trying one and falling back to the other: on a machine running both
# apps, a Claude server whose binding broke would otherwise bind a Codex thread,
# which is the foreign identity D-20260919-012 exists to refuse.
CLAUDE_MARKERS = (session_registry.ENV_SESSION, session_registry.ENV_HOST)
CODEX_MARKERS = ("CODEX_HOME", "CODEX_CLI_PATH")

CLAUDE, CODEX = "claude", "codex"


def _platform_of(ctx: Context) -> str:
    """Which app started this server. Claude unless only Codex says so."""
    if any(str(ctx.environ.get(k, "")).strip() for k in CLAUDE_MARKERS):
        return CLAUDE
    if any(str(ctx.environ.get(k, "")).strip() for k in CODEX_MARKERS):
        return CODEX
    return CLAUDE                      # the existing path, and its messages


def _bind_codex(ctx: Context, nothing: str) -> dict:
    """The Codex thread that is asking, or a refusal saying why it cannot be told.

    Codex hands an MCP server no thread id of any kind, so the caller is
    identified from what the machine shows - which Codex surface owns this
    server, the sidecar's record and Codex's own rollouts (`codex_caller`) - and
    only when exactly one thread fits. Both surfaces fail closed on ambiguity.
    """
    host = codex_caller.surface(ctx)
    if host in (codex_caller.CODEX_CLI, codex_caller.CODEX_HOST):
        thread_id, why = codex_caller.bind_cli_rollout(ctx)
    else:
        thread_id, why = codex_caller.bind_desktop(ctx)
    if thread_id is None:
        from . import codex_caller_log
        codex_caller_log.record(ctx.ppid, ctx.tool_name, why, ctx.binding_trace)
        raise ToolFailure(
            f"{why} {nothing} This refusal applies to this call only. "
            "Tell the user; do not retry this call blindly or guess another target. "
            "A later closure must obtain a fresh binding.")
    return {"sessionId": thread_id, "platform": CODEX, "surface": host,
            "cwd": None}


def _bind_session(ctx: Context, need_bridge: bool = True, nothing: str = "Nothing was queued.") -> str:
    """The live session id of the claude process that started this server."""
    return _bind_record(ctx, need_bridge, nothing)["sessionId"]


def _bind_record(ctx: Context, need_bridge: bool = True, nothing: str = "Nothing was queued.") -> dict:
    """The session record of the claude process that started this server, its id checked.

    `need_bridge` is False only for a tool that sends nothing: holding a toast
    needs no bridge, and a session whose Remote Control is off is exactly the one
    that cannot be told any other way. The identity checks are the same either way.

    A Codex thread needs no bridge at all: nothing is sent to it, the request is
    executed by the sidecar at the end of the turn, which is the same
    intent/execution split D-20260919-006 sets for Claude.
    """
    if _platform_of(ctx) == CODEX:
        return _bind_codex(ctx, nothing)
    environ = dict(ctx.environ)
    # The OS parent pid, not an inherited variable: that is the process whose
    # session record this server belongs to.
    environ[session_registry.ENV_PID] = str(ctx.ppid)
    resolve = session_registry.resolve_self if need_bridge else session_registry.resolve_self_unbound
    try:
        record = resolve(environ=environ, sessions_dir=ctx.sessions_dir)
    except session_registry.TargetError as exc:
        if "Remote Control is not connected" in str(exc):
            raise ToolFailure(
                "Remote Control is not connected for this session, so a compaction could not be "
                f"delivered. {nothing} Tell the user; do not retry.") from exc
        raise ToolFailure(
            f"Could not identify this session ({exc}). {nothing} If the session "
            "was cleared or resumed after the conpact MCP server started, reconnect the server from "
            "/mcp and try again; otherwise tell the user and stop.") from exc
    session_id = record.get("sessionId")
    if not compaction.is_valid_session_id(session_id):
        raise ToolFailure(f"This session's record has no usable session id ({session_id!r}). "
                          f"{nothing} Tell the user and stop.")
    return record


def _measure(session_id: str, ctx: Context) -> int | None:
    """How big this session is now, read from whichever app's record holds it.

    Claude keeps a transcript; Codex keeps a rollout, and neither reader can
    read the other's file. Measured live: a Codex thread asking for its own
    status got `context_tokens: null` until this branched, which is the one
    number the answer is about.
    """
    if _platform_of(ctx) == CODEX:
        return _measure_codex(session_id, ctx)
    return context_meter.current_context_tokens(
        context_meter.find_transcript(session_id, projects_dir=ctx.projects_dir))


def _measure_codex(thread_id: str, ctx: Context) -> int | None:
    """The thread's context size from its rollout, or None if it cannot be read.

    Imported here rather than at module scope: the MCP server starts on every
    session, and this is needed only by the half of them that are Codex.
    """
    try:
        from . import codex_meter, codex_threads
        for row in codex_threads.threads(ctx.environ) or []:
            if row.get("id") == thread_id:
                return codex_meter.current_context_tokens(row.get("rollout_path"))
    except Exception:
        return None
    return None


def _result(text: str, data: dict) -> dict:
    # Prose for the model first, then the same data as JSON (the spec's
    # backward-compatible copy of structuredContent).
    return {"content": [{"type": "text", "text": text}, {"type": "text", "text": json.dumps(data)}],
            "structuredContent": data, "isError": False}


def _error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _only(arguments: dict, allowed: set, nothing: str = "Nothing was queued.") -> None:
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise ToolFailure(f"Unexpected argument(s): {', '.join(extra)}. This tool never takes a target "
                          f"session - it always acts on the session that called it. {nothing}")


def _queue(arguments: dict, ctx: Context) -> dict:
    _only(arguments, {"focus", "min_context_tokens"})
    focus = arguments.get("focus", "")
    if not isinstance(focus, str) or len(focus) > compaction.MAX_FOCUS_CHARS:
        raise ToolFailure(f"focus must be text of at most {compaction.MAX_FOCUS_CHARS} characters. "
                          "Nothing was queued.")
    try:
        minimum = compaction.validate_min_context_tokens(arguments.get("min_context_tokens"))
    except ValueError as exc:
        raise ToolFailure(f"{exc}. Nothing was queued.") from exc
    record = _bind_record(ctx)
    session_id = record["sessionId"]
    if record.get("surface") == codex_caller.CODEX_CLI:
        raise ToolFailure(
            "conPACT identified this Codex CLI task, but the CLI does not expose its active "
            "app-server stream to the ChatGPT Desktop sidecar, so a turn-end compaction "
            "cannot be delivered safely. Nothing was queued. Tell the user; do not retry.")
    if spin_off.refuses(record.get("cwd")):
        # A refusal, not a failure: the tool worked and the answer is no, so it
        # reads as queued=False rather than as something to retry around.
        return _result(spin_off.REFUSAL,
                       {"queued": False, "replaced": False, "session_id": session_id,
                        "focus": compaction.normalize_focus(focus), "min_context_tokens": minimum,
                        "context_tokens": _measure(session_id, ctx)})
    replaced = compaction.pending_request(session_id, requests_dir=ctx.requests_dir) is not None
    compaction.request_compaction(session_id, focus=focus, min_context_tokens=minimum,
                                  requests_dir=ctx.requests_dir)
    tokens = _measure(session_id, ctx)
    data = {"queued": True, "replaced": replaced, "session_id": session_id,
            "focus": compaction.normalize_focus(focus), "min_context_tokens": minimum, "context_tokens": tokens}
    text = "Compaction queued for this session. It runs at the end of this turn, after your final answer"
    text += (f", only if the context is then at least {minimum} tokens" if minimum is not None else "") + "."
    if tokens is not None:
        text += f" The context is about {tokens} tokens now."
    if replaced:
        text += " This replaced the request that was already queued."
    text += " Finish your answer normally; do not call this again."
    return _result(text, data)


def _cancel(arguments: dict, ctx: Context) -> dict:
    _only(arguments, set())
    session_id = _bind_session(ctx)
    cancelled = compaction.cancel_request(session_id, requests_dir=ctx.requests_dir)
    text = "Cancelled the queued compaction." if cancelled else "Nothing was queued for this session."
    return _result(text, {"cancelled": cancelled, "session_id": session_id})


NOT_HELD = "Nothing was held."


def _hold(arguments: dict, ctx: Context) -> dict:
    _only(arguments, {"minutes", "reason"}, NOT_HELD)
    minutes = arguments.get("minutes", DEFAULT_HOLD_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= MAX_HOLD_MINUTES:
        raise ToolFailure(f"minutes must be a whole number from 0 to {MAX_HOLD_MINUTES} "
                          f"(0 releases the hold). Nothing was held.")
    reason = arguments.get("reason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 200):
        raise ToolFailure("reason must be text of at most 200 characters. Nothing was held.")
    # No bridge needed: this only writes a file, and a session with Remote
    # Control off is the one that most needs to be able to quieten its toast.
    record = _bind_record(ctx, need_bridge=False, nothing=NOT_HELD)
    session_id = record["sessionId"]
    if record.get("surface") == codex_caller.CODEX_CLI:
        raise ToolFailure(
            "conPACT identified this Codex CLI task, but no sidecar observes its turn end, "
            "so no idle toast is armed for it. Nothing was held. Tell the user; do not retry.")
    if minutes == 0:
        released = idle_state.clear_hold(session_id)
        text = ("The early idle toast is no longer held for this session." if released
                else "The early idle toast was not held for this session.")
        return _result(text, {"held": False, "minutes": 0, "session_id": session_id, "reason": None})
    idle_state.set_hold(session_id, until=time.time() + minutes * 60, reason=reason)
    text = (f"Holding this session's early idle toast for {minutes} minutes. The toast before the prompt "
            "cache expires still comes, and nothing is compacted. Call again with minutes 0 to release it.")
    return _result(text, {"held": True, "minutes": minutes, "session_id": session_id, "reason": reason})


def _hold_minutes_left(session_id: str) -> int | None:
    hold = idle_state.read_hold(session_id)
    if hold is None:
        return None
    left = hold["until"] - time.time()
    return max(0, round(left / 60)) if left > 0 else None


def _status(arguments: dict, ctx: Context) -> dict:
    _only(arguments, set())
    session_id = _bind_session(ctx)
    request = compaction.pending_request(session_id, requests_dir=ctx.requests_dir)
    tokens = _measure(session_id, ctx)
    data = {"pending": request is not None, "session_id": session_id,
            "focus": compaction.normalize_focus(request.get("focus")) if request else None,
            "min_context_tokens": request.get("min_context_tokens") if request else None,
            "context_tokens": tokens, "hold_minutes_left": _hold_minutes_left(session_id)}
    text = "A compaction is queued for the end of this turn." if request else "Nothing is queued for this session."
    if tokens is not None:
        text += f" The context is about {tokens} tokens."
    if data["hold_minutes_left"] is not None:
        text += f" The early idle toast is held for another {data['hold_minutes_left']} minutes."
    return _result(text, data)


_HANDLERS = {QUEUE: _queue, CANCEL: _cancel, STATUS: _status, HOLD: _hold}


def call_tool(name: str, arguments: dict, ctx: Context) -> dict:
    """Run one tool. Unknown names raise UnknownTool; everything else is a result."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise UnknownTool(name)
    try:
        from dataclasses import replace
        return handler(arguments, replace(ctx, tool_name=name, binding_trace={}))
    except ToolFailure as exc:
        return _error(str(exc))
