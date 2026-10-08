"""
@module conpact.settings
@description The user's conPACT settings: what each one means, its default
             and its allowed range, stored in one file in conPACT's own
             folder (D-009, D-016). The idle toast's on/off setting is kept as
             the off-switch file instead, which the Stop wrapper checks before it
             starts Python. Reading never fails: a missing or unusable file, or
             an unusable value, gives the default. Saving checks every value
             first and writes nothing if any is refused; it stores only values
             that differ from their defaults and keeps keys it does not know.
@input      setting keys, and values from the settings window or command (typed
            text is parsed here)
@output     settings dicts; settings.json and the off switch on disk
@dependencies conpact.compaction, conpact.idle_state; stdlib: dataclasses, json, os
"""
from __future__ import annotations

import dataclasses
import json
import os

from . import compaction, idle_state

TOGGLE = "idle_toast"
GUARD_SPIN_OFF = "guard_spin_off_sessions"
APPLIES = "New values apply from the next turn end."
MAX_DAY = 86_400


@dataclasses.dataclass(frozen=True)
class Setting:
    key: str
    label: str
    help: str
    default: object
    low: int | None = None
    high: int | None = None
    unit: str | None = None  # "tokens", "percent" or "seconds"; None for the on/off toggle
    optional: bool = False   # may be off (None)


SETTINGS = (
    Setting(TOGGLE, "Idle toast",
            "Offers to compact a session that has gone idle, shortly before its prompt cache expires.", True),
    Setting("min_context_fill", "Toast only for sessions at least this full",
            "Used wherever the app reports its context window - ChatGPT Desktop does. "
            "A fraction travels between apps in a way a token count does not: "
            "300,000 tokens is a large Claude session and is more than a ChatGPT "
            "session's whole window, so an absolute minimum silenced that app entirely.",
            50, 1, 100, "percent"),
    Setting("min_context_tokens", "Toast only for sessions of at least",
            "Smaller sessions are cheap to pick up again, so they get no toast. "
            "Used where the app does not report a context window to take a fraction of, "
            "which today means Claude Code.",
            100_000, 1, compaction.MAX_CONTEXT_TOKENS, "tokens"),
    Setting("lead_seconds", "Show the toast this long before the cache expires",
            "Never earlier than 60% of the way through the cache's lifetime. With the default and a 1-hour "
            "cache, the toast comes 55 minutes after the last reply.",
            300, 10, MAX_DAY, "seconds"),
    Setting("idle_seconds", "Also show an early toast after an idle time of",
            "An extra, earlier offer. Dismissing it does not stop the one before the cache expires. "
            "Off unless set.",
            None, 10, MAX_DAY, "seconds", optional=True),
    Setting("early_toast_seconds", "The early toast waits for an answer for",
            "It closes itself after this, leaving the one before the cache expires to come later.",
            120, 10, MAX_DAY, "seconds"),
    Setting("mute_seconds", "\"Silence this session\" silences it for",
            "Or until the session is used again, whichever comes first.",
            86_400, 60, 604_800, "seconds"),
    Setting("closure_min_context_tokens", "Compaction an agent queues: only if the context is at least",
            "Used when the agent sets no minimum itself. When off, such a compaction always runs.",
            None, 1, compaction.MAX_CONTEXT_TOKENS, "tokens", optional=True),
    Setting(GUARD_SPIN_OFF, "Refuse a compaction queued in a worktree session",
            "A session working in a .claude/worktrees/... checkout is merged and archived rather than "
            "resumed, so the summary is never read. Turn this off to let one compact itself anyway.",
            True),
    Setting("result_seconds", "Keep the result on screen for",
            "How long the toast shows the finished compaction before it closes.", 8, 1, 600, "seconds"),
)
_BY_KEY = {s.key: s for s in SETTINGS}
_ON = {"on", "true", "yes", "1"}
_OFF = {"off", "false", "no", "0"}
_EMPTY = {"", "off", "none"}


def settings_path():
    return compaction.STATE_DIR / "settings.json"


def get(key) -> Setting:
    try:
        return _BY_KEY[key]
    except (KeyError, TypeError):
        raise ValueError(f"unknown setting {key!r} (known: {', '.join(_BY_KEY)})") from None


def defaults() -> dict:
    return {s.key: s.default for s in SETTINGS}


def allowed(key) -> str:
    """The values a setting accepts, in words."""
    s = get(key)
    if s.unit is None:
        return "on or off"
    return f"{s.low:,} to {s.high:,} {s.unit}" + (", or off" if s.optional else "")


def describe(key, value) -> str:
    """A value as the user reads it: "on", "100,000 tokens", "50%", "300 s", "off"."""
    s = get(key)
    if s.unit is None:
        return "on" if value else "off"
    if value is None:
        return "off"
    if s.unit == "tokens":
        return f"{value:,} tokens"
    return f"{value}%" if s.unit == "percent" else f"{value:,} s"


def check(key, value):
    """The value if the setting accepts it; otherwise ValueError saying what it accepts."""
    s = get(key)
    if s.unit is None:
        if isinstance(value, bool):
            return value
        raise ValueError(f"{key} must be on or off")
    if value is None:
        if s.optional:
            return None
        raise ValueError(f"{key} needs a value ({allowed(key)})")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a whole number: {allowed(key)}")
    if not s.low <= value <= s.high:
        raise ValueError(f"{key} must be from {allowed(key)}")
    return value


def parse(key, text) -> object:
    """A typed value: "150000", "150,000", "150k", "50%", "on", "off", or empty."""
    s = get(key)
    word = str(text).strip().lower()
    if s.unit is None:
        if word in _ON:
            return True
        if word in _OFF:
            return False
        raise ValueError(f"{key} must be on or off")
    if word in _EMPTY:
        return check(key, None)
    digits, scale = word.replace(",", "").replace("_", "").replace(" ", ""), 1
    if s.unit == "percent" and digits.endswith("%"):
        digits = digits[:-1]            # "50%" is exactly how `describe` writes it
    if digits.endswith("k"):
        digits, scale = digits[:-1], 1000
    if not (digits.isascii() and digits.isdigit()):
        raise ValueError(f"{key} must be a whole number: {allowed(key)}")
    return check(key, int(digits) * scale)


def _read() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load() -> dict:
    """Every setting: the file's usable values over the defaults, and the toggle from the off switch."""
    values = defaults()
    for key, value in _read().items():
        if key in _BY_KEY and key != TOGGLE:
            try:
                values[key] = check(key, value)
            except ValueError:
                pass
    values[TOGGLE] = idle_state.is_enabled()
    return values


def _write(data: dict) -> None:
    path = settings_path()
    if not data:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _switch(on: bool) -> None:
    path = idle_state.off_switch_path()
    if on:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def save(changes: dict) -> dict:
    """Check every change, then store them all (or, if any is refused, none). Returns load()."""
    checked = {key: check(key, value) for key, value in changes.items()}
    data = _read()
    for key, value in checked.items():
        if key == TOGGLE:
            continue
        if value == _BY_KEY[key].default:
            data.pop(key, None)
        else:
            data[key] = value
    _write(data)
    if TOGGLE in checked:
        _switch(checked[TOGGLE])
    return load()


def reset(keys=None) -> dict:
    """Put these settings (all when None) back to their defaults. Returns load()."""
    keys = list(_BY_KEY) if keys is None else list(keys)
    return save({key: get(key).default for key in keys})
