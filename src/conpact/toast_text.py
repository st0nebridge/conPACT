"""
@module conpact.toast_text
@description Every word the idle toast shows and the number formats it uses, as
             pure functions of the controller's model and the current time, so
             the wording is testable without a display.
@input      a toast model dict (kind ask/notice/remote, stage early/expiry, name,
            context_tokens, last_call, deadline, span, expires_at, mute_seconds,
            variant, compacting, detail, offer_always_on, offer_auto_off), the
            current time, a view state (from a click, or the progress of a sent
            compaction)
@output     strings; the button list (action, label, style) for a model. Styles
            are primary/secondary/ghost for the choices that end this toast and
            link for the standing ones, which the view puts on a second line;
            labels are kept short enough for the card to hold the row.
@dependencies none
"""
from __future__ import annotations

BRAND = "conPACT"
MAX_NAME = 40
SETTINGS_LINK = "Settings"

_ACTIONS = {
    # Labels are kept short on purpose: measured against the card, "Auto-compact
    # this session" and "Always compact before expiry" pushed "Not now" off the
    # right-hand edge - half of it was clipped on the toast the user actually saw.
    "ask": (("compact", "Compact now", "primary"),
            ("auto", "Always compact", "secondary"),
            ("dismiss", "Not now", "ghost")),
    "notice": (("turn_off_auto", "Turn off auto-compact", "secondary"),
               ("dismiss", "OK", "ghost")),
    "remote": (("open_session", "Open the session", "primary"),
               ("always_on", "Always on for new sessions", "secondary"),
               ("dismiss", "Not now", "ghost")),
}
# The early toast is the only one with a later stage to hand the work to, so it
# is the only one that can offer to wait: "defer" for this idle, "auto_expiry"
# for every idle after it. The two standing choices are links rather than
# buttons because the row cannot hold five - see toast_view.
_EARLY_ACTIONS = (("compact", "Compact now", "primary"),
                  ("defer", "Near expiry", "secondary"),
                  ("dismiss", "Not now", "ghost"),
                  ("auto", "Always when idle", "link"),
                  ("auto_expiry", "Always near expiry", "link"))
# The auto button sets the stage it was pressed at, so it says which one.
_AUTO_LABELS = {"expiry": "Always near expiry"}


def tokens(count: int) -> str:
    """656725 -> "657k"; 1250000 -> "1.3M"; 950 -> "950"."""
    if count < 1000:
        return str(count)
    if round(count / 1000) < 1000:
        return f"{round(count / 1000)}k"
    return f"{count / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def duration(seconds: float) -> str:
    """45 -> "45 s"; 3300 -> "55 min"; 3900 -> "1 h 5 min"."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def elapsed(seconds: float) -> str:
    """42.9 -> "42 s"; 102 -> "1 min 42 s"; 600 -> "10 min"."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes} min {secs} s" if secs else f"{minutes} min"


def countdown(seconds: float) -> str:
    """299.2 -> "5:00" (rounded up, never below 0:00)."""
    whole = max(0, -int(-seconds // 1))
    minutes, secs = divmod(whole, 60)
    return f"{minutes}:{secs:02d}"


def session_name(name) -> str:
    # A Codex thread is a session too - ChatGPT Desktop's own - so the toast
    # calls both the same thing and the user is not taught a second word.
    if not isinstance(name, str) or not name.strip():
        return "this session"
    name = " ".join(name.split())
    return name if len(name) <= MAX_NAME else name[:MAX_NAME - 1].rstrip() + "…"


def _quoted(model) -> str:
    name = session_name(model.get("name"))
    return name if name == "this session" else f"“{name}”"


def title(model: dict, state: str | None = None) -> str:
    """The toast's heading; `state` is "compacting" or "compacted" once a compaction is under way."""
    name, auto = _quoted(model), model["kind"] == "notice"
    if model["kind"] == "remote":
        return f"Remote Control is off for {name}"
    if state == "compacted":
        return f"{'Auto-compacted' if auto else 'Compacted'} {name}"
    if auto and model.get("variant") == "failed":
        return f"Couldn't auto-compact {name}"
    if auto or state == "compacting":
        return f"{'Auto-compacting' if auto else 'Compacting'} {name}"
    return f"Compact {name}?"


def body(model: dict, now: float) -> str:
    return f"{tokens(model['context_tokens'])} tokens · idle {duration(now - model['last_call'])}"


def status(model: dict, now: float) -> str:
    if model["kind"] == "remote":
        if model.get("offer_always_on"):
            return "Nothing can be sent to it. Open it for the switch, or turn Remote Control on for every new session."
        return "Nothing can be sent to it, so it cannot be compacted. The switch is in its toolbar."
    if model["kind"] == "ask":
        # Codex never states its cache lifetime, so ours is modelled from
        # measurement (codex_window) and the toast says so rather than implying
        # it was read from the app.
        about = "Prompt cache expires in" if not model.get("ttl_is_modelled")             else "Prompt cache should expire in about"
        if model.get("stage") == "early":  # the cache has a long way to go: no ticking clock
            return f"{about} {duration(model['expires_at'] - now)}"
        return f"{about} {countdown(model['deadline'] - now)}"
    if model.get("variant") == "failed":
        return f"Couldn't compact: {model.get('detail')}"
    return "Compacting…"


def state_message(state: dict) -> str:
    kind = state.get("state")
    if kind == "working":
        return "Sending /compact…"
    if kind == "compacting":
        return f"Compacting… {countdown(int(state['elapsed']))}"
    if kind == "compacted":
        before, after = state.get("pre_tokens"), state.get("post_tokens")
        done = f"Done in {elapsed(state['seconds'])}"
        return f"{done}: {tokens(before)} → {tokens(after)} tokens." if None not in (before, after) else f"{done}."
    if kind == "unconfirmed":
        return f"No result after {duration(state['seconds'])}. Check the session."
    if kind == "untracked":
        return "Compaction started. It can take a minute or two."
    if kind == "auto_off":
        return "Auto-compact is off for this session."
    if kind == "deferred":
        return "Compacting near expiry instead, unless you use this session first."
    if kind == "auto_expiry_set":
        return "Compacting near expiry from now on."
    if kind == "startup_on":
        return "Remote Control will start with every new session."
    if kind == "startup_failed":
        return f"Couldn't change the setting: {state.get('detail')}"
    if kind == "remote_failed":
        return f"Couldn't open the session: {state.get('detail')}"
    return f"Couldn't compact: {state.get('detail')}"


def actions(model: dict) -> tuple:
    found = _ACTIONS[model["kind"]]
    if model["kind"] == "remote":
        # Nothing offers to change a setting that is already set.
        return tuple(a for a in found if a[0] != "always_on" or model.get("offer_always_on"))
    if model["kind"] == "notice":
        # A compaction deferred for this idle alone set no switch to turn off.
        return tuple(a for a in found if a[0] != "turn_off_auto" or model.get("offer_auto_off", True))
    if model.get("stage") == "early":
        return _EARLY_ACTIONS
    label = _AUTO_LABELS.get(model.get("stage"))
    if label is None:
        return found
    return tuple((action, label if action == "auto" else text, style) for action, text, style in found)


def mute_label(seconds) -> str:
    """The link that silences this session; it says how long for."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return "Silence"
    return f"Silence {duration(seconds)}"


def settings_failed(exc: Exception) -> str:
    """The toast's line when the settings window could not be started."""
    return f"Couldn't open the settings: {exc}"
