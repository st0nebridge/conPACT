"""
@module conpact.win_process
@description Read one running Windows process's identity in-process: its parent
             pid, image path, command line and creation time, all through one
             handle, so the fields cannot describe two processes and its pid
             cannot be reused while they are read. Nothing is started, so no
             window is shown and nothing waits on how busy the machine is.
@input a pid
@output a row shaped like Win32_Process (ProcessId, ParentProcessId,
        ExecutablePath, CommandLine, and CreationDate as fixed-width UTC ISO
        text, so text order is time order), a field it could not read as None;
        or None for a process that cannot be opened or has exited, or off Windows
@dependencies stdlib: ctypes, datetime
"""
import ctypes
import datetime

_ACCESS = 0x00100000 | 0x1000            # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
_WAIT_TIMEOUT = 0x102                    # still running
_BASIC, _COMMAND_LINE = 0, 60            # ProcessBasicInformation, ProcessCommandLineInformation
_EPOCH = datetime.datetime(1601, 1, 1)   # FILETIME's origin, in UTC


class _Basic(ctypes.Structure):          # PROCESS_BASIC_INFORMATION
    _fields_ = [('exit_status', ctypes.c_long), ('peb', ctypes.c_void_p),
                ('affinity', ctypes.c_size_t), ('priority', ctypes.c_long),
                ('pid', ctypes.c_size_t), ('parent', ctypes.c_size_t)]


class _Text(ctypes.Structure):           # UNICODE_STRING
    _fields_ = [('length', ctypes.c_ushort), ('maximum', ctypes.c_ushort),
                ('buffer', ctypes.c_void_p)]


def stamp(ticks):
    """FILETIME ticks (100 ns since 1601, UTC) as ISO text to the tick."""
    seconds, rest = divmod(ticks, 10_000_000)
    return f'{_EPOCH + datetime.timedelta(seconds=seconds):%Y-%m-%dT%H:%M:%S}.{rest:07d}Z'


def _api():
    """Private bindings with exact signatures: a HANDLE must not be cut to 32 bits."""
    kernel32 = ctypes.WinDLL('kernel32')
    ntdll = ctypes.WinDLL('ntdll')
    handle, dword, filetime = ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulonglong)
    kernel32.OpenProcess.restype = handle
    kernel32.OpenProcess.argtypes = (dword, ctypes.c_int, dword)
    kernel32.WaitForSingleObject.restype = dword
    kernel32.WaitForSingleObject.argtypes = (handle, dword)
    kernel32.QueryFullProcessImageNameW.argtypes = (handle, dword, ctypes.c_wchar_p, ctypes.POINTER(dword))
    kernel32.GetProcessTimes.argtypes = (handle, filetime, filetime, filetime, filetime)
    kernel32.CloseHandle.argtypes = (handle,)
    ntdll.NtQueryInformationProcess.restype = dword
    ntdll.NtQueryInformationProcess.argtypes = (handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.POINTER(dword))
    return kernel32, ntdll


def _parent(ntdll, handle):
    basic = _Basic()
    failed = ntdll.NtQueryInformationProcess(handle, _BASIC, ctypes.byref(basic), ctypes.sizeof(basic), None)
    return None if failed else basic.parent


def _image(kernel32, handle):
    size = ctypes.c_ulong(0x8000)
    buffer = ctypes.create_unicode_buffer(size.value)
    return buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else None


def _command_line(ntdll, handle):
    """Room for the longest command line Windows allows, so one call reads it."""
    buffer = ctypes.create_string_buffer(ctypes.sizeof(_Text) + 0x10000)
    if ntdll.NtQueryInformationProcess(handle, _COMMAND_LINE, buffer, len(buffer), None):
        return None
    text = _Text.from_buffer(buffer)
    return ctypes.wstring_at(text.buffer, text.length // 2)


def _created(kernel32, handle):
    created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
    read = kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user))
    return stamp(created.value) if read and created.value else None


def snapshot(pid):
    """The running process with this pid, read through one handle, or None."""
    try:
        kernel32, ntdll = _api()
    except (AttributeError, OSError):
        return None
    handle = kernel32.OpenProcess(_ACCESS, False, pid)
    if not handle:
        return None
    try:
        if kernel32.WaitForSingleObject(handle, 0) != _WAIT_TIMEOUT:
            return None
        return dict(ProcessId=pid, ParentProcessId=_parent(ntdll, handle),
                    ExecutablePath=_image(kernel32, handle), CommandLine=_command_line(ntdll, handle),
                    CreationDate=_created(kernel32, handle))
    except OSError:
        return None
    finally:
        kernel32.CloseHandle(handle)
