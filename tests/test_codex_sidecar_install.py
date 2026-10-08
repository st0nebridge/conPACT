"""
@module tests.test_codex_sidecar_install
@description Putting the shim in the desktop's path and taking it out, on all
             three platforms from whichever one is running the tests: the shim it
             makes (compiled on Windows, generated everywhere else), the marker it
             writes, the one user-scope env key it sets, what it refuses to
             half-do, and the promise that uninstall leaves a CODEX_CLI_PATH the
             user set themselves alone.
@input      conpact.codex_sidecar_install, against a fake env store and a
            fake compiler
@output     assertions on build, status, install, uninstall and every refusal
@dependencies conpact.codex_sidecar_install, conpact.codex_env; stdlib:
              pathlib
"""
import os
import pathlib

import pytest

from conpact import codex_appserver, codex_env, codex_inject, detach
from conpact import codex_sidecar_install as si

WINDOWS, MACOS, LINUX = "win32", "darwin", "linux"


class FakeStore:
    """The user's environment, in memory, whatever the platform stores it in."""

    def __init__(self):
        self.values, self.caller, self.gui, self.broadcasts = {}, {}, {}, 0

    def opener(self, access):
        return self.values

    def broadcaster(self):
        self.broadcasts += 1

    def runner(self, argv):
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


def put(store, platform, value):
    """Set CODEX_CLI_PATH the way that platform stores it."""
    codex_env.set_value(si.ENV_KEY, value, platform, opener=store.opener,
                        broadcaster=store.broadcaster, runner=store.runner)


def stored(store, platform):
    """What CODEX_CLI_PATH is now, however that platform stores it."""
    return si.read_env(platform, store.opener, store.runner)


@pytest.fixture
def store(monkeypatch):
    """One store for every backend, so a test reads as "the user's environment"
    rather than as a registry or a plist."""
    fake = FakeStore()

    class Winreg:
        KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1

        def QueryValueEx(self, handle, name):
            if name not in handle:
                raise FileNotFoundError(name)
            return handle[name], 1

        def SetValueEx(self, handle, name, reserved, kind, value):
            handle[name] = value

        def DeleteValue(self, handle, name):
            handle.pop(name, None)

        def CloseKey(self, handle):
            pass

    monkeypatch.setattr(codex_env, "_winreg", Winreg)
    monkeypatch.setattr(codex_env, "_win_open", lambda access: fake.values)
    monkeypatch.setattr(codex_env, "_win_broadcast", fake.broadcaster)
    monkeypatch.setattr(codex_env, "_run", fake.runner)
    return fake


@pytest.fixture
def here(monkeypatch, tmp_path):
    """The sidecar folder, somewhere harmless."""
    monkeypatch.setattr(si, "sidecar_dir", lambda: tmp_path)
    monkeypatch.setattr(codex_inject, "read_record", lambda: None)
    return tmp_path


@pytest.fixture
def built(monkeypatch, here, request):
    """A shim and a real codex, both present, for the platform under test."""
    platform = getattr(request, "param", WINDOWS)
    exe = here / si.sidecar_exe_name(platform)
    exe.write_text("", encoding="utf-8")
    real = here / "codex"
    real.write_text("", encoding="utf-8")
    monkeypatch.setattr(si, "real_codex", lambda environ=None: real)
    return {"exe": exe, "real": real, "platform": platform}


EVERY = [WINDOWS, MACOS, LINUX]


class TestTheShimIsNamedForItsPlatform:
    def test_windows_needs_an_exe_because_that_is_all_the_desktop_can_spawn(self):
        assert si.sidecar_exe_name(WINDOWS) == "codex_sidecar.exe"

    @pytest.mark.parametrize("platform", [MACOS, LINUX])
    def test_elsewhere_it_is_a_plain_executable(self, platform):
        assert si.sidecar_exe_name(platform) == "codex_sidecar"


class TestBuildingTheShim:
    @pytest.mark.parametrize("platform", [MACOS, LINUX])
    def test_on_posix_it_is_generated_and_needs_no_compiler(self, here, platform):
        got = si.build(platform, python="/usr/bin/python3")
        assert got["done"] is True
        body = si.sidecar_exe(platform).read_text(encoding="utf-8")
        assert body.startswith("#!/bin/sh")
        assert "-m conpact.codex_sidecar" in body
        assert "/usr/bin/python3" in body

    @pytest.mark.parametrize("platform", [MACOS, LINUX])
    def test_the_generated_shim_is_made_executable(self, here, platform, monkeypatch):
        """Asked for, not read back: Windows has no execute bit to observe, and
        this suite must measure the same thing on every machine."""
        asked = []
        monkeypatch.setattr(pathlib.Path, "chmod",
                            lambda self, mode, **k: asked.append(mode))
        si.build(platform, python="/usr/bin/python3")
        assert asked and all(mode & 0o111 for mode in asked)

    def test_a_python_whose_path_has_a_space_is_still_one_word(self, here):
        si.build(LINUX, python="/opt/my tools/python3")
        body = si.sidecar_exe(LINUX).read_text(encoding="utf-8")
        assert "'/opt/my tools/python3'" in body

    def test_the_generated_shim_passes_every_argument_through(self, here):
        si.build(LINUX, python="/usr/bin/python3")
        assert '"$@"' in si.sidecar_exe(LINUX).read_text(encoding="utf-8")

    def test_the_generated_shim_names_the_folder_the_marker_is_in(self, here):
        """Run as `python -m`, argv[0] is inside the package, so the shim has to
        say where it lives or the marker is never found."""
        si.build(LINUX, python="/usr/bin/python3")
        body = si.sidecar_exe(LINUX).read_text(encoding="utf-8")
        assert "CONPACT_SIDECAR_DIR=" in body and str(here) in body

    def test_on_windows_the_launcher_is_told_the_interpreter_and_the_root(self, here):
        si.build(WINDOWS, runner=lambda argv, cwd=None: _made(here), python=r"C:\py\python.exe")
        lines = si.launcher_config().read_text(encoding="utf-8").splitlines()
        assert lines[0] == r"C:\py\python.exe"
        assert lines[1] == str(si.src_root())

    def test_on_windows_an_exe_that_is_already_there_is_not_rebuilt(self, here):
        (here / "codex_sidecar.exe").write_text("", encoding="utf-8")
        ran = []
        got = si.build(WINDOWS, runner=lambda argv, cwd=None: ran.append(argv))
        assert got["done"] is True and ran == []

    def test_on_windows_a_compiler_that_produces_nothing_is_said_plainly(self, here):
        (here / "build.cmd").write_text("", encoding="utf-8")
        got = si.build(WINDOWS, runner=lambda argv, cwd=None: _output("clang not found"))
        assert got["done"] is False
        assert "compiler" in got["message"].lower() or "clang" in got["message"].lower()
        assert got["detail"] == "clang not found"

    def test_on_windows_a_missing_build_script_is_said_plainly(self, here):
        got = si.build(WINDOWS, runner=lambda argv, cwd=None: None)
        assert got["done"] is False and "build" in got["message"].lower()

    def test_a_compiler_that_will_not_start_is_reported_not_raised(self, here):
        (here / "build.cmd").write_text("", encoding="utf-8")

        def explode(argv, cwd=None):
            raise OSError("no shell")

        got = si.build(WINDOWS, runner=explode)
        assert got["done"] is False and "OSError" in got["detail"]


def _made(where):
    (where / "codex_sidecar.exe").write_text("", encoding="utf-8")
    return _output("built")


def _output(text):
    return type("Result", (), {"stdout": text, "stderr": "", "returncode": 0})()


class TestStatus:
    @pytest.mark.parametrize("platform", EVERY)
    def test_nothing_built_reads_as_not_installed(self, here, store, platform):
        got = si.status(platform=platform, opener=store.opener, runner=store.runner)
        assert got["built"] is False
        assert got["installed"] is False
        assert got["platform"] == codex_env.platform_name(platform)

    @pytest.mark.parametrize("built", EVERY, indirect=True)
    def test_built_and_pointed_at_reads_as_installed(self, built, store):
        platform = built["platform"]
        si.marker_path().write_text(str(built["real"]), encoding="utf-8")
        put(store, platform, str(built["exe"]))
        got = si.status(platform=platform, opener=store.opener, runner=store.runner)
        assert got["installed"] is True
        assert got["env_points_at_shim"] is True

    def test_a_running_shim_is_seen(self, built, store, monkeypatch):
        monkeypatch.setattr(codex_inject, "read_record", lambda: {"pid": 4242})
        monkeypatch.setattr(detach, "pid_alive", lambda pid, *a, **k: True)
        got = si.status(platform=WINDOWS, opener=store.opener, runner=store.runner)
        assert got["sidecar_running"] is True

    def test_an_env_pointing_elsewhere_is_not_installed(self, built, store):
        si.marker_path().write_text(str(built["real"]), encoding="utf-8")
        put(store, WINDOWS, r"C:\somewhere\else\codex.exe")
        got = si.status(platform=WINDOWS, opener=store.opener, runner=store.runner)
        assert got["env_points_at_shim"] is False
        assert got["installed"] is False

    @pytest.mark.parametrize("platform", EVERY)
    def test_it_says_how_the_change_will_reach_the_desktop(self, here, store, platform):
        got = si.status(platform=platform, opener=store.opener, runner=store.runner)
        assert got["store_note"] == codex_env.store_note(platform)

    def test_macos_status_exposes_each_bootstrap_domain(self, here, store, monkeypatch):
        monkeypatch.setattr(codex_env, "HOME", here)
        store.caller[si.ENV_KEY] = "/caller/codex"
        store.gui[si.ENV_KEY] = "/gui/codex"

        got = si.status(platform=MACOS, runner=store.runner)

        assert got["env_persistent_value"] is None
        assert got["env_caller_value"] == "/caller/codex"
        assert got["env_gui_value"] == "/gui/codex"
        assert got["env_value"] == "/gui/codex"
        assert got["env_discrepancy"] is True

    def test_status_reports_derived_config_that_can_restore_the_override(
            self, here, store):
        codex = here / ".codex"
        cached = codex / "plugins" / "cache" / "example" / ".mcp.json"
        cached.parent.mkdir(parents=True)
        (codex / "config.toml").write_text(
            'env = { CODEX_CLI_PATH = "/old/sidecar" }\n', encoding="utf-8")
        cached.write_text('{"env":{"CODEX_CLI_PATH":"/old/sidecar"}}', encoding="utf-8")

        got = si.status(environ={"CODEX_HOME": str(codex)}, platform=WINDOWS,
                        opener=store.opener, runner=store.runner)

        assert got["derived_override_paths"] == [
            str(codex / "config.toml"), str(cached)]


class TestInstall:
    @pytest.mark.parametrize("built", EVERY, indirect=True)
    def test_it_names_the_real_codex_and_points_the_env_at_the_shim(self, built, store):
        platform = built["platform"]
        got = si.install(platform=platform, opener=store.opener,
                         broadcaster=store.broadcaster, runner=store.runner)
        assert got["done"] is True
        assert si.marker_path().read_text(encoding="utf-8") == str(built["real"])
        assert stored(store, platform) == str(built["exe"])

    def test_on_windows_the_change_is_broadcast(self, built, store):
        si.install(platform=WINDOWS, opener=store.opener,
                   broadcaster=store.broadcaster, runner=store.runner)
        assert store.broadcasts == 1

    @pytest.mark.parametrize("platform", [MACOS, LINUX])
    def test_on_posix_it_builds_the_shim_itself_so_install_is_one_step(
            self, here, store, monkeypatch, platform):
        """No shim yet and no compiler anywhere: it still installs."""
        monkeypatch.setattr(si, "real_codex", lambda environ=None: here / "codex")
        got = si.install(platform=platform, opener=store.opener,
                         broadcaster=store.broadcaster, runner=store.runner,
                         python="/usr/bin/python3")
        assert got["done"] is True
        assert si.sidecar_exe(platform).is_file()

    def test_it_refuses_when_the_shim_cannot_be_made(self, here, store, monkeypatch):
        monkeypatch.setattr(si, "real_codex", lambda environ=None: here / "codex")
        got = si.install(platform=WINDOWS, opener=store.opener,
                         broadcaster=store.broadcaster, runner=store.runner,
                         builder=lambda *a, **k: {"done": False, "detail": None,
                                                  "message": "no compiler"})
        assert got["done"] is False
        assert got["message"] == "no compiler"
        assert stored(store, WINDOWS) is None

    def test_it_refuses_when_the_real_codex_cannot_be_found(self, built, store, monkeypatch):
        monkeypatch.setattr(si, "real_codex", lambda environ=None: None)
        got = si.install(platform=WINDOWS, opener=store.opener,
                         broadcaster=store.broadcaster, runner=store.runner)
        assert got["done"] is False
        assert stored(store, WINDOWS) is None

    @pytest.mark.parametrize("built", EVERY, indirect=True)
    def test_it_tells_the_user_how_to_make_the_change_take(self, built, store):
        got = si.install(platform=built["platform"], opener=store.opener,
                         broadcaster=store.broadcaster, runner=store.runner)
        assert "restart" in got["message"].lower() or "log out" in got["message"].lower()

    def test_an_environment_that_will_not_take_it_is_reported_not_raised(
            self, built, store, monkeypatch):
        def refuse(*a, **k):
            raise OSError("the key is read-only")
        monkeypatch.setattr(codex_env, "set_value", refuse)
        got = si.install(platform=WINDOWS, opener=store.opener,
                         broadcaster=store.broadcaster, runner=store.runner)
        assert got["done"] is False and "OSError" in got["detail"]


class TestUninstall:
    @pytest.mark.parametrize("built", EVERY, indirect=True)
    def test_it_clears_the_env_and_removes_the_marker(self, built, store):
        platform = built["platform"]
        si.install(platform=platform, opener=store.opener,
                   broadcaster=store.broadcaster, runner=store.runner)
        got = si.uninstall(platform=platform, opener=store.opener,
                           broadcaster=store.broadcaster, runner=store.runner)
        assert got["done"] is True
        assert stored(store, platform) is None
        assert si.marker_path().is_file() is False

    @pytest.mark.parametrize("built", EVERY, indirect=True)
    def test_it_leaves_an_env_the_user_set_to_something_else_alone(self, built, store):
        put(store, built["platform"], "/my/own/codex")
        si.uninstall(platform=built["platform"], opener=store.opener,
                     broadcaster=store.broadcaster, runner=store.runner)
        assert stored(store, built["platform"]) == "/my/own/codex"

    def test_uninstalling_when_nothing_is_installed_does_not_raise(self, built, store):
        got = si.uninstall(platform=WINDOWS, opener=store.opener,
                           broadcaster=store.broadcaster, runner=store.runner)
        assert got["done"] is True

    def test_an_environment_that_will_not_take_it_is_reported_not_raised(
            self, built, store, monkeypatch):
        si.install(platform=WINDOWS, opener=store.opener,
                   broadcaster=store.broadcaster, runner=store.runner)

        def refuse(*a, **k):
            raise OSError("the key is read-only")
        monkeypatch.setattr(codex_env, "clear", refuse)
        got = si.uninstall(platform=WINDOWS, opener=store.opener,
                           broadcaster=store.broadcaster, runner=store.runner)
        assert got["done"] is False and "OSError" in got["detail"]

    def test_macos_uninstall_clears_a_gui_only_stale_override(
            self, here, store, monkeypatch):
        monkeypatch.setattr(codex_env, "HOME", here)
        shim = si.sidecar_exe(MACOS)
        shim.touch()
        si.marker_path().write_text("/Applications/ChatGPT.app/codex", encoding="utf-8")
        store.gui[si.ENV_KEY] = str(shim)

        got = si.uninstall(platform=MACOS, runner=store.runner)

        assert got["done"] is True
        assert si.ENV_KEY not in store.gui
        assert si.marker_path().is_file() is False

    def test_macos_uninstall_refuses_conflicting_user_and_sidecar_values(
            self, here, store, monkeypatch):
        monkeypatch.setattr(codex_env, "HOME", here)
        shim = si.sidecar_exe(MACOS)
        shim.touch()
        si.marker_path().write_text("/Applications/ChatGPT.app/codex", encoding="utf-8")
        store.caller[si.ENV_KEY] = "/my/own/codex"
        store.gui[si.ENV_KEY] = str(shim)

        got = si.uninstall(platform=MACOS, runner=store.runner)

        assert got["done"] is False
        assert store.caller[si.ENV_KEY] == "/my/own/codex"
        assert store.gui[si.ENV_KEY] == str(shim)
        assert si.marker_path().is_file() is True


class TestRealCodexIsResolvedWithoutTheShim:
    def test_the_marker_is_ignored_when_naming_the_real_codex(self, monkeypatch, tmp_path):
        """Otherwise install could name the shim as its own target and loop."""
        seen = {}

        def fake_cli(env):
            seen["env"] = env
            return tmp_path / "codex.exe"

        monkeypatch.setattr(codex_appserver, "codex_cli", fake_cli)
        si.real_codex({"CODEX_CLI_PATH": r"C:\shim\codex_sidecar.exe"})
        assert "CODEX_CLI_PATH" not in seen["env"]


class TestOurToolingResolvesThroughTheShim:
    def test_codex_cli_returns_the_real_codex_when_the_marker_is_present(self, tmp_path):
        shim = tmp_path / "codex_sidecar.exe"
        shim.write_text("", encoding="utf-8")
        real = tmp_path / "real" / "codex.exe"
        real.parent.mkdir()
        real.write_text("", encoding="utf-8")
        (tmp_path / codex_appserver.REAL_CODEX_MARKER).write_text(str(real), encoding="utf-8")
        assert codex_appserver.codex_cli({"LOCALAPPDATA": str(tmp_path / "installs"),
                                         "CODEX_CLI_PATH": str(shim)}) == real

    def test_a_plain_codex_with_no_marker_is_returned_as_is(self, tmp_path):
        real = tmp_path / "codex.exe"
        real.write_text("", encoding="utf-8")
        assert codex_appserver.codex_cli({"CODEX_CLI_PATH": str(real)}) == real


class TestInstallAndUninstallAreOneRoundTrip:
    @pytest.mark.parametrize("built", EVERY, indirect=True)
    def test_the_machine_is_left_as_it_was_found(self, built, store):
        """One click each way: whatever install touches, uninstall puts back."""
        platform = built["platform"]
        before = stored(store, platform)
        si.install(platform=platform, opener=store.opener,
                   broadcaster=store.broadcaster, runner=store.runner)
        si.uninstall(platform=platform, opener=store.opener,
                     broadcaster=store.broadcaster, runner=store.runner)
        assert stored(store, platform) == before
        assert si.status(platform=platform, opener=store.opener,
                         runner=store.runner)["installed"] is False


class TestWhichCodexIsPinned:
    """The marker is written once at install, and Codex keeps installing new
    builds beside the old ones, so the shim can drift onto a superseded codex
    without anything saying so."""

    def _install(self, root, name, mtime):
        folder = root / "OpenAI" / "Codex" / "bin" / name
        folder.mkdir(parents=True)
        exe = folder / "codex.exe"
        exe.write_text("", encoding="utf-8")
        os.utime(exe, (mtime, mtime))
        return exe

    def test_it_says_when_the_pinned_build_is_the_newest(self, tmp_path, monkeypatch):
        newest = self._install(tmp_path, "aaaa", 1_789_811_209.0)
        marker = tmp_path / "real-codex.txt"
        marker.write_text(str(newest), encoding="utf-8")
        monkeypatch.setattr(si, "marker_path", lambda: marker)

        found = si.pinned_build({"LOCALAPPDATA": str(tmp_path)})

        assert found["is_newest"] is True
        assert found["pinned"] == str(newest)

    def test_it_says_when_the_shim_has_drifted_onto_an_older_build(self, tmp_path,
                                                                   monkeypatch):
        older = self._install(tmp_path, "cdef", 1_789_723_284.0)
        newer = self._install(tmp_path, "2475", 1_789_811_209.0)
        marker = tmp_path / "real-codex.txt"
        marker.write_text(str(older), encoding="utf-8")
        monkeypatch.setattr(si, "marker_path", lambda: marker)

        found = si.pinned_build({"LOCALAPPDATA": str(tmp_path)})

        assert found["is_newest"] is False
        assert found["pinned"] == str(older)
        assert found["newest"] == str(newer)

    def test_no_marker_at_all_is_not_an_error(self, tmp_path, monkeypatch):
        self._install(tmp_path, "aaaa", 1_789_811_209.0)
        monkeypatch.setattr(si, "marker_path", lambda: tmp_path / "absent.txt")

        found = si.pinned_build({"LOCALAPPDATA": str(tmp_path)})

        assert found["pinned"] is None
        assert found["is_newest"] is False

    def test_an_empty_marker_reads_as_nothing_pinned(self, tmp_path, monkeypatch):
        marker = tmp_path / "real-codex.txt"
        marker.write_text("   \n", encoding="utf-8")
        monkeypatch.setattr(si, "marker_path", lambda: marker)

        assert si.pinned_build({"LOCALAPPDATA": str(tmp_path)})["pinned"] is None

    def test_without_localappdata_there_is_no_newest_to_compare_against(self, tmp_path,
                                                                        monkeypatch):
        marker = tmp_path / "real-codex.txt"
        marker.write_text(r"C:\codex.exe", encoding="utf-8")
        monkeypatch.setattr(si, "marker_path", lambda: marker)

        found = si.pinned_build({"LOCALAPPDATA": str(tmp_path / "nothing-installed")})

        assert found["newest"] is None and found["is_newest"] is False
