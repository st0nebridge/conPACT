"""Tests for conpact.session_ready: what each live session is still missing."""
import json

import pytest

from conpact import session_ready as sr

ROOT = "C:/src/conPACT"


def _record(pid=100, name="Lighthouse", sid="sess-a", bridge=None, **fields):
    return {"pid": pid, "name": name, "sessionId": sid, "status": "idle",
            **({"bridgeSessionId": bridge} if bridge else {}), **fields}


def _server(pid, parent, root=ROOT, script="tools/mcp_server.py"):
    return {"pid": pid, "parent": parent, "command": f'"C:/Python/python.exe" "{root}/{script}"'}


def test_the_root_is_this_checkout():
    """ROOT is what "this checkout's server" is matched against, so it must be the repo."""
    assert (sr.ROOT / "tools" / "mcp_server.py").is_file()
    assert (sr.ROOT / "src" / "conpact" / "session_ready.py").is_file()


# --- which sessions are running this checkout's MCP server -------------------

def test_a_server_started_by_a_session_belongs_to_it():
    assert sr.server_pids([_server(201, 100)], ROOT) == {100: 201}


def test_a_server_from_another_checkout_does_not_count():
    """Only the server this Stop hook and toast would use counts as loaded."""
    assert sr.server_pids([_server(201, 100, root="D:/elsewhere/conPACT")], ROOT) == {}


def test_another_python_child_is_not_a_server():
    other = {"pid": 202, "parent": 100, "command": f'"python.exe" "{ROOT}/tools/settings.py" show'}
    assert sr.server_pids([other], ROOT) == {}


@pytest.mark.parametrize("process", [
    {"pid": None, "parent": 100, "command": f"{ROOT}/tools/mcp_server.py"},
    {"pid": 201, "parent": None, "command": f"{ROOT}/tools/mcp_server.py"},
    {"pid": 201, "parent": 100, "command": None},
    {"pid": 201, "parent": 100},
    "not a process",
])
def test_an_unusable_process_row_is_skipped(process):
    assert sr.server_pids([process], ROOT) == {}


def test_the_match_ignores_case_and_slash_direction():
    windows = {"pid": 201, "parent": 100,
               "command": r'"python.exe" "c:\src\CONPACT\tools\mcp_server.py"'}
    assert sr.server_pids([windows], ROOT) == {100: 201}


def test_the_last_server_listed_wins_when_a_session_somehow_has_two():
    assert sr.server_pids([_server(201, 100), _server(202, 100)], ROOT) == {100: 202}


# --- when the Stop hook last ran for a session -------------------------------

def test_the_newest_log_entry_for_that_session_is_the_hook_evidence():
    entries = [{"ts": "2026-09-20T00:16:44Z", "session_id": "sess-a"},
               {"ts": "2026-09-19T22:23:14Z", "session_id": "sess-a"},
               {"ts": "2026-09-20T01:00:00Z", "session_id": "sess-b"}]
    assert sr.last_hook_run("sess-a", entries) == "2026-09-20T00:16:44Z"
    assert sr.last_hook_run("sess-c", entries) is None


@pytest.mark.parametrize("entry", [{}, {"ts": None, "session_id": "sess-a"}, {"ts": "x"}, "not an entry"])
def test_an_unusable_log_entry_is_ignored(entry):
    assert sr.last_hook_run("sess-a", [entry]) is None


# --- the verdict per session -------------------------------------------------

def _rows(records, processes=(), entries=()):
    return sr.readiness(records, list(processes), list(entries), ROOT)


def test_a_session_with_everything_is_ready():
    [row] = _rows([_record(bridge="bridge-a")], [_server(201, 100)],
                  [{"ts": "2026-09-20T00:16:44Z", "session_id": "sess-a"}])
    assert (row["name"], row["pid"], row["ready"]) == ("Lighthouse", 100, True)
    assert (row["remote_control"], row["mcp"], row["hook"]) == (True, True, "2026-09-20T00:16:44Z")
    assert row["actions"] == []


def test_remote_control_off_is_named_first_because_nothing_works_without_it():
    [row] = _rows([_record(bridge=None)], [_server(201, 100)])
    assert row["ready"] is False
    assert row["actions"][0].startswith("Turn Remote Control on")


def test_a_session_whose_process_predates_the_server_is_told_to_reopen():
    [row] = _rows([_record(bridge="bridge-a")], [])
    assert (row["mcp"], row["ready"]) == (False, False)
    assert row["actions"] == ["Reopen the session so its process loads the MCP server."]


def test_both_gaps_are_reported_together():
    [row] = _rows([_record(bridge=None)], [])
    assert len(row["actions"]) == 2


def test_the_hook_is_reported_as_unseen_rather_than_broken():
    """The hook writes nothing at a quiet turn end, so silence is not failure."""
    [row] = _rows([_record(bridge="bridge-a")], [_server(201, 100)])
    assert row["hook"] is None
    assert row["ready"] is True  # an unseen hook is not a gap to act on


def test_a_long_session_name_is_cut_to_fit_the_column():
    rows = _rows([_record(name="A session with a name far longer than the column allows", bridge="b")])
    assert "  A session with a name far long     100" in "\n".join(sr.lines(rows))


def test_sessions_come_back_in_the_order_their_records_are_read():
    rows = _rows([_record(pid=100, name="A", sid="sess-a", bridge="b"),
                  _record(pid=101, name="B", sid="sess-b")])
    assert [r["name"] for r in rows] == ["A", "B"]


def test_a_record_without_a_pid_is_skipped():
    record = {"name": "odd", "sessionId": "sess-a"}
    assert _rows([record, _record(bridge="b")]) == _rows([_record(bridge="b")])


# --- the printed report ------------------------------------------------------

def test_the_report_names_every_session_and_what_it_needs():
    rows = _rows([_record(bridge="bridge-a"), _record(pid=101, name="Old", sid="sess-b")],
                 [_server(201, 100)], [{"ts": "2026-09-20T00:16:44Z", "session_id": "sess-a"}])
    text = "\n".join(sr.lines(rows))
    assert "Lighthouse" in text and "Old" in text
    assert "1 of 2 sessions ready" in text
    assert "Turn Remote Control on" in text and "Reopen the session" in text


def test_the_whole_report_reads_as_intended():
    """The report is the product here, so it is pinned line for line."""
    rows = _rows([_record(bridge="bridge-a"), _record(pid=101, name="Old", sid="sess-b")],
                 [_server(201, 100)], [{"ts": "2026-09-20T00:16:44Z", "session_id": "sess-a"}])
    assert sr.lines(rows) == [
        "conPACT readiness: 1 of 2 sessions ready",
        "",
        "  session                            pid  remote mcp  hook last seen",
        "  Lighthouse                         100  yes    yes  2026-09-20T00:16:44Z",
        "  Old                                101  NO     NO   -",
        "",
        "  Old:",
        "    - Turn Remote Control on for this session (the switch in its toolbar), "
        "so its record gets a bridgeSessionId.",
        "    - Reopen the session so its process loads the MCP server.",
        "",
        "  The Stop hook needs no action: it is read at every turn end, so it already",
        "  reaches sessions that were open before it was installed. A hook that has not",
        "  been seen yet has simply had nothing to say.",
    ]


def test_a_report_with_nothing_missing_stops_after_the_table():
    rows = _rows([_record(bridge="bridge-a")], [_server(201, 100)])
    assert sr.lines(rows) == [
        "conPACT readiness: 1 of 1 sessions ready",
        "",
        "  session                            pid  remote mcp  hook last seen",
        "  Lighthouse                         100  yes    yes  -",
    ]


def test_the_report_says_so_when_there_is_nothing_to_read():
    assert sr.lines([]) == [
        "conPACT readiness: no live sessions to check.",
        "A session appears here once its process is running and has written its record.",
    ]


def test_a_ready_session_is_not_given_an_action_list():
    text = "\n".join(sr.lines(_rows([_record(bridge="b")], [_server(201, 100)])))
    assert "2 of" not in text and "1 of 1 sessions ready" in text
    assert "Reopen" not in text


# --- reading the real machine (edges) ----------------------------------------

def test_log_entries_come_from_both_of_our_logs(tmp_path, monkeypatch):
    idle = tmp_path / "idle-log.jsonl"
    hook = tmp_path / "hook-log.jsonl"
    idle.write_text(json.dumps({"ts": "1", "session_id": "sess-a"}) + "\nnot json\n", encoding="utf-8")
    hook.write_text(json.dumps({"ts": "2", "session_id": "sess-b"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(sr.idle_state, "log_path", lambda: idle)
    monkeypatch.setattr(sr.closure_hook, "LOG_PATH", hook)
    assert sr.log_entries() == [{"ts": "1", "session_id": "sess-a"}, {"ts": "2", "session_id": "sess-b"}]


def test_a_log_line_that_is_not_an_entry_is_ignored(tmp_path, monkeypatch):
    log = tmp_path / "idle-log.jsonl"
    log.write_text("[1, 2]\n7\n" + json.dumps({"ts": "1", "session_id": "sess-a"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(sr.idle_state, "log_path", lambda: log)
    monkeypatch.setattr(sr.closure_hook, "LOG_PATH", tmp_path / "none.jsonl")
    assert sr.log_entries() == [{"ts": "1", "session_id": "sess-a"}]


def test_missing_logs_are_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sr.idle_state, "log_path", lambda: tmp_path / "nope.jsonl")
    monkeypatch.setattr(sr.closure_hook, "LOG_PATH", tmp_path / "also-nope.jsonl")
    assert sr.log_entries() == []


def test_the_process_list_is_read_with_one_powershell_call(monkeypatch):
    seen = {}

    def runner(argv, **kw):
        seen["argv"] = argv
        return json.dumps([{"ProcessId": 201, "ParentProcessId": 100, "CommandLine": "py mcp_server.py"}])
    assert sr.list_processes(runner, platform="win32") == [{"pid": 201, "parent": 100, "command": "py mcp_server.py"}]
    assert seen["argv"] == [
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%mcp_server%'\" | "
        "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"]


def test_a_single_process_comes_back_as_one_row(monkeypatch):
    """ConvertTo-Json gives an object, not a list, when there is exactly one."""
    one = json.dumps({"ProcessId": 201, "ParentProcessId": 100, "CommandLine": "py mcp_server.py"})
    assert sr.list_processes(lambda argv, **kw: one, platform="win32")[0]["pid"] == 201


@pytest.mark.parametrize("output", ["", "not json", "null", "7"])
def test_an_unreadable_process_list_is_empty_not_an_error(output):
    assert sr.list_processes(lambda argv, **kw: output, platform="win32") == []


def test_the_query_is_captured_as_text_and_cannot_run_forever():
    """A process query that hangs must not hang the report."""
    seen = {}

    class Result:
        stdout = "[]"

    def run(argv, **kw):
        seen.update(kw)
        return Result()
    assert sr._capture(["powershell"], run) == "[]"
    assert seen == {"capture_output": True, "text": True, "timeout": 30}


def test_powershell_failing_is_not_an_error():
    def boom(argv, **kw):
        raise OSError("no powershell here")
    assert sr.list_processes(boom, platform="win32") == []


# --- macOS and Linux: ps ------------------------------------------------------

PS_OUTPUT = """    1     0 /sbin/init
  100     1 /usr/bin/claude --session x
  201   100 /usr/bin/python3 /home/me/conpact/tools/mcp_server.py
  305   100 node /opt/other/server.js
  410   300 /usr/bin/python3 -m conpact.mcp_server
"""


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_off_windows_the_process_list_is_one_ps_call(platform):
    seen = {}

    def runner(argv, **kw):
        seen["argv"] = argv
        return PS_OUTPUT
    assert sr.list_processes(runner, platform=platform) == [
        {"pid": 201, "parent": 100, "command": "/usr/bin/python3 /home/me/conpact/tools/mcp_server.py"},
        {"pid": 410, "parent": 300, "command": "/usr/bin/python3 -m conpact.mcp_server"}]
    assert seen["argv"] == ["ps", "-A", "-o", "pid=,ppid=,args="]


@pytest.mark.parametrize("output", ["", "garbage", "abc def mcp_server", "  12 x mcp_server.py"])
def test_unreadable_ps_lines_are_skipped_not_an_error(output):
    assert sr.list_processes(lambda argv, **kw: output, platform="linux") == []


def test_ps_failing_is_not_an_error():
    def boom(argv, **kw):
        raise OSError("no ps here")
    assert sr.list_processes(boom, platform="darwin") == []


def test_a_ps_row_feeds_the_same_readiness_as_a_powershell_one():
    """The two platforms differ only in how the list is read; what counts as this
    checkout's server under that session is decided once."""
    rows = sr.parse_ps("  201   100 python3 /home/me/conpact/tools/mcp_server.py")
    assert sr.server_pids(rows, root="/home/me/conpact") == {100: 201}


# --- the command ------------------------------------------------------------

def test_main_prints_the_report_and_returns_zero(monkeypatch, capsys):
    """main() uses this checkout's own root, wherever the checkout happens to be."""
    monkeypatch.setattr(sr.session_registry, "load_records", lambda: [_record(bridge="b")])
    monkeypatch.setattr(sr, "list_processes", lambda: [_server(201, 100, root=sr.ROOT)])
    monkeypatch.setattr(sr, "log_entries", lambda: [])
    assert sr.main() == 0
    rows = sr.readiness([_record(bridge="b")], [_server(201, 100, root=sr.ROOT)], [])
    assert capsys.readouterr().out == "\n".join(sr.lines(rows)) + "\n"


def test_main_returns_one_when_a_session_needs_something(monkeypatch, capsys):
    monkeypatch.setattr(sr.session_registry, "load_records", lambda: [_record()])
    monkeypatch.setattr(sr, "list_processes", lambda: [])
    monkeypatch.setattr(sr, "log_entries", lambda: [])
    assert sr.main() == 1
    assert "Turn Remote Control on" in capsys.readouterr().out
