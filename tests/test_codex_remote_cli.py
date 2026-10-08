"""
@module tests.test_codex_remote_cli
@description The Codex remote-control command: what `show` prints, which call
             each action makes, and the exit code a refusal gets.
@input      conpact.codex_remote_cli, with the module it drives stubbed out
@output     assertions on the printed report, on the call each command makes and
            on the promise that `show` calls no action
@dependencies conpact.codex_remote_cli; stdlib: io
"""
import io

import pytest

from conpact import codex_remote, codex_remote_cli

READY = {
    "cli": r"C:\codex.exe", "packaged": False,
    "host": {"running": True, "ready": True, "port": 5000, "pid": 77},
    "offered": "enabled",
    "record": r"C:\home\.conpact\codex-host.json",
    "daemon_socket": r"C:\home\.codex\app-server-control\app-server-control.sock",
    "daemon_socket_present": False,
    "enrolled": True, "enabled": True, "server_name": "WORKSTATION",
    "client_name": "Codex Desktop", "remote_host": "chatgpt.com",
    "desktop_shares_daemon": False, "desktop_detail": "it runs its own stdio child",
    "needs": [], "ready": True,
}
BARE = {**READY, "cli": None,
        "host": {"running": False, "ready": False, "port": None, "pid": None},
        "offered": None, "enrolled": False, "enabled": False, "server_name": None,
        "client_name": None, "remote_host": None,
        "needs": [codex_remote.NO_CLI, "host", "remote_control"], "ready": False}


@pytest.fixture
def pipes():
    return io.StringIO(), io.StringIO()


def done(detail=None):
    return {"done": True, "reason": None, "detail": detail, "message": None}


def refused(reason=codex_remote.NO_HOST, detail=None):
    return {"done": False, "reason": reason, "detail": detail,
            "message": codex_remote.NOT_DONE[reason]}


def _explode(why):
    def boom(*a, **k):
        raise AssertionError(why)
    return boom


def showing(monkeypatch, status):
    monkeypatch.setattr(codex_remote, "status",
                        lambda environ, asker, platform=None, opener=None: status)


class TestShow:
    def test_a_ready_machine_says_so_and_names_itself(self, monkeypatch, pipes):
        out, err = pipes
        showing(monkeypatch, READY)
        assert codex_remote_cli.main([], out, err) == 0
        printed = out.getvalue()
        assert "WORKSTATION via chatgpt.com" in printed
        assert "running on 127.0.0.1:5000 (pid 77)" in printed
        assert "remote control enabled" in printed
        assert "ready            yes" in printed
        assert err.getvalue() == ""

    def test_no_command_at_all_shows_rather_than_acting(self, monkeypatch, pipes):
        out, err = pipes
        showing(monkeypatch, READY)
        for name in ("start", "stop", "enable", "disable", "pairing_code"):
            monkeypatch.setattr(codex_remote, name, _explode(f"show must not run {name}"))
        assert codex_remote_cli.main([], out, err) == 0

    def test_a_machine_that_is_not_ready_lists_what_it_needs(self, monkeypatch, pipes):
        out, err = pipes
        showing(monkeypatch, BARE)
        codex_remote_cli.main(["show"], out, err)
        printed = out.getvalue()
        assert "ready            no" in printed
        assert "tools/codex_remote.py start" in printed
        assert "tools/codex_remote.py enable" in printed
        assert "not running" in printed

    def test_a_server_that_is_alive_but_silent_is_not_called_running(self, monkeypatch, pipes):
        """"running" for a process nothing can reach is the report lying."""
        out, err = pipes
        showing(monkeypatch, {**READY, "ready": False, "needs": ["host"],
                              "offered": None,
                              "host": {"running": True, "ready": False,
                                       "port": 5000, "pid": 77}})
        codex_remote_cli.main(["show"], out, err)
        assert "alive but not answering" in out.getvalue()

    def test_an_enrolment_that_is_switched_off_says_so(self, monkeypatch, pipes):
        out, err = pipes
        showing(monkeypatch, {**READY, "enabled": False})
        codex_remote_cli.main(["show"], out, err)
        assert "(switched off)" in out.getvalue()

    def test_it_says_the_desktop_app_does_not_share_one(self, monkeypatch, pipes):
        out, err = pipes
        showing(monkeypatch, READY)
        codex_remote_cli.main(["show"], out, err)
        assert "does not share one" in out.getvalue()


class TestTheActions:
    @pytest.mark.parametrize("command", ["start", "stop"])
    def test_starting_and_stopping_act_on_our_own_app_server(self, monkeypatch, pipes, command):
        out, err = pipes
        seen = []
        monkeypatch.setattr(codex_remote, command,
                            lambda environ=None: (seen.append(command), done())[1])
        assert codex_remote_cli.main([command], out, err) == 0
        assert seen == [command]
        assert "done" in out.getvalue()

    @pytest.mark.parametrize("command, function", [
        ("enable", "enable"), ("disable", "disable"),
        ("pair", "pairing_code"), ("remote", "remote_status")])
    def test_each_call_goes_to_its_own_function(self, monkeypatch, pipes, command, function):
        out, err = pipes
        seen = []
        monkeypatch.setattr(codex_remote_cli, "RPC_ACTIONS", {
            **codex_remote_cli.RPC_ACTIONS,
            command: lambda environ, opener: (seen.append(function), done())[1]})
        assert codex_remote_cli.main([command], out, err) == 0
        assert seen == [function]

    def test_every_rpc_action_names_a_real_function(self):
        for name, call in codex_remote_cli.RPC_ACTIONS.items():
            assert callable(call), name

    def test_a_pairing_code_is_printed(self, monkeypatch, pipes):
        out, err = pipes
        monkeypatch.setattr(codex_remote_cli, "RPC_ACTIONS", {
            "pair": lambda environ, opener: done({"manualPairingCode": "ABCD-1234"})})
        assert codex_remote_cli.main(["pair"], out, err) == 0
        assert "ABCD-1234" in out.getvalue()

    def test_a_refusal_goes_to_stderr_and_exits_one(self, monkeypatch, pipes):
        out, err = pipes
        monkeypatch.setattr(codex_remote, "start", lambda environ=None: refused(detail="why"))
        assert codex_remote_cli.main(["start"], out, err) == 1
        assert codex_remote.NOT_DONE[codex_remote.NO_HOST] in err.getvalue()
        assert "why" in err.getvalue()
        assert out.getvalue() == ""

    def test_clients_are_listed_as_json(self, monkeypatch, pipes):
        out, err = pipes
        monkeypatch.setattr(codex_remote, "clients",
                            lambda environ, opener: done({"data": [{"clientId": "c-1"}]}))
        assert codex_remote_cli.main(["clients"], out, err) == 0
        assert "c-1" in out.getvalue()

    def test_revoke_passes_the_id_it_was_given(self, monkeypatch, pipes):
        out, err = pipes
        seen = []
        monkeypatch.setattr(codex_remote, "revoke",
                            lambda client_id, environ, opener: (seen.append(client_id), done())[1])
        assert codex_remote_cli.main(["revoke", "c-7"], out, err) == 0
        assert seen == ["c-7"]

    def test_claimed_passes_the_code_and_which_kind_it_is(self, monkeypatch, pipes):
        out, err = pipes
        seen = []
        monkeypatch.setattr(codex_remote, "pairing_status",
                            lambda code, manual, environ, opener:
                            (seen.append((code, manual)), done())[1])
        codex_remote_cli.main(["claimed", "AB-12"], out, err)
        codex_remote_cli.main(["claimed", "ZZZZ", "--manual"], out, err)
        assert seen == [("AB-12", False), ("ZZZZ", True)]

    @pytest.mark.parametrize("argv", [["revoke"], ["claimed"]])
    def test_a_command_missing_its_argument_is_a_usage_error(self, pipes, argv):
        with pytest.raises(SystemExit) as stopped:
            codex_remote_cli.main(argv, *pipes)
        assert stopped.value.code == 2


class TestRendering:
    def test_a_dict_is_printed_as_json_and_a_string_as_itself(self):
        assert codex_remote_cli._text({"a": 1}) == '{\n  "a": 1\n}'
        assert codex_remote_cli._text("Remote control is enabled") == "Remote control is enabled"

    def test_every_need_has_something_to_do_about_it(self):
        """A need with no line under it would print as a bare word."""
        for need in (codex_remote.NO_CLI, "host", "remote_control"):
            assert need in codex_remote_cli.NEEDS
