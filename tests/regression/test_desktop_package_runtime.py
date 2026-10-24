"""
@module tests.regression.test_desktop_package_runtime
@description Desktop's registered runtime wins even when WindowsApps cannot be listed.
@input isolated package and cache paths
@output assertions on sidecar and CLI runtime selection after updates
@dependencies conpact.codex_appserver, conpact.codex_sidecar; stdlib: os
"""
import os

from conpact import codex_appserver, codex_sidecar


def test_registered_package_bypasses_unlistable_store_and_newer_cache_timestamp(
        tmp_path, monkeypatch):
    cached = tmp_path / 'OpenAI/Codex/bin/stale/codex.exe'
    cached.parent.mkdir(parents=True)
    cached.touch()
    current = tmp_path / 'protected/registered/app/resources/codex.exe'
    current.parent.mkdir(parents=True)
    current.touch()
    os.utime(cached, (300, 300))
    os.utime(current, (100, 100))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.delenv('CONPACT_CODEX_REAL', raising=False)
    monkeypatch.setattr(codex_appserver, '_windows_bundled', lambda env: iter(()))
    monkeypatch.setattr(codex_appserver, '_registered_windows_runtime', lambda: current, raising=False)
    assert codex_appserver.newest_build() == current
    assert codex_sidecar.real_codex(beside=tmp_path) == str(current)


def test_supplied_environment_does_not_borrow_host_package_registration(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError('isolated lookup must not read host packages')
    monkeypatch.setattr(codex_appserver, '_registered_windows_runtime', forbidden, raising=False)
    assert codex_appserver.newest_build({'LOCALAPPDATA': str(tmp_path)}) is None


def test_missing_registered_runtime_keeps_existing_cache_fallback(tmp_path, monkeypatch):
    cached = tmp_path / 'OpenAI/Codex/bin/usable/codex.exe'
    cached.parent.mkdir(parents=True)
    cached.touch()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(codex_appserver, '_registered_windows_runtime', lambda: None, raising=False)
    monkeypatch.setattr(codex_appserver, '_windows_bundled', lambda env: iter(()))
    assert codex_appserver.newest_build() == cached


def test_registration_is_rechecked_and_explicit_pins_still_win(tmp_path, monkeypatch):
    first, second = tmp_path / 'first.exe', tmp_path / 'second.exe'
    first.touch()
    second.touch()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.delenv('CONPACT_CODEX_REAL', raising=False)
    monkeypatch.setattr(codex_appserver, '_registered_windows_runtime', lambda: first)
    assert codex_sidecar.real_codex(beside=tmp_path) == str(first)
    monkeypatch.setattr(codex_appserver, '_registered_windows_runtime', lambda: second)
    assert codex_sidecar.real_codex(beside=tmp_path) == str(second)
    monkeypatch.setenv('CONPACT_CODEX_REAL', str(first))
    assert codex_sidecar.real_codex(beside=tmp_path) == str(first)
    assert codex_appserver.codex_cli() == first
