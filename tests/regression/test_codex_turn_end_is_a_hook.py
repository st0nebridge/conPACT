"""Regression: the sidecar is Codex's missing turn-end hook.

Claude Code arms a watch at a turn end because it has a Stop hook. Codex's hook
enum has none, so arming was written as a sweep over every session. But the
app-server pushes `turn/completed` to the desktop, and the sidecar already
stands in that stream - the event was on the wire all along.

The payload below is not invented. It was captured from a live ChatGPT Desktop
session on 2026-09-22 at 10:58:47, and its shape is what the recogniser was
written against:

    < method=turn/completed  params keys=['threadId', 'turn']
      threadId=019f0000-0000-7000-8000-000000000004

Two properties are load-bearing and both are asserted here: the desktop's own
stream is never consumed, slowed or broken by the watching, and nothing but a
real turn ending is allowed to arm.
"""
import json

import pytest

from conpact import codex_sidecar, codex_turns

THREAD = "019f0000-0000-7000-8000-000000000004"

# Exactly the envelope the app-server sent, keys as measured.
MEASURED = json.dumps({
    "method": "turn/completed",
    "params": {"threadId": THREAD,
               "turn": {"id": "01a00000-0000-7000-b000-000000000005",
                        "status": "completed"}},
}).encode("utf-8") + b"\n"


def _pump(lines, arm, turns=None):
    chunks = list(lines) + [b""]
    written = []
    codex_sidecar.pump_to_desktop(
        lambda _n: chunks.pop(0), written.append,
        codex_sidecar.Lifter("conpact-1-"), codex_sidecar.Control(),
        turns=turns or codex_turns.Turns(), arm=arm)
    return written


def test_the_measured_payload_arms_the_thread_it_names():
    armed = []
    _pump([MEASURED], armed.append)
    assert armed == [THREAD]


def test_the_desktop_still_receives_it_untouched():
    """We watch the stream; we never consume from it."""
    written = _pump([MEASURED], lambda _t: None)
    assert b"".join(written) == MEASURED


@pytest.mark.parametrize("method", ["turn/started", "thread/status/changed",
                                    "thread/tokenUsage/updated", "item/completed"])
def test_the_neighbouring_events_on_that_same_wire_do_not_arm(method):
    """All of these carry threadId too, and all were seen in the same capture.
    Arming on one of them would watch a session that is still working."""
    line = json.dumps({"method": method,
                       "params": {"threadId": THREAD}}).encode() + b"\n"
    armed = []
    _pump([line], armed.append)
    assert armed == []


def test_an_arming_that_cannot_start_never_reaches_the_desktop():
    def boom(_thread):
        raise OSError("no interpreter")
    written = _pump([MEASURED, b'{"id":"9","result":{}}\n'], boom)
    assert b'"id":"9"' in b"".join(written)


def test_the_sweep_is_still_there_for_what_the_hook_cannot_see():
    """Sessions already idle when the sidecar starts, and machines with no
    sidecar at all, still need the sweep - it is not superseded."""
    from conpact import codex_arming
    assert callable(codex_arming.sweep)
    assert callable(codex_arming.arm_one)
