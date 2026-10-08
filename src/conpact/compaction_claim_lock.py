"""@module conpact.compaction_claim_lock
@description Nonblocking process-shared serialization of request-file claims.
@input The canonical request path, never the request body or an executable target.
@output A context owning the claim lease or a busy/unavailable refusal.
@dependencies conpact.home; stdlib: contextlib, ctypes, hashlib, os, sys; fcntl on Unix
"""
from contextlib import contextmanager
import ctypes
import hashlib
import os
import sys

from . import home


def _key(path):
    canonical = os.path.normcase(os.path.realpath(path))
    return hashlib.sha256(os.fsencode(canonical)).hexdigest()


def _kernel32():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    for name in ('ReleaseMutex', 'CloseHandle'):
        function = getattr(kernel, name)
        function.argtypes = [ctypes.c_void_p]
        function.restype = ctypes.c_int
    return kernel


def _windows(key):
    kernel = _kernel32()
    handle = kernel.CreateMutexW(None, False, 'Global\\conpact-claim-' + key)
    if not handle:
        return None
    if kernel.WaitForSingleObject(handle, 0) not in (0, 0x80):
        kernel.CloseHandle(handle)
        return None

    def release():
        try:
            if not kernel.ReleaseMutex(handle):
                raise OSError('could not release compaction claim mutex')
        finally:
            kernel.CloseHandle(handle)
    return release


def _fcntl():
    import fcntl
    return fcntl


def _unix(key):
    locks = home.HOME / 'claim-locks'
    locks.mkdir(parents=True, exist_ok=True)
    handle = (locks / (key + '.lock')).open('a+b')
    flock = _fcntl()
    try:
        flock.flock(handle.fileno(), flock.LOCK_EX | flock.LOCK_NB)
    except OSError:
        handle.close()
        return None

    def release():
        try:
            flock.flock(handle.fileno(), flock.LOCK_UN)
        finally:
            handle.close()
    # Keep the file: unlinking a lock inode lets another process lock a different
    # inode under the same name. The OS releases the actual lease on process exit.
    return release


@contextmanager
def hold(path):
    try:
        release = (_windows if sys.platform == 'win32' else _unix)(_key(path))
    except OSError:
        release = None
    try:
        yield release is not None
    finally:
        if release is not None:
            release()
