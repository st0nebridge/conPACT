"""
@module tests.test_codex_host
@description conPACT's own Codex app-server: the record it keeps, the token
             it mints, what starting and stopping actually do, and the promise
             that a pid it signals is one it wrote down itself.
@input      conpact.codex_host, with the port, the process and /readyz all
            injected
@output     assertions on the record, the argv, every named refusal and the
            token never reaching the app-server
@dependencies conpact.codex_host; stdlib: hashlib, json
"""
import hashlib
import json

import pytest

from conpact import codex_appserver, codex_host, compaction, detach


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Our own state folder, somewhere harmless."""
    monkeypatch.setattr(compaction, "STATE_DIR", tmp_path / "conpact")
    return tmp_path


@pytest.fixture
def cli(tmp_path):
    exe = tmp_path / "codex.exe"
    exe.write_text("", encoding="utf-8")
    return {"CODEX_CLI_PATH": str(exe)}


@pytest.fixture
def no_cli(tmp_path):
    return {"LOCALAPPDATA": str(tmp_path / "no"), "PATH": str(tmp_path / "no")}


@pytest.fixture
def alive(monkeypatch):
    """Whether a pid is alive, under the test's control."""
    living = {"pids": set()}
    monkeypatch.setattr(detach, "pid_alive", lambda pid, *a, **k: pid in living["pids"])
    return living


def answering(status=200):
    class Answer:
        def __init__(self):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    return lambda url, timeout=None: Answer()


def refusing(url, timeout=None):
    raise OSError("nothing is listening")


class TestTheRecord:
    def test_what_is_written_is_what_is_read_back(self, state):
        codex_host.write_record(1234, 99, "t0ken")
        assert codex_host.read_record() == {"port": 1234, "pid": 99, "token": "t0ken",
                                            "started_at": pytest.approx(
                                                codex_host.read_record()["started_at"])}

    def test_it_lives_in_our_own_folder_never_in_codex_s(self, state):
        assert codex_host.record_path().parent == compaction.STATE_DIR

    def test_no_record_reads_as_nothing(self, state):
        assert codex_host.read_record() is None

    @pytest.mark.parametrize("body", ["not json", "[]", '{"port": "x", "pid": 1}',
                                      '{"pid": 1}', '{"port": 1}'])
    def test_a_record_that_makes_no_sense_reads_as_nothing(self, state, body):
        """It must never raise into a hook or a toast."""
        codex_host.record_path().parent.mkdir(parents=True, exist_ok=True)
        codex_host.record_path().write_text(body, encoding="utf-8")
        assert codex_host.read_record() is None

    def test_clearing_removes_it_and_clearing_again_does_not_raise(self, state):
        codex_host.write_record(1, 2, "t")
        codex_host.clear_record()
        codex_host.clear_record()
        assert codex_host.read_record() is None

    def test_a_second_write_replaces_the_first(self, state):
        codex_host.write_record(1, 2, "a")
        codex_host.write_record(3, 4, "b")
        assert codex_host.read_record()["port"] == 3
        assert json.loads(codex_host.record_path().read_text(encoding="utf-8"))["token"] == "b"


class TestTheToken:
    def test_the_digest_is_the_sha256_of_the_token(self):
        token, digest = codex_host.mint_token()
        assert digest == hashlib.sha256(token.encode()).hexdigest()

    def test_two_mints_do_not_match(self):
        assert codex_host.mint_token()[0] != codex_host.mint_token()[0]

    def test_the_app_server_is_given_the_digest_and_never_the_token(self, state, cli, alive,
                                                                    monkeypatch):
        """The secret has to stay out of the argv, which any process can read."""
        seen = []
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)

        def spawn(argv, environ):
            seen.append(argv)
            alive["pids"].add(77)
            return 77

        codex_host.start(cli, spawn=spawn, asker=answering(), sleep=lambda _s: None)
        token = codex_host.read_record()["token"]
        assert token not in " ".join(seen[0])
        assert hashlib.sha256(token.encode()).hexdigest() in seen[0]


class TestStarting:
    def test_the_argv_is_a_loopback_listener_with_token_auth(self, state, cli, alive, monkeypatch):
        seen = []
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)

        def spawn(argv, environ):
            seen.append(argv)
            alive["pids"].add(77)
            return 77

        got = codex_host.start(cli, spawn=spawn, asker=answering(), sleep=lambda _s: None)
        assert got["done"] is True
        assert seen[0][1:4] == ["app-server", "--listen", "ws://127.0.0.1:5000"]
        assert "--ws-auth" in seen[0] and "capability-token" in seen[0]

    def test_it_reports_where_it_put_the_server(self, state, cli, alive, monkeypatch):
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)
        alive["pids"].add(77)
        got = codex_host.start(cli, spawn=lambda a, e: 77, asker=answering(),
                               sleep=lambda _s: None)
        assert got["detail"] == {"port": 5000, "pid": 77, "already": False}

    def test_a_server_already_up_is_a_success_with_nothing_done(self, state, cli, alive):
        codex_host.write_record(5000, 77, "t")
        alive["pids"].add(77)
        got = codex_host.start(cli, spawn=None, asker=answering())
        assert (got["done"], got["detail"]["already"]) == (True, True)

    def test_a_record_pointing_at_a_dead_process_is_replaced_not_trusted(
            self, state, cli, alive, monkeypatch):
        codex_host.write_record(4000, 11, "old")
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)
        monkeypatch.setattr(codex_host, "_kill", lambda pid: None)
        alive["pids"].add(77)
        codex_host.start(cli, spawn=lambda a, e: 77, asker=answering(), sleep=lambda _s: None)
        assert codex_host.read_record()["pid"] == 77

    def test_with_no_executable_nothing_is_started(self, state, no_cli):
        def never(argv, environ):
            raise AssertionError("nothing may be started without a codex")

        got = codex_host.start(no_cli, spawn=never, asker=refusing)
        assert (got["done"], got["reason"]) == (False, codex_host.NO_CLI)

    def test_a_spawn_that_cannot_start_is_reported_not_raised(self, state, cli, alive, monkeypatch):
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)

        def broken(argv, environ):
            raise OSError("no such file")

        got = codex_host.start(cli, spawn=broken, asker=refusing)
        assert (got["done"], got["reason"]) == (False, codex_host.FAILED)

    def test_a_server_that_dies_while_starting_is_reported_and_forgotten(
            self, state, cli, alive, monkeypatch):
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)
        got = codex_host.start(cli, spawn=lambda a, e: 77, asker=refusing, sleep=lambda _s: None)
        assert (got["done"], got["reason"]) == (False, codex_host.FAILED)
        assert codex_host.read_record() is None

    def test_a_server_that_never_answers_is_a_named_refusal(self, state, cli, alive, monkeypatch):
        monkeypatch.setattr(codex_host, "free_port", lambda binder=None: 5000)
        alive["pids"].add(77)
        got = codex_host.start(cli, spawn=lambda a, e: 77, asker=refusing,
                               timeout=0.01, sleep=lambda _s: None)
        assert (got["done"], got["reason"]) == (False, codex_host.NOT_READY)
        assert isinstance(got["message"], str)


class TestStopping:
    def test_it_signals_the_pid_it_wrote_down_and_forgets_it(self, state):
        signalled = []
        codex_host.write_record(5000, 77, "t")
        got = codex_host.stop(None, killer=signalled.append)
        assert (got["done"], signalled) == (True, [77])
        assert codex_host.read_record() is None

    def test_with_no_record_there_is_nothing_to_stop(self, state):
        def never(pid):
            raise AssertionError("nothing may be signalled without a record")

        got = codex_host.stop(None, killer=never)
        assert (got["done"], got["reason"]) == (False, codex_host.NOT_RUNNING)

    def test_a_signal_that_fails_is_reported_and_the_record_still_goes(self, state):
        codex_host.write_record(5000, 77, "t")

        def broken(pid):
            raise OSError("access denied")

        got = codex_host.stop(None, killer=broken)
        assert (got["done"], got["reason"]) == (False, codex_host.FAILED)
        assert codex_host.read_record() is None


class TestWhatIsRunning:
    def test_nothing_recorded_is_nothing_running(self, state, alive):
        assert codex_host.running() == {"running": False, "ready": False,
                                        "port": None, "pid": None}

    def test_a_dead_pid_is_not_running_and_is_not_asked_about(self, state, alive):
        codex_host.write_record(5000, 77, "t")
        assert codex_host.running(asker=refusing)["running"] is False

    def test_alive_but_silent_is_running_and_not_ready(self, state, alive):
        codex_host.write_record(5000, 77, "t")
        alive["pids"].add(77)
        got = codex_host.running(asker=refusing)
        assert (got["running"], got["ready"]) == (True, False)

    def test_alive_and_answering_is_ready(self, state, alive):
        codex_host.write_record(5000, 77, "t")
        alive["pids"].add(77)
        assert codex_host.running(asker=answering())["ready"] is True

    def test_a_non_2xx_answer_is_not_ready(self, state, alive):
        codex_host.write_record(5000, 77, "t")
        alive["pids"].add(77)
        assert codex_host.running(asker=answering(503))["ready"] is False

    def test_readiness_is_asked_of_the_path_the_app_server_serves(self, state):
        asked = []

        def asker(url, timeout=None):
            asked.append(url)
            raise OSError("no")

        codex_host.ready(5000, asker)
        assert asked == [f"http://127.0.0.1:5000{codex_appserver.READY_PATH}"]


class TestOpeningAConversation:
    def test_a_server_that_is_not_running_is_a_named_refusal(self, state, alive):
        server, refused = codex_host.open_server()
        assert server is None
        assert refused["reason"] == codex_host.NOT_RUNNING

    def test_the_token_from_the_record_is_the_one_presented(self, state, alive, monkeypatch):
        codex_host.write_record(5000, 77, "t0ken")
        alive["pids"].add(77)
        seen = {}

        def connect_ws(host, port, token, timeout, opener):
            seen.update(host=host, port=port, token=token)
            return "server"

        monkeypatch.setattr(codex_appserver, "connect_ws", connect_ws)
        server, refused = codex_host.open_server()
        assert (server, refused) == ("server", None)
        assert seen == {"host": "127.0.0.1", "port": 5000, "token": "t0ken"}

    def test_a_connection_that_is_refused_is_reported_not_raised(self, state, alive, monkeypatch):
        codex_host.write_record(5000, 77, "t")
        alive["pids"].add(77)

        def broken(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr(codex_appserver, "connect_ws", broken)
        server, refused = codex_host.open_server()
        assert server is None
        assert refused["reason"] == codex_host.FAILED
