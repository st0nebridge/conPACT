"""
@module tests.test_codex_caller
@description conpact.codex_caller called directly: which Codex surface owns the
             MCP server, and which thread is calling it. The binding regression
             file proves the same rules through mcp_tools; these tests pin each
             function's own answer, every refusal's words, and the two bounds
             (the CLI's settle window and the tool-call marker scan). Nothing
             here starts PowerShell or ps, or reads the real clock: the runner,
             the clock, the thread store and the rollouts are all stood in.
@input      conpact.codex_caller, with a stand-in context, a recording runner, a
            scripted clock and hand-written rollouts
@output     assertions on the command process_command asks to run and what it
            makes of the answer, the surface each parent names, and each
            binding and refusal
@dependencies conpact.codex_caller, conpact.codex_active, conpact.codex_host,
              conpact.codex_threads; stdlib: inspect, json, os, subprocess,
              types
"""
import inspect
import json
import os
import subprocess
import types

import pytest

from conpact import codex_active, codex_caller, codex_host, codex_threads

THREAD = "019d0000-0000-7000-a000-000000000003"
OTHER = "019d0000-0000-7000-a000-000000000004"
CALLING = "conPACT will not guess which of 2 recent Codex rollouts are calling it at once."
RUNNING = ("conPACT will not guess which of 2 recent Codex rollouts with running turns "
           "is asking.")
NOTHING = "conPACT cannot find a recent running Codex CLI rollout."
WRITTEN = 1_700_000_000.0     # a whole number of seconds, so every age is exact


def _ctx(parent_command=None, ppid=41):
    """What codex_caller reads of mcp_tools.Context, and nothing else."""
    return types.SimpleNamespace(environ={}, ppid=ppid, parent_command=parent_command)


class _Runner:
    """Stands in for subprocess.run: records what it was asked to run and answers."""

    def __init__(self, stdout="", raises=None):
        self.stdout, self.raises, self.calls = stdout, raises, []

    def __call__(self, argv, **options):
        self.calls.append((argv, options))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")


def _on(monkeypatch, platform):
    """process_command reads sys.platform, which has no argument, so the module's
    own sys is stood in for; the interpreter's stays as it is."""
    monkeypatch.setattr(codex_caller, "sys", types.SimpleNamespace(platform=platform))


class TestProcessCommand:
    ASKED = {"capture_output": True, "text": True, "timeout": 5}

    def test_windows_asks_powershell_for_the_parent_s_command_line(self, monkeypatch):
        _on(monkeypatch, "win32")
        runner = _Runner(stdout="codex.exe app-server --analytics-default-enabled\r\n")
        assert codex_caller.process_command(4242, runner) == \
            "codex.exe app-server --analytics-default-enabled"
        assert runner.calls == [(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             '(Get-CimInstance Win32_Process -Filter "ProcessId = 4242").CommandLine'],
            self.ASKED)]

    @pytest.mark.parametrize("platform", ["linux", "darwin"])
    def test_elsewhere_it_asks_ps(self, monkeypatch, platform):
        _on(monkeypatch, platform)
        runner = _Runner(stdout="/usr/local/bin/codex exec --json\n")
        assert codex_caller.process_command(4242, runner) == "/usr/local/bin/codex exec --json"
        assert runner.calls == [(["ps", "-p", "4242", "-o", "args="], self.ASKED)]

    @pytest.mark.parametrize("platform", ["win32", "linux"])
    def test_a_pid_that_is_not_a_number_never_reaches_the_command(self, monkeypatch, platform):
        """The pid is written into a PowerShell script, so it is made an integer
        first; anything else is no command, and nothing is run."""
        _on(monkeypatch, platform)
        runner = _Runner(stdout="codex")
        assert codex_caller.process_command('1").CommandLine; Remove-Item x #', runner) is None
        assert runner.calls == []

    @pytest.mark.parametrize("stdout", ["", "  \r\n", None])
    def test_an_empty_answer_is_no_command(self, monkeypatch, stdout):
        _on(monkeypatch, "win32")
        assert codex_caller.process_command(4242, _Runner(stdout=stdout)) is None

    @pytest.mark.parametrize("failure", [
        OSError("powershell is not on PATH"),
        subprocess.TimeoutExpired("powershell", 5),
        subprocess.CalledProcessError(1, "ps"),
    ])
    def test_a_lookup_that_fails_is_no_command(self, monkeypatch, failure):
        _on(monkeypatch, "win32")
        assert codex_caller.process_command(4242, _Runner(raises=failure)) is None

    def test_the_real_runner_is_subprocess_run(self):
        """Standing it in changes nothing the server does when nothing is given."""
        default = inspect.signature(codex_caller.process_command).parameters["runner"].default
        assert default is subprocess.run


class TestSurface:
    @pytest.mark.parametrize(("command", "expected"), [
        (None, codex_caller.CODEX_UNKNOWN),
        ("", codex_caller.CODEX_UNKNOWN),
        ("/bin/zsh -l", codex_caller.CODEX_UNKNOWN),
        (r'"C:\Program Files\WindowsApps\OpenAI.ChatGPT\app\resources\CODEX.EXE" APP-SERVER',
         codex_caller.CODEX_DESKTOP),
        ("/usr/local/bin/codex", codex_caller.CODEX_CLI),
        ("/usr/local/bin/codex exec --json", codex_caller.CODEX_CLI),
    ])
    def test_the_direct_parent_names_the_surface(self, command, expected):
        assert codex_caller.surface(_ctx(command)) == expected

    def test_conpact_s_own_recorded_app_server_is_the_host(self):
        codex_host.write_record(5000, 41, "token")
        ctx = _ctx("codex app-server --listen ws://127.0.0.1:5000", ppid=41)
        assert codex_caller.surface(ctx) == codex_caller.CODEX_HOST

    def test_an_app_server_conpact_did_not_start_is_the_desktop(self):
        """A record exists, but for another process: this server's parent is
        ChatGPT Desktop's own app-server, not ours."""
        codex_host.write_record(5000, 41, "token")
        ctx = _ctx("codex app-server --listen ws://127.0.0.1:5000", ppid=99)
        assert codex_caller.surface(ctx) == codex_caller.CODEX_DESKTOP

    def test_with_no_record_an_app_server_is_the_desktop(self):
        assert codex_caller.surface(_ctx("codex app-server", ppid=41)) == \
            codex_caller.CODEX_DESKTOP

    def test_a_record_that_cannot_be_read_is_the_desktop(self, monkeypatch):
        def broken():
            raise RuntimeError("record unreadable")
        monkeypatch.setattr(codex_host, "read_record", broken)
        assert codex_caller.surface(_ctx("codex app-server", ppid=41)) == \
            codex_caller.CODEX_DESKTOP

    def test_the_four_surfaces_are_told_apart(self):
        assert len({codex_caller.CODEX_CLI, codex_caller.CODEX_DESKTOP,
                    codex_caller.CODEX_HOST, codex_caller.CODEX_UNKNOWN}) == 4


def _scan(monkeypatch, calling, running):
    """Stand in for the rollout scan with one fixed answer, counting the calls."""
    asked = []
    monkeypatch.setattr(codex_caller, "recent_threads",
                        lambda ctx: asked.append(ctx) or (list(calling), list(running)))
    return asked


class TestBindDesktop:
    def test_the_sidecar_s_single_call_binds_without_reading_rollouts(self, monkeypatch):
        codex_active.publish([THREAD], calling=[THREAD], parent_pid=41)
        asked = _scan(monkeypatch, [OTHER], [OTHER])
        assert codex_caller.bind_desktop(_ctx("codex app-server")) == (THREAD, None)
        assert asked == []

    def test_sidecar_ambiguity_refuses_without_reading_rollouts(self, monkeypatch):
        codex_active.publish([THREAD, OTHER], calling=[THREAD, OTHER], parent_pid=41)
        asked = _scan(monkeypatch, [THREAD], [THREAD])
        thread_id, why = codex_caller.bind_desktop(_ctx("codex app-server"))
        assert thread_id is None
        assert why == "conPACT will not guess which of 2 threads calling it at once is asking."
        assert asked == []

    def test_one_rollout_calling_conpact_binds_among_several_running(self, monkeypatch):
        codex_active.publish([])
        _scan(monkeypatch, [THREAD], [THREAD, OTHER])
        assert codex_caller.bind_desktop(_ctx("codex app-server"))[0] == THREAD

    def test_two_rollouts_calling_conpact_refuse(self, monkeypatch):
        codex_active.publish([])
        _scan(monkeypatch, [THREAD, OTHER], [THREAD, OTHER])
        assert codex_caller.bind_desktop(_ctx("codex app-server")) == (None, CALLING)

    def test_with_no_caller_the_one_running_rollout_refuses(self, monkeypatch):
        codex_active.publish([])
        _scan(monkeypatch, [], [OTHER])
        assert codex_caller.bind_desktop(_ctx("codex app-server"))[0] is None

    def test_with_no_caller_two_running_rollouts_refuse(self, monkeypatch):
        codex_active.publish([])
        _scan(monkeypatch, [], [THREAD, OTHER])
        assert codex_caller.bind_desktop(_ctx("codex app-server")) == (None, RUNNING)

    def test_nothing_anywhere_keeps_the_sidecar_s_reason(self, monkeypatch):
        monkeypatch.setattr(codex_caller, "time", _Clock(0.0, 1.0))
        asked = _scan(monkeypatch, [], [])
        thread_id, why = codex_caller.bind_desktop(_ctx("codex app-server"))
        assert thread_id is None
        assert "the sidecar is not running" in why
        assert len(asked) == 1


class _Clock:
    """Stands in for codex_caller's time. monotonic() answers from a script; once
    the script has run out it answers "long after the window" and counts the
    extra reading, for the test to check. sleep() only records what it was asked
    for. Nothing here asserts: the test does, afterwards."""

    def __init__(self, *readings):
        self.readings, self.slept, self.overrun = list(readings), [], 0

    def monotonic(self):
        if self.readings:
            return self.readings.pop(0)
        self.overrun += 1
        return float("inf")

    def sleep(self, seconds):
        self.slept.append(seconds)


class _Scan:
    """Stands in for the rollout scan: one (calling, running) answer per call, and
    counts every call. Once the script has run out it answers with a caller no
    test expects, which ends any wait whatever the clock says, so code that reads
    the rollouts too often fails its test instead of looping."""

    UNSCRIPTED = "a caller no test expects"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, ctx):
        self.calls += 1
        return self.answers.pop(0) if self.answers else ([self.UNSCRIPTED], [])


def _stand_in(monkeypatch, clock, *answers):
    monkeypatch.setattr(codex_caller, "time", clock)
    scan = _Scan(*answers)
    monkeypatch.setattr(codex_caller, "recent_threads", scan)
    return scan


class TestBindCliRollout:
    POLL = codex_caller.CODEX_CALL_POLL_SECONDS

    def test_a_caller_already_recorded_binds_without_waiting(self, monkeypatch):
        clock = _Clock(0.0, 0.0)
        scan = _stand_in(monkeypatch, clock, ([THREAD], [THREAD, OTHER]))
        assert codex_caller.bind_cli_rollout(_ctx("codex")) == (THREAD, "")
        assert (clock.slept, scan.calls) == ([], 1)

    def test_it_waits_for_a_call_marker_that_lands_a_moment_later(self, monkeypatch):
        """The CLI writes its tool-call record around when it calls us, so the
        caller is looked for again until the settle window closes."""
        clock = _Clock(0.0, 0.1, 0.2, 0.3)
        scan = _stand_in(monkeypatch, clock, ([], [THREAD, OTHER]), ([], [THREAD, OTHER]),
                         ([THREAD], [THREAD, OTHER]))
        assert codex_caller.bind_cli_rollout(_ctx("codex")) == (THREAD, "")
        assert (clock.slept, scan.calls, clock.overrun) == ([self.POLL, self.POLL], 3, 0)

    def test_the_wait_ends_when_the_settle_window_does(self, monkeypatch):
        start = 100.0
        window = codex_caller.CODEX_CALL_SETTLE_SECONDS
        clock = _Clock(start, start + window * 0.4, start + window * 0.8, start + window)
        scan = _stand_in(monkeypatch, clock, *[([], [THREAD, OTHER])] * 3)
        assert codex_caller.bind_cli_rollout(_ctx("codex")) == (None, RUNNING)
        assert (clock.slept, scan.calls, clock.readings, clock.overrun) ==             ([self.POLL, self.POLL], 3, [], 0)

    @pytest.mark.parametrize(("calling", "running", "expected"), [
        ([THREAD, OTHER], [THREAD, OTHER], (None, CALLING)),
        ([], [OTHER], (None, "conPACT cannot identify the caller without its conPACT tool call.")),
        ([], [THREAD, OTHER], (None, RUNNING)),
        ([], [], (None, NOTHING)),
    ])
    def test_after_the_window_it_binds_one_or_says_why_not(self, monkeypatch, calling,
                                                            running, expected):
        scan = _stand_in(monkeypatch, _Clock(0.0, 1.0), (calling, running))
        assert codex_caller.bind_cli_rollout(_ctx("codex")) == expected
        assert scan.calls == 1

    def test_it_never_reads_the_desktop_sidecar(self, monkeypatch):
        """D-20260924-057: a CLI call binds from its own rollout only."""
        codex_active.publish([OTHER])
        _stand_in(monkeypatch, _Clock(0.0, 1.0), ([], []))
        assert codex_caller.bind_cli_rollout(_ctx("codex")) == (None, NOTHING)


def _rollout(tmp_path, name, *records):
    path = tmp_path / f"{name}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8")
    return path


STARTED = {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}}
COMPLETE = {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}}
TOKENS = {"type": "event_msg", "payload": {"type": "token_count", "info": None}}


def _call(source="const r=await tools.mcp__conpact__compaction_status({});", name="exec"):
    return {"type": "response_item", "payload": {"type": "custom_tool_call", "name": name,
                                                 "input": source}}


RETURNED = {"type": "response_item", "payload": {"type": "custom_tool_call_output",
                                                 "name": "exec", "output": []}}


class TestRecentThreads:
    @staticmethod
    def _row(tmp_path, thread_id=THREAD, *records):
        """A thread row whose rollout was last written at WRITTEN."""
        path = _rollout(tmp_path, thread_id, *(records or (STARTED,)))
        os.utime(path, (WRITTEN, WRITTEN))
        return {"id": thread_id, "rollout_path": str(path), "kind": "user",
                "archived": False}

    @staticmethod
    def _store(monkeypatch, *rows):
        monkeypatch.setattr(codex_threads, "threads", lambda environ=None: list(rows))

    @staticmethod
    def _now(age=0.0):
        """A clock `age` seconds after every rollout here was last written."""
        return lambda: WRITTEN + age

    def test_a_running_rollout_calling_conpact_is_a_caller(self, tmp_path, monkeypatch):
        row = self._row(tmp_path, THREAD, STARTED, _call())
        self._store(monkeypatch, row)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([THREAD], [THREAD])

    def test_a_running_rollout_that_is_not_calling_is_only_running(self, tmp_path,
                                                                   monkeypatch):
        row = self._row(tmp_path)
        self._store(monkeypatch, row)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([], [THREAD])

    @pytest.mark.parametrize("records", [(STARTED, COMPLETE), (TOKENS,)],
                             ids=["between turns", "no turn marker"])
    def test_a_rollout_with_no_turn_running_is_neither(self, tmp_path, monkeypatch, records):
        row = self._row(tmp_path, THREAD, *records)
        self._store(monkeypatch, row)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([], [])

    def test_a_rollout_is_recent_up_to_the_sidecar_s_own_age_limit(self, tmp_path,
                                                                   monkeypatch):
        row = self._row(tmp_path)
        self._store(monkeypatch, row)
        limit = codex_active.MAX_AGE_SECONDS
        assert codex_caller.recent_threads(_ctx(), self._now(limit)) == ([], [THREAD])
        assert codex_caller.recent_threads(_ctx(), self._now(limit + 1)) == ([], [])

    @pytest.mark.parametrize("fields", [
        {"id": None}, {"id": "../escape"}, {"rollout_path": None}, {"rollout_path": ""},
        {"kind": "subagent"}, {"kind": "guardian_review"}, {"archived": True},
    ], ids=["no id", "an id that is not one", "no rollout", "an empty rollout path",
            "a subagent", "a guardian review", "archived"])
    def test_a_thread_that_cannot_be_the_caller_is_passed_over(self, tmp_path, monkeypatch,
                                                               fields):
        """Each of these has a fresh rollout with a conPACT call in flight, so only
        the row itself rules it out; the user's thread after it is still found."""
        passed_over = {**self._row(tmp_path, OTHER, STARTED, _call()), **fields}
        user = self._row(tmp_path, THREAD, STARTED, _call())
        self._store(monkeypatch, passed_over, user)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([THREAD], [THREAD])

    def test_every_candidate_is_returned_in_a_stable_order(self, tmp_path, monkeypatch):
        rows = [self._row(tmp_path, OTHER, STARTED, _call()),
                self._row(tmp_path, THREAD, STARTED, _call())]
        self._store(monkeypatch, *rows)
        assert codex_caller.recent_threads(_ctx(), self._now()) == \
            ([THREAD, OTHER], [THREAD, OTHER])

    def test_the_server_s_own_environment_chooses_the_store(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(codex_threads, "threads",
                            lambda environ=None: seen.append(environ) or [])
        ctx = types.SimpleNamespace(environ={"CODEX_HOME": str(tmp_path)}, ppid=41,
                                    parent_command=None)
        assert codex_caller.recent_threads(ctx) == ([], [])
        assert seen == [{"CODEX_HOME": str(tmp_path)}]

    def test_a_store_that_cannot_be_read_is_no_candidates(self, monkeypatch):
        def broken(environ=None):
            raise OSError("state database locked")
        monkeypatch.setattr(codex_threads, "threads", broken)
        assert codex_caller.recent_threads(_ctx()) == ([], [])

    @pytest.mark.parametrize("where", ["gone.jsonl", "a-file/under-a-file.jsonl"],
                             ids=["no such file", "a path through a file"])
    def test_a_thread_whose_rollout_is_not_there_is_passed_over(self, tmp_path, monkeypatch,
                                                                where):
        """No rollout records no turn, as an empty one does: it is no candidate,
        and the thread that is calling is still found."""
        (tmp_path / "a-file").write_text("", encoding="utf-8")
        user = self._row(tmp_path, THREAD, STARTED, _call())
        self._store(monkeypatch, {**user, "id": OTHER, "rollout_path": str(tmp_path / where)},
                    user)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([THREAD], [THREAD])

    def test_a_rollout_that_goes_between_its_age_and_its_reading_is_passed_over(
            self, tmp_path, monkeypatch):
        going = self._row(tmp_path, OTHER, STARTED, _call())
        user = self._row(tmp_path, THREAD, STARTED, _call())
        self._store(monkeypatch, going, user)
        removed = []

        def clock():
            """Read once per row, after its rollout's age and before it is opened."""
            if not removed:
                os.remove(going["rollout_path"])
                removed.append(going["rollout_path"])
            return WRITTEN
        assert codex_caller.recent_threads(_ctx(), clock) == ([THREAD], [THREAD])
        assert removed == [going["rollout_path"]]

    def test_a_recent_rollout_that_cannot_be_opened_refuses_the_scan(self, tmp_path,
                                                                     monkeypatch):
        """It is there and recent, so it may be a second caller: passing it over
        would turn two candidates into one. A folder stands in for a file that
        cannot be opened, on every platform."""
        unreadable = tmp_path / "unreadable.jsonl"
        unreadable.mkdir()
        os.utime(unreadable, (WRITTEN, WRITTEN))
        user = self._row(tmp_path, THREAD, STARTED, _call())
        self._store(monkeypatch, {**user, "id": OTHER, "rollout_path": str(unreadable)}, user)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([], [])

    def test_an_old_rollout_that_cannot_be_opened_is_passed_over(self, tmp_path, monkeypatch):
        unreadable = tmp_path / "unreadable.jsonl"
        unreadable.mkdir()
        os.utime(unreadable, (WRITTEN, WRITTEN))
        user = self._row(tmp_path, THREAD, STARTED, _call())
        os.utime(user["rollout_path"], (WRITTEN + 60, WRITTEN + 60))
        self._store(monkeypatch, {**user, "id": OTHER, "rollout_path": str(unreadable)}, user)
        clock = self._now(codex_active.MAX_AGE_SECONDS + 30)
        assert codex_caller.recent_threads(_ctx(), clock) == ([THREAD], [THREAD])

    @pytest.mark.parametrize("reader", ["turn_state", "rollout_is_calling_conpact"])
    def test_a_rollout_its_readers_fail_on_refuses_the_scan(self, tmp_path, monkeypatch,
                                                            reader):
        """What that rollout records is unknown, so it may be a second caller."""
        from conpact import codex_meter
        failing = self._row(tmp_path, OTHER, STARTED, _call())
        user = self._row(tmp_path, THREAD, STARTED, _call())
        self._store(monkeypatch, failing, user)
        owner = codex_meter if reader == "turn_state" else codex_caller
        real = getattr(owner, reader)
        asked = []

        def fails_on_one(path, *args):
            asked.append(str(path))
            if str(path) == failing["rollout_path"]:
                raise RuntimeError("a record this reader cannot handle")
            return real(path, *args)
        monkeypatch.setattr(owner, reader, fails_on_one)
        assert codex_caller.recent_threads(_ctx(), self._now()) == ([], [])
        assert failing["rollout_path"] in asked


class TestRecentRunningThreads:
    @pytest.mark.parametrize(("calling", "running", "expected"), [
        ([THREAD], [THREAD, OTHER], [THREAD]),
        ([], [THREAD, OTHER], [THREAD, OTHER]),
        ([], [], []),
    ])
    def test_callers_when_there_are_any_otherwise_running_turns(self, monkeypatch, calling,
                                                                running, expected):
        clocks = []
        monkeypatch.setattr(codex_caller, "recent_threads",
                            lambda ctx, clock: clocks.append(clock) or (calling, running))
        clock = lambda: 0.0
        assert codex_caller.recent_running_threads(_ctx(), clock) == expected
        assert clocks == [clock]


class TestRolloutIsCallingConpact:
    def test_an_exec_call_to_a_conpact_tool_is_a_call(self, tmp_path):
        path = _rollout(tmp_path, "r", STARTED, _call())
        assert codex_caller.rollout_is_calling_conpact(path) is True

    @pytest.mark.parametrize("call", [
        _call("const r=await tools.mcp__node_repl__run({});"),
        _call("conpact compaction_status, as plain prose"),
        _call(name="shell"),
        _call(source=["tools.mcp__conpact__compaction_status"]),
        _call(source=None),
    ], ids=["another server", "prose naming conPACT", "not code mode's exec",
            "input that is not text", "no input"])
    def test_only_code_mode_s_own_call_to_conpact_counts(self, tmp_path, call):
        path = _rollout(tmp_path, "r", STARTED, call)
        assert codex_caller.rollout_is_calling_conpact(path) is False

    def test_a_call_that_has_returned_is_not_a_call_now(self, tmp_path):
        path = _rollout(tmp_path, "r", STARTED, _call(), RETURNED)
        assert codex_caller.rollout_is_calling_conpact(path) is False

    @pytest.mark.parametrize("records", [(STARTED,), ()], ids=["no tool records", "empty"])
    def test_a_rollout_with_no_tool_call_is_not_a_call(self, tmp_path, records):
        path = _rollout(tmp_path, "r", *records)
        assert codex_caller.rollout_is_calling_conpact(path) is False

    def test_a_missing_rollout_is_not_a_call(self, tmp_path):
        assert codex_caller.rollout_is_calling_conpact(tmp_path / "gone.jsonl") is False

    def test_records_that_are_not_tool_records_are_read_past(self, tmp_path):
        path = _rollout(tmp_path, "r", STARTED, _call(), TOKENS,
                        {"type": "response_item", "payload": "not an object"},
                        {"type": "response_item", "payload": {"type": "message"}})
        assert codex_caller.rollout_is_calling_conpact(path) is True

    def test_the_scan_reads_the_newest_two_hundred_records(self, tmp_path):
        """A call further back than that is too old to be this call."""
        inside = _rollout(tmp_path, "inside", _call(), *[TOKENS] * 199)
        beyond = _rollout(tmp_path, "beyond", _call(), *[TOKENS] * 200)
        assert codex_caller.rollout_is_calling_conpact(inside) is True
        assert codex_caller.rollout_is_calling_conpact(beyond) is False
