"""
@module conpact.remote_startup
@description One setting of Claude Code's own, read here and written only when the
             user clicks for it: "remoteControlAtStartup" - start the Remote
             Control bridge with every session. It is the difference between
             fixing one session's Remote Control and never having to think about
             it again, and Claude Code only honours it at user scope (a repo's
             settings cannot enable Remote Control). Only this key is touched,
             through conpact.claude_settings, which keeps everything already in
             the file, writes atomically and refuses a file it cannot parse -
             these are the user's settings, not ours (D-021).
@input      ~/.claude/settings.json
@output     whether the setting is on; a file with that one key added
@dependencies conpact.claude_settings; stdlib: os, pathlib
"""
from __future__ import annotations

import os  # noqa: F401 (tests reach the rename through this module)
import pathlib

from . import claude_settings

KEY = "remoteControlAtStartup"
NAME = claude_settings.NAME


def settings_path() -> pathlib.Path:
    """The user-scope settings file. Project and local scopes cannot enable Remote Control."""
    return claude_settings.path()


def is_on(path: pathlib.Path | None = None) -> bool:
    """True only if the setting is there and true. Unreadable reads as off, so we offer."""
    data = claude_settings.read(path)
    return isinstance(data, dict) and data.get(KEY) is True


def turn_on(path: pathlib.Path | None = None) -> bool:
    """Add the setting, keeping everything else. True if the file changed.

    Raises ValueError if the file is not a JSON object we can add a key to, and
    OSError if it cannot be written: either way the file is left as it was.
    """
    return claude_settings.set_key(KEY, True, path)
