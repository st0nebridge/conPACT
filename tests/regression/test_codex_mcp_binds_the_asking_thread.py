"""Regression: an MCP tool acts on the thread that called it, or on nothing.

D-20260919-012 requires the MCP server to bind to the session that started it
and to refuse a foreign identity. Codex makes that harder than Claude does: it
hands an MCP server no thread id at all. Three MCP servers codex had spawned
were read on 2026-09-22 and carried only CODEX_HOME, CODEX_CLI_PATH and a pipe
path - nothing that names a thread.

The caller is identified from an outstanding conPACT tool call, with an
owner-matched sidecar record or an explicit rollout invocation. Two rules keep that honest and both are anchored here: the
platform is decided from this server's own environment rather than by trying
Claude and falling back, and an ambiguous or absent call identity refuses
instead of guessing.
"""
import json
import os
import time

import pytest

from conpact import codex_active, codex_caller, codex_host, mcp_tools

THREAD = "019d0000-0000-7000-a000-000000000003"
CODEX_ENV = {"CODEX_HOME": r"C:\Users\x\.codex",
             "CODEX_CLI_PATH": r"C:\shim\codex_sidecar.exe"}


def _ctx(environ, _home=None, parent_command=None):
    """The state home is the package's own (`compaction.STATE_DIR`), which the
    suite isolates per test - there is no second, bespoke way to point at it."""
    return mcp_tools.Context(environ=dict(environ), ppid=1,
                             parent_command=parent_command)


class TestThePlatformIsDecidedNotGuessed:
    def test_a_codex_server_is_recognised_by_its_own_environment(self, tmp_path):
        assert mcp_tools._platform_of(_ctx(CODEX_ENV, tmp_path)) == mcp_tools.CODEX

    @pytest.mark.parametrize("marker", ["CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID"])
    def test_claude_wins_even_with_codex_variables_present(self, marker, tmp_path):
        """A machine runs both apps. A Claude server whose binding broke must
        never fall through and bind a Codex thread - that is the foreign
        identity D-20260919-012 exists to refuse."""
        ctx = _ctx({**CODEX_ENV, marker: "some-id"}, tmp_path)
        assert mcp_tools._platform_of(ctx) == mcp_tools.CLAUDE

    def test_an_environment_naming_neither_stays_on_the_claude_path(self, tmp_path):
        assert mcp_tools._platform_of(_ctx({}, tmp_path)) == mcp_tools.CLAUDE

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_claude_marker_does_not_count_as_claude(self, value, tmp_path):
        ctx = _ctx({**CODEX_ENV, "CLAUDE_CODE_SESSION_ID": value}, tmp_path)
        assert mcp_tools._platform_of(ctx) == mcp_tools.CODEX


class TestItBindsOneThreadOrNone:
    def test_the_single_in_flight_turn_is_the_caller(self, tmp_path):
        codex_active.publish([THREAD], calling=[THREAD], parent_pid=1)
        assert mcp_tools._bind_session(_ctx(CODEX_ENV, tmp_path)) == THREAD

    def test_two_turns_at_once_refuses(self, tmp_path):
        codex_active.publish([THREAD, "other-thread"], calling=[THREAD, "other-thread"], parent_pid=1)
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._bind_session(_ctx(CODEX_ENV, tmp_path))
        assert "will not guess" in str(exc.value)

    def test_no_turn_in_flight_refuses(self, tmp_path):
        codex_active.publish([])
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV, tmp_path))

    def test_no_sidecar_refuses_and_says_so(self, tmp_path):
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._bind_session(_ctx(CODEX_ENV, tmp_path))
        assert "sidecar is not running" in str(exc.value)

    def test_a_refusal_tells_the_agent_not_to_retry(self, tmp_path):
        """A retry cannot help: the ambiguity is about the world, not timing."""
        codex_active.publish([])
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._bind_session(_ctx(CODEX_ENV, tmp_path))
        assert "do not retry" in str(exc.value)


class TestTheRolloutIsTheFallbackWhenTheSidecarMissesATurn:
    """The desktop can write ``task_started`` without forwarding the matching
    app-server notification through the sidecar. That happened live on an old,
    resumed thread while it called ``compaction_status``. The rollout is safe
    evidence when it records the live conPACT invocation, while a running turn alone cannot establish identity."""

    @staticmethod
    def _running(tmp_path, thread_id=THREAD, age=0, calling=False, returned=False):
        path = tmp_path / f"{thread_id}.jsonl"
        records = [{"type": "event_msg", "payload": {
            "type": "task_started", "turn_id": "turn-1"}}]
        if calling:
            records.append({"type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec",
                "input": "const r=await tools.mcp__conpact__compaction_status({});"}})
        if returned:
            records.append({"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "name": "exec", "output": []}})
        path.write_text("".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8")
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return {"id": thread_id, "rollout_path": str(path), "kind": "user",
                "archived": False}

    def test_one_recent_running_rollout_without_a_call_refuses(self, tmp_path, monkeypatch):
        from conpact import codex_threads
        codex_active.publish([])
        row = self._running(tmp_path)
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: [row])
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))

    def test_two_recent_running_rollouts_are_still_refused(self, tmp_path, monkeypatch):
        from conpact import codex_threads
        codex_active.publish([])
        rows = [self._running(tmp_path, THREAD),
                self._running(tmp_path, "019d0000-0000-7000-a000-000000000004")]
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: rows)
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._bind_session(_ctx(CODEX_ENV))
        assert "2 recent Codex rollouts" in str(exc.value)

    def test_the_rollout_invoking_conpact_wins_over_another_running_task(self, tmp_path,
                                                                        monkeypatch):
        from conpact import codex_threads
        codex_active.publish([])
        other = "019d0000-0000-7000-a000-000000000004"
        rows = [self._running(tmp_path, THREAD, calling=True),
                self._running(tmp_path, other)]
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: rows)
        assert mcp_tools._bind_session(_ctx(CODEX_ENV)) == THREAD

    def test_two_rollouts_invoking_conpact_are_refused(self, tmp_path, monkeypatch):
        from conpact import codex_threads
        codex_active.publish([])
        rows = [self._running(tmp_path, THREAD, calling=True),
                self._running(tmp_path, "019d0000-0000-7000-a000-000000000004",
                              calling=True)]
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: rows)
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))

    def test_a_returned_conpact_call_is_not_a_current_caller(self, tmp_path, monkeypatch):
        from conpact import codex_threads
        codex_active.publish([])
        other = "019d0000-0000-7000-a000-000000000004"
        rows = [self._running(tmp_path, THREAD, calling=True, returned=True),
                self._running(tmp_path, other)]
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: rows)
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))

    def test_a_stale_running_marker_is_not_an_identity(self, tmp_path, monkeypatch):
        from conpact import codex_threads
        codex_active.publish([])
        row = self._running(tmp_path, age=codex_active.MAX_AGE_SECONDS + 1)
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: [row])
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))

    def test_sidecar_ambiguity_is_never_overridden_by_the_rollout(self, tmp_path,
                                                                  monkeypatch):
        from conpact import codex_threads
        codex_active.publish([THREAD, "other-thread"], calling=[THREAD, "other-thread"], parent_pid=1)
        row = self._running(tmp_path)
        called = []
        monkeypatch.setattr(codex_threads, "threads",
                            lambda environ=None: called.append(True) or [row])
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))
        assert called == []

    def test_cli_ignores_unrelated_desktop_ambiguity(self, tmp_path, monkeypatch):
        """The CLI does not pass through the desktop sidecar. Its exact rollout
        call is stronger evidence than unrelated desktop turns in that record."""
        from conpact import codex_threads
        codex_active.publish(["desktop-a", "desktop-b"])
        other = "019d0000-0000-7000-a000-000000000004"
        rows = [self._running(tmp_path, THREAD, calling=True),
                self._running(tmp_path, other)]
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: rows)
        assert mcp_tools._bind_session(
            _ctx(CODEX_ENV, parent_command="/Applications/ChatGPT.app/codex exec")) == THREAD

    def test_cli_call_marker_gets_a_bounded_settle_window(self, monkeypatch):
        codex_active.publish(["desktop-a", "desktop-b"])
        seen = iter([([], [THREAD]), ([THREAD], [THREAD])])
        monkeypatch.setattr(codex_caller, "recent_threads", lambda ctx: next(seen))
        monkeypatch.setattr(codex_caller.time, "sleep", lambda seconds: None)
        ticks = iter([0.0, 0.0, 0.1])
        monkeypatch.setattr(codex_caller.time, "monotonic", lambda: next(ticks))
        assert mcp_tools._bind_session(
            _ctx(CODEX_ENV, parent_command="/usr/local/bin/codex")) == THREAD

    def test_cli_queue_refuses_instead_of_stranding_a_request(self, monkeypatch):
        monkeypatch.setattr(codex_caller, "bind_cli_rollout", lambda ctx: (THREAD, ""))
        ctx = _ctx(CODEX_ENV, parent_command="/usr/local/bin/codex")
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._queue({}, ctx)
        assert "Nothing was queued" in str(exc.value)

    def test_cli_idle_hold_refuses_because_no_watcher_is_armed(self, monkeypatch):
        monkeypatch.setattr(codex_caller, "bind_cli_rollout", lambda ctx: (THREAD, ""))
        ctx = _ctx(CODEX_ENV, parent_command="/usr/local/bin/codex")
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._hold({}, ctx)
        assert "Nothing was held" in str(exc.value)

    def test_cli_on_conpact_s_app_server_can_queue_and_hold(self, monkeypatch):
        monkeypatch.setattr(codex_host, "read_record",
                            lambda: {"pid": 1, "port": 5000, "token": "t"})
        monkeypatch.setattr(codex_caller, "bind_cli_rollout", lambda ctx: (THREAD, ""))
        ctx = _ctx(CODEX_ENV, parent_command="codex app-server --listen ws://127.0.0.1:5000")
        queued = mcp_tools._queue({}, ctx)
        held = mcp_tools._hold({"minutes": 1}, ctx)
        assert queued["structuredContent"]["queued"] is True
        assert held["structuredContent"]["held"] is True
        assert codex_caller.surface(ctx) == codex_caller.CODEX_HOST

    @pytest.mark.parametrize(("command", "expected"), [
        ("/Applications/ChatGPT.app/Contents/Resources/codex app-server",
         codex_caller.CODEX_DESKTOP),
        ("/usr/local/bin/codex exec --json", codex_caller.CODEX_CLI),
        (None, codex_caller.CODEX_UNKNOWN),
    ])
    def test_the_parent_command_distinguishes_cli_from_desktop(self, command, expected):
        assert codex_caller.surface(_ctx(CODEX_ENV, parent_command=command)) == expected


class TestItMeasuresTheRightApp:
    """Found live, not in review: a Codex thread asking for its own status got
    `context_tokens: null`, because the measurement read Claude's transcript
    store. Neither app's reader can read the other's file, and the size is the
    one number the answer is about."""

    def test_a_codex_thread_is_measured_from_its_rollout(self, tmp_path, monkeypatch):
        from conpact import codex_meter, codex_threads
        monkeypatch.setattr(codex_threads, "threads",
                            lambda environ=None, **k: [{"id": THREAD,
                                                        "rollout_path": "r.jsonl"}])
        monkeypatch.setattr(codex_meter, "current_context_tokens",
                            lambda path: 32_959 if path == "r.jsonl" else None)

        assert mcp_tools._measure(THREAD, _ctx(CODEX_ENV, tmp_path)) == 32_959

    def test_a_thread_with_no_rollout_yet_measures_as_unknown_not_zero(self, tmp_path,
                                                                       monkeypatch):
        from conpact import codex_threads
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None, **k: [])
        assert mcp_tools._measure(THREAD, _ctx(CODEX_ENV, tmp_path)) is None

    def test_an_unreadable_rollout_does_not_fail_the_tool(self, tmp_path, monkeypatch):
        """The size is a nicety; the answer is still useful without it."""
        from conpact import codex_threads
        def boom(environ=None, **k):
            raise OSError("sessions folder gone")
        monkeypatch.setattr(codex_threads, "threads", boom)
        assert mcp_tools._measure(THREAD, _ctx(CODEX_ENV, tmp_path)) is None

    def test_a_claude_session_is_still_measured_from_its_transcript(self, tmp_path,
                                                                    monkeypatch):
        from conpact import context_meter
        monkeypatch.setattr(context_meter, "find_transcript", lambda s, **k: "t.jsonl")
        monkeypatch.setattr(context_meter, "current_context_tokens",
                            lambda p: 120_000 if p == "t.jsonl" else None)
        ctx = _ctx({"CLAUDE_CODE_SESSION_ID": "s-1"}, tmp_path)
        assert mcp_tools._measure("s-1", ctx) == 120_000


class TestTheCallerIsStatedNotInferred:
    """`item/started` carries an `mcpToolCall` item naming the server and the
    thread. When that server is conPACT, the caller is not the "only turn in
    flight" - it is the thread the app-server said is calling us, and that stays
    exact with any number of turns running at once."""

    def test_the_calling_thread_wins_over_several_in_flight(self, tmp_path):
        codex_active.publish(["other-1", THREAD, "other-2"], calling=[THREAD], parent_pid=1)
        assert mcp_tools._bind_session(_ctx(CODEX_ENV)) == THREAD

    def test_it_is_used_even_when_that_thread_is_not_the_only_one_working(self, tmp_path):
        codex_active.publish(["a", "b", "c", "d"], calling=["c"], parent_pid=1)
        assert mcp_tools._bind_session(_ctx(CODEX_ENV)) == "c"

    def test_two_threads_calling_us_at_once_still_refuses(self, tmp_path):
        codex_active.publish(["a", "b"], calling=["a", "b"], parent_pid=1)
        with pytest.raises(mcp_tools.ToolFailure) as exc:
            mcp_tools._bind_session(_ctx(CODEX_ENV))
        assert "calling it at once" in str(exc.value)

    def test_without_a_stated_caller_it_refuses_the_sole_turn(self, tmp_path):
        """Older sidecars, and any call the notification did not cover."""
        codex_active.publish([THREAD], calling=[], parent_pid=1)
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))

    def test_a_record_with_no_calling_field_cannot_identify_a_caller(self, tmp_path):
        """A record written before this existed must not become unreadable."""
        import json
        path = codex_active.record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"threads": [THREAD], "at": __import__("time").time()}),
                        encoding="utf-8")
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(CODEX_ENV))

    def test_only_calls_to_our_own_server_count(self):
        """A thread calling node_repl is not a thread calling us."""
        import json
        from conpact import codex_turns
        turns = codex_turns.Turns()
        for server, item_id, thread in (("node_repl", "i1", "X"), ("conpact", "i2", "T")):
            turns.note(json.dumps({"method": "item/started", "params": {
                "threadId": thread, "item": {"type": "mcpToolCall", "id": item_id,
                                             "server": server, "tool": "t"}}}).encode())
        assert turns.calling() == {"T"}
