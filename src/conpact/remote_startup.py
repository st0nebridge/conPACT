"""
@module conpact.remote_startup
@description One setting of Claude Code's own, read here and written only when the
             user clicks for it: "remoteControlAtStartup" - start the Remote
             Control bridge with every session. It is the difference between
             fixing one session's Remote Control and never having to think about
             it again, and Claude Code only honours it at user scope (a repo's
             settings cannot enable Remote Control). This module touches that one
             key and nothing else: everything already in the file is kept, the
             write is atomic, and a file that cannot be parsed is refused rather
             than replaced - these are the user's settings, not ours (D-021).
@input      ~/.claude/settings.json
@output     whether the setting is on; a file with that one key added
@dependencies conpact.session_registry; stdlib: json, os, pathlib
"""
from __future__ import annotations

import json
import os
import pathlib

from . import session_registry

KEY = "remoteControlAtStartup"
NAME = "settings.json"


def settings_path() -> pathlib.Path:
    """The user-scope settings file. Project and local scopes cannot enable Remote Control."""
    return session_registry.CLAUDE_DIR / NAME


def _read(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_on(path: pathlib.Path | None = None) -> bool:
    """True only if the setting is there and true. Unreadable reads as off, so we offer."""
    data = _read(path or settings_path())
    return isinstance(data, dict) and data.get(KEY) is True


def turn_on(path: pathlib.Path | None = None) -> bool:
    """Add the setting, keeping everything else. True if the file changed.

    Raises ValueError if the file is not a JSON object we can add a key to, and
    OSError if it cannot be written: either way the file is left as it was.
    """
    target = path or settings_path()
    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{target} is not readable as JSON, so it will not be written: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{target} does not hold a JSON object, so it will not be written")
    if data.get(KEY) is True:
        return False
    data[KEY] = True
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return True
