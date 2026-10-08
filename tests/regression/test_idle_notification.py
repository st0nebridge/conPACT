"""
Regression test for CU-20260919-010 (idle toast before the prompt cache expires).

The contract, end to end through the real modules (clock, toast and bridge faked):

  1. A turn end in a session whose context is at least the minimum arms one watch
     that acts 5 minutes before the session's prompt cache expires: after 55
     minutes idle on a 1-hour cache, 3 minutes on a 5-minute cache. Below the
     minimum, or with the notifier switched off, nothing is armed.
  2. At that time, if the session is still idle, the toast asks; "Compact now"
     sends exactly "/compact" to the bridge of the session bound from the
     runtime - once.
  3. "Always compact" also compacts now, and switches that session
     (only that one) to compacting without asking on its later idles, with a
     notice that can switch it off again.
  4. Nothing is ever sent to a session that is busy or was used again since its
     turn end, nor when the toast is dismissed or the cache expires first.
"""
import datetime
import functools
import json

import pytest

from conpact import compaction, idle_arming, idle_state, idle_watch, session_registry, token_store

T0 = 1_800_000_000.0


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _session(status="idle", changed=T0 + 1, sid="sess-a", pid=4242):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": sid, "bridgeSessionId": f"bridge-{sid}", "name": "Anchor",
        "status": status, "statusUpdatedAt": int(changed * 1000)}), encoding="utf-8")


def _transcript(tmp_path, tokens, ttl_field):
    stamp = datetime.datetime.fromtimestamp(T0, datetime.timezone.utc).isoformat()
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "assistant", "isSidechain": False, "timestamp": stamp, "message": {
        "model": "claude-opus-5", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 10, "cache_read_input_tokens": tokens - 10,
            "output_tokens": 0, "cache_creation": {ttl_field: 10}}}}) + "\n", encoding="utf-8")
    return str(path)


def _arm(tmp_path, tokens=200_000, ttl_field="ephemeral_1h_input_tokens", sid="sess-a"):
    started = []
    status = idle_arming.arm({"session_id": sid, "transcript_path": _transcript(tmp_path, tokens, ttl_field)},
                             environ={}, clock=lambda: T0 + 1,
                             spawner=lambda argv, env: started.append(argv) or 99)
    return status, started


def _wire(sent):
    """The real compaction path down to the bridge call, with the token and HTTP faked."""
    token = token_store.AccessToken("tok", False)
    return functools.partial(compaction.compact_record, token_getter=lambda: token,
                             sender=lambda bridge, text, tok: sent.append((bridge, text)) or (200, {}))


def _deps(clock, sent, present):
    return idle_watch.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None,
                           compactor=_wire(sent), present=present)


@pytest.mark.parametrize("ttl_field, idle_minutes", [("ephemeral_1h_input_tokens", 55),
                                                     ("ephemeral_5m_input_tokens", 3)])
def test_1_a_large_session_is_watched_until_5_minutes_before_its_cache_expires(tmp_path, ttl_field, idle_minutes):
    _session()
    status, started = _arm(tmp_path, ttl_field=ttl_field)
    assert status["action"] == "armed" and len(started) == 1
    assert idle_state.read_marker("sess-a")["fire_at"] == T0 + idle_minutes * 60


def test_1_small_sessions_and_a_switched_off_notifier_arm_nothing(tmp_path):
    _session()
    assert _arm(tmp_path, tokens=99_999) == ({"action": "skip", "reason": "context 99999 tokens < minimum 100000"}, [])
    idle_state.off_switch_path().parent.mkdir(parents=True, exist_ok=True)
    idle_state.off_switch_path().write_text("", encoding="utf-8")
    assert _arm(tmp_path)[0]["action"] == "skip"
    assert idle_state.read_marker("sess-a") is None


def test_2_compact_now_sends_exactly_compact_to_the_bound_session_once(tmp_path):
    _session()
    _arm(tmp_path)
    generation = idle_state.read_marker("sess-a")["generation"]
    sent = []

    states = []

    def click(prompt):  # the watcher swallows what this raises: assert outside it
        states.extend([prompt.act("compact"), prompt.act("compact")])
    outcome = idle_watch.watch("sess-a", generation, _deps(Clock(T0 + 1), sent, click))
    assert states == [{"state": "sent"}, {"state": "closed"}]  # the second click sends nothing
    assert sent == [("bridge-sess-a", "/compact")]
    assert outcome["event"] == "compacted"


def test_3_auto_compact_switches_that_session_only_and_later_idles_do_not_ask(tmp_path):
    _session()
    _session(sid="sess-b", pid=4343)
    _arm(tmp_path)
    sent = []
    idle_watch.watch("sess-a", idle_state.read_marker("sess-a")["generation"],
                     _deps(Clock(T0 + 1), sent, lambda prompt: prompt.act("auto")))
    assert (idle_state.auto_mode("sess-a"), idle_state.auto_mode("sess-b")) == ("expiry", None)

    _arm(tmp_path)
    shown = []

    def present(controller):  # the watcher swallows what present() raises: assert outside it
        shown.append((controller, controller.act("turn_off_auto")))
    outcome = idle_watch.watch("sess-a", idle_state.read_marker("sess-a")["generation"],
                               _deps(Clock(T0 + 1), sent, present))
    assert sent == [("bridge-sess-a", "/compact")] * 2
    # told, not asked, and the notice's switch says it turned auto off
    assert [(type(c), state) for c, state in shown] == [(idle_watch.Notice, {"state": "auto_off"})]
    assert outcome["event"] == "auto_compacted" and idle_state.auto_mode("sess-a") is None


def test_4_nothing_is_sent_to_a_busy_or_resumed_session_or_after_dismiss_or_expiry(tmp_path):
    sent = []
    _session()
    _arm(tmp_path)
    _session(status="busy", changed=T0 + 900)  # the user came back during the wait
    assert idle_watch.watch("sess-a", idle_state.read_marker("sess-a")["generation"],
                            _deps(Clock(T0 + 1), sent, None))["event"] == "resumed"

    _session()
    _arm(tmp_path)

    clicked = []

    def busy_at_click(prompt):  # the watcher swallows what this raises: assert outside it
        _session(status="busy", changed=T0 + 3400)
        clicked.append(prompt.act("compact"))
    assert idle_watch.watch("sess-a", idle_state.read_marker("sess-a")["generation"],
                            _deps(Clock(T0 + 1), sent, busy_at_click))["event"] == "resumed"
    assert clicked == [{"state": "closed"}]

    for close in (lambda prompt: prompt.act("dismiss"), lambda prompt: None):
        _session()
        _arm(tmp_path)
        idle_watch.watch("sess-a", idle_state.read_marker("sess-a")["generation"], _deps(Clock(T0 + 1), sent, close))

    _session()
    _arm(tmp_path)
    clock = Clock(T0 + 1)

    polled = []

    def let_it_expire(prompt):  # the watcher swallows what this raises: assert outside it
        clock.t = T0 + 3600
        polled.append(prompt.poll())
    idle_watch.watch("sess-a", idle_state.read_marker("sess-a")["generation"], _deps(clock, sent, let_it_expire))
    assert polled == ["expired"]
    assert sent == []
