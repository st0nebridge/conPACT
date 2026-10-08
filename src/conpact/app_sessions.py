"""
@module conpact.app_sessions
@description What the Claude Code desktop app itself knows about a session, read
             only: has the user archived it, and what link opens it? The app keeps
             its own record of every session it has ever shown, under
             %APPDATA%/Claude/claude-code-sessions/<install>/<profile>/: one
             local_<host id>.json per session (with isArchived) and an
             archived-sessions.idx listing the archived ones, rewritten within a
             second of an archive. Archiving does not stop the session, so its
             runtime record stays and the idle notifier would otherwise still
             toast it. This module answers that one question and nothing else: it
             only reads, and an unreadable or missing store reads as "not
             archived" - a session the user can still see must never be silenced
             by a file we failed to parse.
             The app is Electron, so its folder is Electron's per-user data
             folder: %APPDATA% on Windows, ~/Library/Application Support on
             macOS, $XDG_CONFIG_HOME (else ~/.config) on Linux. Only the Windows
             layout has been read on a real machine; the others are Electron's
             documented defaults with the same app name.
@input      a host session id (the runtime record's hostSessionId)
@output     True only when the app's own store says the session is archived; the
            app's own claude:// link to a session, whose sidebar segment comes
            from the app's config (the toast's "Open the session")
@dependencies stdlib: json, os, pathlib, re, sys
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

APP_FOLDER = ("Claude", "claude-code-sessions")
INDEX_NAME = "archived-sessions.idx"
CONFIG = ("Claude", "claude_desktop_config.json")
LINK_PREFIX = "claude://claude.ai"
DEFAULT_SIDEBAR = "epitaxy"          # what the app calls its Claude Code sidebar
_PLAIN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _environ(environ) -> dict:
    return os.environ if environ is None else environ


def app_data(environ=None, platform=None) -> pathlib.Path | None:
    """Electron's per-user data folder, which the app's own "Claude" folder is in.

    APPDATA is Windows' own variable and, where it is set, it is the answer on
    any platform - which is also right for a Python that reports itself as
    cygwin or msys while running on Windows. Without it: Windows has nothing to
    read, macOS keeps app data under Library, and a Linux desktop under the XDG
    config folder.
    """
    env = _environ(environ)
    if env.get("APPDATA"):
        return pathlib.Path(env["APPDATA"])
    where = platform or sys.platform
    if where == "win32":
        return None
    home = env.get("HOME") or os.path.expanduser("~")
    if where == "darwin":
        return pathlib.Path(home, "Library", "Application Support")
    xdg = env.get("XDG_CONFIG_HOME")
    return pathlib.Path(xdg) if xdg else pathlib.Path(home, ".config")


def store_dirs(environ=None, platform=None) -> list[pathlib.Path]:
    """Every <install>/<profile> folder the app keeps session records in."""
    root = app_data(environ, platform)
    if root is None:
        return []
    base = root.joinpath(*APP_FOLDER)
    try:
        return sorted(path for path in base.glob("*/*") if path.is_dir())
    except OSError:
        return []


def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def archived_ids(environ=None, platform=None) -> set:
    """The host session ids the app's indexes list as archived."""
    found = set()
    for folder in store_dirs(environ, platform):
        data = _read_json(folder / INDEX_NAME)
        if isinstance(data, dict) and isinstance(data.get("archived"), list):
            found.update(item for item in data["archived"] if isinstance(item, str))
    return found


def _record_says(folder: pathlib.Path, host_session_id: str):
    """The session record's own isArchived, or None when it does not say."""
    data = _read_json(folder / f"{host_session_id}.json")
    if isinstance(data, dict) and isinstance(data.get("isArchived"), bool):
        return data["isArchived"]
    return None


def is_archived(host_session_id, environ=None, platform=None) -> bool:
    """True only if the app's store says so. The record wins: unarchiving rewrites it."""
    if not isinstance(host_session_id, str) or not _PLAIN.fullmatch(host_session_id):
        return False
    indexed = False
    for folder in store_dirs(environ, platform):
        stated = _record_says(folder, host_session_id)
        if stated is not None:
            return stated
        data = _read_json(folder / INDEX_NAME)
        if isinstance(data, dict) and isinstance(data.get("archived"), list):
            indexed = indexed or host_session_id in data["archived"]
    return indexed


def sidebar_mode(environ=None, platform=None) -> str:
    """What the app calls its Claude Code sidebar; its own links carry that word."""
    root = app_data(environ, platform)
    data = _read_json(root.joinpath(*CONFIG)) if root is not None else None
    mode = (data.get("preferences") or {}).get("sidebarMode") if isinstance(data, dict) else None
    return mode if isinstance(mode, str) and _PLAIN.fullmatch(mode) else DEFAULT_SIDEBAR


def session_link(host_session_id, environ=None, platform=None) -> str | None:
    """The app's own link to one session, which opens it - or None for an id we will not use."""
    if not isinstance(host_session_id, str) or not _PLAIN.fullmatch(host_session_id):
        return None
    return f"{LINK_PREFIX}/{sidebar_mode(environ, platform)}/{host_session_id}"
