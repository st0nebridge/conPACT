"""
The promises the Codex remote-control surface makes, anchored.

Remote control is the one Codex feature whose obvious implementation is the
wrong one. The relay has two halves, and the half that would reach a thread the
running desktop app holds is the *client* half - a device-keyed enrolment minted
behind a step-up authorisation on the user's ChatGPT account (D-20260921-032).
conPACT implements the host half only, on an app-server it runs itself, and
these tests are what stops that boundary being crossed by a later change that
looks like an improvement.
"""
import pathlib

import pytest

from conpact import codex_host, codex_remote, codex_remote_cli, codex_ws

SOURCES = {name: pathlib.Path(module.__file__).read_text(encoding="utf-8")
           for name, module in (("codex_remote", codex_remote), ("codex_host", codex_host),
                                ("codex_ws", codex_ws))}

# The client half, spelled as the binary spells it. Any of these appearing here
# means someone has started building the thing D-032 rules out.
CLIENT_ROLE = (
    "device_key", "deviceKey", "device_key_proof", "device_key_challenge",
    "remote_control_client_websocket", "enroll/start", "enroll/finish",
    "client/enroll", "getHandshake",
)


class TestItNeverBecomesARemoteControlClient:
    @pytest.mark.parametrize("marker", CLIENT_ROLE)
    def test_no_part_of_the_client_enrolment_is_here(self, marker):
        for name, source in SOURCES.items():
            assert marker not in source, name

    def test_nothing_here_reaches_off_this_machine(self):
        """Every address is loopback. A `wham/` or `chatgpt.com` URL would mean
        it had grown a network path of its own."""
        for name, source in SOURCES.items():
            for marker in ("wham/", "https://", "wss://"):
                assert marker not in source, f"{name}: {marker}"

    def test_the_listener_is_bound_to_loopback_and_nothing_else(self):
        assert codex_host.HOST == "127.0.0.1"
        argv = codex_appserver_listen()
        assert any(part.startswith("ws://127.0.0.1:") for part in argv)
        assert not any("0.0.0.0" in part for part in argv)


def codex_appserver_listen():
    from conpact import codex_appserver
    return codex_appserver.listen_args(codex_host.HOST, 5000, "d" * 64)


class TestTheListenerIsNotOpenToAnyone:
    def test_it_always_demands_a_token(self):
        """Measured: without `--ws-auth` the app-server accepts any local caller,
        and a local caller can drive the user's Codex account."""
        argv = codex_appserver_listen()
        assert "--ws-auth" in argv
        assert "capability-token" in argv

    def test_the_app_server_is_given_the_digest_rather_than_the_secret(self):
        token, digest = codex_host.mint_token()
        assert token not in codex_appserver_listen()
        assert digest != token


class TestTheDesktopAppIsNeverReachedThroughIt:
    def test_on_windows_the_desktop_never_shares_an_app_server(self):
        """So a thread the app holds stays refused (D-20260921-031). Measured
        from the app's own launcher: the first conjunct of the condition that
        picks the shared socket is `process.platform !== "win32"`."""
        assert codex_remote.desktop_shares_daemon("win32") == (
            False, codex_remote.WINDOWS_STDIO)

    def test_nothing_here_compacts_or_resumes_a_thread(self):
        for name, source in SOURCES.items():
            for method in ("thread/compact/start", "thread/resume", "thread/"):
                assert method not in source, f"{name}: {method}"


class TestNothingActsUnlessAsked:
    def test_the_actions_are_reached_only_by_naming_them(self):
        """Every state-changing path is a subcommand the user typed. `show` -
        the default - is not one of them."""
        assert codex_remote_cli.SHOW not in codex_remote_cli.RPC_ACTIONS
        assert codex_remote_cli.SHOW not in codex_remote_cli.HOST_ACTIONS
        assert set(codex_remote_cli.HOST_ACTIONS) == {"start", "stop"}
        assert set(codex_remote_cli.RPC_ACTIONS) == {"enable", "disable", "pair", "remote"}

    def test_reading_the_state_starts_nothing(self, tmp_path, monkeypatch):
        """`status` is what a report and a toast call. If it ever started an
        app-server, every listing would change the machine."""
        started = []
        monkeypatch.setattr(codex_host, "start",
                            lambda *a, **k: started.append(a) or {"done": True})
        codex_remote.status({"CODEX_HOME": str(tmp_path)},
                            asker=lambda url, timeout=None: (_ for _ in ()).throw(OSError()),
                            platform="win32")
        assert started == []

    def test_a_refusal_is_an_answer_rather_than_an_exception(self, tmp_path, monkeypatch):
        """A hook or a toast must never be crashed by a server that is not up."""
        monkeypatch.setattr(codex_host, "running", lambda environ=None, asker=None: {
            "running": False, "ready": False, "port": None, "pid": None})
        bare = {"CODEX_HOME": str(tmp_path)}
        for outcome in (codex_remote.enable(bare), codex_remote.disable(bare),
                        codex_remote.pairing_code(bare), codex_remote.remote_status(bare),
                        codex_remote.clients(bare), codex_remote.revoke("c-1", bare)):
            assert outcome["done"] is False
            assert outcome["reason"] == codex_remote.NO_HOST
            assert isinstance(outcome["message"], str)


class TestOurStateStaysOurs:
    def test_the_record_is_never_written_inside_codex_s_own_folder(self, tmp_path):
        """Our state lives in conPACT's own home (D-20260923-048), and D-030
        keeps everything of Codex's read-only."""
        record = str(codex_host.record_path()).replace("\\", "/")
        assert "/.codex/" not in record
        assert "/.conpact/" in record
