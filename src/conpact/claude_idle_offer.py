"""
@module conpact.claude_idle_offer
@description The one time conPACT asks about Claude Code's own idle compaction.
             When Anthropic switches it on for the account, it does the job
             conPACT's idle toast does - a minute sooner and without asking - so
             at the next turn end the Stop hook asks which one the user wants:
             conPACT's (Claude Code's is turned off with "idleCompaction": false),
             Claude Code's (conPACT's idle toast is turned off), or both (nothing
             changes). It is asked only while Claude Code's is active and
             conPACT's toast is on, and only once: a record in conPACT's home is
             claimed before the toast starts, so two turn ends at once ask once,
             and it is never asked again whatever the answer - or none - and
             whatever Anthropic's switch does later. Only a toast that never
             started, or found nothing left to ask about, gives the claim back.
             The settings window keeps both switches for any later change.
             The toast waits for its answer rather than timing out (D-20261014-092).
@input      Claude Code's idle-compaction state (conpact.claude_idle_compaction); the record
@output     a detached process showing the question; the answer applied, recorded and logged
@dependencies conpact.claude_idle_compaction, conpact.compaction, conpact.detach,
              conpact.idle_state, conpact.settings, conpact.toast_view (lazily);
              stdlib: json, os, pathlib, sys, time
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from . import claude_idle_compaction, compaction, detach, idle_state, settings as user_settings

MODULE = "conpact.claude_idle_offer"
SRC_ROOT = str(pathlib.Path(__file__).resolve().parents[1])
RECORD_NAME = "claude-idle-offer.json"
ANSWERS = {"use_conpact": "claude_idle_off", "use_claude": "conpact_idle_off"}


def record_path() -> pathlib.Path:
    return compaction.STATE_DIR / RECORD_NAME


def read_record() -> dict | None:
    """What was asked and answered; None if never asked, {} if the record is damaged."""
    path = record_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_record(data: dict) -> None:
    path = record_path()
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data) + "\n", encoding="utf-8")
    os.replace(temp, path)


def claim(now: float, found: dict) -> bool:
    """Take the one question for this process. False if it was already taken."""
    path = record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps({"asked_at": now, "server": found["server"]}) + "\n")
    except FileExistsError:
        return False
    return True


def _release() -> None:
    record_path().unlink(missing_ok=True)


def offer(environ=None, clock=time.time, spawner=None) -> dict:
    """Ask, in a detached toast, if it is time to; a status either way. The
    cheapest reasons come first: once asked, a turn end reads nothing more."""
    environ = os.environ if environ is None else environ
    if record_path().exists():
        return {"action": "skip", "reason": "already asked"}
    if not idle_state.is_enabled():
        return {"action": "skip", "reason": "conPACT's idle toast is off"}
    found = claude_idle_compaction.state(environ)
    if not found["active"]:
        return {"action": "skip", "reason": "Claude Code's idle compaction is not active"}
    if not claim(clock(), found):
        return {"action": "skip", "reason": "already asked"}
    argv = [detach.windowless_python(), "-m", MODULE]
    try:
        pid = (spawner or detach.spawn)(argv, env={**environ, "PYTHONPATH": SRC_ROOT})
    except OSError as exc:
        _release()   # never shown, so never asked
        return {"action": "error", "reason": f"the question did not start: {exc}"}
    return {"action": "offered", "pid": pid, "server": found["server"]}


def run(environ=None, **options) -> dict:
    """offer(), logging everything but a skip. Never raises: it runs in the Stop hook."""
    try:
        status = offer(environ, **options)
    except Exception as exc:  # the hook must never fail because of the question
        status = {"action": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if status["action"] == "offered":
        idle_state.append_log({"event": "claude_idle_offered", "server": status["server"], "pid": status["pid"]})
    elif status["action"] == "error":
        idle_state.append_log({"event": "claude_idle_offer_error", "reason": status["reason"]})
    return status


class Offer:
    """The toast's controller: the question, and what each answer changes."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.outcome = None

    def model(self) -> dict:
        # No deadline: it is asked once, so it waits to be answered.
        return {"kind": "claude_idle", "deadline": None, "span": None}

    def poll(self) -> str | None:
        return None

    def progress(self) -> dict:
        return {"state": "untracked"}

    def act(self, action: str) -> dict:
        if self.outcome is not None:
            return {"state": "closed"}
        if action == "dismiss":
            self.outcome = {"event": "claude_idle_answered", "answer": "keep_both"}
            return {"state": "closed"}
        if action not in ANSWERS:
            return {"state": "closed"}
        try:
            if action == "use_conpact":
                claude_idle_compaction.set_allowed(False)
            else:
                user_settings.save({user_settings.TOGGLE: False})
        except (OSError, ValueError) as exc:
            self.outcome = {"event": "claude_idle_failed", "answer": action, "reason": f"{type(exc).__name__}: {exc}"}
            return {"state": "setting_failed", "detail": str(exc)}
        self.outcome = {"event": "claude_idle_answered", "answer": action}
        return {"state": ANSWERS[action]}


def main(argv=None, clock=time.time, environ=None) -> int:
    found = claude_idle_compaction.state(environ)
    if not (found["active"] and idle_state.is_enabled()):
        _release()   # nothing left to ask about, so nothing was asked
        idle_state.append_log({"event": "claude_idle_moot", "server": found["server"]})
        return 0
    from . import toast_view  # tkinter is only needed once there is something to show
    asked = Offer(clock)
    try:
        toast_view.present(asked)
        outcome = asked.outcome or {"event": "claude_idle_unanswered"}
    except Exception as exc:  # a detached process has nowhere else to report
        outcome = asked.outcome or {"event": "claude_idle_offer_error", "reason": f"{type(exc).__name__}: {exc}"}
    record = read_record() or {}
    _write_record({**record, "answer": outcome.get("answer", "none"), "answered_at": clock()})
    idle_state.append_log(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
