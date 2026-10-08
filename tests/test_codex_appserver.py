"""
@module tests.test_codex_appserver
@description The transport both Codex features share: finding the executable,
             the two argv that select a transport, and the handshake that is
             part of connecting rather than of the caller's work.
@input      conpact.codex_appserver, against a fake app-server process
@output     assertions on the wire literals, on what connect sends, and on the
            promise that a failed handshake leaves no process behind
@dependencies conpact.codex_appserver; stdlib: json
"""
import json
import time

import pytest
import plistlib

from conpact import codex_appserver


class FakeProcess:
    """An app-server that answers from a script instead of being one."""

    def __init__(self, replies, *, answer=True):
        self.replies, self.answer = list(replies), answer
        self.sent, self.lines, self.terminated, self.closed = [], [], False, False

    @property
    def stdin(self):
        return self

    def write(self, body):
        self.sent.append(json.loads(body))
        if not self.answer:
            return
        reply = self.replies[len(self.sent) - 1] if len(self.sent) <= len(self.replies) else {}
        self.lines.append(json.dumps({**reply, "id": self.sent[-1]["id"]}))

    def flush(self):
        pass

    def close(self):
        self.closed = self.terminated = True

    @property
    def stdout(self):
        while True:
            if self.lines:
                yield self.lines.pop(0)
            elif self.terminated or len(self.sent) >= len(self.replies) or not self.answer:
                return
            else:
                time.sleep(0.001)          # the caller has more to ask; do not spin

    def terminate(self):
        self.terminated = True


class TestTheWireLiterals:
    """Strings that are a contract with someone else's binary, asserted as
    literals: comparing them against the module's own constants cannot catch a
    rename, and a mutation run found exactly that (CU-20260921-034)."""

    def test_the_plain_transport_is_the_app_server_subcommand(self):
        assert codex_appserver.ARGS == ("app-server",)

    def test_the_shared_transport_is_the_proxy_to_the_control_socket(self):
        assert codex_appserver.PROXY_ARGS == ("app-server", "proxy")

    def test_the_paths_the_app_server_serves(self):
        assert codex_appserver.RPC_PATH == "/rpc"
        assert codex_appserver.READY_PATH == "/readyz"

    def test_the_handshake_is_the_method_codex_serves(self):
        assert codex_appserver.INITIALIZE == "initialize"

    def test_the_handshake_sends_a_name_and_a_version(self):
        assert codex_appserver.CLIENT == {"name": "conpact", "version": "1"}

    def test_the_handshake_asks_for_the_experimental_api(self):
        """Measured, not assumed: without it the app-server answers
        "remoteControl/status/read requires experimentalApi capability"."""
        assert codex_appserver.CAPABILITIES == {"experimentalApi": True}

    def test_the_executable_is_looked_for_where_codex_installs_it(self):
        assert codex_appserver.CLI_VAR == "CODEX_CLI_PATH"
        assert codex_appserver.CLI_GLOB == ("OpenAI", "Codex", "bin", "*", "codex.exe")


class TestFindingTheExecutable:
    def test_the_named_path_wins_when_it_is_really_there(self, tmp_path):
        cli = tmp_path / "codex.exe"
        cli.write_text("", encoding="utf-8")
        assert codex_appserver.codex_cli({"CODEX_CLI_PATH": str(cli)}) == cli

    def test_a_named_path_that_is_not_there_is_ignored(self, tmp_path):
        env = {"CODEX_CLI_PATH": str(tmp_path / "gone.exe"),
               "LOCALAPPDATA": str(tmp_path / "nowhere"), "PATH": str(tmp_path / "nowhere")}
        assert codex_appserver.codex_cli(env) is None


class TestConnecting:
    def test_the_handshake_is_sent_and_the_server_handed_back(self, tmp_path):
        process = FakeProcess([{"result": {}}])
        server = codex_appserver.connect("codex.exe", spawn=lambda c, e: process)
        try:
            assert process.sent[0]["method"] == "initialize"
            assert process.sent[0]["params"] == {
                "clientInfo": {"name": "conpact", "version": "1"},
                "capabilities": {"experimentalApi": True}}
        finally:
            server.close()

    def test_the_transport_argv_is_the_executable_then_the_subcommand(self):
        seen = []

        def spy(command, environ):
            seen.append(command)
            return FakeProcess([{"result": {}}])

        codex_appserver.connect("codex.exe", codex_appserver.PROXY_ARGS, spawn=spy).close()
        assert seen == [["codex.exe", "app-server", "proxy"]]

    def test_a_server_that_will_not_handshake_is_shut_down_before_the_error_leaves(self):
        """Otherwise a refused connection leaks a process for every attempt."""
        process = FakeProcess([], answer=False)
        with pytest.raises(TimeoutError):
            codex_appserver.connect("codex.exe", spawn=lambda c, e: process)
        assert (process.closed, process.terminated) == (True, True)

    def test_without_an_injected_spawn_the_real_starter_is_looked_up_at_call_time(
            self, _isolate_user_state):
        """A default bound at import would sail straight past the guard that
        stands for 'no test starts a real app-server' (D-20260920-018)."""
        with pytest.raises(AssertionError):
            codex_appserver.connect("codex.exe")
        assert _isolate_user_state == ["start a codex app-server"]
        _isolate_user_state.clear()


class TestTheListener:
    """`--listen ws://IP:PORT` is the transport that outlives its caller, and the
    only one open to us: the shared daemon's socket is AF_UNIX, which Python on
    Windows cannot open, and the daemon will not run from this CLI anyway."""

    def test_the_argv_binds_one_loopback_port_behind_a_token(self):
        assert codex_appserver.listen_args("127.0.0.1", 5000, "abc123") == (
            "app-server", "--listen", "ws://127.0.0.1:5000",
            "--ws-auth", "capability-token", "--ws-token-sha256", "abc123")

    def test_only_the_digest_is_named_never_a_token_file(self):
        """Measured: the server refuses every upgrade with 401 unless the caller
        presents the token, and it is given only the SHA-256 of it, so the secret
        never reaches the app-server process."""
        argv = codex_appserver.listen_args("127.0.0.1", 1, "d" * 64)
        assert "--ws-token-file" not in argv
        assert "--ws-shared-secret-file" not in argv


class TestTheConversationOverAWebSocket:
    class FakeConnection:
        def __init__(self, *messages):
            self.messages = list(messages)
            self.sent, self.closed = [], False
            self.sock = self

        def settimeout(self, value):
            self.timeout = value

        def send(self, text):
            self.sent.append(json.loads(text))

        def recv(self):
            if not self.messages:
                raise OSError("closed")
            reply = self.messages.pop(0)
            return json.dumps({**reply, "id": self.sent[-1]["id"]}
                              if reply.get("id") is None else reply)

        def close(self):
            self.closed = True

    def test_a_reply_is_matched_by_id_and_everything_else_dropped(self):
        connection = self.FakeConnection({"id": "someone-else", "result": {"wrong": True}},
                                         {"result": {"right": True}})
        server = codex_appserver.WebSocketServer(connection)
        assert server.request("m", {}, 5)["result"] == {"right": True}

    def test_the_deadline_is_put_on_the_socket(self):
        """A socket read can be given one; a Windows pipe read cannot, which is
        why this transport needs no reader thread."""
        connection = self.FakeConnection({"result": {}})
        codex_appserver.WebSocketServer(connection).request("m", {}, 12.5)
        assert 0 < connection.timeout <= 12.5

    def test_the_handshake_is_sent_before_the_server_is_handed_back(self, monkeypatch):
        connection = self.FakeConnection({"result": {}})
        monkeypatch.setattr(codex_appserver.codex_ws, "connect",
                            lambda *a, **k: connection)
        server = codex_appserver.connect_ws("h", 1, "t")
        assert connection.sent[0]["method"] == "initialize"
        assert connection.sent[0]["params"]["capabilities"] == {"experimentalApi": True}
        server.close()

    def test_a_server_that_will_not_handshake_is_closed_before_the_error_leaves(
            self, monkeypatch):
        connection = self.FakeConnection()
        monkeypatch.setattr(codex_appserver.codex_ws, "connect", lambda *a, **k: connection)
        with pytest.raises(OSError):
            codex_appserver.connect_ws("h", 1, "t")
        assert connection.closed is True


# --- which codex the desktop runs, off Windows --------------------------------

def _build(path, mtime):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"codex")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def bundles(tmp_path, monkeypatch):
    """The platforms' install places, moved under tmp_path."""
    system = tmp_path / "system"
    monkeypatch.setattr(codex_appserver, "BUNDLED", {
        "darwin": ((str(system / "Applications" / "ChatGPT.app"),
                    "Contents/Resources/codex"),
                   (str(tmp_path / "home" / "Applications" / "ChatGPT.app"),
                    "Contents/Resources/codex")),
        "linux": ((str(system / "opt"), "*/resources/codex"),
                  ("~/.local/share", "*/resources/codex")),
    })
    return system


def test_on_macos_the_codex_inside_the_newest_app_bundle_is_the_one(tmp_path, bundles):
    """The active system or user ChatGPT installation may supply Codex."""
    old = _build(bundles / "Applications" / "ChatGPT.app" / "Contents" / "Resources" / "codex", 1000)
    new = _build(tmp_path / "home" / "Applications" / "ChatGPT.app" / "Contents" / "Resources" / "codex", 2000)
    env = {"HOME": str(tmp_path / "home")}
    assert codex_appserver.newest_build(env, "darwin") == new
    new.unlink()
    assert codex_appserver.newest_build(env, "darwin") == old


def test_on_linux_the_codex_in_an_apps_resources_folder_is_the_one(tmp_path, bundles):
    found = _build(bundles / "opt" / "ChatGPT" / "resources" / "codex", 1000)
    assert codex_appserver.newest_build({"HOME": str(tmp_path)}, "linux") == found


def test_a_folder_named_codex_is_not_a_build(tmp_path, bundles):
    (bundles / "opt" / "Odd" / "resources" / "codex").mkdir(parents=True)
    assert codex_appserver.newest_build({"HOME": str(tmp_path)}, "linux") is None


def test_localappdata_wins_wherever_it_is_set(tmp_path, bundles):
    """Windows' own variable: a cygwin or msys Python on Windows still finds the
    per-version folders, and a Mac bundle is never consulted there."""
    _build(bundles / "Applications" / "ChatGPT.app" / "Contents" / "Resources" / "codex", 9000)
    win = _build(tmp_path / "local" / "OpenAI" / "Codex" / "bin" / "abc" / "codex.exe", 1000)
    env = {"LOCALAPPDATA": str(tmp_path / "local"), "HOME": str(tmp_path)}
    assert codex_appserver.newest_build(env, "darwin") == win


def test_empty_localappdata_does_not_fall_through_to_a_host_bundle(tmp_path, monkeypatch):
    """An isolated Windows-shaped lookup must not discover the Mac host's app."""
    monkeypatch.setattr(
        codex_appserver,
        "_bundled",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an explicit LOCALAPPDATA must end the lookup")),
    )
    env = {"LOCALAPPDATA": str(tmp_path / "empty")}
    assert codex_appserver.newest_build(env, "darwin") is None


def test_windows_without_localappdata_has_no_bundle_to_look_in(tmp_path, bundles):
    _build(bundles / "opt" / "ChatGPT" / "resources" / "codex", 1000)
    assert codex_appserver.newest_build({"HOME": str(tmp_path)}, "win32") is None


def test_the_real_install_places_are_the_platforms_standard_ones():
    assert codex_appserver.BUNDLED["darwin"][0] == (
        "/Applications/ChatGPT.app", "Contents/Resources/codex")
    assert codex_appserver.BUNDLED["darwin"][1] == (
        "/Applications/ChatGPT.app",
        "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    )
    assert [base for base, _ in codex_appserver.BUNDLED["linux"]] == ["/opt", "/usr/lib", "~/.local/share"]


def test_a_selected_codex_names_its_outer_app_bundle_and_version(tmp_path):
    app = tmp_path / "ChatGPT.app"
    executable = app / "Contents" / "Resources" / "codex-cli" / \
        "CodexCLI.app" / "Contents" / "MacOS" / "codex"
    executable.parent.mkdir(parents=True)
    executable.touch()
    with open(app / "Contents" / "Info.plist", "wb") as handle:
        plistlib.dump({"CFBundleShortVersionString": "26.1002.52244"}, handle)

    assert codex_appserver.bundle_details(executable) == {
        "bundle": str(app), "version": "26.1002.52244"}
