"""
@module conpact.win_packages
@description Locate the current user's registered Codex runtime without listing WindowsApps.
@input Windows package APIs (injectable), host architecture
@output newest registered compatible runtime path, or None when unavailable
@dependencies stdlib: ctypes, pathlib, platform
"""
import ctypes
import pathlib
import platform

FAMILY = 'OpenAI.Codex_2p2nqsd0c76g0'
_MORE = 122                         # ERROR_INSUFFICIENT_BUFFER


def _api():
    kernel32 = ctypes.WinDLL('kernel32')
    uint = ctypes.c_uint32
    kernel32.GetPackagesByPackageFamily.argtypes = (
        ctypes.c_wchar_p, ctypes.POINTER(uint), ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(uint), ctypes.c_wchar_p)
    kernel32.GetPackagesByPackageFamily.restype = ctypes.c_long
    kernel32.GetPackagePathByFullName.argtypes = (
        ctypes.c_wchar_p, ctypes.POINTER(uint), ctypes.c_wchar_p)
    kernel32.GetPackagePathByFullName.restype = ctypes.c_long
    return kernel32


def _names(api):
    count, size = ctypes.c_uint32(), ctypes.c_uint32()
    status = api.GetPackagesByPackageFamily(
        FAMILY, ctypes.byref(count), None, ctypes.byref(size), None)
    for _ in range(3):
        if status != _MORE or not 0 < count.value <= 1024 or not 0 < size.value <= 1048576:
            return []
        names = (ctypes.c_wchar_p * count.value)()
        buffer = ctypes.create_unicode_buffer(size.value)
        status = api.GetPackagesByPackageFamily(
            FAMILY, ctypes.byref(count), names, ctypes.byref(size), buffer)
        if status == 0:
            return [name for name in names if name]
    return []


def _path(api, name):
    size = ctypes.c_uint32()
    status = api.GetPackagePathByFullName(name, ctypes.byref(size), None)
    for _ in range(3):
        if status != _MORE or not 0 < size.value <= 32768:
            return None
        buffer = ctypes.create_unicode_buffer(size.value)
        status = api.GetPackagePathByFullName(name, ctypes.byref(size), buffer)
        if status == 0:
            return pathlib.Path(buffer.value) if buffer.value else None
    return None


def runtime(api=None, machine=None):
    """Registration, not copy times, identifies the installed Desktop version.

    Reads only current-user package metadata. No process, registry write, broad
    directory scan or persistent pin; a concurrent update gets bounded retries.
    """
    try:
        api = _api() if api is None else api
        arch = (machine or platform.machine()).lower()
        arch = {'amd64': 'x64', 'aarch64': 'arm64', 'i386': 'x86', 'i686': 'x86'}.get(arch, arch)
        candidates = []
        for name in _names(api):
            parts = name.split('_')
            if len(parts) != 5 or parts[0] != 'OpenAI.Codex' or parts[4] != '2p2nqsd0c76g0' \
                    or parts[2] not in (arch, 'neutral') or parts[3]:
                continue
            try:
                version = tuple(int(n) for n in parts[1].split('.'))
            except ValueError:
                continue
            if len(version) != 4 or any(n < 0 or n > 65535 for n in version):
                continue
            candidates.append((version, name))
        for _, name in sorted(candidates, reverse=True):
            root = _path(api, name)
            if root is not None:
                exe = root / 'app' / 'resources' / 'codex.exe'
                if exe.is_file():
                    return exe
    except (AttributeError, OSError):
        pass
    return None
