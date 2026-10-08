"""
@module tests.test_codex_env
@description The one persistent user environment variable the sidecar install
             depends on, on all three platforms from whichever one is running
             the tests: what each backend stores, that reading gives back what
             was written, that clearing one key leaves another alone, and that a
             value with a space, a quote or an `&` in it survives the file it is
             stored in.
@input      conpact.codex_env, against a fake registry and a fake launchctl
@output     assertions per platform on get / set_value / clear, and on the shapes
            written to disk
@dependencies conpact.codex_env; stdlib: plistlib
"""
import plistlib

import pytest

from conpact import codex_env

KEY = "CODEX_CLI_PATH"
AWKWARD = "/Applications/My Tools/py thon & co/codex"


class FakeWinreg:
    """`winreg`, in memory: one HKCU\\Environment key."""
    KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1
    HKEY_CURRENT_USER = object()

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.closed = 0

    # -- the handle is the store itself, so an injected opener is trivial --
    def OpenKey(self, root, sub, reserved, access):
        return self.values

    def QueryValueEx(self, handle, name):
        if name not in handle:
            raise FileNotFoundError(name)
        return handle[name], self.REG_SZ

    def SetValueEx(self, handle, name, reserved, kind, value):
        handle[name] = value

    def DeleteValue(self, handle, name):
        if name not in handle:
            raise FileNotFoundError(name)
        del handle[name]

    def CloseKey(self, handle):
        self.closed += 1


class FakeLaunchctl:
    """`launchctl` as a runner with distinct caller and GUI domains."""

    def __init__(self):
        self.caller, self.gui, self.calls = {}, {}, []
        self.session = self.caller

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[1] == "print":
            body = "\n".join(f"\t\t{k} => {v}" for k, v in self.gui.items())
            return type("Result", (), {"stdout": f"environment = {{\n{body}\n}}\n",
                                        "returncode": 0})()
        target, offset = (self.gui, 4) if argv[1] == "asuser" else (self.caller, 1)
        verb, key = argv[offset], argv[offset + 1]
        if verb == "setenv":
            target[key] = argv[offset + 2]
        elif verb == "unsetenv":
            target.pop(key, None)
        return type("Result", (), {"stdout": target.get(key, ""), "returncode": 0})()


@pytest.fixture
def registry(monkeypatch):
    """A whole registry in memory, standing in for both the module and the key
    the backend opens - so the Windows path is exercised from any machine, and
    the conftest guard that forbids the real one stays in force everywhere
    else."""
    fake = FakeWinreg()
    fake.broadcasts = 0
    monkeypatch.setattr(codex_env, "_winreg", lambda: fake)
    monkeypatch.setattr(codex_env, "_win_open", lambda access: fake.values)
    monkeypatch.setattr(codex_env, "_win_broadcast",
                        lambda: setattr(fake, "broadcasts", fake.broadcasts + 1))
    return fake


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_env, "HOME", tmp_path)
    return tmp_path


class TestWhichPlatform:
    @pytest.mark.parametrize("given,expected", [
        ("win32", codex_env.WINDOWS), ("cygwin", codex_env.LINUX),
        ("darwin", codex_env.MACOS), ("linux", codex_env.LINUX),
        ("linux2", codex_env.LINUX), ("freebsd13", codex_env.LINUX)])
    def test_the_platform_is_named_from_the_prefix(self, given, expected):
        assert codex_env.platform_name(given) == expected

    def test_every_platform_says_how_the_change_reaches_a_gui_app(self):
        for platform in ("win32", "darwin", "linux"):
            note = codex_env.store_note(platform)
            assert note and note[-1] == "."


class TestWindows:
    def test_a_value_is_written_read_back_and_cleared(self, registry):
        codex_env.set_value(KEY, AWKWARD, "win32")
        assert registry.values[KEY] == AWKWARD
        assert codex_env.get(KEY, "win32") == AWKWARD
        codex_env.clear(KEY, "win32")
        assert KEY not in registry.values
        assert codex_env.get(KEY, "win32") is None

    def test_a_key_that_was_never_set_reads_as_nothing(self, registry):
        assert codex_env.get(KEY, "win32") is None

    def test_clearing_a_key_that_is_not_there_is_not_an_error(self, registry):
        assert codex_env.clear(KEY, "win32") is True

    def test_the_change_is_broadcast_so_new_processes_see_it(self, registry):
        codex_env.set_value(KEY, "x", "win32")
        assert registry.broadcasts == 1

    def test_every_handle_it_opens_it_closes(self, registry):
        codex_env.set_value(KEY, "x", "win32")
        codex_env.get(KEY, "win32")
        codex_env.clear(KEY, "win32")
        assert registry.closed == 3

    def test_an_injected_opener_is_used_instead_of_the_real_key(self, registry):
        asked = []
        codex_env.set_value(KEY, "x", "win32",
                            opener=lambda access: asked.append(access) or registry.values)
        assert asked == [FakeWinreg.KEY_SET_VALUE]

    def test_an_environment_key_that_will_not_open_reads_as_nothing(self, registry):
        def refuse(access):
            raise OSError("no such key")
        assert codex_env.get(KEY, "win32", opener=refuse) is None


class TestMacOS:
    def test_a_value_is_set_in_the_session_and_in_a_login_agent(self, home):
        launchctl = FakeLaunchctl()
        codex_env.set_value(KEY, AWKWARD, "darwin", runner=launchctl)
        assert launchctl.session[KEY] == AWKWARD
        assert launchctl.gui[KEY] == AWKWARD
        assert codex_env.agent_path().is_file()
        with open(codex_env.agent_path(), "rb") as handle:
            plist = plistlib.load(handle)
        assert plist["Label"] == codex_env.AGENT_LABEL
        assert plist["RunAtLoad"] is True
        assert plist[codex_env.AGENT_RECORD] == {KEY: AWKWARD}

    def test_the_agent_command_keeps_an_awkward_value_as_one_argument(self, home):
        codex_env.set_value(KEY, AWKWARD, "darwin", runner=FakeLaunchctl())
        with open(codex_env.agent_path(), "rb") as handle:
            command = plistlib.load(handle)["ProgramArguments"][-1]
        assert "'" in command or '"' in command          # it was quoted
        assert AWKWARD in command

    def test_the_value_is_read_back_from_the_running_session(self, home):
        launchctl = FakeLaunchctl()
        codex_env.set_value(KEY, "/x/codex", "darwin", runner=launchctl)
        assert codex_env.get(KEY, "darwin", runner=launchctl) == "/x/codex"

    def test_before_the_next_login_the_agent_is_what_answers(self, home):
        """launchctl was not told (a different session), but the agent holds it."""
        codex_env.set_value(KEY, "/x/codex", "darwin", runner=FakeLaunchctl())
        assert codex_env.get(KEY, "darwin", runner=FakeLaunchctl()) == "/x/codex"

    def test_clearing_removes_it_from_the_session_and_the_agent(self, home):
        launchctl = FakeLaunchctl()
        codex_env.set_value(KEY, "/x/codex", "darwin", runner=launchctl)
        codex_env.clear(KEY, "darwin", runner=launchctl)
        assert KEY not in launchctl.session
        assert KEY not in launchctl.gui
        assert codex_env.agent_path().is_file() is False     # it set nothing else
        assert codex_env.get(KEY, "darwin", runner=launchctl) is None

    def test_clearing_one_key_leaves_another_we_set_alone(self, home):
        launchctl = FakeLaunchctl()
        codex_env.set_value(KEY, "/x/codex", "darwin", runner=launchctl)
        codex_env.set_value("OTHER", "/y", "darwin", runner=launchctl)
        codex_env.clear(KEY, "darwin", runner=launchctl)
        assert codex_env.get("OTHER", "darwin", runner=launchctl) == "/y"
        assert codex_env.get(KEY, "darwin", runner=launchctl) is None

    def test_no_agent_reads_as_nothing(self, home):
        assert codex_env.get(KEY, "darwin", runner=FakeLaunchctl()) is None

    def test_an_unreadable_agent_reads_as_nothing_rather_than_raising(self, home):
        codex_env.agent_path().parent.mkdir(parents=True, exist_ok=True)
        codex_env.agent_path().write_text("not a plist", encoding="utf-8")
        assert codex_env.get(KEY, "darwin", runner=FakeLaunchctl()) is None

    def test_a_launchctl_that_is_not_there_is_not_an_error(self, home):
        def missing(argv):
            raise OSError("launchctl: not found")
        codex_env.set_value(KEY, "/x/codex", "darwin", runner=FakeLaunchctl())
        assert codex_env.get(KEY, "darwin", runner=missing) == "/x/codex"

    def test_clearing_reaches_a_stale_gui_value_when_the_caller_has_none(self, home):
        launchctl = FakeLaunchctl()
        launchctl.gui[KEY] = "/x/codex"

        codex_env.clear(KEY, "darwin", runner=launchctl)

        assert KEY not in launchctl.gui

    def test_status_separates_persistent_caller_and_gui_values(self, home):
        launchctl = FakeLaunchctl()
        launchctl.caller[KEY] = "/caller/codex"
        launchctl.gui[KEY] = "/gui/codex"

        status = codex_env.status(KEY, "darwin", runner=launchctl)

        assert status == {
            "persistent": None,
            "caller": "/caller/codex",
            "gui": "/gui/codex",
            "effective": "/gui/codex",
            "discrepancy": True,
        }


class TestLinux:
    def test_a_value_is_written_to_the_environment_d_drop_in(self, home):
        codex_env.set_value(KEY, AWKWARD, "linux")
        body = codex_env.envd_path().read_text(encoding="utf-8")
        assert body == f'{KEY}="{AWKWARD}"\n'
        assert codex_env.get(KEY, "linux") == AWKWARD

    def test_a_value_with_a_space_survives_the_round_trip(self, home):
        codex_env.set_value(KEY, "/opt/my codex/codex", "linux")
        assert codex_env.get(KEY, "linux") == "/opt/my codex/codex"

    def test_clearing_one_key_leaves_another_we_set_alone(self, home):
        codex_env.set_value(KEY, "/x/codex", "linux")
        codex_env.set_value("OTHER", "/y", "linux")
        codex_env.clear(KEY, "linux")
        assert codex_env.get("OTHER", "linux") == "/y"
        assert codex_env.get(KEY, "linux") is None

    def test_clearing_the_last_key_removes_the_file(self, home):
        codex_env.set_value(KEY, "/x/codex", "linux")
        codex_env.clear(KEY, "linux")
        assert codex_env.envd_path().is_file() is False

    def test_no_drop_in_reads_as_nothing(self, home):
        assert codex_env.get(KEY, "linux") is None

    def test_comments_and_blank_lines_are_ignored(self, home):
        codex_env.envd_path().parent.mkdir(parents=True, exist_ok=True)
        codex_env.envd_path().write_text(f'# a note\n\n{KEY}="/x/codex"\n', encoding="utf-8")
        assert codex_env.get(KEY, "linux") == "/x/codex"

    def test_clearing_a_key_that_is_not_there_is_not_an_error(self, home):
        assert codex_env.clear(KEY, "linux") is True


class TestTheExactShapesItWrites:
    """Mutation testing found these blind: the tests above assert through the
    module's own constants, so changing what `launchctl` is actually called with,
    or which folder a file lands in, or whether a write reports success, changed
    nothing any assertion could see. These name the literals."""

    def test_the_platform_names_are_the_ones_sys_platform_reports(self):
        assert (codex_env.WINDOWS, codex_env.MACOS, codex_env.LINUX) == \
            ("win32", "darwin", "linux")

    @pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
    def test_a_completed_write_says_so(self, platform, registry, home, monkeypatch):
        monkeypatch.setattr(codex_env, "_run", FakeLaunchctl())
        assert codex_env.set_value(KEY, "/x", platform) is True
        assert codex_env.clear(KEY, platform) is True

    def test_clearing_on_windows_broadcasts_too(self, registry):
        """Otherwise a shell started afterwards still has the old value."""
        codex_env.set_value(KEY, "/x", "win32")
        codex_env.clear(KEY, "win32")
        assert registry.broadcasts == 2

    @pytest.mark.parametrize("value", [b"bytes", 42, ""])
    def test_a_registry_value_that_is_not_a_string_reads_as_nothing(self, registry, value):
        registry.values[KEY] = value
        assert codex_env.get(KEY, "win32") is None

    def test_the_login_agent_lands_where_launchd_looks(self, home):
        assert codex_env.agent_path() == home / "Library" / "LaunchAgents" / \
            "com.conpact.codexcli.plist"

    def test_the_drop_in_lands_where_systemd_looks(self, home):
        assert codex_env.envd_path() == home / ".config" / "environment.d" / \
            "10-conpact-codex.conf"

    def test_the_agent_runs_launchctl_setenv_under_a_shell(self, home):
        codex_env.set_value(KEY, "/x/codex", "darwin", runner=FakeLaunchctl())
        with open(codex_env.agent_path(), "rb") as handle:
            argv = plistlib.load(handle)["ProgramArguments"]
        assert argv[:2] == ["/bin/sh", "-c"]
        assert argv[2] == f"launchctl setenv {KEY} /x/codex"

    def test_two_variables_are_both_applied_at_login(self, home):
        runner = FakeLaunchctl()
        codex_env.set_value(KEY, "/x", "darwin", runner=runner)
        codex_env.set_value("OTHER", "/y", "darwin", runner=runner)
        with open(codex_env.agent_path(), "rb") as handle:
            command = plistlib.load(handle)["ProgramArguments"][2]
        assert command == f"launchctl setenv {KEY} /x && launchctl setenv OTHER /y"

    @pytest.mark.parametrize("verb,call", [
        ("setenv", lambda r: codex_env.set_value(KEY, "/x", "darwin", runner=r)),
        ("unsetenv", lambda r: codex_env.clear(KEY, "darwin", runner=r)),
        ("getenv", lambda r: codex_env.get(KEY, "darwin", runner=r))])
    def test_launchctl_is_called_with_the_argv_it_documents(self, home, verb, call):
        runner = FakeLaunchctl()
        call(runner)
        asked = [argv for argv in runner.calls if len(argv) > 2 and argv[1] == verb]
        assert asked, f"launchctl {verb} was never called"
        assert asked[0][0] == "/bin/launchctl"
        assert asked[0][:3] == ["/bin/launchctl", verb, KEY]

    @pytest.mark.parametrize("verb,call", [
        ("setenv", lambda r: codex_env.set_value(KEY, "/x", "darwin", runner=r)),
        ("unsetenv", lambda r: codex_env.clear(KEY, "darwin", runner=r))])
    def test_macos_changes_target_the_gui_bootstrap_domain(self, home, verb, call):
        runner = FakeLaunchctl()
        call(runner)
        assert ["/bin/launchctl", "asuser", str(__import__("os").getuid()),
                "/bin/launchctl", verb, KEY] in [argv[:6] for argv in runner.calls]
        assert ["/bin/launchctl", "print", f"gui/{__import__('os').getuid()}"] \
            in runner.calls

    def test_what_launchctl_prints_is_stripped(self, home):
        class Padded(FakeLaunchctl):
            def __call__(self, argv):
                return type("Result", (), {"stdout": "  /x/codex \n", "returncode": 0})()
        assert codex_env.get(KEY, "darwin", runner=Padded()) == "/x/codex"

    def test_a_launchctl_that_prints_nothing_is_nothing(self, home):
        class Silent(FakeLaunchctl):
            def __call__(self, argv):
                return type("Result", (), {"stdout": "   \n", "returncode": 0})()
        assert codex_env.get(KEY, "darwin", runner=Silent()) is None

    def test_a_drop_in_line_with_no_value_is_ignored(self, home):
        codex_env.envd_path().parent.mkdir(parents=True, exist_ok=True)
        codex_env.envd_path().write_text(f"{KEY}=\n", encoding="utf-8")
        assert codex_env.get(KEY, "linux") is None

    def test_an_unquoted_drop_in_value_is_read_too(self, home):
        """systemd accepts both; a file a user edited by hand must still parse."""
        codex_env.envd_path().parent.mkdir(parents=True, exist_ok=True)
        codex_env.envd_path().write_text(f"{KEY}=/x/codex\n", encoding="utf-8")
        assert codex_env.get(KEY, "linux") == "/x/codex"

    def test_a_one_character_value_is_not_mistaken_for_a_quote(self, home):
        codex_env.set_value(KEY, '"', "linux")
        assert codex_env.get(KEY, "linux") == '"'


class TestEachPlatformGoesToItsOwnBackend:
    """A dispatch that sent macOS to the Linux backend would still pass every
    test above, because each one names its own platform."""

    def test_windows_touches_the_registry_and_no_file(self, registry, home):
        codex_env.set_value(KEY, "/x", "win32")
        assert registry.values == {KEY: "/x"}
        assert codex_env.agent_path().exists() is False
        assert codex_env.envd_path().exists() is False

    def test_macos_writes_the_agent_and_not_the_drop_in(self, registry, home):
        codex_env.set_value(KEY, "/x", "darwin", runner=FakeLaunchctl())
        assert codex_env.agent_path().is_file()
        assert codex_env.envd_path().exists() is False
        assert registry.values == {}

    def test_linux_writes_the_drop_in_and_not_the_agent(self, registry, home):
        codex_env.set_value(KEY, "/x", "linux")
        assert codex_env.envd_path().is_file()
        assert codex_env.agent_path().exists() is False
        assert registry.values == {}
