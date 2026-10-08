"""
@module conpact.codex_caller
@description Which Codex surface started this MCP server, and which Codex thread
             is calling it (D-20260922-043, D-20260924-057, D-20260924-058).
             Codex hands an MCP server no thread id, so the caller is found from
             what the machine shows: the server's direct parent (`codex ...
             app-server` is ChatGPT Desktop, or conPACT's own recorded
             app-server behind `conpact-codex`; `codex` or `codex exec` is the
             CLI), the sidecar's record of the turns in flight, and Codex's own
             rollouts. Every source is exact-one-or-none: ambiguity refuses and
             never guesses. A Desktop call binds from the sidecar first and from
             the rollouts only when the sidecar names nobody; a CLI call binds
             from its own recent rollout only, never from the Desktop's sidecar.
             Contributed by Lance Sandino inside mcp_tools, and moved here
             unchanged so that module keeps to the tools themselves.
@input      a context carrying the server's environ, ppid and parent_command
            (mcp_tools.Context); a parent pid, and what runs PowerShell or ps
            (subprocess.run unless a test stands in for it)
@output     a surface (CODEX_CLI, CODEX_DESKTOP, CODEX_HOST or CODEX_UNKNOWN);
            a (thread id or None, why) binding
@dependencies conpact.codex_active, conpact.compaction, and lazily
              conpact.codex_host, conpact.codex_meter, conpact.codex_threads,
              conpact.context_meter; stdlib: pathlib, re, subprocess, sys, time
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time

from . import codex_active, compaction

MAX_CALL_MARKER_RECORDS = 200
CODEX_CALL_SETTLE_SECONDS = 0.5
CODEX_CALL_POLL_SECONDS = 0.05

CODEX_CLI, CODEX_DESKTOP, CODEX_HOST, CODEX_UNKNOWN = (
    "cli", "desktop", "conpact_host", "unknown")


def process_command(pid: int, runner=subprocess.run) -> str | None:
    """One process command line, for distinguishing Codex CLI from app-server.

    Codex does not pass its surface to an MCP child. The direct parent does:
    ChatGPT Desktop runs ``codex ... app-server`` and the CLI runs ``codex`` or
    ``codex exec``. Failure to inspect it stays unknown and takes the existing,
    fail-closed desktop path. ``runner`` is what starts PowerShell or ps, so a
    test reads what it would be asked to run (D-20260920-023).
    """
    try:
        if sys.platform == "win32":
            script = ("(Get-CimInstance Win32_Process -Filter \"ProcessId = "
                      f"{int(pid)}\").CommandLine")
            done = runner(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=5)
        else:
            done = runner(["ps", "-p", str(int(pid)), "-o", "args="],
                          capture_output=True, text=True, timeout=5)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    command = (done.stdout or "").strip()
    return command or None


def surface(ctx) -> str:
    """Which Codex surface directly owns this MCP server."""
    command = (ctx.parent_command or "").lower()
    if not command or "codex" not in command:
        return CODEX_UNKNOWN
    if "app-server" in command:
        # A CLI launched through ``conpact-codex`` is a remote client of the
        # token-protected app-server conPACT already runs.  Its MCP children are
        # direct children of that recorded process, which distinguishes it from
        # ChatGPT Desktop's separate stdio app-server without trusting a caller-
        # supplied environment marker.
        try:
            from . import codex_host
            record = codex_host.read_record()
            if record is not None and record.get("pid") == ctx.ppid:
                return CODEX_HOST
        except Exception:
            pass
        return CODEX_DESKTOP
    return CODEX_CLI


def bind_desktop(ctx) -> tuple[str | None, str | None]:
    """Allow the outstanding call to reach the record before refusing.

    This only repeats read-only identity checks, never a tool operation. An
    explicit ambiguity or foreign owner refuses immediately.
    """
    deadline = time.monotonic() + CODEX_CALL_SETTLE_SECONDS
    while True:
        trace = getattr(ctx, "binding_trace", None)
        if isinstance(trace, dict):
            trace["attempts"] = trace.get("attempts", 0) + 1
        thread_id, why, unsettled = _desktop_once(ctx)
        remaining = deadline - time.monotonic()
        if thread_id is not None or not unsettled or remaining <= 0:
            return thread_id, why
        time.sleep(min(CODEX_CALL_POLL_SECONDS, remaining))


def _desktop_once(ctx):
    """The ChatGPT Desktop caller: the sidecar's record first, then the rollouts.

    Some paths do not publish native MCP calls onto the sidecar's stream.
    Their explicit rollout tool invocation is a second exact-one-or-none source.
    Ambiguous native calls from this MCP parent's process refuse immediately.
    Running turns alone never identify a caller.
    """
    thread_id, why = codex_active.sole_thread(parent_pid=ctx.ppid,
                                             tool_name=getattr(ctx, "tool_name", None))
    trace = getattr(ctx, "binding_trace", None)
    if isinstance(trace, dict):
        native = codex_active.read()
        trace["native"] = ({"parent_pid": native.get("parent_pid"),
            "age_seconds": round(time.time() - native["at"], 3),
            "calling": native.get("calling_tools", {}).get(ctx.tool_name, [])}
            if native and isinstance(native.get("calling_tools", {}), dict) else None)
    if (thread_id is not None or why == codex_active.FOREIGN_PROCESS
            or "will not guess" in str(why)):
        return thread_id, why, False
    calling, running = recent_threads(ctx)
    if len(calling) == 1:
        return calling[0], None, False
    if len(calling) > 1:
        return None, (f"conPACT will not guess which of {len(calling)} recent Codex "
                      "rollouts are calling it at once."), False
    if len(running) == 1:
        why = "conPACT cannot identify the caller without its conPACT tool call."
    elif len(running) > 1:
        why = (f"conPACT will not guess which of {len(running)} recent Codex "
               "rollouts with running turns is asking.")
    return None, why, True


def bind_cli_rollout(ctx) -> tuple[str | None, str]:
    """Bind a CLI call from its rollout, never from the desktop sidecar."""
    calling, running = recent_threads(ctx)
    deadline = time.monotonic() + CODEX_CALL_SETTLE_SECONDS
    while time.monotonic() < deadline and not calling:
        time.sleep(CODEX_CALL_POLL_SECONDS)
        calling, running = recent_threads(ctx)
    if len(calling) == 1:
        return calling[0], ""
    if len(calling) > 1:
        return None, (f"conPACT will not guess which of {len(calling)} recent Codex "
                      "rollouts are calling it at once.")
    if len(running) == 1:
        return None, "conPACT cannot identify the caller without its conPACT tool call."
    if len(running) > 1:
        return None, (f"conPACT will not guess which of {len(running)} recent Codex "
                      "rollouts with running turns is asking.")
    return None, "conPACT cannot find a recent running Codex CLI rollout."


def recent_threads(ctx, clock=time.time) -> tuple[list[str], list[str]]:
    """(calling, running) recent user threads from Codex's own rollouts.

    A crashed process can leave ``task_started`` as the newest marker forever,
    so the marker alone is not an identity. Requiring a fresh rollout gives it
    the same lifetime as the sidecar record. More than one candidate remains an
    ambiguity for the caller to refuse.

    A thread whose rollout is not there records no turn, as an empty rollout
    does, so it is passed over. A fresh rollout that is there but cannot be
    read, or that a reader fails on, might be a second caller: passing it over
    could turn two candidates into one, so the whole scan answers nothing and
    the caller refuses. So does a store that cannot be read.

    For a method-specific binding, the current open ``exec`` call is the
    evidence. Its turn-start marker may be thousands of records older and is
    not needed to identify that call. Closed turns and returned calls are
    rejected by the call reader. The deeper turn scan is diagnostic only,
    retained for callers that do not ask for a particular method.
    """
    try:
        from . import codex_meter, codex_threads
        found = set()
        calling = set()
        method = getattr(ctx, "tool_name", None)
        trace = getattr(ctx, "binding_trace", None)
        if isinstance(trace, dict):
            trace["rollouts"] = []
        for row in codex_threads.threads(ctx.environ) or []:
            thread_id = row.get("id")
            rollout = row.get("rollout_path")
            if (not compaction.is_valid_session_id(thread_id) or not rollout
                    or codex_threads.is_spin_off(row) or codex_threads.is_archived(row)):
                continue
            path = pathlib.Path(rollout)
            try:
                written = path.stat().st_mtime
                if clock() - written > codex_active.MAX_AGE_SECONDS:
                    continue
                # The readers below take a rollout they cannot open for one with
                # no turn marker. Here that would drop a possible caller, so any
                # failure but absence reaches the guard below instead.
                with path.open("rb"):
                    pass
            except (FileNotFoundError, NotADirectoryError):
                continue
            item_trace = {}
            current = rollout_is_calling_conpact(path, method, item_trace)
            if isinstance(trace, dict) and len(trace["rollouts"]) < 32:
                trace["rollouts"].append({"id": thread_id, "calling": current,
                    "age_seconds": round(clock() - written, 3), **item_trace})
            if method:
                # Polling must not spend its short deadline reading older turn
                # history before it gets back to a newly persisted call.
                if current:
                    found.add(thread_id)
                    calling.add(thread_id)
            elif codex_meter.turn_state(path) == codex_meter.RUNNING:
                found.add(thread_id)
                if current:
                    calling.add(thread_id)
        return sorted(calling), sorted(found)
    except Exception:
        return [], []


def recent_running_threads(ctx, clock=time.time) -> list[str]:
    """Compatibility seam: exact callers when present, otherwise running turns."""
    calling, running = recent_threads(ctx, clock)
    return calling or running


def rollout_is_calling_conpact(path: pathlib.Path, tool_name=None, evidence=None) -> bool:
    """Whether the newest code-mode tool lifecycle record invokes conPACT.

    The output record means that invocation has already returned, so an older
    call below it is not evidence for a new one. This is deliberately a narrow
    recognition of Codex's own generated wrapper, not arbitrary prose that
    happens to mention the server name.
    """
    from . import context_meter
    for index, record in enumerate(context_meter.entries_from_end(path)):
        if index >= MAX_CALL_MARKER_RECORDS:
            break
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if record.get("type") == "event_msg" and kind in (
                "task_started", "task_complete", "turn_aborted"):
            _marker_evidence(evidence, record, kind)
            return False
        if record.get("type") != "response_item":
            continue
        if (kind == "message" and payload.get("role") == "assistant"
                and (payload.get("phase") == "final_answer"
                     or payload.get("channel") == "final")):
            _marker_evidence(evidence, record, "final_answer")
            return False
        if kind == "custom_tool_call_output":
            _marker_evidence(evidence, record, kind)
            return False
        if kind == "custom_tool_call":
            _marker_evidence(evidence, record, kind)
            source = payload.get("input")
            return (payload.get("name") == "exec" and isinstance(source, str)
                    and _invokes_conpact(source, tool_name))
    return False


def _marker_evidence(evidence, record, kind):
    """Only record the lifecycle kind and time, never its text or arguments."""
    if isinstance(evidence, dict):
        evidence.update(marker=kind, marker_at=record.get("timestamp"))


def _invokes_conpact(source: str, tool_name=None) -> bool:
    """Literal awaited calls only: quoted diagnostic text is not an invocation.

    Templates are skipped in full; an unrecognised wrapper refuses binding.
    The current method distinguishes a pending status call from a queue call.
    """
    executable = re.sub(
        r"//[^\r\n]*|/\*[\s\S]*?\*/|'(?:\\[\s\S]|[^'\\])*'|"
        r'"(?:\\[\s\S]|[^"\\])*"|`(?:\\[\s\S]|[^`\\])*`',
        " ", source)
    method = re.escape(tool_name) if tool_name else r"[A-Za-z_][A-Za-z_0-9]*"
    call = r"tools\.mcp__conpact__" + method + r"\s*\("
    for match in re.finditer(r"\bawait\s+" + call, executable):
        if _eager_at(executable, match.start()):
            return True
    for batch in re.finditer(r"\bawait\s+Promise\.(?:all|allSettled)\s*\(\s*\[",
                             executable):
        if _eager_at(executable, batch.start()):
            for item in _array_items(executable, batch.end()):
                if re.match(r"\s*(?:await\s+)?" + call, item):
                    return True
    return False


def _array_items(source, start):
    """Top-level elements of one literal array; nested arguments stay together."""
    stack, at = [], start
    pairs = {"(": ")", "[": "]", "{": "}"}
    for index in range(start, len(source)):
        char = source[index]
        if char in pairs:
            stack.append(pairs[char])
        elif char in ")]}":
            if not stack:
                if char == "]":
                    yield source[at:index]
                return
            if stack.pop() != char:
                return
        elif char == "," and not stack:
            yield source[at:index]
            at = index + 1


def _eager_at(source, position):
    """Exclude literal awaits inside function definitions and arrow callbacks.

    This recognizes a narrow executable wrapper, not arbitrary JavaScript.
    Invoked callbacks and aliases can still refuse; they never guess a caller.
    Strings/comments have already been removed before punctuation is examined.
    """
    stack, deferred, functions = [], [], []
    pairs = {"(": ")", "[": "]", "{": "}"}
    for token in re.finditer(r"=>|\bfunction\b|[()\[\]{};,]", source[:position]):
        value = token.group()
        if value == "=>":
            deferred.append((tuple(stack), False))
        elif value == "function":
            functions.append(tuple(stack))
        elif value in pairs:
            parent = tuple(stack)
            stack.append((pairs[value], token.start()))
            if value == "{" and parent in functions:
                functions.remove(parent)
                deferred.append((tuple(stack), True))
        elif value in ")]}":
            if not stack or stack.pop()[0] != value:
                return False
            deferred = [(prefix, block) for prefix, block in deferred
                        if tuple(stack[:len(prefix)]) == prefix]
        else:
            deferred = [(prefix, block) for prefix, block in deferred
                        if block or prefix != tuple(stack)]
    return not deferred
