"""
@module conpact.idle_state
@description On-disk state of the idle notifier, all inside conPACT's own
             folder (D-009): the off switch (which conpact.settings presents
             as the idle_toast setting, and the Stop wrapper checks); the per-session
             watch marker whose generation tells a watcher it is still the
             current one; the per-session auto-compact switch, which holds the
             stage it acts at, and the per-session mute, both set only from the
             toast; the per-session hold, which skips only the early toast and is
             the one piece an agent can set (D-022); the notifier's log; and the screen slots that keep several
             toasts from overlapping. Paths are derived from compaction.STATE_DIR
             at call time.
@input      session ids, marker data, a mute's end and the call it was set after
@output     markers with a generation, switch states, mutes, log lines, slot numbers
@dependencies conpact.compaction, conpact.session_registry;
              stdlib: json, os, time, uuid
"""
from __future__ import annotations

import json
import os
import time
import uuid

from . import compaction, session_registry

AUTO_MODES = ("early", "expiry")
MAX_SLOTS = 4


def _base():
    return compaction.STATE_DIR


def off_switch_path():
    return _base() / "idle-notify.off"


def log_path():
    return _base() / "idle-log.jsonl"


def _plain(session_id: str) -> str:
    if not session_registry.is_valid_session_id(session_id):
        raise ValueError(f"not a plain session id: {session_id!r}")
    return session_id


def watch_path(session_id: str):
    return _base() / "idle" / "watch" / f"{_plain(session_id)}.json"


def auto_path(session_id: str):
    return _base() / "idle" / "auto" / _plain(session_id)


def mute_path(session_id: str):
    return _base() / "idle" / "mute" / f"{_plain(session_id)}.json"


def hold_path(session_id: str):
    return _base() / "idle" / "hold" / f"{_plain(session_id)}.json"


def slot_path(slot: int):
    return _base() / "idle" / "toasts" / f"slot-{slot}"


def is_enabled() -> bool:
    """On unless the user created the off switch (which the Stop wrapper also checks)."""
    return not off_switch_path().exists()


def _write_atomic(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_marker(session_id: str, data: dict) -> str:
    """Record a new watch for this session; returns its generation. Any older
    watcher for the session sees a different generation and stands down."""
    generation = uuid.uuid4().hex
    _write_atomic(watch_path(session_id), json.dumps({**data, "generation": generation}))
    return generation


def read_marker(session_id: str) -> dict | None:
    try:
        data = json.loads(watch_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_marker(session_id: str, generation: str) -> bool:
    """Remove the marker only if it is still this generation's."""
    marker = read_marker(session_id)
    if marker is None or marker.get("generation") != generation:
        return False
    try:
        watch_path(session_id).unlink()
    except OSError:
        return False
    return True


def set_auto(session_id: str, mode: str) -> None:
    """Compact this session at that stage - "early" or "expiry" - without asking
    on its later idles. Set only by the toast (D-014)."""
    if mode not in AUTO_MODES:
        raise ValueError(f"not an auto-compact mode: {mode!r}")
    path = auto_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode, encoding="utf-8")


def auto_mode(session_id: str) -> str | None:
    """Which stage compacts this session without asking, if any. A switch written
    before the stages existed, or one since damaged, means before the cache expires."""
    try:
        text = auto_path(session_id).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return text if text in AUTO_MODES else "expiry"


def clear_auto(session_id: str) -> bool:
    try:
        auto_path(session_id).unlink()
    except (OSError, ValueError):
        return False
    return True


def set_mute(session_id: str, until: float, after_call: float) -> None:
    """Silence this session's toasts until then - or until it is used after after_call."""
    _write_atomic(mute_path(session_id), json.dumps({"until": until, "after_call": after_call}))


def read_mute(session_id: str) -> dict | None:
    try:
        data = json.loads(mute_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    values = {}
    for field in ("until", "after_call"):
        value = data.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        values[field] = value
    return values


def clear_mute(session_id: str) -> bool:
    try:
        mute_path(session_id).unlink()
    except (OSError, ValueError):
        return False
    return True


def set_hold(session_id: str, until: float, reason: str | None = None) -> None:
    """Skip this session's early toast until then: an agent is mid-run, not gone.

    Unlike a mute this is not spent by using the session - a run takes many
    turns - and it never touches the toast before the cache expires (D-022).
    """
    body = {"until": until, **({"reason": reason} if reason else {})}
    _write_atomic(hold_path(session_id), json.dumps(body))


def read_hold(session_id: str) -> dict | None:
    try:
        data = json.loads(hold_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    until = data.get("until")
    if not isinstance(until, (int, float)) or isinstance(until, bool):
        return None
    reason = data.get("reason")
    return {"until": until, "reason": reason if isinstance(reason, str) else None}


def clear_hold(session_id: str) -> bool:
    try:
        hold_path(session_id).unlink()
    except (OSError, ValueError):
        return False
    return True


def append_log(entry: dict) -> None:
    """One JSON line per notable event. Diagnostics only: never raises."""
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry})
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _holder(slot: int) -> int | None:
    try:
        return int(slot_path(slot).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def claim_slot(pid: int, alive) -> int | None:
    """The lowest screen slot not held by a live toast, claimed for `pid`; None if all are held."""
    for slot in range(MAX_SLOTS):
        path = slot_path(slot)
        path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = _holder(slot)
                if holder is not None and alive(holder):
                    break  # held: try the next slot
                release_slot(slot)  # left behind by a toast that is gone: reclaim it
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(str(pid))
            return slot
    return None


def release_slot(slot: int | None) -> None:
    if slot is None:
        return
    try:
        slot_path(slot).unlink()
    except OSError:
        pass
