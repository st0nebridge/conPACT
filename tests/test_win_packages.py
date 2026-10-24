"""
@module tests.test_win_packages
@description Registered Desktop discovery through fake Windows package APIs.
@input package identities, paths, native errors and concurrent buffer growth
@output runtime selection and bounded failure assertions without host package reads
@dependencies conpact.win_packages; stdlib: ctypes, os; pytest
"""
import ctypes
import os

import pytest

from conpact import win_packages as wp

bind_api = wp._api                    # fixture blocks the real loader in ordinary tests


def package(version='26.1021.3705.0', arch='x64'):
    return f'OpenAI.Codex_{version}_{arch}__2p2nqsd0c76g0'


class Packages:
    def __init__(self, paths, names_error=0, path_error=0, growing=False):
        self.paths = paths
        self.names_error, self.path_error, self.growing = names_error, path_error, growing
        self.calls = 0

    def GetPackagesByPackageFamily(self, family, count, names, size, buffer):
        assert family == 'OpenAI.Codex_2p2nqsd0c76g0'
        self.calls += 1
        count._obj.value, size._obj.value = len(self.paths), sum(len(s)+1 for s in self.paths)
        if self.names_error:
            return self.names_error
        if names is None or self.growing:
            return 122
        for i, name in enumerate(self.paths):
            names[i] = name
        return 0

    def GetPackagePathByFullName(self, name, size, buffer):
        if self.path_error:
            return self.path_error
        path = str(self.paths[name])
        size._obj.value = len(path) + 1
        if buffer is None:
            return 122
        buffer.value = path
        return 0


def install(root):
    exe = root / 'app/resources/codex.exe'
    exe.parent.mkdir(parents=True)
    exe.touch()
    return exe


def test_registered_version_beats_copy_timestamp_and_lexical_order(tmp_path):
    old = install(tmp_path / 'old')
    current = install(tmp_path / 'current')
    os.utime(old, (300, 300))
    os.utime(current, (100, 100))
    api = Packages({package('26.99.1.0'): tmp_path / 'old',
                    package('26.100.1.0'): tmp_path / 'current'})
    assert wp.runtime(api, machine='AMD64') == current


@pytest.mark.parametrize('name', [package(arch='arm64'), package('invalid'),
    package('1.2.3'), package('-1.2.3.4'), package('65536.2.3.4'),
    'Other_26.1021.3705.0_x64__publisher',
    'OpenAI.Codex_26.1021.3705.0_x64_resources_2p2nqsd0c76g0'])
def test_foreign_malformed_and_wrong_architecture_packages_are_ignored(tmp_path, name):
    install(tmp_path)
    assert wp.runtime(Packages({name: tmp_path}), machine='AMD64') is None


def test_removed_latest_package_uses_remaining_registered_runtime(tmp_path):
    older = install(tmp_path / 'older')
    api = Packages({package('26.100.0.0'): tmp_path / 'gone',
                    package('26.99.0.0'): tmp_path / 'older'})
    assert wp.runtime(api, machine='x64') == older


@pytest.mark.parametrize('kwargs', [dict(names_error=5), dict(path_error=5), dict(growing=True)])
def test_native_errors_and_update_races_terminate(tmp_path, kwargs):
    api = Packages({package(): tmp_path}, **kwargs)
    assert wp.runtime(api, machine='x64') is None
    assert api.calls <= 4


def test_no_packages_is_unavailable():
    assert wp.runtime(Packages({}), machine='x64') is None


def test_package_path_growth_is_bounded(tmp_path):
    class Growing(Packages):
        def GetPackagePathByFullName(self, name, size, buffer):
            size._obj.value = 10 if buffer is None else size._obj.value + 1
            return 122
    assert wp.runtime(Growing({package(): tmp_path}), machine='x64') is None


def test_package_path_grows_once_then_succeeds(tmp_path):
    current = install(tmp_path)
    class GrowingOnce(Packages):
        grew = False
        def GetPackagePathByFullName(self, name, size, buffer):
            if buffer is None:
                size._obj.value = 1
                return 122
            if not self.grew:
                self.grew = True
                size._obj.value = len(str(tmp_path)) + 1
                return 122
            return super().GetPackagePathByFullName(name, size, buffer)
    assert wp.runtime(GrowingOnce({package(): tmp_path}), machine='x64') == current


def test_api_error_after_path_sizing_returns_none(tmp_path):
    class Removed(Packages):
        def GetPackagePathByFullName(self, name, size, buffer):
            if buffer is None:
                size._obj.value = 10
                return 122
            return 5
    assert wp.runtime(Removed({package(): tmp_path}), machine='x64') is None


def test_unavailable_api_is_harmless(monkeypatch):
    def unavailable():
        raise OSError('not Windows')
    monkeypatch.setattr(wp, '_api', unavailable)
    assert wp.runtime() is None


def test_real_binding_signatures_without_loading_windows(monkeypatch):
    class Function:
        pass
    class Library:
        GetPackagesByPackageFamily = Function()
        GetPackagePathByFullName = Function()
    library = Library()
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name: library, raising=False)
    assert bind_api() is library
    assert library.GetPackagesByPackageFamily.restype is ctypes.c_long
    assert len(library.GetPackagesByPackageFamily.argtypes) == 5
    assert library.GetPackagePathByFullName.argtypes == (
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p)
