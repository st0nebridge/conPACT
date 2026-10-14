"""
@module conpact.claude_settings
@description Claude Code's own user settings file (~/.claude/settings.json), read
             whole and written one key at a time. It is the user's file, not
             ours: a write keeps every other key where it was, keeps Claude
             Code's two-space indentation, is atomic, and refuses a file it
             cannot parse as a JSON object rather than replacing it (D-021). The
             keys conPACT may write, and when, are decided by the modules that
             call this one.
@input      ~/.claude/settings.json
@output     its contents; the file with one key set or removed
@dependencies conpact.session_registry; stdlib: json, os, pathlib
"""
from __future__ import annotations

import json
import os
import pathlib

from . import session_registry

NAME = "settings.json"


def path() -> pathlib.Path:
    """The user-scope settings file."""
    return session_registry.CLAUDE_DIR / NAME


def read(target: pathlib.Path | None = None) -> dict | None:
    """The settings, {} when there is no file, None when it cannot be read as a JSON object."""
    target = target or path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _for_writing(target: pathlib.Path) -> dict:
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{target} is not readable as JSON, so it will not be written: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{target} does not hold a JSON object, so it will not be written")
    return data


def _write(target: pathlib.Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _same(a, b) -> bool:
    """The same JSON value: in Python False == 0 and True == 1, which a settings file does not mean."""
    return json.dumps(a) == json.dumps(b)


def set_key(key: str, value, target: pathlib.Path | None = None) -> bool:
    """Set one key, keeping everything else. True if the file changed.

    Raises ValueError if the file is not a JSON object, and OSError if it cannot
    be written: either way the file is left as it was.
    """
    target = target or path()
    data = _for_writing(target)
    if key in data and _same(data[key], value):
        return False
    data[key] = value
    _write(target, data)
    return True


def remove_key(key: str, target: pathlib.Path | None = None) -> bool:
    """Take one key out, keeping everything else. True if the file changed; no file is created."""
    target = target or path()
    data = _for_writing(target)
    if key not in data:
        return False
    del data[key]
    _write(target, data)
    return True
