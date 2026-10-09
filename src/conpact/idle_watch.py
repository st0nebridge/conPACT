"""
@module conpact.idle_watch
@description The idle watcher: a detached process the Stop hook starts for one
             session and one watch generation. It sleeps until the notify time,
             standing down as soon as the session is used again (a newer Stop
             re-armed it, its record shows it busy or changed since the Stop),
             is compacted by anything else (its transcript gains a compaction
             after the turn that armed it) or goes away. At the notify time it binds the session from the runtime
             and requires it to be idle; then, if the user switched this session
             to auto-compact, it sends /compact and shows a short notice (which
             can switch auto off again), and otherwise shows the toast and acts
             on the user's choice. From the early toast that choice can be to
             wait: "defer" hands this idle's compaction to the stage before the
             cache expires, which then acts without asking again, and
             "auto_expiry" writes the switch so every later idle does the same.
             A deferral lives in this process and nowhere else, so using the
             session ends the watcher and the deferral with it; the later stage
             re-checks before anything is sent regardless. Where the session's
             Claude Code mod is running (its beat is fresh) the compaction is
             handed to the mod, which compacts the session in-process with no
             Remote Control (conpact.mod_handoff); otherwise it is sent over
             the bridge. A session with neither gets a
             different toast, which says so and can open that session in the app
             but can never send (D-020); both are read at the notify time,
             so a switch flipped while the session sat idle is honoured.
             It sends only a constructed /compact (or asks the mod for the same
             compaction), only to the session bound from
             the runtime, never to a busy one, and at most once per watch.
             After a send it follows the session transcript until
             the compaction has finished (the toast shows its progress and result;
             if the toast was closed, the watcher keeps following it for the log).
             The toast itself lives in toast_view; this module is its controller.
@input      argv: a session id and the watch generation; the watch marker
@output     at most one /compact over the bridge, or one request to the mod; one
            log line with the outcome, the send time and the compaction's result
@dependencies conpact.app_sessions, conpact.bridge_client,
              conpact.closure_hook (FIRING_ERRORS), conpact.compact_progress,
              conpact.compaction, conpact.desktop, conpact.idle_state,
              conpact.mod_handoff, conpact.remote_startup, conpact.session_registry, conpact.settings,
              conpact.toast_view (lazily); stdlib: dataclasses, os, sys, time
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time

from . import (app_sessions, bridge_client, closure_hook, compact_progress, compaction, desktop, idle_state,
               mod_handoff, remote_startup, session_registry, settings as user_settings)
# Re-exported: `idle_watch.Interrupted` and `idle_watch.Platform` are how the
# rest of the package names these, and they live in `watching` so that a
# platform adapter can use them without importing the watcher back (a cycle).
from .watching import Interrupted, Platform  # noqa: F401

# The user let a toast go, handed the work to the later stage, or an agent held
# one: a later stage still comes.
CONTINUING = ("dismissed", "timeout", "held", "deferred", "auto_expiry_set")
POLL_SECONDS = 5
SETTLE_SECONDS = 120   # a Stop's own busy -> idle switch lands well within this
NOTICE_SECONDS = 20


def claude_platform() -> Platform:
    return Platform(name="claude", resumed=_claude_resumed, reachable=_claude_reachable,
                    ensure_idle=_claude_ensure_idle, send=_claude_send)


@dataclasses.dataclass
class Deps:
    clock: object
    sleep: object
    environ: object
    sessions_dir: object
    compactor: object
    present: object
    opener: object = None
    platform: object = None

    def side(self) -> Platform:
        """The platform adapter, defaulting to Claude Code's."""
        return self.platform or claude_platform()


def default_deps(platform=None) -> Deps:
    from . import toast_view  # tkinter is only needed once a toast is due
    return Deps(clock=time.time, sleep=time.sleep, environ=os.environ, sessions_dir=None,
                compactor=compaction.compact_record, present=toast_view.present,
                opener=desktop.open_url, platform=platform)


def activity(record: dict, marker: dict, now: float, strict: bool = False) -> str | None:
    """
    "resumed" if the session has been used since the Stop that armed this watch.
    Its status changes to idle just after the Stop, so a change stamped later
    than the settle time means a new turn, and after the settle time (or when
    about to send: strict) it must say idle.
    """
    settle_end = marker["armed_at"] + SETTLE_SECONDS
    changed = record.get("statusUpdatedAt")
    if isinstance(changed, (int, float)) and not isinstance(changed, bool) and changed / 1000 > settle_end:
        return "resumed"
    if (strict or now >= settle_end) and record.get("status") != "idle":
        return "resumed"
    return None


def find_record(session_id: str, sessions_dir) -> dict | None:
    for record in session_registry.load_records(sessions_dir):
        if record.get("sessionId") == session_id:
            return record
    return None


def compacted_since_armed(marker: dict) -> bool:
    """Has the session been compacted since the turn that armed this watch?

    By the agent's own closure request, which the mod runs just after the Stop
    that armed this watch, by the user's /compact, or by Claude Code's automatic
    compaction: none of them is a turn end, so none re-arms the watch, and one
    that finishes inside the settle time leaves the record looking like the
    Stop's own busy -> idle switch. The transcript says so plainly - a boundary
    past where it ended at the Stop, stamped after that turn's last call (a
    boundary Claude Code copies forward while compacting is older). A marker
    without the transcript's size cannot tell, and does not stop the watch.
    """
    offset = marker.get("transcript_size")
    if not isinstance(offset, int) or isinstance(offset, bool):
        return False
    return compact_progress.compacted_since(marker.get("transcript_path"), offset, marker["last_call"]) is not None


def _claude_resumed(session_id: str, marker: dict, deps: Deps) -> str | None:
    record = find_record(session_id, deps.sessions_dir)
    if record is None:
        return "closed"
    if app_sessions.is_archived(record.get("hostSessionId"), deps.environ):
        return "archived"
    if compacted_since_armed(marker):
        return "already_compacted"
    return activity(record, marker, deps.clock())


def interruption(session_id: str, generation: str, marker: dict, deps: Deps) -> str | None:
    """Why this watch should stop, or None. The generation checks are the same
    whichever app the watch is for; what counts as "used since" is not."""
    current = idle_state.read_marker(session_id)
    if current is None:
        return "cancelled"
    if current.get("generation") != generation:
        return "superseded"
    return deps.side().resumed(session_id, marker, deps)


def wait_for(deadline: float, check, deps: Deps) -> str | None:
    """Sleep until the deadline in POLL_SECONDS steps; the first reason check() gives wins."""
    while True:
        now = deps.clock()
        if now >= deadline:
            return None
        deps.sleep(min(POLL_SECONDS, deadline - now))
        reason = check()
        if reason:
            return reason


def stage_list(marker: dict) -> list[dict]:
    """The toasts this watch should show. A marker written before stages existed has one."""
    def usable(stage):
        return isinstance(stage, dict) and all(isinstance(stage.get(f), (int, float)) for f in ("at", "until"))
    found = [stage for stage in marker.get("stages") or [] if usable(stage)]
    return found or [{"kind": "expiry", "at": marker["fire_at"], "until": marker["expires_at"]}]


def auto_stage(mode, stages: list[dict]) -> dict | None:
    """The stage that compacts without asking, if the user set one for this session.
    A mode whose stage this watch does not have acts at the last one instead."""
    if mode is None:
        return None
    for stage in stages:
        if stage.get("kind") == mode:
            return stage
    return stages[-1]


def by_mod(session_id: str, deps: Deps) -> bool:
    """Is the session's mod running, so that it can compact the session itself?"""
    return mod_handoff.alive(session_id, deps.clock())


def bound(session_id: str, deps: Deps) -> bool:
    """Is Remote Control connected for this session right now? Nothing can be sent without it."""
    record = find_record(session_id, deps.sessions_dir)
    return bool(record and record.get("bridgeSessionId"))


def held(session_id: str, deps: Deps) -> bool:
    """Has this session asked for its early toast to be skipped, and is that still in force?

    A run that waits on a build is idle without being finished. A hold that has
    run out is cleared here, so the next early stage is shown as usual.
    """
    hold = idle_state.read_hold(session_id)
    if hold is None:
        return False
    if deps.clock() < hold["until"]:
        return True
    idle_state.clear_hold(session_id)
    return False


def _claude_reachable(session_id: str, deps: Deps) -> bool:
    """Through its mod where that is running, else over Remote Control."""
    return by_mod(session_id, deps) or bound(session_id, deps)


def bind_idle(session_id: str, marker: dict, deps: Deps, bridge: bool = True) -> dict:
    """The session's record, bound from the runtime, idle and not compacted since
    its Stop - or raise. Only a send over the bridge needs Remote Control
    connected (`bridge`)."""
    resolve = session_registry.resolve_self if bridge else session_registry.resolve_self_unbound
    record = resolve(environ=deps.environ, session_id=session_id, sessions_dir=deps.sessions_dir)
    reason = "already_compacted" if compacted_since_armed(marker) else         activity(record, marker, deps.clock(), strict=True)
    if reason:
        raise Interrupted(reason)
    return record


def _send(session_id: str, marker: dict, deps: Deps) -> dict:
    """Send /compact to the idle, bound session. Returns the outcome, the view
    state and, once sent, a tracker that starts where the transcript ended."""
    try:
        record = bind_idle(session_id, marker, deps)
        path = marker.get("transcript_path")
        offset = compact_progress.size(path)
        started = deps.clock()
        result = deps.compactor(record)
    except Interrupted as exc:
        return {"outcome": {"event": exc.reason}, "state": {"state": "closed"}}
    except closure_hook.FIRING_ERRORS as exc:
        return {"outcome": {"event": "error", "reason": f"{type(exc).__name__}: {exc}"},
                "state": {"state": "error", "detail": str(exc)}}
    status = result.get("http_status")
    sent = {"http_status": status, "token_refreshed": result.get("token_refreshed"), "sent_at": started}
    if not bridge_client.is_success(status):
        return {"outcome": {"event": "failed", **sent},
                "state": {"state": "error", "detail": f"bridge returned HTTP {status}"}}
    tracker = None if offset is None else compact_progress.Tracker(path, offset, started, deps.clock)
    return {"outcome": {"event": "compacted", **sent}, "state": {"state": "sent"}, "tracker": tracker}


def _claude_ensure_idle(session_id: str, marker: dict, deps: Deps) -> dict:
    return bind_idle(session_id, marker, deps, bridge=not by_mod(session_id, deps))


def _claude_send(session_id: str, marker: dict, deps: Deps) -> dict:
    return _hand_to_mod(session_id, marker, deps) if by_mod(session_id, deps) else _send(session_id, marker, deps)


def _hand_to_mod(session_id: str, marker: dict, deps: Deps) -> dict:
    """Ask the session's mod to compact the idle, bound session, and wait for it
    to take the request. A request it does not take lapses, and the mod will not
    take it later, so nothing is sent over the bridge instead: a slow mod must
    not end in two compactions."""
    try:
        bind_idle(session_id, marker, deps, bridge=False)
        path = marker.get("transcript_path")
        offset = compact_progress.size(path)
        started = deps.clock()
        request_id = mod_handoff.ask(session_id, started)
    except Interrupted as exc:
        return {"outcome": {"event": exc.reason}, "state": {"state": "closed"}}
    except (session_registry.TargetError, OSError) as exc:
        return {"outcome": {"event": "error", "reason": f"{type(exc).__name__}: {exc}"},
                "state": {"state": "error", "detail": str(exc)}}
    sent = {"transport": "mod", "request_id": request_id, "sent_at": started}
    found = mod_handoff.await_answer(session_id, request_id, started, deps.clock, deps.sleep)
    if found is None or found.get("action") in mod_handoff.REFUSED:
        detail = "the session's mod did not take the compaction" if found is None else mod_handoff.refusal(found)
        return {"outcome": {"event": "failed", "reason": detail, **sent},
                "state": {"state": "error", "detail": detail}}
    inner = None if offset is None else compact_progress.Tracker(path, offset, started, deps.clock)
    tracker = mod_handoff.Tracker(inner, session_id, request_id, started)
    return {"outcome": {"event": "compacted", **sent}, "state": {"state": "sent"}, "tracker": tracker}


def progress(tracker) -> dict:
    """How a sent compaction is going, as the toast shows it."""
    return tracker.check() if tracker else {"state": "untracked"}


def follow(tracker, deps: Deps) -> dict:
    """Wait, without a toast, for a sent compaction's result."""
    return tracker.wait(deps.sleep, POLL_SECONDS) if tracker else {"state": "untracked"}


class AskPrompt:
    """One stage's toast: asks whether to compact this session now."""

    def __init__(self, session_id: str, generation: str, marker: dict, stage: dict, deps: Deps):
        self.session_id, self.generation, self.marker, self.deps = session_id, generation, marker, deps
        self.stage = stage
        self.clock = deps.clock
        self.mute_seconds = user_settings.load()["mute_seconds"]
        self.outcome = None
        self.sent, self.tracker = False, None

    def model(self) -> dict:
        m = self.marker
        return {"kind": "ask", "stage": self.stage.get("kind"), "name": m.get("name"),
                "platform": m.get("platform"), "ttl_is_modelled": m.get("ttl_is_modelled"),
                "context_tokens": m["context_tokens"], "last_call": m["last_call"],
                "deadline": self.stage["until"], "span": self.stage["until"] - self.stage["at"],
                "expires_at": m["expires_at"], "mute_seconds": self.mute_seconds}

    def poll(self) -> str | None:
        """A reason to close the toast, if any; the first one is also the outcome.
        An early stage times out and leaves the later one to come."""
        if self.clock() >= self.stage["until"]:
            reason = "expired" if self.stage["until"] >= self.marker["expires_at"] else "timeout"
        else:
            reason = interruption(self.session_id, self.generation, self.marker, self.deps)
        if reason and self.outcome is None:
            self.outcome = {"event": reason}
        return reason

    def act(self, action: str) -> dict:
        if self.outcome is not None or action not in ("compact", "auto", "defer", "auto_expiry",
                                                      "dismiss", "mute"):
            return {"state": "closed"}
        if action in ("defer", "auto_expiry"):
            return self._later(action)
        if action == "mute":
            idle_state.set_mute(self.session_id, self.clock() + self.mute_seconds, self.marker["last_call"])
            self.outcome = {"event": "muted", "for_seconds": self.mute_seconds}
            return {"state": "closed"}
        if action == "dismiss":
            self.outcome = {"event": "dismissed"}
            return {"state": "closed"}
        reason = interruption(self.session_id, self.generation, self.marker, self.deps)
        if reason:
            self.outcome = {"event": reason}
            return {"state": "closed"}
        if action == "auto":
            idle_state.set_auto(self.session_id, self.stage.get("kind") or "expiry")
        sent = self.deps.side().send(self.session_id, self.marker, self.deps)
        self.outcome = sent["outcome"]
        self.sent, self.tracker = "tracker" in sent, sent.get("tracker")
        if action == "auto" and self.outcome["event"] == "compacted":
            self.outcome["event"] = "compacted_auto_on"
        return sent["state"]

    def _later(self, action: str) -> dict:
        """Hand this idle's compaction to the stage before the cache expires, which
        then acts without asking again. Nothing is sent here, and nothing is sent
        there either if the session is used in between: that stage re-checks.

        Only the early toast has a later stage to hand it to (idle_arming.stages
        appends the expiry one and puts an early one strictly before it), so on
        any other stage this is not an offer and does nothing.
        """
        if self.stage.get("kind") != "early":
            return {"state": "closed"}
        if action == "auto_expiry":
            # The standing choice: every later idle compacts there too, so this
            # is the one that outlives the watcher.
            idle_state.set_auto(self.session_id, "expiry")
            self.outcome = {"event": "auto_expiry_set"}
            return {"state": "auto_expiry_set"}
        self.outcome = {"event": "deferred"}
        return {"state": "deferred"}

    def progress(self) -> dict:
        return progress(self.tracker)


class RemotePrompt(AskPrompt):
    """The toast for a session whose Remote Control is off.

    It can say something and it can open that session in the app, so its switch
    is one click away. It can never send: turning Remote Control on is the
    user's own action, and there is no bridge to send over anyway (D-020).
    """

    def model(self) -> dict:
        # The offer is made only when the setting is not already on.
        return {**super().model(), "kind": "remote", "offer_always_on": not remote_startup.is_on()}

    def act(self, action: str) -> dict:
        if action in ("mute", "dismiss"):
            return super().act(action)      # the same silence and the same dismissal
        if action not in ("open_session", "always_on") or self.outcome is not None:
            return {"state": "closed"}      # "compact" and "auto" do not exist here
        return self._always_on() if action == "always_on" else self._open_session()

    def _open_session(self) -> dict:
        link = app_sessions.session_link(self.marker.get("host_session_id"), self.deps.environ)
        if link is None:
            self.outcome = {"event": "remote_no_link"}
            return {"state": "remote_failed", "detail": "the app has no link for this session"}
        try:
            self.deps.opener(link)
        except (OSError, TypeError) as exc:
            self.outcome = {"event": "remote_open_failed", "reason": f"{type(exc).__name__}: {exc}"}
            return {"state": "remote_failed", "detail": str(exc)}
        self.outcome = {"event": "remote_opened", "link": link}
        return {"state": "closed"}

    def _always_on(self) -> dict:
        """The user asked for it on this toast: write that one Claude Code setting (D-021)."""
        try:
            changed = remote_startup.turn_on()
        except (OSError, ValueError) as exc:
            self.outcome = {"event": "remote_startup_failed", "reason": f"{type(exc).__name__}: {exc}"}
            return {"state": "startup_failed", "detail": str(exc)}
        self.outcome = {"event": "remote_startup_on", "changed": changed}
        return {"state": "startup_on"}


class Notice:
    """Controller for the short notice shown after an automatic compaction."""

    def __init__(self, marker: dict, clock, variant: str, detail: str | None = None, tracker=None,
                 stage: str | None = None, offer_auto_off: bool = True):
        self.marker, self.clock, self.variant, self.detail, self.tracker = marker, clock, variant, detail, tracker
        self.stage = stage
        # A compaction deferred for this idle alone set no switch, so there is
        # nothing for "Turn off auto-compact" to turn off.
        self.offer_auto_off = offer_auto_off
        self.shown_at = clock()
        self.auto_off = False

    def model(self) -> dict:
        m = self.marker
        return {"kind": "notice", "stage": self.stage, "variant": self.variant,
                "compacting": self.variant == "compacted", "detail": self.detail, "name": m.get("name"),
                "context_tokens": m["context_tokens"], "last_call": m["last_call"],
                "offer_auto_off": self.offer_auto_off,
                "deadline": self.shown_at + NOTICE_SECONDS, "span": NOTICE_SECONDS}

    def progress(self) -> dict:
        return progress(self.tracker)

    def poll(self) -> str | None:
        return "timeout" if self.clock() >= self.shown_at + NOTICE_SECONDS else None

    def act(self, action: str) -> dict:
        if action == "turn_off_auto":
            idle_state.clear_auto(self.marker["session_id"])
            self.auto_off = True
            return {"state": "auto_off"}
        return {"state": "closed"}


def _auto_compact(session_id: str, marker: dict, stage: dict, deps: Deps,
                  offer_auto_off: bool = True) -> dict:
    sent = deps.side().send(session_id, marker, deps)
    outcome = sent["outcome"]
    if sent["state"]["state"] == "closed":
        return outcome  # no longer idle: nothing was sent, nothing to tell
    variant = "compacted" if outcome["event"] == "compacted" else "failed"
    if variant == "compacted":
        outcome["event"] = "auto_compacted"
    notice = Notice(marker, deps.clock, variant, sent["state"].get("detail"), sent.get("tracker"),
                    stage=stage.get("kind"), offer_auto_off=offer_auto_off)
    try:
        deps.present(notice)
    except Exception as exc:  # the send already happened; report it regardless
        outcome["notice_error"] = f"{type(exc).__name__}: {exc}"
    if notice.auto_off:
        outcome["auto_off"] = True
    if variant == "compacted":
        outcome["result"] = follow(notice.tracker, deps)
    return outcome


def _present(prompt, deps: Deps) -> dict:
    """Show a toast and take its outcome. A toast that fails must not end the watcher."""
    try:
        deps.present(prompt)
        return prompt.outcome or {"event": "closed"}
    except Exception as exc:
        return prompt.outcome or {"event": "error", "reason": f"toast failed: {type(exc).__name__}: {exc}"}


def _ask(session_id: str, generation: str, marker: dict, stage: dict, deps: Deps) -> dict:
    try:
        deps.side().ensure_idle(session_id, marker, deps)
    except Interrupted as exc:
        return {"event": exc.reason}
    except session_registry.TargetError as exc:
        return {"event": "error", "reason": f"session not bound: {exc}"}
    prompt = AskPrompt(session_id, generation, marker, stage, deps)
    outcome = _present(prompt, deps)
    if prompt.sent:
        outcome = {**outcome, "result": follow(prompt.tracker, deps)}
    return outcome


def _ask_remote(session_id: str, generation: str, marker: dict, stage: dict, deps: Deps) -> dict:
    """The toast for a session with Remote Control off: nothing can be sent to it."""
    return _present(RemotePrompt(session_id, generation, marker, stage, deps), deps)


def watch(session_id: str, generation: str, deps: Deps) -> dict:
    marker = idle_state.read_marker(session_id)
    if marker is None:
        return {"event": "cancelled"}
    if marker.get("generation") != generation:
        return {"event": "superseded"}
    sizes = {"context_tokens": marker.get("context_tokens"), "ttl": marker.get("ttl")}
    history = []
    try:
        stages = stage_list(marker)
        held_early = deferred = False
        for stage in stages:
            switched = auto_stage(idle_state.auto_mode(session_id), stages)
            automatic = switched
            if automatic is None and deferred:
                # The user deferred on the early toast: act here, without asking
                # again. This lives in the watcher and nowhere else, so using the
                # session kills the watcher and the deferral with it.
                automatic = stage
            if automatic is not None and stage is not automatic and not held_early:
                continue  # the user chose another stage for this session: this one stays quiet
            reason = wait_for(stage["at"], lambda: interruption(session_id, generation, marker, deps), deps)
            asked_for_remote = False
            if reason:
                result = {"event": reason}
            elif stage.get("kind") == "early" and held(session_id, deps):
                # An agent is mid-run. The stage before the cache expires still
                # comes - and still acts, even if this was the auto stage: by
                # then the context really is about to go cold.
                result, held_early = {"event": "held"}, True
            elif not deps.side().reachable(session_id, deps):
                # Read now, not at the turn end: Remote Control may have been
                # switched either way while the session sat idle.
                result = _ask_remote(session_id, generation, marker, stage, deps)
                asked_for_remote = True
            elif automatic is not None:
                result = _auto_compact(session_id, marker, stage, deps,
                                       offer_auto_off=switched is not None)
            else:
                result = _ask(session_id, generation, marker, stage, deps)
            history.append({**result, "stage": stage.get("kind")})
            deferred = deferred or result["event"] == "deferred"
            # A later stage would only repeat the same question, and the answer
            # does not change as the cache runs down: ask for Remote Control once.
            if asked_for_remote or result["event"] not in CONTINUING:
                break
        outcome = history[-1]
        if len(history) > 1:
            outcome = {**outcome, "earlier": [{"stage": e["stage"], "event": e["event"]} for e in history[:-1]]}
        return {**outcome, **sizes}
    finally:
        idle_state.clear_marker(session_id, generation)


def platform_for(marker) -> Platform | None:
    """The adapter this watch needs, named by the arming that wrote the marker.
    None means Claude Code, which is the default and needs no adapter.

    `codex_watching` imports this module, so it is imported here rather than at
    module scope - the watcher for a Claude session never loads it at all.
    """
    if (marker or {}).get("platform") == "codex":
        from . import codex_watching
        return codex_watching.platform()
    return None


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or not all(session_registry.is_valid_session_id(a) for a in argv):
        return 2
    session_id, generation = argv
    mod_handoff.prune()   # what sessions long gone left for their mod
    try:
        side = platform_for(idle_state.read_marker(session_id))
        outcome = watch(session_id, generation, default_deps(side))
    except Exception as exc:  # a detached process has nowhere else to report
        outcome = {"event": "error", "reason": f"{type(exc).__name__}: {exc}"}
    idle_state.append_log({"session_id": session_id, **outcome})
    return 0


if __name__ == "__main__":
    sys.exit(main())
