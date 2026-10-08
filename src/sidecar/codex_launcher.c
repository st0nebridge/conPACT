/*
 * @module sidecar/codex_launcher
 * @description The Windows half of the sidecar, and nothing more than a way in.
 *
 *              The sidecar itself is `conpact.codex_sidecar`, one Python
 *              module shared by every platform. On macOS and Linux the desktop
 *              runs it through a generated shell script and no native code is
 *              involved at all. On Windows it cannot: ChatGPT Desktop spawns
 *              CODEX_CLI_PATH through Node, which starts real executables only -
 *              not a .py, and not a .cmd (Node refuses those without a shell
 *              since CVE-2024-27980). So this exists: a real exe whose whole job
 *              is to exec the Python module with the arguments it was handed.
 *
 *              It holds no proxy logic, no framing and no protocol, so the part
 *              that can be got wrong lives in Python where it is unit-tested.
 *              What it needs to know - which interpreter, and where the package
 *              is - it reads from `launcher.txt` written beside it at install,
 *              so moving Python or reinstalling never means compiling again.
 *
 * @input       argv (passed through verbatim), launcher.txt beside this exe
 * @output      the Python process's exit code
 * @dependencies Win32 only: kernel32
 */
#include <windows.h>
#include <stdio.h>

#define SMALL 1024
#define BIG 32768

/* Read launcher.txt beside this exe: line 1 the interpreter, line 2 the import
   root. UTF-8 on disk, wide in memory - a user folder may hold anything. */
static int read_config(wchar_t *dir, wchar_t *python, wchar_t *root)
{
    wchar_t path[MAX_PATH];
    char raw[SMALL * 3];
    wchar_t wide[SMALL * 3];
    HANDLE file;
    DWORD got = 0;
    wchar_t *newline;

    if (wcslen(dir) + 16 >= MAX_PATH)
        return 0;
    wcscpy(path, dir);
    wcscat(path, L"launcher.txt");
    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return 0;
    if (!ReadFile(file, raw, sizeof(raw) - 1, &got, NULL) || got == 0) {
        CloseHandle(file);
        return 0;
    }
    CloseHandle(file);
    raw[got] = 0;
    if (MultiByteToWideChar(CP_UTF8, 0, raw, -1, wide, SMALL * 3) == 0)
        return 0;

    newline = wcschr(wide, L'\n');
    if (!newline)
        return 0;
    *newline = 0;
    wcsncpy(python, wide, SMALL - 1);
    python[SMALL - 1] = 0;
    wcsncpy(root, newline + 1, SMALL - 1);
    root[SMALL - 1] = 0;

    /* Both lines may carry a CR, and the second a trailing newline. */
    while (wcslen(python) && (python[wcslen(python) - 1] == L'\r'))
        python[wcslen(python) - 1] = 0;
    while (wcslen(root) && (root[wcslen(root) - 1] == L'\r' ||
                            root[wcslen(root) - 1] == L'\n'))
        root[wcslen(root) - 1] = 0;
    return python[0] && root[0];
}

/* Our arguments, exactly as the desktop wrote them, after the executable. */
static const wchar_t *args_after_exe(void)
{
    const wchar_t *p = GetCommandLineW();
    if (*p == L'"') {
        p++;
        while (*p && *p != L'"')
            p++;
        if (*p == L'"')
            p++;
    } else {
        while (*p && *p != L' ' && *p != L'\t')
            p++;
    }
    while (*p == L' ' || *p == L'\t')
        p++;
    return p;
}

int main(void)
{
    wchar_t self[MAX_PATH], python[SMALL], root[SMALL], *slash;
    wchar_t existing[BIG], combined[BIG];
    static wchar_t command[BIG];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD code = 1;

    if (!GetModuleFileNameW(NULL, self, MAX_PATH))
        return 1;
    slash = wcsrchr(self, L'\\');
    if (!slash)
        return 1;
    slash[1] = 0;                                   /* the folder we live in */

    if (!read_config(self, python, root)) {
        fwprintf(stderr, L"codex_sidecar: launcher.txt is missing or unreadable\n");
        return 1;
    }

    /* The package's import root goes in front of any PYTHONPATH already set,
       and the marker naming the real codex is found beside this exe. */
    if (GetEnvironmentVariableW(L"PYTHONPATH", existing, BIG) > 0)
        _snwprintf(combined, BIG, L"%s;%s", root, existing);
    else
        _snwprintf(combined, BIG, L"%s", root);
    SetEnvironmentVariableW(L"PYTHONPATH", combined);
    SetEnvironmentVariableW(L"CONPACT_SIDECAR_DIR", self);

    _snwprintf(command, BIG, L"\"%s\" -m conpact.codex_sidecar %s",
               python, args_after_exe());

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    /* No STARTF_USESTDHANDLES: the child inherits ours, which is the point -
       the desktop's stdin and stdout reach Python untouched. */
    if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) {
        fwprintf(stderr, L"codex_sidecar: could not start %s\n", python);
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return (int)code;
}
