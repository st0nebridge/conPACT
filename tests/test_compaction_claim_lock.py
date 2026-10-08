"""@module tests.test_compaction_claim_lock
@description Claim leases fail closed, release reliably and cross process boundaries.
@input Injected Windows/Unix APIs and isolated native child processes.
@output Exclusive, nonblocking ownership with no request or credential side effects.
@dependencies conpact.compaction_claim_lock, conpact.home; stdlib: os, pathlib, subprocess, sys
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from conpact import compaction_claim_lock as lock, home


class Kernel:
    def __init__(self, handle=17, wait=0, release=1):
        self.handle, self.wait, self.release = handle, wait, release
        self.calls = []

    def CreateMutexW(self, security, owner, name):
        self.calls.append(('create', security, owner, name))
        return self.handle

    def WaitForSingleObject(self, handle, timeout):
        self.calls.append(('wait', handle, timeout))
        return self.wait

    def ReleaseMutex(self, handle):
        self.calls.append(('release', handle))
        return self.release

    def CloseHandle(self, handle):
        self.calls.append(('close', handle))
        return 1


@pytest.mark.parametrize('wait', [0, 0x80])
def test_windows_owned_and_abandoned_leases_release_and_close(monkeypatch, wait):
    kernel = Kernel(wait=wait)
    monkeypatch.setattr(lock, '_kernel32', lambda: kernel)
    monkeypatch.setattr(lock.sys, 'platform', 'win32')
    with lock.hold('synthetic-request.json') as owned:
        assert owned
    assert kernel.calls[0][3].startswith('Global\\conpact-claim-')
    assert kernel.calls[-3:] == [('wait', 17, 0), ('release', 17), ('close', 17)]


@pytest.mark.parametrize('handle,wait', [(0, 0), (17, 258), (17, 0xFFFFFFFF)])
def test_windows_busy_or_unavailable_never_owns_a_lease(monkeypatch, handle, wait):
    kernel = Kernel(handle=handle, wait=wait)
    monkeypatch.setattr(lock, '_kernel32', lambda: kernel)
    monkeypatch.setattr(lock.sys, 'platform', 'win32')
    with lock.hold('synthetic-request.json') as owned:
        assert not owned
    assert not any(call[0] == 'release' for call in kernel.calls)
    if handle:
        assert kernel.calls[-1] == ('close', handle)


def test_windows_release_failure_still_closes_and_prevents_a_success(monkeypatch):
    kernel = Kernel(release=0)
    monkeypatch.setattr(lock, '_kernel32', lambda: kernel)
    with pytest.raises(OSError, match='release'):
        lock._windows('synthetic-key')()
    assert kernel.calls[-1] == ('close', 17)


class Flock:
    LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4

    def __init__(self, busy=False):
        self.busy, self.calls = busy, []

    def flock(self, descriptor, operation):
        self.calls.append((descriptor, operation))
        if self.busy and operation != self.LOCK_UN:
            raise BlockingIOError('another process owns the inode')


@pytest.mark.parametrize('busy', [False, True])
def test_unix_uses_the_same_retained_inode_and_nonblocking_lock(monkeypatch, busy):
    flock = Flock(busy)
    monkeypatch.setattr(lock, '_fcntl', lambda: flock)
    monkeypatch.setattr(lock.sys, 'platform', 'linux')
    for _ in range(2):
        with lock.hold('synthetic-request.json') as owned:
            assert owned is not busy
    files = list((home.HOME / 'claim-locks').iterdir())
    assert len(files) == 1 and files[0].stat().st_size == 0
    assert [op for _, op in flock.calls] == ([3, 3] if busy else [3, 4, 3, 4])


def test_acquisition_failure_refuses_without_entering_an_owned_context(monkeypatch):
    def unavailable(key):
        raise PermissionError('state is unavailable')
    monkeypatch.setattr(lock, '_windows', unavailable)
    monkeypatch.setattr(lock, '_unix', unavailable)
    with lock.hold('synthetic-request.json') as owned:
        assert not owned


def test_lease_releases_when_the_protected_operation_fails(monkeypatch):
    released = []
    monkeypatch.setattr(lock, '_windows', lambda key: lambda: released.append(key))
    monkeypatch.setattr(lock, '_unix', lambda key: lambda: released.append(key))
    with pytest.raises(ValueError):
        with lock.hold('synthetic-request.json') as owned:
            assert owned
            raise ValueError('protected operation failed')
    assert len(released) == 1


def test_a_native_child_cannot_acquire_the_parent_lease(tmp_path):
    path = tmp_path / 'request.json'
    profile = str(home.HOME.parent)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CONPACT_', 'CODEX_', 'OPENAI_', 'CHATGPT_'))
           and not k.endswith(('TOKEN', 'API_KEY'))}
    for name in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME'):
        env[name] = profile
    env['PYTHONPATH'] = str(Path(lock.__file__).resolve().parents[1])
    code = ('from conpact.compaction_claim_lock import hold; import sys; '
            'lease=hold(sys.argv[1]); owned=lease.__enter__(); '
            'print(int(owned)); lease.__exit__(None,None,None)')

    def child():
        return subprocess.run([sys.executable, '-c', code, str(path)], env=env,
                              capture_output=True, text=True, timeout=10,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    with lock.hold(path) as owned:
        assert owned
        blocked = child()
        assert blocked.returncode == 0, blocked.stderr
        assert blocked.stdout.strip() == '0'
    available = child()
    assert available.returncode == 0, available.stderr
    assert available.stdout.strip() == '1'
