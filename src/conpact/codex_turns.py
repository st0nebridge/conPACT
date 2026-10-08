"""
@module conpact.codex_turns
@description Turn-end events out of the app-server's own stream, which is what
             lets conPACT arm a Codex session the moment it goes idle instead of
             sweeping every session and asking.

             Before Codex CLI exposed Stop, `codex_arming` was written as a
             sweep (D-20260921-031 covers compaction; the sweep was the arming
             half). ChatGPT Desktop still uses the sidecar, which stands in the app-server's
             stdio path and sees every notification the app-server pushes to the
             desktop - including `turn/completed`. That is the missing event; it
             was there all along on the Desktop wire.

             This module is only the recognition, deliberately: given the bytes,
             say which thread just finished a turn. It starts nothing, spawns
             nothing and touches no disk, so the part that decides *when* to act
             can be tested without the part that acts. The sidecar wires it.

             Recognition is kept tolerant on the id and strict on the event. The
             id travels as `threadId` on the wire, but the same binary carries
             `thread_id` and a nested thread object, so all three are read; the
             event is a fixed, small set, because acting on the wrong event is
             worse than missing one - a sweep still catches what this misses.
@input      whole lines from the app-server's stdout
@output     the thread id whose turn just ended, at most once per settling window
@dependencies stdlib: json, time
"""
from __future__ import annotations

import json
import time

# The events that mean "this thread is now between turns". Kept narrow on
# purpose: `turn/started` is its opposite, and an item completing is one step
# inside a turn, not the end of one.
TURN_END = ("turn/completed",)
TURN_START = ("turn/started",)

# Where the thread id may travel. camelCase is what the wire uses; the rest are
# read because the same binary carries them and a missed arming is silent.
ID_KEYS = ("threadId", "thread_id", "conversationId")

# An `item/started` whose item is an `mcpToolCall` names the server being called
# and the thread calling it. When that server is us, the caller is not a guess:
# it is stated, and it stays exact with any number of turns running at once.
ITEM_START = ("item/started",)
ITEM_END = ("item/completed",)
MCP_CALL = "mcpToolCall"
OUR_SERVER = "conpact"

# One arming per thread per this many seconds. A turn can end more than once in
# a burst (a turn that is retried, a notification repeated to two windows), and
# re-arming retires the live watcher and restarts its timer - the same reason
# the sweep is idempotent.
SETTLE_SECONDS = 2.0


def thread_of(params) -> str | None:
    """The thread a notification concerns, wherever the id is carried."""
    if not isinstance(params, dict):
        return None
    for key in ID_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value
    thread = params.get("thread")
    if isinstance(thread, dict):
        for key in ("id", *ID_KEYS):
            value = thread.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def turn_ended(message) -> str | None:
    """The thread whose turn just ended, or None for everything else.

    A message with an `id` is a reply to somebody's request, never a
    notification, and is not an event no matter what method it names.
    """
    if not isinstance(message, dict) or message.get("id") is not None:
        return None
    if message.get("method") not in TURN_END:
        return None
    return thread_of(message.get("params"))


def turn_started(message) -> str | None:
    """The thread whose turn just began, or None. The opposite of `turn_ended`,
    and the other half of knowing who is mid-turn."""
    if not isinstance(message, dict) or message.get("id") is not None:
        return None
    if message.get("method") not in TURN_START:
        return None
    return thread_of(message.get("params"))


def _item_of(params):
    return params.get("item") if isinstance(params, dict) else None


def calling_us(message):
    """(thread, item id) when this is the start of an MCP call to our server."""
    if not isinstance(message, dict) or message.get("id") is not None:
        return None
    if message.get("method") not in ITEM_START:
        return None
    params = message.get("params")
    item = _item_of(params)
    if not isinstance(item, dict):
        return None
    kind = item.get("type") or item.get("itemType") or item.get("kind")
    if kind != MCP_CALL and MCP_CALL not in str(item.get("variant", "")):
        # Some shapes carry the variant as the key rather than a field.
        if MCP_CALL not in item:
            return None
        item = item[MCP_CALL] if isinstance(item.get(MCP_CALL), dict) else item
    if str(item.get("server", "")).strip().lower() != OUR_SERVER:
        return None
    thread = thread_of(params)
    item_id = item.get("id") or item.get("itemId") or params.get("itemId")
    return (thread, item_id) if thread else None


def call_finished(message):
    """The item id of an MCP call that just finished, or None."""
    if not isinstance(message, dict) or message.get("id") is not None:
        return None
    if message.get("method") not in ITEM_END:
        return None
    params = message.get("params")
    item = _item_of(params)
    if isinstance(item, dict):
        return item.get("id") or item.get("itemId") or (params or {}).get("itemId")
    return (params or {}).get("itemId")


def parse(line: bytes):
    """One line as JSON, or None. Anything unparseable is simply not an event."""
    try:
        return json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None


class Turns:
    """Whole lines in, thread ids out - at most one per thread per window.

    Holds only the last time each thread was reported, so it can be dropped and
    rebuilt at any moment; the sweep is what makes that safe.
    """

    def __init__(self, clock=time.monotonic, settle: float = SETTLE_SECONDS):
        self._clock = clock
        self._settle = settle
        self._last: dict[str, float] = {}
        self._running: set = set()
        self._calls: dict = {}          # item id -> the thread calling our server
        self._methods: dict = {}        # item id -> method, when the wire names it

    def calling(self) -> set:
        """Threads with an MCP call to *our* server open right now. Exact, not
        inferred: the app-server said so."""
        return set(self._calls.values())

    def calling_tools(self) -> dict:
        """Method-specific callers, so a status call cannot identify a queue call."""
        found = {}
        for item, caller in self._calls.items():
            method = self._methods.get(item)
            if isinstance(method, str):
                found.setdefault(method, set()).add(caller)
        return {method: sorted(callers) for method, callers in found.items()}

    def in_flight(self) -> set:
        """The threads whose turns have started and not yet completed."""
        return set(self._running)

    def note(self, line: bytes) -> str | None:
        """The thread to arm because of this line, or None. Never raises: this
        runs inside the sidecar's pump, which must not break for a diagnostic
        or for a notification shape we did not expect."""
        try:
            message = parse(line)
            call = calling_us(message)
            if call is not None:
                self._calls[call[1]] = call[0]
                item = _item_of(message.get("params")) or {}
                item = item.get(MCP_CALL, item)
                if isinstance(item, dict):
                    self._methods[call[1]] = item.get("tool")
                return None
            done = call_finished(message)
            if done is not None:
                self._calls.pop(done, None)
                self._methods.pop(done, None)
            started = turn_started(message)
            if started is not None:
                self._running.add(started)
                return None
            thread = turn_ended(message)
            if thread is None:
                return None
            self._running.discard(thread)
            self._calls = {item: caller for item, caller in self._calls.items()
                           if caller != thread}
            self._methods = {item: method for item, method in self._methods.items()
                             if item in self._calls}
            now = self._clock()
            seen = self._last.get(thread)
            if seen is not None and now - seen < self._settle:
                return None                     # still settling; one is enough
            self._last[thread] = now
            return thread
        except Exception:
            return None
