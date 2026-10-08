"""An install-time marker must not keep Desktop on a superseded Codex.

The old executable can survive pruning while its tool host is deleted. Select
the newer build before that happens, and re-evaluate on every launch.
"""
import os

from conpact import codex_appserver, codex_sidecar, codex_sidecar_install, doctor


def build(root, name, mtime):
    folder = root / "OpenAI" / "Codex" / "bin" / name
    folder.mkdir(parents=True)
    exe = folder / "codex.exe"
    exe.touch()
    (folder / "codex-code-mode-host.exe").touch()
    os.utime(exe, (mtime, mtime))
    return exe


def test_a_complete_old_marker_follows_an_update_on_the_next_launch(tmp_path):
    old = build(tmp_path, "old", 100)
    shim = tmp_path / "codex_sidecar.exe"
    shim.touch()
    (tmp_path / "real-codex.txt").write_text(str(old), encoding="utf-8")
    env = {"LOCALAPPDATA": str(tmp_path), "CODEX_CLI_PATH": str(shim)}
    assert codex_sidecar.real_codex(env, beside=tmp_path) == str(old)

    new = build(tmp_path, "new", 200)
    assert codex_sidecar.real_codex(env, beside=tmp_path) == str(new)
    assert codex_appserver.codex_cli(env) == new


def test_a_new_desktop_bundle_is_found_before_desktop_copies_it_to_the_cache(tmp_path):
    old = build(tmp_path, "old", 100)
    (tmp_path / "real-codex.txt").write_text(str(old), encoding="utf-8")
    resources = tmp_path / "Program Files" / "WindowsApps" / \
        "OpenAI.Codex_2.0_x64__publisher" / "app" / "resources"
    resources.mkdir(parents=True)
    new = resources / "codex.exe"
    new.touch()
    (resources / "codex-code-mode-host.exe").touch()
    os.utime(new, (200, 200))
    env = {"LOCALAPPDATA": str(tmp_path), "ProgramFiles": str(tmp_path / "Program Files")}
    assert codex_sidecar.real_codex(env, beside=tmp_path) == str(new)
    assert codex_appserver.codex_cli(env) == new

    cached = build(tmp_path, "new", 200)
    assert codex_sidecar.real_codex(env, beside=tmp_path) == str(cached)

    cached.unlink()
    old.unlink()
    assert codex_appserver.newest_build(env) == new


def test_a_macos_sidecar_follows_codex_into_the_nested_desktop_bundle(
        tmp_path, monkeypatch):
    """Desktop 26.930 moved codex below Resources/codex-cli/CodexCLI.app."""
    old = tmp_path / "old" / "codex"
    old.parent.mkdir()
    old.touch()
    os.utime(old, (100, 100))
    shim = tmp_path / "codex_sidecar"
    shim.touch()
    (tmp_path / "real-codex.txt").write_text(str(old), encoding="utf-8")

    applications = tmp_path / "Applications"
    active = applications / "ChatGPT.app"
    new = active / "Contents" / "Resources" / \
        "codex-cli" / "CodexCLI.app" / "Contents" / "MacOS" / "codex"
    new.parent.mkdir(parents=True)
    new.touch()
    os.utime(new, (200, 200))
    patterns = [pattern for base, pattern in codex_appserver.BUNDLED["darwin"]
                if base == "/Applications/ChatGPT.app"]
    assert patterns, "the active system ChatGPT bundle must be named explicitly"
    monkeypatch.setattr(codex_appserver, "BUNDLED", {
        "darwin": tuple((str(active), pattern) for pattern in patterns),
    })
    monkeypatch.setattr(codex_appserver.sys, "platform", "darwin")
    backup = applications / "ChatGPT-26.917.71314.app" / "Contents" / \
        "Resources" / "codex"
    backup.parent.mkdir(parents=True)
    backup.touch()
    os.utime(backup, (300, 300))
    env = {"HOME": str(tmp_path), "CODEX_CLI_PATH": str(shim)}

    assert codex_sidecar.real_codex(env, beside=tmp_path) == str(new)
    assert codex_appserver.codex_cli(env) == new


def test_macos_does_not_fall_back_to_a_marker_outside_the_active_app(
        tmp_path, monkeypatch):
    backup = tmp_path / "ChatGPT-backup.app" / "Contents" / "Resources" / "codex"
    backup.parent.mkdir(parents=True)
    backup.touch()
    monkeypatch.setattr(codex_appserver, "BUNDLED", {
        "darwin": ((str(tmp_path / "Applications" / "ChatGPT.app"),
                    "Contents/Resources/codex"),),
    })

    assert codex_appserver.selected_build(str(backup), {}, platform="darwin") is None


def test_an_unreadable_store_directory_keeps_the_cached_build(tmp_path, monkeypatch):
    from pathlib import Path
    cached = build(tmp_path, "cached", 100)
    original_glob = Path.glob

    def restricted_glob(path, pattern):
        if str(path) == str(tmp_path / "Program Files"):
            raise PermissionError("WindowsApps is unreadable")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", restricted_glob)
    env = {"LOCALAPPDATA": str(tmp_path), "ProgramFiles": str(tmp_path / "Program Files")}
    assert codex_appserver.newest_build(env) == cached


def test_status_names_the_selected_build_even_when_the_marker_is_old(tmp_path, monkeypatch):
    old = build(tmp_path, "old", 100)
    new = build(tmp_path, "new", 200)
    marker = tmp_path / "real-codex.txt"
    marker.write_text(str(old), encoding="utf-8")
    monkeypatch.setattr(codex_sidecar_install, "marker_path", lambda: marker)
    found = codex_sidecar_install.pinned_build({"LOCALAPPDATA": str(tmp_path)})
    assert found["selected"] == str(new)
    assert found["selection"] == "automatic"


def test_an_explicit_environment_pin_still_selects_the_requested_build(tmp_path, monkeypatch):
    old = build(tmp_path, "old", 100)
    build(tmp_path, "new", 200)
    marker = tmp_path / "real-codex.txt"
    marker.write_text(str(old), encoding="utf-8")
    monkeypatch.setattr(codex_sidecar_install, "marker_path", lambda: marker)
    env = {"LOCALAPPDATA": str(tmp_path), "CONPACT_CODEX_REAL": str(old)}
    assert codex_sidecar.real_codex(env, beside=tmp_path) == str(old)
    assert codex_appserver.codex_cli(env) == old
    found = codex_sidecar_install.pinned_build(env)
    assert found["selected"] == str(old)
    assert found["selection"] == "explicit pin"


def test_doctor_checks_the_selected_build_instead_of_the_old_marker(monkeypatch):
    status = {
        "installed": True, "sidecar_running": True,
        "codex_pinned": "/old/codex", "codex_newest": "/new/codex",
        "codex_is_newest": False, "codex_selected": "/new/codex",
    }
    monkeypatch.setattr(codex_sidecar_install, "status", lambda **kwargs: status)
    check = doctor._sidecar({})[-1]
    assert check.level == "OK"
    assert "next launch" in check.detail
    status["codex_selected"] = "/old/codex"
    assert doctor._sidecar({})[-1].level == "WARN"
