"""
Regression test for CU-20260920-019 (what an existing session still needs).

The contract, end to end through the real modules, with only the process query
and the session records faked:

  1. The three requirements are reported separately, because they fail
     separately: Remote Control is a per-session switch, the MCP server is a
     child process started with the session's own process, and the Stop hook is
     read at every turn end.
  2. A session with Remote Control off is told so first - without a
     bridgeSessionId nothing can be sent at all, so the MCP tools would refuse
     even when they are loaded. That is the shape the real "Lighthouse" was in.
  3. A session whose process is older than the MCP registration has no server
     under it and is told to reopen the session. That is the shape this very
     session is in.
  4. A hook that has not been seen is never reported as a gap: it writes nothing
     at a quiet turn end.
  5. The check only reads. It never sends to a session or writes state - the
     isolation fixture's guards would fail the test if it did.
"""
import json

import pytest

from conpact import closure_hook, idle_state, session_ready, session_registry


def _record(pid, name, sid, bridge=None):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    body = {"pid": pid, "sessionId": sid, "name": name, "status": "idle"}
    if bridge:
        body["bridgeSessionId"] = bridge
    (session_registry.SESSIONS_DIR / f"{pid}.json").write_text(json.dumps(body), encoding="utf-8")


def _server_process(pid, parent):
    return {"ProcessId": pid, "ParentProcessId": parent,
            "CommandLine": f'"python.exe" "{session_ready.ROOT}/tools/mcp_server.py"'}


@pytest.fixture
def machine(monkeypatch):
    """The real check, with the process query and the logs under our control."""
    def run(processes, log=()):
        monkeypatch.setattr(session_ready, "_capture", lambda argv: json.dumps(list(processes)))
        idle_state.log_path().parent.mkdir(parents=True, exist_ok=True)
        idle_state.log_path().write_text("".join(json.dumps(e) + "\n" for e in log), encoding="utf-8")
        rows = session_ready.readiness(session_registry.load_records(),
                                       session_ready.list_processes(platform="win32"), session_ready.log_entries())
        return {row["name"]: row for row in rows}, "\n".join(session_ready.lines(rows))
    return run


def test_1_the_three_requirements_are_reported_separately(machine):
    _record(100, "ready", "sess-a", bridge="bridge-a")
    rows, _ = machine([_server_process(201, 100)], [{"ts": "2026-09-20T00:16:44Z", "session_id": "sess-a"}])
    assert rows["ready"] == {"name": "ready", "pid": 100, "session_id": "sess-a", "remote_control": True,
                             "mcp": True, "hook": "2026-09-20T00:16:44Z", "actions": [], "ready": True}


def test_2_remote_control_off_is_the_first_thing_to_fix_even_with_the_tools_loaded(machine):
    """Lighthouse: the server was running under it, but nothing could be sent."""
    _record(100, "Lighthouse", "sess-a")
    rows, text = machine([_server_process(201, 100)], [{"ts": "2026-09-20T00:16:44Z", "session_id": "sess-a"}])
    row = rows["Lighthouse"]
    assert (row["mcp"], row["remote_control"], row["ready"]) == (True, False, False)
    assert row["actions"] == [session_ready.REMOTE_CONTROL_FIX]
    assert "Turn Remote Control on" in text


def test_3_a_process_older_than_the_registration_is_told_to_reopen_the_session(machine):
    """This session: Remote Control on, hook running, no server under its pid."""
    _record(100, "conPACT", "sess-a", bridge="bridge-a")
    _record(101, "newer", "sess-b", bridge="bridge-b")
    rows, text = machine([_server_process(201, 101)])
    assert (rows["conPACT"]["mcp"], rows["newer"]["mcp"]) == (False, True)
    assert rows["conPACT"]["actions"] == [session_ready.MCP_FIX]
    assert "1 of 2 sessions ready" in text


def test_4_an_unseen_hook_is_not_a_gap(machine):
    _record(100, "quiet", "sess-a", bridge="bridge-a")
    rows, text = machine([_server_process(201, 100)])
    assert rows["quiet"]["hook"] is None and rows["quiet"]["ready"] is True
    assert "2 of" not in text


def test_5_the_check_only_reads(machine, tmp_path):
    """Nothing is sent, nothing is armed, no state is written - the guards would fire."""
    _record(100, "Lighthouse", "sess-a")
    before = sorted(p.name for p in idle_state.log_path().parent.glob("*")) if \
        idle_state.log_path().parent.exists() else []
    machine([_server_process(201, 100)])
    after = sorted(p.name for p in idle_state.log_path().parent.glob("*"))
    assert after == before or after == ["idle-log.jsonl"]
    assert not closure_hook.LOG_PATH.exists()
