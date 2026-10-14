"""
@module conpact.claude_idle_compaction
@description Claude Code's own idle compaction: since 2.1.286 it can compact a
             large idle session (200k tokens or more) at 90% of its one-hour
             cache - about 54 minutes, a minute before conPACT's toast - without
             asking. Whether it runs is decided in three places, all read here:
             Anthropic's switch for the account, which Claude Code caches in
             ~/.claude.json under cachedGrowthBookFeatures (off, log or compact);
             the user's opt-out, "idleCompaction": false in Claude Code's user
             settings; and auto-compaction itself (autoCompactEnabled,
             DISABLE_AUTO_COMPACT, DISABLE_COMPACT), without which it never runs.
             The switch is an undocumented, internally named flag: one that
             cannot be found reads as unknown, never as off. Writing the opt-out
             goes through conpact.claude_settings; allowing it again removes the
             key, because "true" does not turn idle compaction on (D-20261014-092).
@input      ~/.claude.json, ~/.claude/settings.json, the environment
@output     the state (server mode, allowed, auto_compact, active); the opt-out written or removed
@dependencies conpact.claude_settings, conpact.session_registry; stdlib: json, os, pathlib
"""
from __future__ import annotations

import json
import os
import pathlib

from . import claude_settings, session_registry

KEY = "idleCompaction"
FLAG = "tengu_sunny_locket"   # Claude Code 2.1.286 to 2.1.295 at least
CONFIG_NAME = ".claude.json"
NOT_OFF = ("log", "compact")   # the two modes Claude Code tells apart from off
DISABLING = ("DISABLE_AUTO_COMPACT", "DISABLE_COMPACT")
_TRUE = ("1", "true", "yes", "on")   # what Claude Code takes as a set environment switch
_WORDS = {"compact": "on", "log": "logging only, not compacting", "off": "off", None: "not found"}


def config_path() -> pathlib.Path:
    """Claude Code's own config file, which sits beside its folder in the user's home."""
    return session_registry.CLAUDE_DIR.parent / CONFIG_NAME


def server_mode(path: pathlib.Path | None = None) -> str | None:
    """Anthropic's switch as Claude Code last cached it: "compact", "log" or "off".
    None when it cannot be found - no file, no cache, or a flag not in it."""
    try:
        data = json.loads((path or config_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    features = data.get("cachedGrowthBookFeatures") if isinstance(data, dict) else None
    if not isinstance(features, dict) or FLAG not in features:
        return None
    value = features[FLAG]
    mode = value.get("mode") if isinstance(value, dict) else None
    return mode if mode in NOT_OFF else "off"


def allowed(path: pathlib.Path | None = None) -> bool:
    """False only when the user's settings say "idleCompaction": false."""
    data = claude_settings.read(path)
    return not (isinstance(data, dict) and data.get(KEY) is False)


def _set(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in _TRUE


def auto_compact_on(environ=None, path: pathlib.Path | None = None) -> bool:
    """Is auto-compaction on? Idle compaction is part of it and never runs without it."""
    environ = os.environ if environ is None else environ
    data = claude_settings.read(path)
    data = data if isinstance(data, dict) else {}
    block = data.get("env") if isinstance(data.get("env"), dict) else {}
    if any(_set(environ.get(name)) or _set(block.get(name)) for name in DISABLING):
        return False
    return data.get("autoCompactEnabled") is not False


def state(environ=None) -> dict:
    """Everything that decides it, and whether it will run: `active`."""
    server, allowing, auto = server_mode(), allowed(), auto_compact_on(environ)
    return {"server": server, "allowed": allowing, "auto_compact": auto,
            "active": server == "compact" and allowing and auto}


def set_allowed(allow: bool) -> bool:
    """Write the opt-out, or take it away. True if the file changed.
    Raises ValueError for a settings file that cannot be parsed, OSError if it cannot be written."""
    if allow:
        return claude_settings.remove_key(KEY)
    return claude_settings.set_key(KEY, False)


def server_words(mode) -> str:
    """Anthropic's switch as the user reads it."""
    return _WORDS.get(mode, "not found")
