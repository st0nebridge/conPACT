"""Regression test for CU-20260921-029 (D-20260921-028).

A session working in a `.claude/worktrees/...` checkout is a throwaway spin-off:
the desktop app makes one for a suggestion card, a task chip or an agent run
isolated in a worktree, and the user merges and archives it rather than resuming
it. A compaction summary written there is never read, so queuing one spends a
turn and a compaction on nothing.

`mcp_server.INSTRUCTIONS` has asked agents not to since b7db9b1. This anchors the
code-level refusal, which is what holds when the instructions are not followed -
and the setting that turns it off, so the refusal never becomes unappealable.
"""
import json

import pytest

from conpact import compaction, mcp_tools, settings, spin_off

QUEUE = "queue_compaction"
RECORD = dict(name="Spin-off", pid=4242, status="busy", sessionId="sess-wt",
              hostSessionId="local_wt", bridgeSessionId="bridge_wt")


def _ctx(tmp_path, cwd):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "4242.json").write_text(json.dumps({**RECORD, "cwd": cwd}), encoding="utf-8")
    return mcp_tools.Context(environ={"CLAUDE_CODE_SESSION_ID": "sess-wt"}, ppid=4242,
                             sessions_dir=sessions, requests_dir=tmp_path / "requests",
                             projects_dir=tmp_path / "projects")


@pytest.mark.parametrize("cwd", [
    r"C:\src\conPACT\.claude\worktrees\angry-dirac-98738b",
    "C:/src/conPACT/.claude/worktrees/angry-dirac-98738b",
    r"C:\src\conPACT\.claude\worktrees\angry-dirac-98738b\src",
])
def test_a_worktree_session_cannot_queue_a_compaction(tmp_path, cwd):
    ctx = _ctx(tmp_path, cwd)
    result = mcp_tools.call_tool(QUEUE, {"focus": "everything"}, ctx)
    assert result["structuredContent"]["queued"] is False
    assert compaction.pending_request("sess-wt", requests_dir=ctx.requests_dir) is None


@pytest.mark.parametrize("cwd", [
    r"C:\src\conPACT",
    # A desktop scratch workspace is a session the user talks in, so its summary
    # does get read. It is deliberately out of the guard's scope.
    r"C:\Users\<you>\AppData\Roaming\Claude\scratch-workspaces\f5a74ef6\68ffed3c\scratch-2026-09-19",
])
def test_every_other_session_still_can(tmp_path, cwd):
    ctx = _ctx(tmp_path, cwd)
    assert mcp_tools.call_tool(QUEUE, {}, ctx)["structuredContent"]["queued"] is True
    assert compaction.pending_request("sess-wt", requests_dir=ctx.requests_dir) is not None


def test_a_record_with_no_cwd_at_all_is_not_refused(tmp_path):
    """Failing open: an unreadable or older record must not silence a real session."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "4242.json").write_text(json.dumps(RECORD), encoding="utf-8")
    ctx = mcp_tools.Context(environ={"CLAUDE_CODE_SESSION_ID": "sess-wt"}, ppid=4242,
                            sessions_dir=sessions, requests_dir=tmp_path / "requests",
                            projects_dir=tmp_path / "projects")
    assert mcp_tools.call_tool(QUEUE, {}, ctx)["structuredContent"]["queued"] is True


def test_the_setting_turns_the_refusal_off(tmp_path):
    ctx = _ctx(tmp_path, r"C:\Dev\P\.claude\worktrees\w1")
    settings.save({spin_off.SETTING: False})
    assert mcp_tools.call_tool(QUEUE, {}, ctx)["structuredContent"]["queued"] is True
    settings.save({spin_off.SETTING: True})
    assert mcp_tools.call_tool(QUEUE, {}, ctx)["structuredContent"]["queued"] is False


def test_the_instructions_and_the_code_say_the_same_thing():
    """The wording an agent reads and the wording it gets refused with must agree."""
    from conpact import mcp_server
    assert ".claude/worktrees" in mcp_server.INSTRUCTIONS
    assert ".claude/worktrees" in spin_off.REFUSAL
    assert ".claude/worktrees" in next(t for t in mcp_tools.TOOLS if t["name"] == QUEUE)["description"]
