"""
@module conpact.watching
@description The two things the idle watcher and each platform's adapter both
             need to name: the shape of an adapter, and the exception that says
             "this session is no longer idle, stop".

             They live here rather than in `idle_watch` because the dependency
             has to run one way. The watcher reaches for a platform's adapter
             (`idle_watch.platform_for`), so an adapter that reached back for the
             watcher's types would make the two modules a cycle - which is what
             a module-structure check's `cycles` test found the moment the Codex adapter was added,
             even though the import was lazy enough to work at runtime. A cycle
             that only happens not to bite is still a cycle.

             `Platform` is four questions, and they are exactly the ones whose
             answers differ between Claude Code and ChatGPT Desktop. Everything
             else the watch does - the stages, the mute, the hold, the toast, the
             generation checks that retire a superseded watcher - is the same on
             both sides and is written once, in `idle_watch`.
@input      none; this module is types only
@output     Platform, Interrupted
@dependencies stdlib: dataclasses
"""
from __future__ import annotations

import dataclasses


class Interrupted(Exception):
    """The session is no longer idle since it was armed; the reason names why."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclasses.dataclass
class Platform:
    """One app's answers to the four questions a watch has to ask.

    resumed(session_id, marker, deps) -> reason | None
        Has it been used since we armed, or gone away, or been archived?
    reachable(session_id, deps) -> bool
        Can we act on it at all? On Claude this is Remote Control; on Codex
        there is no bridge, so it is always true.
    ensure_idle(session_id, marker, deps) -> record
        The same question as `resumed`, asked at the moment of acting, and
        raising `Interrupted` rather than returning a reason.
    send(session_id, marker, deps) -> {"outcome": ..., "state": ..., "tracker"?}
        Compact it, and say what happened in the watcher's own shape.
    """
    name: str
    resumed: object
    reachable: object
    ensure_idle: object
    send: object
