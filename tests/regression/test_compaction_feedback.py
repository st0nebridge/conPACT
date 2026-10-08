"""
Regression test for CU-20260919-011 (the toast follows a compaction to its end).

Seen 2026-09-19: "Compact now" sent /compact at 06:17:32 and the compaction ran
for 101.8 s, but the toast said "Compaction started" and closed after 3 s. With
nothing on screen for 100 s, it looked as if nothing had happened until the
user typed. The contract, through the real modules (clock, toast and bridge
faked, transcript real):

  1. After a send the watcher follows the session transcript from where it
     ended just before the send, and reports the compaction as done only when a
     compact boundary appears after that point, with the context size before
     and after and the duration Claude Code measured.
  2. An earlier compaction never counts, and with no boundary within the time
     limit the result is "unconfirmed" - never a claimed success.
  3. Closing the toast does not lose the result: the log line still gets the
     send time and the result.

CU-20260919-014, seen live the same day (session a0b1c2d3): while compacting,
Claude Code appended about 7 MB of earlier rows after the send, among them a
copy of the 04:29 boundary, so the toast reported that one (656,725 -> 19,111
tokens in 77.6 s) instead of this compaction (354,583 -> 23,557 in 90.8 s):

  4. Only a boundary stamped at or after the send is this compaction's result.
"""
import datetime
import functools
import json

from conpact import compact_progress, compaction, idle_arming, idle_state, idle_watch, session_registry, token_store

T0 = 1_800_000_000.0
FINISHED = "2027-01-15T08:56:40.000Z"  # T0 + 3400: after the send at T0 + 3300
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "isSidechain": False,
            "timestamp": FINISHED, "content": "Conversation compacted",
            "compactMetadata": {"trigger": "manual", "preTokens": 459_517, "postTokens": 23_498,
                                "durationMs": 101_836}}
DONE = {"state": "compacted", "pre_tokens": 459_517, "post_tokens": 23_498, "seconds": 101.8,
        "trigger": "manual", "at": FINISHED}
EARLIER = {**BOUNDARY, "timestamp": "2026-09-19T04:29:52.238Z",
           "compactMetadata": {"trigger": "manual", "preTokens": 656_725, "postTokens": 19_111, "durationMs": 77_646}}


class Clock:
    def __init__(self, t):
        self.t = t
        self.on_sleep = None

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.on_sleep:
            self.on_sleep(self.t)


def _session():
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / "4242.json").write_text(json.dumps({
        "pid": 4242, "sessionId": "sess-a", "bridgeSessionId": "bridge-sess-a", "name": "Anchor",
        "status": "idle", "statusUpdatedAt": int((T0 + 1) * 1000)}), encoding="utf-8")


def _transcript(tmp_path, *earlier):
    stamp = datetime.datetime.fromtimestamp(T0, datetime.timezone.utc).isoformat()
    call = {"type": "assistant", "isSidechain": False, "timestamp": stamp, "message": {
        "model": "claude-opus-5", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 459_507,
            "output_tokens": 0, "cache_creation": {"ephemeral_1h_input_tokens": 10}}}}
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in [*earlier, call]), encoding="utf-8")
    return path


def _append(path, entry):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _watch(tmp_path, present, clock, *earlier):
    """Arm a real watch on a real transcript, then run the watcher with the toast faked."""
    _session()
    path = _transcript(tmp_path, *earlier)
    idle_arming.arm({"session_id": "sess-a", "transcript_path": str(path)}, environ={},
                    clock=lambda: T0 + 1, spawner=lambda argv, env: 99)
    generation = idle_state.read_marker("sess-a")["generation"]
    token = token_store.AccessToken("tok", False)
    compactor = functools.partial(compaction.compact_record, token_getter=lambda: token,
                                  sender=lambda bridge, text, tok: (200, {}))
    deps = idle_watch.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None,
                           compactor=compactor, present=present(path))
    return idle_watch.watch("sess-a", generation, deps)


def test_1_the_toast_shows_compacting_until_the_boundary_then_the_result(tmp_path):
    clock = Clock(T0 + 1)
    shown = []

    def present(path):
        def toast(prompt):  # the watcher swallows what this raises: assert outside it
            shown.append(prompt.act("compact"))
            clock.t += 45
            shown.append(prompt.progress())
            _append(path, BOUNDARY)
            shown.append(prompt.progress())
        return toast
    outcome = _watch(tmp_path, present, clock)
    assert shown == [{"state": "sent"}, {"state": "compacting", "elapsed": 45.0}, DONE]
    assert (outcome["event"], outcome["sent_at"], outcome["result"]) == ("compacted", T0 + 3300, DONE)  # 55 min idle


def test_2_an_earlier_compaction_never_counts_and_silence_is_unconfirmed(tmp_path):
    clock = Clock(T0 + 1)
    outcome = _watch(tmp_path, lambda path: lambda prompt: prompt.act("compact"), clock, EARLIER)
    assert outcome["result"] == {"state": "unconfirmed", "seconds": float(compact_progress.TRACK_SECONDS)}


def test_3_closing_the_toast_does_not_lose_the_result(tmp_path):
    clock = Clock(T0 + 1)

    def present(path):
        def click_then_close(prompt):
            prompt.act("compact")
            clock.on_sleep = lambda t: _append(path, BOUNDARY) if t >= T0 + 100 else None
        return click_then_close
    outcome = _watch(tmp_path, present, clock)
    assert outcome["result"] == DONE


def test_4_an_earlier_boundary_appended_again_is_not_this_compactions_result(tmp_path):
    clock = Clock(T0 + 1)

    def present(path):
        def click(prompt):
            prompt.act("compact")
            _append(path, {"type": "user", "isSidechain": False, "timestamp": "2026-09-19T04:28:34.590Z"})
            _append(path, EARLIER)
            clock.on_sleep = lambda t: _append(path, BOUNDARY) if t >= T0 + 3400 else None
        return click
    outcome = _watch(tmp_path, present, clock, EARLIER)
    assert outcome["result"] == DONE
