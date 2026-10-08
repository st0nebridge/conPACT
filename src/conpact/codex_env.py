"""
@module conpact.codex_env
@description Set, read and clear one persistent *user* environment variable that
             a GUI-launched app will see - the single mechanism the Codex sidecar
             install depends on, isolated here because it is the part that
             differs by operating system. ChatGPT Desktop reads `CODEX_CLI_PATH`
             from its own process environment, and a GUI app does not inherit a
             shell's exports, so each platform needs its own durable store:

               - Windows: `HKCU\\Environment` (the user's registry environment),
                 with a WM_SETTINGCHANGE broadcast; new processes inherit it and
                 the desktop picks it up on its next launch. Verified live.
               - macOS: a per-user LaunchAgent that runs `launchctl setenv` at
                 login, plus explicit writes to both the caller and `gui/<uid>`
                 bootstrap domains now. The GUI value is read back after every
                 write because Finder-launched apps inherit that domain.
               - Linux: `~/.config/environment.d/*.conf`, the systemd user
                 environment a graphical session imports at login.

             Every backend is user scope only, reversible, and touches only the
             key it was asked about: the macOS agent and the Linux drop-in are
             read, merged and rewritten, so clearing one key never discards
             another. The plist is written and read with `plistlib` and the shell
             command quoted with `shlex`, so no value can break the file it is
             stored in. All three take their side-effecting calls as arguments -
             the registry module, the command runner, the home directory - so a
             test drives any platform's backend from any platform.
@input      a variable name and value, the platform to act as, and injected
            registry / command / home seams
@output     the stored value (or None), and True for a completed set or clear
@dependencies stdlib: os, pathlib, plistlib, shlex, subprocess, sys; winreg
              (Windows only, imported through one seam)
"""
from __future__ import annotations

import os
import pathlib
import plistlib
import shlex
import subprocess
import sys

WINDOWS, MACOS, LINUX = "win32", "darwin", "linux"

# macOS LaunchAgent that re-applies the variables at each login.
AGENT_LABEL = "com.conpact.codexcli"
# Our own record inside that agent: launchd ignores keys it does not know, so
# what we set can be read back exactly rather than parsed out of a command line.
AGENT_RECORD = "ConpactVariables"
# Linux systemd user-environment drop-in.
ENVD_FILE = "10-conpact-codex.conf"

# Tests point this at a temporary directory; None means the real user's home.
HOME = None
LAUNCHCTL = "/bin/launchctl"


def platform_name(platform=None) -> str:
    """One of WINDOWS / MACOS / LINUX for the platform we are acting as."""
    name = sys.platform if platform is None else platform
    if name.startswith("win"):
        return WINDOWS
    if name.startswith("darwin"):
        return MACOS
    return LINUX


def home() -> pathlib.Path:
    return pathlib.Path(HOME) if HOME else pathlib.Path(os.path.expanduser("~"))


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=15)


# --------------------------------------------------------------- Windows -----

ENV_SUBKEY = "Environment"
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002


def _winreg():
    """The registry module, imported here rather than at module scope: this file
    is imported on every platform and `winreg` exists only on Windows. A test
    substitutes a stand-in, which is how the Windows backend is exercised from
    any machine."""
    import winreg
    return winreg


def _win_open(access):
    winreg = _winreg()
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_SUBKEY, 0, access)


def _win_broadcast():
    import ctypes
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p(ENV_SUBKEY),
        SMTO_ABORTIFHUNG, 5000, None)


def _win_get(key, opener):
    winreg = _winreg()
    try:
        handle = (opener or _win_open)(winreg.KEY_READ)
    except OSError:
        return None
    try:
        value, _ = winreg.QueryValueEx(handle, key)
        return value if isinstance(value, str) and value else None
    except FileNotFoundError:
        return None
    finally:
        winreg.CloseKey(handle)


def _win_set(key, value, opener, broadcaster):
    winreg = _winreg()
    handle = (opener or _win_open)(winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(handle, key, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(handle)
    (broadcaster or _win_broadcast)()
    return True


def _win_clear(key, opener, broadcaster):
    winreg = _winreg()
    handle = (opener or _win_open)(winreg.KEY_SET_VALUE)
    try:
        winreg.DeleteValue(handle, key)
    except FileNotFoundError:
        pass
    finally:
        winreg.CloseKey(handle)
    (broadcaster or _win_broadcast)()
    return True


# ----------------------------------------------------------------- macOS -----

def agent_path() -> pathlib.Path:
    return home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def _agent_plist(pairs: dict) -> dict:
    """The login agent: one `launchctl setenv` per variable, run at login. The
    command is built with shlex so a path with a space or a quote in it stays one
    argument, and the pairs are kept verbatim under our own key so reading them
    back is not a parse."""
    command = " && ".join(
        "launchctl setenv " + shlex.quote(key) + " " + shlex.quote(value)
        for key, value in sorted(pairs.items()))
    return {"Label": AGENT_LABEL,
            "ProgramArguments": ["/bin/sh", "-c", command],
            "RunAtLoad": True,
            AGENT_RECORD: dict(pairs)}


def _agent_pairs() -> dict:
    """What our login agent currently sets."""
    try:
        with open(agent_path(), "rb") as handle:
            stored = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}
    record = stored.get(AGENT_RECORD) if isinstance(stored, dict) else None
    return {k: v for k, v in record.items() if isinstance(v, str)} \
        if isinstance(record, dict) else {}


def _write_agent(pairs) -> None:
    path = agent_path()
    if not pairs:
        try:
            path.unlink()
        except OSError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        plistlib.dump(_agent_plist(pairs), handle)


def _launchctl(argv, runner):
    result = (runner or _run)([LAUNCHCTL, *argv])
    if getattr(result, "returncode", 0) != 0:
        detail = (getattr(result, "stderr", "") or "").strip()
        raise OSError(detail or f"launchctl {' '.join(argv)} failed")
    return result


def _mac_caller_value(key, runner):
    try:
        result = _launchctl(["getenv", key], runner)
        live = (getattr(result, "stdout", "") or "").strip()
    except (OSError, subprocess.SubprocessError):
        live = ""
    return live or None


def _mac_gui_value(key, runner, uid=None):
    """Read the graphical login bootstrap directly, not the caller's domain."""
    user = os.getuid() if uid is None else uid
    try:
        result = _launchctl(["print", f"gui/{user}"], runner)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (getattr(result, "stdout", "") or "").splitlines():
        name, marker, value = line.strip().partition(" => ")
        if marker and name == key:
            return value.strip() or None
    return None


def _mac_status(key, runner):
    persistent = _agent_pairs().get(key) or None
    caller = _mac_caller_value(key, runner)
    gui = _mac_gui_value(key, runner)
    values = {"persistent": persistent, "caller": caller, "gui": gui}
    effective = gui or caller or persistent
    return {**values, "effective": effective,
            "discrepancy": len(set(values.values())) > 1}


def _mac_get(key, runner):
    """The GUI value, then caller value, then the durable login record."""
    return _mac_status(key, runner)["effective"]


def _mac_set(key, value, runner):
    user = os.getuid()
    _launchctl(["setenv", key, value], runner)
    _launchctl(["asuser", str(user), LAUNCHCTL, "setenv", key, value], runner)
    if _mac_gui_value(key, runner, user) != value:
        raise OSError(f"gui/{user} did not retain {key}")
    pairs = _agent_pairs()
    pairs[key] = value
    _write_agent(pairs)
    return True


def _mac_clear(key, runner):
    pairs = _agent_pairs()
    pairs.pop(key, None)
    _write_agent(pairs)
    user = os.getuid()
    _launchctl(["unsetenv", key], runner)
    _launchctl(["asuser", str(user), LAUNCHCTL, "unsetenv", key], runner)
    if _mac_gui_value(key, runner, user) is not None:
        raise OSError(f"gui/{user} still contains {key}")
    return True


# ----------------------------------------------------------------- Linux -----

def envd_path() -> pathlib.Path:
    return home() / ".config" / "environment.d" / ENVD_FILE


def _envd_pairs() -> dict:
    pairs = {}
    try:
        body = envd_path().read_text(encoding="utf-8")
    except OSError:
        return pairs
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if sep and name.strip() and value:
            pairs[name.strip()] = value
    return pairs


def _write_envd(pairs) -> None:
    path = envd_path()
    if not pairs:
        try:
            path.unlink()
        except OSError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Quoted: systemd's parser would otherwise end the value at the first space.
    path.write_text("".join(f'{key}="{value}"\n' for key, value in sorted(pairs.items())),
                    encoding="utf-8")


def _linux_get(key):
    return _envd_pairs().get(key) or None


def _linux_set(key, value):
    pairs = _envd_pairs()
    pairs[key] = value
    _write_envd(pairs)
    return True


def _linux_clear(key):
    pairs = _envd_pairs()
    pairs.pop(key, None)
    _write_envd(pairs)
    return True


# -------------------------------------------------------------- dispatch -----

def get(key, platform=None, opener=None, runner=None):
    """The current user-scope value of `key`, or None."""
    which = platform_name(platform)
    if which == WINDOWS:
        return _win_get(key, opener)
    if which == MACOS:
        return _mac_get(key, runner)
    return _linux_get(key)


def status(key, platform=None, opener=None, runner=None) -> dict:
    """Values by persistence/bootstrap domain, with the GUI-effective value."""
    which = platform_name(platform)
    if which == MACOS:
        return _mac_status(key, runner)
    value = get(key, platform, opener=opener, runner=runner)
    return {"persistent": value, "caller": None, "gui": None,
            "effective": value, "discrepancy": False}


def set_value(key, value, platform=None, opener=None, broadcaster=None, runner=None) -> bool:
    """Store `key`=`value` durably for the user's GUI session, or raise OSError."""
    which = platform_name(platform)
    if which == WINDOWS:
        return _win_set(key, value, opener, broadcaster)
    if which == MACOS:
        return _mac_set(key, value, runner)
    return _linux_set(key, value)


def clear(key, platform=None, opener=None, broadcaster=None, runner=None) -> bool:
    """Remove `key` from the user's environment store, leaving every other key we
    stored in place."""
    which = platform_name(platform)
    if which == WINDOWS:
        return _win_clear(key, opener, broadcaster)
    if which == MACOS:
        return _mac_clear(key, runner)
    return _linux_clear(key)


def store_note(platform=None) -> str:
    """How the change reaches a GUI app, per platform - shown to the user so the
    restart step is understood rather than guessed at."""
    which = platform_name(platform)
    if which == WINDOWS:
        return "written to your user environment (HKCU); restart ChatGPT Desktop to apply."
    if which == MACOS:
        return ("set with launchctl and a login agent; restart ChatGPT Desktop to apply "
                "(a full log out and back in applies it to every app).")
    return ("written to ~/.config/environment.d; log out and back in, then start ChatGPT, "
            "for a graphical session to import it.")
