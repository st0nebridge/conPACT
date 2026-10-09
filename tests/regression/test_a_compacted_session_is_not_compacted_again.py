"""
Regression test for CU-20261009-111 (a session compacted since its turn end is
not compacted again by the idle watch).

On 2026-10-08 a Desktop session's agent finished its work and queued a
compaction. The turn ended at 21:08:44; the Stop hook armed the idle watch
(336,867 tokens), and a second later the mod ran /compact, which finished at
21:09:23 (to 13,971 tokens). A /compact is not a turn end, so nothing re-armed
the watch, and the session's record went busy and back to idle inside the 120 s
the watcher allows for the Stop's own switch - so to the watcher the session
had not been touched. The early toast came at 21:09:41 offering to compact a
session that had just been compacted; it was deferred to the expiry stage, which
at 22:03:43 compacted the 14,123-token session to 22,065 tokens, larger than
before. The old route never had this: the Stop hook that sends /compact itself
does not arm a watch in the same turn end, but the mod's queue is not seen by
the Stop hook.

The contract:

  1. The watch records where the transcript ended at the Stop that armed it.
  2. A compaction that finishes after that turn - the agent's own run just after
     the Stop, the user's /compact, Claude Code's automatic one - ends the watch:
     no toast is shown, nothing is sent, and the log says `already_compacted`.
     This holds inside the settle time, where the record cannot tell.
  3. It holds at every point a watch could act: while waiting for a stage, on a
     toast already on screen (which closes, and whose Compact button sends
     nothing), at the expiry stage a deferral handed the compaction to, and at
     the moment of sending.
  4. A boundary Claude Code copies forward from an earlier compaction while
     compacting does not count: it is stamped before the turn's last call.
"""
import datetime
import functools
import json

from conpact import compaction, idle_arming, idle_state, idle_watch, session_registry, settings, token_store

T0 = 1_800_000_000.0          # the turn's last API call
STOP = T0 + 2                 # the Stop that arms the watch
EARLY_AT = T0 + 57


class Clock:
    def __init__(self, t=STOP):
        self.t = t
        self.on_sleep = None

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.on_sleep:
            self.on_sleep(self.t)


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _session(changed=STOP + 1):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / "4242.json").write_text(json.dumps({
        "pid": 4242, "sessionId": "sess-a", "bridgeSessionId": "bridge-a", "name": "Anchor",
        "status": "idle", "statusUpdatedAt": int(changed * 1000)}), encoding="utf-8")


def _transcript(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "assistant", "isSidechain": False, "timestamp": _iso(T0), "message": {
        "model": "claude-opus-5", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 336_857,
            "output_tokens": 0, "cache_creation": {"ephemeral_1h_input_tokens": 10}}}}) + "\n", encoding="utf-8")
    return path


def _boundary(at, pre=336_867, post=13_971):
    return {"type": "system", "subtype": "compact_boundary", "isSidechain": False, "timestamp": _iso(at),
            "compactMetadata": {"trigger": "manual", "preTokens": pre, "postTokens": post, "durationMs": 38_610}}


def _compact(path, at, copies=()):
    """What a compaction appends: copies of earlier rows, then its own boundary."""
    with open(path, "a", encoding="utf-8") as handle:
        for row in (*copies, _boundary(at)):
            handle.write(json.dumps(row) + "\n")


def _arm(tmp_path):
    settings.save({"idle_seconds": 57})
    _session()
    path = _transcript(tmp_path)
    status = idle_arming.arm({"session_id": "sess-a", "transcript_path": str(path)}, environ={},
                             clock=lambda: STOP, spawner=lambda argv, env: 99)
    assert status["action"] == "armed"
    return path


def _deps(clock, sent, present):
    token = token_store.AccessToken("tok", False)
    compactor = functools.partial(compaction.compact_record, token_getter=lambda: token,
                                  sender=lambda bridge, text, tok: sent.append(text) or (200, {}))
    return idle_watch.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None,
                           compactor=compactor, present=present)


def _watch(clock, sent, present):
    generation = idle_state.read_marker("sess-a")["generation"]
    return idle_watch.watch("sess-a", generation, _deps(clock, sent, present))


def _no_toast(controller):
    raise AssertionError(f"no toast may be shown: {controller.model()}")


def test_1_the_watch_records_where_the_transcript_ended_at_the_stop(tmp_path):
    path = _arm(tmp_path)
    assert idle_state.read_marker("sess-a")["transcript_size"] == path.stat().st_size


def test_2_the_agents_own_compaction_just_after_the_stop_ends_the_watch(tmp_path):
    path = _arm(tmp_path)
    _compact(path, STOP + 39)          # the mod's /compact, finished inside the settle time
    _session(changed=STOP + 40)        # busy and back to idle: to the record, nothing happened
    clock, sent = Clock(), []
    outcome = _watch(clock, sent, _no_toast)
    assert sent == []
    assert outcome["event"] == "already_compacted" and outcome["stage"] == "early"
    assert clock.t < EARLY_AT          # it stood down while waiting, not at the toast
    assert idle_state.read_marker("sess-a") is None


def test_3_a_deferred_expiry_stage_does_not_compact_a_session_compacted_in_between(tmp_path):
    """The 2026-10-08 sequence, with the compaction landing after the deferral."""
    path = _arm(tmp_path)
    clock, sent, seen = Clock(), [], []

    def present(controller):
        seen.append(controller.model()["stage"])
        controller.act("defer")
        _compact(path, clock() + 30)   # the user's own /compact, while the session sits idle

    outcome = _watch(clock, sent, present)
    assert seen == ["early"] and sent == []
    assert outcome["event"] == "already_compacted" and outcome["stage"] == "expiry"
    assert outcome["earlier"] == [{"stage": "early", "event": "deferred"}]


def test_3_a_toast_on_screen_closes_and_its_compact_button_sends_nothing(tmp_path):
    path = _arm(tmp_path)
    clock, sent, answers = Clock(), [], []

    def present(controller):
        _compact(path, clock())        # lands while the toast is up
        answers.append((controller.poll(), controller.act("compact")))

    outcome = _watch(clock, sent, present)
    assert answers == [("already_compacted", {"state": "closed"})]
    assert sent == [] and outcome["event"] == "already_compacted"


def test_3_the_moment_of_sending_checks_again(tmp_path):
    path = _arm(tmp_path)
    marker = idle_state.read_marker("sess-a")
    _compact(path, STOP + 50)
    sent = []
    result = idle_watch._send("sess-a", marker, _deps(Clock(EARLY_AT), sent, _no_toast))
    assert result["outcome"] == {"event": "already_compacted"} and sent == []


def test_4_a_boundary_copied_forward_from_an_earlier_compaction_does_not_count(tmp_path):
    path = _arm(tmp_path)
    earlier = _boundary(T0 - 3600, pre=600_000, post=12_000)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "user", "timestamp": _iso(T0 - 4000)}) + "\n")
        handle.write(json.dumps(earlier) + "\n")
    clock, sent, seen = Clock(), [], []

    def present(controller):
        seen.append(controller.model()["stage"])
        controller.act("dismiss")

    outcome = _watch(clock, sent, present)
    assert seen == ["early", "expiry"]           # the watch went on as usual
    assert outcome["event"] == "dismissed"
