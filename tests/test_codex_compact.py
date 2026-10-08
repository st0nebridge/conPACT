"""
@module tests.test_codex_compact
@description Compacting one Codex thread, and - far more often - refusing to.
@input      conpact.codex_compact, against a stand-in state store and a fake
            app-server
@output     assertions on every refusal, the JSON-RPC conversation and the
            promise that a refused thread never reaches a subprocess
@dependencies conpact.codex_compact; stdlib: json, sqlite3
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from conpact import codex_appserver, codex_compact, codex_host, codex_inject, codex_threads, platforms

STATE = """
create table threads (
    id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, cwd TEXT NOT NULL,
    name TEXT, title TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0, updated_at_ms INTEGER,
    thread_source TEXT, model TEXT, source TEXT NOT NULL DEFAULT '')
"""


class FakeProcess:
    """An app-server that answers from a script instead of being one."""

    def __init__(self, replies, *, close_after=None):
        self.replies, self.close_after = list(replies), close_after
        self.sent, self.terminated, self.lines = [], False, []

    # -- the pipes the client writes to and reads from -------------------------
    @property
    def stdin(self):
        return self

    def write(self, body):
        self.sent.append(json.loads(body))
        if self.close_after is not None and len(self.sent) > self.close_after:
            return
        reply = self.replies[len(self.sent) - 1] if len(self.sent) <= len(self.replies) else {}
        self.lines.append(json.dumps({"method": "thread/status/changed", "params": {}}))
        self.lines.append(json.dumps({**reply, "id": self.sent[-1]["id"]}))

    def flush(self):
        pass

    def close(self):
        pass

    @property
    def stdout(self):
        return self._stream()

    def _stream(self):
        while True:
            if self.lines:
                yield self.lines.pop(0)
            elif self.close_after is not None and len(self.sent) > self.close_after:
                return
            elif len(self.sent) >= len(self.replies):
                return

    def terminate(self):
        self.terminated = True


@pytest.fixture
def codex(tmp_path):
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    (home / "thread-writer-locks").mkdir()
    con = sqlite3.connect(str(home / "state_5.sqlite"))
    con.execute(STATE)
    con.commit()

    def add(thread_id="t1", *, kind="user", archived=0):
        rollout = home / "sessions" / f"{thread_id}.jsonl"
        rollout.write_text('{"type":"event_msg","payload":{"type":"task_complete"}}\n',
                           encoding="utf-8")
        con.execute("insert into threads (id, rollout_path, cwd, title, archived, updated_at_ms,"
                    " thread_source) values (?,?,?,?,?,?,?)",
                    (thread_id, str(rollout), r"C:\Dev\x", "A thread", archived, 1000, kind))
        con.commit()
        return thread_id

    yield add
    con.close()


@pytest.fixture(autouse=True)
def recorded_completion(monkeypatch):
    """Transport tests isolate the completion reader; its real files and timing
    are covered by test_codex_completion and the end-to-end regression test."""
    class Completed:
        def __init__(self, path):
            self.path = path

        def wait(self, stop):
            return {"state": "completed", "turn_id": "c-1", "detail": None}

    monkeypatch.setattr(codex_compact.codex_completion, "Rollout", Completed)


@pytest.fixture
def env(tmp_path):
    """A Codex home plus a codex.exe that exists, so that NO_CLI never masks a
    refusal we meant to test."""
    cli = tmp_path / "codex.exe"
    cli.write_text("", encoding="utf-8")
    return {"CODEX_HOME": str(tmp_path / "codex"), "CODEX_CLI_PATH": str(cli)}


@pytest.fixture
def never_spawn():
    """A spawn that fails the test if it is ever called. Every refusal must be
    decided before a process is started."""
    calls = []

    def refuse(command, environ):
        calls.append(command)
        raise AssertionError(f"a refused thread must never start a process: {command}")

    refuse.calls = calls
    return refuse


class TestRefusals:
    def test_a_thread_that_is_not_in_the_store_is_refused(self, codex, env, never_spawn):
        got = codex_compact.compact("absent", env, spawn=never_spawn)
        assert (got["compacted"], got["reason"]) == (False, codex_compact.NO_THREAD)
        assert got["message"]

    def test_a_subagent_thread_is_refused_before_anything_starts(self, codex, env, never_spawn):
        codex("t1", kind="subagent")
        got = codex_compact.compact("t1", env, spawn=never_spawn)
        assert (got["compacted"], got["reason"]) == (False, platforms.SPIN_OFF)

    def test_a_guardian_review_thread_is_refused(self, codex, env, never_spawn):
        codex("t1", kind="guardian_review")
        assert codex_compact.compact("t1", env, spawn=never_spawn)["reason"] == platforms.SPIN_OFF

    def test_an_archived_thread_is_refused(self, codex, env, never_spawn):
        codex("t1", archived=1)
        assert codex_compact.compact("t1", env, spawn=never_spawn)["reason"] == platforms.ARCHIVED

    def test_a_thread_a_running_app_holds_is_refused(self, codex, env, never_spawn, monkeypatch):
        """The load-bearing guard. Codex's app-server is a stdio child of the
        desktop app with no socket, so a thread it holds cannot be reached from
        here at all, and writing to that rollout would corrupt the app's file."""
        codex("t1")
        monkeypatch.setattr(codex_threads, "is_loaded", lambda *a, **k: True)
        got = codex_compact.compact("t1", env, spawn=never_spawn)
        assert (got["compacted"], got["reason"]) == (False, platforms.BUSY)

    def test_with_no_codex_executable_nothing_is_started(self, codex, tmp_path, never_spawn):
        codex("t1")
        env = {"CODEX_HOME": str(tmp_path / "codex"), "LOCALAPPDATA": str(tmp_path / "nowhere"),
               "PATH": str(tmp_path / "nowhere")}
        got = codex_compact.compact("t1", env, spawn=never_spawn)
        assert (got["compacted"], got["reason"]) == (False, codex_compact.NO_CLI)

    def test_every_refusal_carries_words_for_a_user(self, codex, env, never_spawn):
        codex("t1", kind="subagent")
        assert isinstance(codex_compact.compact("t1", env, spawn=never_spawn)["message"], str)


class TestTheConversation:
    def _run(self, env, replies, **kw):
        process = FakeProcess(replies, **kw)
        got = codex_compact.compact("t1", env, spawn=lambda command, environ: process)
        return got, process

    def test_a_free_thread_is_initialised_resumed_and_compacted_in_that_order(self, codex, env):
        codex("t1")
        got, process = self._run(env, [{"result": {}}, {"result": {}}, {"result": {"ok": True}}])
        assert got["compacted"] is True
        assert [m["method"] for m in process.sent] == [
            codex_compact.INITIALIZE, codex_compact.RESUME, codex_compact.COMPACT]

    def test_the_thread_id_is_what_is_sent_to_resume_and_compact(self, codex, env):
        codex("t1")
        _, process = self._run(env, [{"result": {}}, {"result": {}}, {"result": {}}])
        assert process.sent[1]["params"] == {"threadId": "t1", "excludeTurns": True}
        assert process.sent[2]["params"] == {"threadId": "t1"}

    def test_the_handshake_names_this_client(self, codex, env):
        codex("t1")
        _, process = self._run(env, [{"result": {}}, {"result": {}}, {"result": {}}])
        assert process.sent[0]["params"]["clientInfo"]["name"] == "conpact"

    def test_notifications_arriving_among_the_replies_are_not_mistaken_for_one(self, codex, env):
        """The fake interleaves a thread/status/changed before every reply, which
        is what a real app-server does."""
        codex("t1")
        got, _ = self._run(env, [{"result": {}}, {"result": {}}, {"result": {}}])
        assert got["compacted"] is True

    def test_a_refused_resume_is_reported_and_no_compaction_is_asked_for(self, codex, env):
        codex("t1")
        got, process = self._run(env, [{"result": {}}, {"error": {"message": "no such thread"}}])
        assert (got["compacted"], got["reason"]) == (False, codex_compact.FAILED)
        assert [m["method"] for m in process.sent] == [
            codex_compact.INITIALIZE, codex_compact.RESUME]

    def test_a_refused_compaction_is_reported_with_what_the_server_said(self, codex, env):
        codex("t1")
        got, _ = self._run(env, [{"result": {}}, {"result": {}}, {"error": {"message": "busy"}}])
        assert got["reason"] == codex_compact.FAILED
        assert got["detail"] == {"message": "busy"}

    def test_a_server_that_dies_mid_conversation_is_reported_not_raised(self, codex, env):
        codex("t1")
        got, _ = self._run(env, [{"result": {}}], close_after=1)
        assert (got["compacted"], got["reason"]) == (False, codex_compact.FAILED)
        assert "TimeoutError" in got["detail"]

    def test_the_process_is_always_shut_down_afterwards(self, codex, env):
        codex("t1")
        _, process = self._run(env, [{"result": {}}, {"result": {}}, {"result": {}}])
        assert process.terminated is True

    def test_a_spawn_that_cannot_start_is_reported_not_raised(self, codex, env):
        codex("t1")

        def broken(command, environ):
            raise OSError(2, "no such file")

        got = codex_compact.compact("t1", env, spawn=broken)
        assert (got["compacted"], got["reason"]) == (False, codex_compact.FAILED)


class TestTheReachableHost:
    class Server:
        def __init__(self, replies):
            self.replies = iter(replies)
            self.sent = []
            self.closed = False

        def request(self, method, params, timeout):
            self.sent.append((method, params))
            return next(self.replies)

        def close(self):
            self.closed = True

    def test_a_live_cli_thread_is_compacted_on_the_server_that_owns_it(
            self, codex, env, monkeypatch):
        codex("t1")
        monkeypatch.setattr(codex_threads, "is_loaded", lambda *a, **k: True)
        monkeypatch.setattr(codex_inject, "compact_thread", lambda *a, **k: None)
        server = self.Server([{"result": {"ok": True}}])
        monkeypatch.setattr(codex_host, "open_server", lambda *a, **k: (server, None))

        got = codex_compact.compact("t1", env)

        assert got["compacted"] is True
        assert server.sent == [(codex_compact.COMPACT, {"threadId": "t1"})]
        assert server.closed is True

    def test_a_free_thread_is_resumed_on_the_host_after_direct_compact_refuses(
            self, codex, env, monkeypatch):
        codex("t1")
        monkeypatch.setattr(codex_inject, "compact_thread", lambda *a, **k: None)
        server = self.Server([
            {"error": {"code": -32600, "message": "thread not found: t1"}},
            {"result": {}},
            {"result": {"ok": True}},
        ])
        monkeypatch.setattr(codex_host, "open_server", lambda *a, **k: (server, None))

        assert codex_compact.compact("t1", env)["compacted"] is True
        assert [method for method, _params in server.sent] == [
            codex_compact.COMPACT, codex_compact.RESUME, codex_compact.COMPACT]

    @pytest.mark.parametrize("replies,methods", [
        ([{"error": {"message": "busy"}}], [codex_compact.COMPACT]),
        ([{"error": {"code": -32600, "message": "thread not found: t1"}},
          {"error": {"message": "resume refused"}}],
         [codex_compact.COMPACT, codex_compact.RESUME]),
        ([{"error": {"code": -32600, "message": "thread not found: t1"}},
          {"result": {}}, {"error": {"message": "compact refused"}}],
         [codex_compact.COMPACT, codex_compact.RESUME, codex_compact.COMPACT]),
    ])
    def test_host_refusals_stop_without_another_executor(
            self, codex, env, monkeypatch, replies, methods):
        codex("t1")
        server = self.Server(replies)
        monkeypatch.setattr(codex_host, "open_server", lambda *a, **k: (server, None))
        got = codex_compact.compact("t1", env)
        assert not got["compacted"] and got["reason"] == codex_compact.FAILED
        assert [method for method, params in server.sent] == methods and server.closed

    def test_observation_finishes_before_the_owning_server_connection_is_closed(
            self, codex, env, monkeypatch):
        codex("t1")
        server, observed = self.Server([{"result": {}}]), []
        monkeypatch.setattr(codex_host, "open_server", lambda *a, **k: (server, None))
        def wait(stop):
            observed.append(server.closed)
            return {"state": "failed", "turn_id": "c-1", "detail": "interrupted"}
        monkeypatch.setattr(codex_compact.codex_completion, "Rollout",
                            lambda path: SimpleNamespace(wait=wait))
        got = codex_compact.compact("t1", env)
        assert observed == [False] and server.closed
        assert got["accepted"] and not got["compacted"] and got["detail"] == "interrupted"

    def test_host_timeout_is_reported_and_closes_only_that_connection(self, codex, env, monkeypatch):
        codex("t1")
        server = self.Server([])
        def timed_out(*a):
            raise TimeoutError("did not answer")
        server.request = timed_out
        monkeypatch.setattr(codex_host, "open_server", lambda *a, **k: (server, None))
        got = codex_compact.compact("t1", env)
        assert not got["compacted"] and "did not answer" in got["detail"] and server.closed

    def test_unavailable_owned_channel_never_starts_an_unrelated_process(
            self, codex, env, monkeypatch, never_spawn):
        codex("t1")
        env[codex_inject.OWNER_ENV] = "41"
        monkeypatch.setattr(codex_host, "read_record", lambda: {"pid": 99})
        got = codex_compact.compact("t1", env, spawn=never_spawn)
        assert not got["compacted"] and "owning app-server" in got["detail"]
        assert never_spawn.calls == []

    def test_matching_owner_is_required_when_opening_the_listener(self, codex, env, monkeypatch):
        codex("t1")
        env[codex_inject.OWNER_ENV] = "41"
        monkeypatch.setattr(codex_host, "read_record", lambda: {"pid": 41})
        server, openings = self.Server([{"result": {}}]), []
        monkeypatch.setattr(codex_host, "open_server", lambda *a, **k:
                            openings.append(k) or (server, None))
        assert codex_compact.compact("t1", env)["compacted"]
        assert openings[0]["expected_pid"] == 41 and server.closed


def test_running_and_unobservable_rollouts_are_refused_before_rpc(codex, env, monkeypatch):
    codex("t1")
    calls = []
    monkeypatch.setattr(codex_inject, "compact_thread", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(codex_compact.codex_meter, "turn_state", lambda path: "running")
    running = codex_compact.compact("t1", env)
    monkeypatch.setattr(codex_compact.codex_meter, "turn_state", lambda path: "idle")
    def unreadable(path):
        raise OSError("target unreadable")
    monkeypatch.setattr(codex_compact.codex_completion, "Rollout", unreadable)
    unknown = codex_compact.compact("t1", env)
    assert not running["compacted"] and "running" in running["detail"]
    assert not unknown["compacted"] and "unreadable" in unknown["detail"] and calls == []


class TestFindingTheExecutable:
    def test_the_named_path_wins_when_it_is_really_there(self, tmp_path):
        cli = tmp_path / "codex.exe"
        cli.write_text("", encoding="utf-8")
        assert codex_compact.codex_cli({"CODEX_CLI_PATH": str(cli)}) == cli

    def test_a_named_path_that_is_not_there_is_ignored_rather_than_returned(self, tmp_path):
        env = {"CODEX_CLI_PATH": str(tmp_path / "gone.exe"),
               "LOCALAPPDATA": str(tmp_path / "nowhere"), "PATH": str(tmp_path / "nowhere")}
        assert codex_compact.codex_cli(env) is None

    def test_the_newest_versioned_install_is_chosen(self, tmp_path):
        base = tmp_path / "OpenAI" / "Codex" / "bin"
        for version in ("aaa111", "zzz999"):
            (base / version).mkdir(parents=True)
            (base / version / "codex.exe").write_text("", encoding="utf-8")
        got = codex_compact.codex_cli({"LOCALAPPDATA": str(tmp_path)})
        assert got == base / "zzz999" / "codex.exe"


class TestTheWireProtocolIsSpelledOut:
    """These strings are a contract with someone else's binary, so they are
    asserted as literals. Comparing them against the module's own constants -
    which every test above does, deliberately, for readability - cannot catch a
    rename, and a mutation run found exactly that: the method names, the
    subcommand and the client name all survived being changed."""

    def test_the_three_methods_are_the_ones_codex_serves(self):
        assert codex_compact.INITIALIZE == "initialize"
        assert codex_compact.RESUME == "thread/resume"
        assert codex_compact.COMPACT == "thread/compact/start"

    def test_the_subcommand_is_the_one_that_starts_an_app_server(self):
        assert codex_compact.ARGS == ("app-server",)

    def test_the_handshake_sends_a_name_and_a_version(self):
        assert codex_compact.CLIENT == {"name": "conpact", "version": "1"}

    def test_the_executable_is_looked_for_where_codex_installs_it(self):
        assert codex_appserver.CLI_VAR == "CODEX_CLI_PATH"
        assert codex_appserver.CLI_GLOB == ("OpenAI", "Codex", "bin", "*", "codex.exe")

    def test_the_real_argv_is_the_executable_then_the_subcommand(self, codex, env):
        codex("t1")
        seen = []

        def spy(command, environ):
            seen.append(command)
            return FakeProcess([{"result": {}}, {"result": {}}, {"result": {}}])

        codex_compact.compact("t1", env, spawn=spy)
        assert seen[0][1:] == ["app-server"]
        assert seen[0][0].endswith("codex.exe")


class TestTheTransportItself:
    def test_a_request_is_flushed_before_its_reply_is_waited_for(self, codex, env):
        """Without the flush the bytes can sit in the pipe buffer and the reply
        never comes. The fake above answers on write, so only this one can see it."""
        codex("t1")

        class NeedsFlush(FakeProcess):
            def __init__(self, replies):
                super().__init__(replies)
                self.pending, self.flushed = [], 0

            def write(self, body):
                self.pending.append(body)

            def flush(self):
                self.flushed += 1
                for body in self.pending:
                    FakeProcess.write(self, body)
                self.pending.clear()

        process = NeedsFlush([{"result": {}}, {"result": {}}, {"result": {}}])
        got = codex_compact.compact("t1", env, spawn=lambda c, e: process)
        assert got["compacted"] is True
        assert process.flushed == 3

    def test_the_reader_thread_cannot_keep_the_process_alive(self, codex, env):
        """It blocks on a pipe that may never close; as a non-daemon thread it
        would hang every caller at exit."""
        server = codex_compact.AppServer(FakeProcess([]))
        try:
            assert server._reader.daemon is True
        finally:
            server.close()

    def test_a_reply_to_a_different_request_is_not_taken_as_ours(self, codex, env):
        """Each request carries its own id and only its own reply counts."""
        codex("t1")

        class Misaddressed(FakeProcess):
            def write(self, body):
                self.sent.append(__import__("json").loads(body))
                if len(self.sent) == 2:                      # answer resume wrongly first
                    self.lines.append(__import__("json").dumps(
                        {"id": "someone-elses-request", "result": {"wrong": True}}))
                reply = self.replies[len(self.sent) - 1] if len(self.sent) <= len(self.replies) else {}
                self.lines.append(__import__("json").dumps({**reply, "id": self.sent[-1]["id"]}))

        process = Misaddressed([{"result": {}}, {"result": {"right": True}}, {"result": {}}])
        assert codex_compact.compact("t1", env, spawn=lambda c, e: process)["compacted"] is True
