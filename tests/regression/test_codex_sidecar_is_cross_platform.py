"""
The promises the Codex sidecar makes about where it runs, anchored.

Three of these guarded a defect that was actually shipped and found:

  - `codex_inject` imported `ctypes.wintypes` at module scope. That import
    raises on macOS and Linux, so importing it - and therefore `codex_compact`,
    and therefore Codex compaction at all - was impossible off Windows. Nothing
    caught it, because every test ran on Windows. The rule is now structural: no
    module in the package may import a platform-only module at module scope.

  - The sidecar's record was written into conPACT's state folder (then
    `~/.claude/conpact/`, now `~/.conpact/`) with only the last folder created.
    On a machine where the parent did not exist yet, the record was silently
    never written - the sidecar ran and could not be reached.

  - `install` wrote what the Windows launcher needs only when the shim was
    missing, so reinstalling after Python moved left a shim that could not start.

The fourth is the boundary the control channel is: it is a loopback TCP port, and
the token is the only thing standing between any local process and the
app-server's stdin (D-20260922-036).
"""
import ast
import pathlib
import threading

import pytest

from conpact import codex_env, codex_inject, codex_sidecar, codex_sidecar_install

PACKAGE = pathlib.Path(codex_sidecar.__file__).parent
# Modules that exist only on one platform, so importing one at module scope makes
# the whole package unimportable elsewhere.
PLATFORM_ONLY = {"winreg", "ctypes.wintypes", "msvcrt", "fcntl", "termios", "pwd", "grp"}


def _module_scope_imports(source: str):
    """Every module imported at module scope - not inside a function or a class,
    and not inside a `try` that guards it."""
    tree = ast.parse(source)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


class TestEveryModuleImportsOnEveryPlatform:
    @pytest.mark.parametrize("path", sorted(PACKAGE.glob("*.py")), ids=lambda p: p.name)
    def test_no_platform_only_module_is_imported_at_module_scope(self, path):
        imported = _module_scope_imports(path.read_text(encoding="utf-8"))
        offending = imported & PLATFORM_ONLY
        assert offending == set(), (
            f"{path.name} imports {offending} at module scope, so it cannot be "
            f"imported on another platform - move it inside the function that uses it")

    def test_the_windows_registry_is_reached_through_one_seam(self):
        """So the Windows backend can be driven - and tested - from anywhere."""
        assert callable(codex_env._winreg)
        source = pathlib.Path(codex_env.__file__).read_text(encoding="utf-8")
        assert source.count("import winreg") == 1

    def test_the_sidecar_and_its_client_are_the_same_on_every_platform(self):
        """One implementation, so there is no second one to drift."""
        assert "AF_UNIX" not in pathlib.Path(codex_sidecar.__file__).read_text(encoding="utf-8")
        assert "wintypes" not in pathlib.Path(codex_inject.__file__).read_text(encoding="utf-8")


class TestItRunsWithoutTheOtherApp:
    def test_the_record_is_written_where_claude_has_never_been(self, tmp_path):
        """ChatGPT Desktop may be the only app on the machine; `~/.claude` is
        conPACT's own folder and is created, not assumed."""
        assert not (tmp_path / ".claude").exists()
        codex_sidecar.write_record(1234, "token", 99, "tag-", home=tmp_path)
        assert codex_sidecar.record_path(tmp_path).is_file()

    def test_the_shim_is_named_for_the_platform_it_will_run_on(self):
        assert codex_sidecar_install.sidecar_exe_name("darwin") == "codex_sidecar"
        assert codex_sidecar_install.sidecar_exe_name("linux") == "codex_sidecar"
        assert codex_sidecar_install.sidecar_exe_name("win32") == "codex_sidecar.exe"

    def test_installing_off_windows_needs_no_compiler(self, tmp_path, monkeypatch):
        """A Mac with no Xcode must still be one click."""
        monkeypatch.setattr(codex_sidecar_install, "sidecar_dir", lambda: tmp_path)

        def no_compiler(*a, **k):
            raise AssertionError("installing must not need a compiler off Windows")

        monkeypatch.setattr(codex_sidecar_install, "_run", no_compiler)
        got = codex_sidecar_install.build("darwin", python="/usr/bin/python3")
        assert got["done"] is True


class TestTheLauncherIsAlwaysToldWhereThingsAre:
    def test_installing_rewrites_what_the_launcher_needs_every_time(
            self, tmp_path, monkeypatch):
        """A Python that moved since last time would otherwise leave a shim that
        cannot start, and the failure is ChatGPT not starting codex at all."""
        monkeypatch.setattr(codex_sidecar_install, "sidecar_dir", lambda: tmp_path)
        (tmp_path / "codex_sidecar.exe").write_text("", encoding="utf-8")
        monkeypatch.setattr(codex_sidecar_install, "real_codex",
                            lambda environ=None: tmp_path / "codex.exe")
        monkeypatch.setattr(codex_env, "set_value", lambda *a, **k: True)
        codex_sidecar_install.install(platform="win32", python=r"C:\new\python.exe")
        assert codex_sidecar_install.launcher_config().read_text(
            encoding="utf-8").startswith("C:\\new\\python.exe")


class TestTheTokenIsTheBoundary:
    def test_an_unauthenticated_client_writes_nothing_into_the_app_server(self):
        """The control port is on loopback, which every local process can reach;
        the token is what stops them, so this may never become optional."""
        written = []

        class Stdin:
            def write(self, data):
                written.append(data)

            def flush(self):
                pass

            def close(self):
                pass

        class Conn:
            def __init__(self, says):
                self.says = list(says)

            def recv(self, _n):
                return self.says.pop(0) if self.says else b""

            def settimeout(self, seconds):
                self.timeout = seconds

            def close(self):
                pass

        class Server:
            def __init__(self):
                self.left = [Conn([b'no-token\n{"id":"evil","method":"x"}\n'])]

            def accept(self):
                if not self.left:
                    raise OSError("closed")
                return self.left.pop(0), ("127.0.0.1", 1)

        codex_sidecar.serve_control(Server(), codex_sidecar.Control(), Stdin(),
                                    threading.Lock(), "the-real-token")
        assert written == []

    def test_the_token_is_compared_in_constant_time(self):
        source = pathlib.Path(codex_sidecar.__file__).read_text(encoding="utf-8")
        assert "hmac.compare_digest" in source

    def test_the_control_port_is_loopback_only(self):
        assert codex_sidecar.HOST == "127.0.0.1"

    def test_a_record_without_a_token_is_no_record_at_all(self, tmp_path, monkeypatch):
        from conpact import compaction
        monkeypatch.setattr(compaction, "STATE_DIR", tmp_path)
        (tmp_path / codex_inject.RECORD).write_text(
            '{"address": "127.0.0.1:1", "tag": "t-"}', encoding="utf-8")
        assert codex_inject.read_record() is None
