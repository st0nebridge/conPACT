"""A Windows process's identity, read in-process through the one handle it is about."""
import ctypes
import datetime
import os
import subprocess
import sys

import pytest

from conpact import win_process as wp

windows = pytest.mark.skipif(sys.platform != 'win32', reason='reads Windows processes')
UNIX_EPOCH = 116444736000000000          # 1970-01-01 in FILETIME ticks
TICKS = 10_000_000                       # FILETIME ticks per second


@pytest.mark.parametrize('ticks,text', [
    (0, '1601-01-01T00:00:00.0000000Z'),
    (UNIX_EPOCH, '1970-01-01T00:00:00.0000000Z'),
    (UNIX_EPOCH + 1, '1970-01-01T00:00:00.0000001Z'),
    (UNIX_EPOCH + 61 * TICKS + 1_234_567, '1970-01-01T00:01:01.1234567Z'),
])
def test_stamp_is_utc_iso_text_to_the_tick(ticks, text):
    assert wp.stamp(ticks) == text


def test_stamp_text_order_is_time_order():
    ticks = [0, 9, 10, TICKS - 1, TICKS, UNIX_EPOCH, UNIX_EPOCH + 10 ** 9, 2 ** 61]
    assert sorted(ticks, key=wp.stamp) == ticks
    assert len({len(wp.stamp(t)) for t in ticks}) == 1


def test_off_windows_nothing_is_read(monkeypatch):
    monkeypatch.delattr(ctypes, 'WinDLL', raising=False)
    assert wp.snapshot(os.getpid()) is None


class Kernel32:
    """A process whose handle opens and that is running, but whose image and times cannot be read."""

    def __init__(self, handle=77, wait=0x102, image=0, times=0, created=0):
        self.handle, self.wait, self.image, self.times, self.created = handle, wait, image, times, created
        self.opened, self.waited, self.closed = [], [], []

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        return self.handle

    def WaitForSingleObject(self, handle, milliseconds):
        self.waited.append((handle, milliseconds))
        return self.wait

    def QueryFullProcessImageNameW(self, handle, flags, buffer, size):
        buffer.value = 'C:\\x.exe'
        return self.image

    def GetProcessTimes(self, handle, created, *rest):
        created._obj.value = self.created
        return self.times

    def CloseHandle(self, handle):
        self.closed.append(handle)


class Ntdll:
    def __init__(self, status):
        self.status, self.asked = status, []

    def NtQueryInformationProcess(self, handle, info, buffer, size, needed):
        self.asked.append((handle, info))
        return self.status


def test_unreadable_fields_are_missing_and_the_handle_is_closed(monkeypatch):
    kernel32, ntdll = Kernel32(), Ntdll(0xC0000022)
    monkeypatch.setattr(wp, '_api', lambda: (kernel32, ntdll))
    assert wp.snapshot(41) == dict(ProcessId=41, ParentProcessId=None, ExecutablePath=None,
                                   CommandLine=None, CreationDate=None)
    assert kernel32.opened == [(0x00101000, False, 41)]
    assert kernel32.waited == [(77, 0)]
    assert kernel32.closed == [77]
    assert ntdll.asked == [(77, 0), (77, 60)]


def test_a_creation_time_of_zero_is_no_creation_time(monkeypatch):
    kernel32 = Kernel32(image=1, times=1, created=0)
    monkeypatch.setattr(wp, '_api', lambda: (kernel32, Ntdll(0xC0000022)))
    row = wp.snapshot(41)
    assert row['ExecutablePath'] == 'C:\\x.exe' and row['CreationDate'] is None
    kernel32.created = UNIX_EPOCH
    assert wp.snapshot(41)['CreationDate'] == '1970-01-01T00:00:00.0000000Z'


@pytest.mark.parametrize('handle,wait,closed', [(None, 0x102, []), (77, 0, [77]), (77, 0xFFFFFFFF, [77])])
def test_a_process_that_cannot_be_opened_or_has_exited_is_not_read(monkeypatch, handle, wait, closed):
    kernel32, ntdll = Kernel32(handle=handle, wait=wait), Ntdll(0)
    monkeypatch.setattr(wp, '_api', lambda: (kernel32, ntdll))
    assert wp.snapshot(41) is None
    assert kernel32.closed == closed and ntdll.asked == []


def test_a_read_the_system_faults_is_no_row_and_still_closes_the_handle(monkeypatch):
    class Faulting(Ntdll):
        def NtQueryInformationProcess(self, *args):
            raise OSError('exception: access violation reading 0x0000000000000000')
    kernel32 = Kernel32()
    monkeypatch.setattr(wp, '_api', lambda: (kernel32, Faulting(0)))
    assert wp.snapshot(41) is None
    assert kernel32.closed == [77]


def _now(slack):
    """Now, as a stamp, moved by `slack` seconds to absorb the clocks' differing resolution."""
    seconds = datetime.datetime.now(datetime.timezone.utc).timestamp() + slack
    return wp.stamp(int(seconds * TICKS) + UNIX_EPOCH)


@windows
def test_this_process_reads_as_itself():
    row = wp.snapshot(os.getpid())
    assert row['ProcessId'] == os.getpid()
    assert row['ParentProcessId'] == os.getppid()
    assert os.path.samefile(row['ExecutablePath'], getattr(sys, '_base_executable', sys.executable))
    assert row['CommandLine'] and row['CreationDate'] <= _now(1)
    parent = wp.snapshot(os.getppid())
    assert parent['ProcessId'] == os.getppid() and parent['CreationDate'] <= row['CreationDate']


@windows
def test_a_started_child_reads_exactly_as_it_was_started():
    arguments = [sys.executable, '-c', 'import time; time.sleep(60)', 'an argument with spaces', '"quoted"']
    before = _now(-1)
    child = subprocess.Popen(arguments, creationflags=subprocess.CREATE_NO_WINDOW)
    after = _now(1)
    try:
        row = wp.snapshot(child.pid)
    finally:
        child.kill()
        child.wait()
    assert row == dict(ProcessId=child.pid, ParentProcessId=os.getpid(),
                       ExecutablePath=row['ExecutablePath'], CommandLine=subprocess.list2cmdline(arguments),
                       CreationDate=row['CreationDate'])
    assert os.path.samefile(row['ExecutablePath'], sys.executable)
    assert before <= row['CreationDate'] <= after
    assert wp.snapshot(child.pid) is None
