"""
@module tests.test_codex_remote
@description Codex's Remote Control as conPACT sees it: what can be read
             without changing anything, which call each action makes on our own
             app-server, and the promise that nothing acts unless it was asked to.
@input      conpact.codex_remote, against a stand-in Codex state store and a
             fake app-server
@output     assertions on the status shape, every method name and its params,
            each named refusal, and the columns the enrolment query does not read
@dependencies conpact.codex_remote; stdlib: sqlite3, sys
"""
import sqlite3
import sys

import pytest

from conpact import codex_host, codex_remote

ENROLMENTS = """
create table remote_control_enrollments (
    websocket_url TEXT NOT NULL, account_id TEXT NOT NULL,
    app_server_client_name TEXT NOT NULL, server_id TEXT NOT NULL,
    environment_id TEXT NOT NULL, server_name TEXT NOT NULL,
    updated_at INTEGER NOT NULL, remote_control_enabled INTEGER)
"""


class FakeServer:
    """An app-server that answers from a script instead of being one."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked, self.closed = [], False

    def request(self, method, params, timeout):
        self.asked.append((method, params, timeout))
        if not self.replies:
            raise OSError("the app-server closed the connection")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self):
        self.closed = True


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / "codex"
    folder.mkdir()
    con = sqlite3.connect(str(folder / "state_5.sqlite"))
    con.execute(ENROLMENTS)
    con.commit()

    def enrol(*, name="WORKSTATION", client="Codex Desktop", enabled=1, updated_at=1000,
              environment="env-secret", url="wss://chatgpt.com/wham/remote/control/server"):
        con.execute("insert into remote_control_enrollments (websocket_url, account_id,"
                    " app_server_client_name, server_id, environment_id, server_name,"
                    " updated_at, remote_control_enabled) values (?,?,?,?,?,?,?,?)",
                    (url, "acct-secret", client, "srv-secret", environment, name,
                     updated_at, enabled))
        con.commit()

    enrol.folder = folder
    yield enrol
    con.close()


@pytest.fixture
def env(tmp_path, home):
    cli = tmp_path / "codex.exe"
    cli.write_text("", encoding="utf-8")
    return {"CODEX_HOME": str(home.folder), "CODEX_CLI_PATH": str(cli)}


@pytest.fixture
def no_cli(home):
    return {"CODEX_HOME": str(home.folder), "LOCALAPPDATA": str(home.folder / "no"),
            "PATH": str(home.folder / "no")}


@pytest.fixture
def server(monkeypatch):
    """Whatever our app-server would answer, without one existing."""
    def use(*replies, refused=None):
        fake = FakeServer(*replies)
        monkeypatch.setattr(codex_host, "open_server",
                            lambda environ=None, opener=None, timeout=None:
                            (None, refused) if refused else (fake, None))
        return fake
    return use


@pytest.fixture
def up(monkeypatch):
    """Our app-server, running and answering."""
    def state(running=True, ready=True, port=5000, pid=77):
        monkeypatch.setattr(codex_host, "running", lambda environ=None, asker=None: {
            "running": running, "ready": ready, "port": port, "pid": pid})
    return state


def enabled(environment="env-1"):
    return {"result": {"status": "enabled", "serverName": "WORKSTATION",
                       "environmentId": environment}}


class TestWhereCodexKeepsItsOwnDaemon:
    """Reported, not used: the daemon will not start from the CLI ChatGPT
    Desktop installs, and its socket is one Python here cannot open."""

    def test_the_socket_is_the_one_the_desktop_app_looks_for(self, env, home):
        assert codex_remote.socket_path(env) == (
            home.folder / "app-server-control" / "app-server-control.sock")

    def test_the_names_are_the_ones_codex_uses(self):
        assert codex_remote.CONTROL_DIR == "app-server-control"
        assert codex_remote.SOCKET == "app-server-control.sock"
        assert codex_remote.PACKAGE_MANIFEST == "codex-package.json"

    def test_a_cli_with_no_manifest_beside_it_is_not_a_packaged_one(self, env):
        assert codex_remote.packaged(env) is False

    def test_a_cli_with_one_is(self, env, tmp_path):
        (tmp_path / "codex-package.json").write_text("{}", encoding="utf-8")
        assert codex_remote.packaged(env) is True

    def test_no_cli_at_all_is_not_packaged(self, no_cli):
        assert codex_remote.packaged(no_cli) is False


class TestTheDesktopDoesNotShareOneHere:
    """Measured from the app's own launcher: the first conjunct of the condition
    that picks the shared socket is `process.platform !== "win32"`."""

    def test_on_windows_it_never_shares_one(self):
        shares, why = codex_remote.desktop_shares_daemon("win32")
        assert shares is False
        assert "win32" in why

    def test_elsewhere_it_may(self):
        assert codex_remote.desktop_shares_daemon("darwin")[0] is True
        assert codex_remote.desktop_shares_daemon("linux")[0] is True

    def test_the_platform_defaults_to_this_one(self):
        assert codex_remote.desktop_shares_daemon()[0] is (not sys.platform.startswith("win"))


class TestReadingTheEnrolment:
    def test_a_machine_that_never_enrolled_reads_as_nothing(self, env):
        assert codex_remote.enrollment(env) is None

    def test_an_enrolment_is_read_without_its_secrets(self, env, home):
        home()
        assert codex_remote.enrollment(env) == {
            "client_name": "Codex Desktop", "server_name": "WORKSTATION", "enabled": True,
            "updated_at": 1000, "host": "chatgpt.com", "environment_id": "env-secret"}

    def test_remote_control_switched_off_reads_as_off(self, env, home):
        home(enabled=0)
        assert codex_remote.enrollment(env)["enabled"] is False

    def test_the_newest_enrolment_wins(self, env, home):
        home(name="OLD", updated_at=1)
        home(name="NEW", updated_at=2)
        assert codex_remote.enrollment(env)["server_name"] == "NEW"

    def test_a_url_with_no_host_does_not_raise(self, env, home):
        home(url="nonsense")
        assert codex_remote.enrollment(env)["host"] == ""

    def test_the_query_never_asks_for_the_account_or_server_id(self):
        """Those two are credentials-adjacent and nothing here needs them.
        `environment_id` is read, because `client/list` and `client/revoke` are
        refused without it - a scope, not a secret."""
        assert "account_id" not in codex_remote.ENROLLMENT_SQL
        assert "server_id" not in codex_remote.ENROLLMENT_SQL
        assert "environment_id" in codex_remote.ENROLLMENT_SQL

    def test_a_store_that_is_not_there_reads_as_nothing(self, tmp_path):
        assert codex_remote.enrollment({"CODEX_HOME": str(tmp_path / "gone")}) is None


class TestStatus:
    def test_a_machine_with_nothing_set_up_says_what_it_needs(self, no_cli, up):
        up(running=False, ready=False)
        got = codex_remote.status(no_cli, platform="win32")
        assert got["needs"] == [codex_remote.NO_CLI, "host", "remote_control"]
        assert got["ready"] is False

    def test_with_our_server_up_and_offering_itself_nothing_is_needed(
            self, env, home, up, server):
        home()
        up()
        server(enabled())
        got = codex_remote.status(env, platform="win32")
        assert (got["needs"], got["ready"]) == ([], True)
        assert got["offered"] == "enabled"

    def test_whether_remote_control_is_on_is_asked_of_our_own_server(
            self, env, home, up, server):
        """The enrolment row belongs to the *desktop's* app-server. Reading it as
        ours reported "ready" for a server that was offering nothing."""
        home(enabled=1)
        up()
        server({"result": {"status": "disabled", "environmentId": None}})
        got = codex_remote.status(env, platform="win32")
        assert got["offered"] == "disabled"
        assert got["needs"] == ["remote_control"]

    def test_with_no_server_of_ours_the_enrolment_row_is_the_only_hint(self, env, home, up):
        home(enabled=1)
        up(running=False, ready=False)
        got = codex_remote.status(env, platform="win32")
        assert got["needs"] == ["host"]
        assert got["offered"] is None

    def test_it_names_what_the_backend_knows_this_machine_as(self, env, home, up):
        home()
        up(running=False, ready=False)
        got = codex_remote.status(env, platform="win32")
        assert (got["enrolled"], got["server_name"]) == (True, "WORKSTATION")
        assert got["remote_host"] == "chatgpt.com"

    def test_it_says_the_desktop_app_will_not_share_one(self, env, up):
        up(running=False, ready=False)
        got = codex_remote.status(env, platform="win32")
        assert got["desktop_shares_daemon"] is False
        assert "stdio" in got["desktop_detail"]

    def test_a_server_that_will_not_answer_does_not_break_the_report(
            self, env, home, up, server):
        home()
        up()
        server(OSError("gone"))
        got = codex_remote.status(env, platform="win32")
        assert got["offered"] is None
        assert "remote_control" in got["needs"]


class TestTheCallsOnOurServer:
    @pytest.mark.parametrize("call, method", [
        (lambda o: codex_remote.remote_status(None, o), "remoteControl/status/read"),
        (lambda o: codex_remote.enable(None, o), "remoteControl/enable"),
        (lambda o: codex_remote.disable(None, o), "remoteControl/disable"),
        (lambda o: codex_remote.pairing_code(None, o), "remoteControl/pairing/start"),
    ])
    def test_each_one_is_the_method_codex_serves_and_takes_no_params(
            self, server, call, method):
        fake = server({"result": {"ok": True}})
        got = call(None)
        assert got["done"] is True
        assert fake.asked[0][:2] == (method, {})
        assert fake.closed is True

    def test_enrolling_is_given_longer_than_a_read(self, server):
        fake = server({"result": {}})
        codex_remote.enable(None, None)
        assert fake.asked[0][2] == codex_remote.ENROL_TIMEOUT
        assert codex_remote.ENROL_TIMEOUT > codex_remote.RPC_TIMEOUT

    def test_a_pairing_code_comes_straight_back(self, server):
        server({"result": {"pairingCode": "AB-12", "manualPairingCode": "ZZZZ"}})
        got = codex_remote.pairing_code(None, None)
        assert got["detail"]["manualPairingCode"] == "ZZZZ"

    @pytest.mark.parametrize("manual, key", [(False, "pairingCode"), (True, "manualPairingCode")])
    def test_asking_whether_a_code_was_claimed_names_the_kind_it_is(self, server, manual, key):
        fake = server({"result": {"claimed": False}})
        codex_remote.pairing_status("AB-12", manual, None, None)
        assert fake.asked[0][1] == {key: "AB-12"}

    def test_a_server_of_ours_that_is_not_running_is_a_named_refusal(self, server):
        server(refused={"done": False, "reason": codex_host.NOT_RUNNING,
                        "detail": None, "message": "no"})
        got = codex_remote.enable(None, None)
        assert (got["done"], got["reason"]) == (False, codex_remote.NO_HOST)
        assert isinstance(got["message"], str)

    def test_an_error_reply_is_reported_with_what_the_server_said(self, server):
        server({"error": {"message": "remote control is unavailable"}})
        got = codex_remote.enable(None, None)
        assert (got["done"], got["reason"]) == (False, codex_remote.FAILED)
        assert got["detail"] == {"message": "remote control is unavailable"}

    def test_a_server_that_dies_mid_call_is_reported_not_raised(self, server):
        fake = server(OSError("closed"))
        got = codex_remote.enable(None, None)
        assert (got["done"], got["reason"]) == (False, codex_remote.FAILED)
        assert fake.closed is True


class TestTheCallsThatNameAnEnvironment:
    """`client/list` and `client/revoke` are scoped to one environment - measured,
    not assumed: without it the app-server answers "Invalid request: missing
    field `environmentId`"."""

    def test_listing_is_scoped_to_what_the_server_reports(self, server):
        fake = server(enabled(), {"result": {"data": []}})
        codex_remote.clients(None, None)
        assert fake.asked[0][0] == "remoteControl/status/read"
        assert fake.asked[1] == ("remoteControl/client/list",
                                 {"limit": codex_remote.CLIENT_LIMIT,
                                  "environmentId": "env-1"}, codex_remote.RPC_TIMEOUT)

    def test_revoking_names_the_client_and_the_environment(self, server):
        fake = server(enabled(), {"result": {"ok": True}})
        codex_remote.revoke("c-1", None, None)
        assert fake.asked[1][0] == "remoteControl/client/revoke"
        assert fake.asked[1][1] == {"clientId": "c-1", "environmentId": "env-1"}

    def test_both_calls_share_one_connection(self, server):
        """Otherwise listing the clients starts two app-servers."""
        fake = server(enabled(), {"result": {"data": []}})
        codex_remote.clients(None, None)
        assert len(fake.asked) == 2
        assert fake.closed is True

    def test_a_server_with_no_environment_falls_back_to_the_enrolment(self, env, home, server):
        home(environment="env-secret")
        fake = server({"result": {"status": "enabled", "environmentId": None}},
                      {"result": {"data": []}})
        codex_remote.clients(env, None)
        assert fake.asked[1][1]["environmentId"] == "env-secret"

    def test_a_machine_with_no_environment_anywhere_is_told_so(self, env, server):
        server({"result": {"status": "disabled", "environmentId": None}})
        got = codex_remote.clients(env, None)
        assert (got["done"], got["reason"]) == (False, codex_remote.NOT_ENROLLED)

    def test_a_server_that_cannot_say_is_not_a_machine_with_no_environment(
            self, env, home, server):
        """A dead connection cannot serve the next call either, so reporting
        "never enrolled" would name the wrong cause."""
        home()
        server(OSError("closed"))
        got = codex_remote.clients(env, None)
        assert got["reason"] == codex_remote.FAILED


class TestTheMethodNamesAreSpelledOut:
    """A contract with someone else's binary, asserted as literals: comparing
    them against the module's own constants cannot catch a rename, and a mutation
    run found exactly that (CU-20260921-034)."""

    def test_the_seven_app_server_methods(self):
        assert codex_remote.STATUS_READ == "remoteControl/status/read"
        assert codex_remote.ENABLE == "remoteControl/enable"
        assert codex_remote.DISABLE == "remoteControl/disable"
        assert codex_remote.PAIRING_START == "remoteControl/pairing/start"
        assert codex_remote.PAIRING_STATUS == "remoteControl/pairing/status"
        assert codex_remote.CLIENT_LIST == "remoteControl/client/list"
        assert codex_remote.CLIENT_REVOKE == "remoteControl/client/revoke"

    def test_the_word_for_a_server_that_is_offering_itself(self):
        assert codex_remote.ENABLED == "enabled"

    def test_the_client_list_limit_is_inside_the_range_the_server_allows(self):
        """The app-server refuses anything else: "limit must be between 1 and 100"."""
        assert 1 <= codex_remote.CLIENT_LIMIT <= 100


class TestStartingAndStoppingArePassedStraightThrough:
    def test_start_and_stop_are_our_own_app_server(self, monkeypatch):
        seen = []
        monkeypatch.setattr(codex_host, "start",
                            lambda environ=None, **how: seen.append(("start", environ)))
        monkeypatch.setattr(codex_host, "stop",
                            lambda environ=None, **how: seen.append(("stop", environ)))
        codex_remote.start({"a": 1})
        codex_remote.stop({"a": 1})
        assert seen == [("start", {"a": 1}), ("stop", {"a": 1})]
