"""
Regression test for CU-20260919-017 (two toast stages, silencing a session,
archived sessions, and auto-compact per stage).

The contract, end to end through the real modules (clock, toast and bridge faked):

  1. With an idle time set, a watch has two stages: an early toast, then the one
     before the cache expires. Both come: dismissing or ignoring the early one
     does not cancel the later one.
  2. Compacting from the early toast ends the watch - the later toast does not
     come unless the session is used again (which arms a fresh watch).
  3. "Silence this session" stops this watch and every later one for as long as
     the mute lasts, until the session is used again.
  4. A session the user archived in the app is never toasted and never compacted,
     neither at the turn end nor at the notify time.
  5. Auto-compact remembers which stage it was switched on at: "when idle"
     compacts at the early stage, "before expiry" leaves the early stage silent
     and compacts at the later one. Nothing is ever asked twice.
"""
import datetime
import functools
import json

from conpact import (app_sessions, compaction, idle_arming, idle_state, idle_watch, session_registry,
                         settings, token_store)

T0 = 1_800_000_000.0
TTL = 3600
EARLY_AT = T0 + 300            # idle_seconds
EXPIRY_AT = T0 + TTL - 300     # lead_seconds


class Clock:
    def __init__(self, t=T0 + 1):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _session(status="idle", changed=T0 + 1, sid="sess-a", pid=4242, **fields):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": sid, "bridgeSessionId": f"bridge-{sid}", "name": "Anchor",
        "status": status, "statusUpdatedAt": int(changed * 1000), **fields}), encoding="utf-8")


def _transcript(tmp_path, tokens=200_000, last_call=T0):
    stamp = datetime.datetime.fromtimestamp(last_call, datetime.timezone.utc).isoformat()
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "assistant", "isSidechain": False, "timestamp": stamp, "message": {
        "model": "claude-opus-5", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 10, "cache_read_input_tokens": tokens - 10,
            "output_tokens": 0, "cache_creation": {"ephemeral_1h_input_tokens": 10}}}}) + "\n", encoding="utf-8")
    return str(path)


def _arm(tmp_path, sid="sess-a", environ=None, now=T0 + 1, last_call=T0):
    started = []
    status = idle_arming.arm({"session_id": sid, "transcript_path": _transcript(tmp_path, last_call=last_call)},
                             environ={} if environ is None else environ, clock=lambda: now,
                             spawner=lambda argv, env: started.append(argv) or 99)
    return status, started


def _deps(clock, sent, present, environ=None):
    token = token_store.AccessToken("tok", False)
    compactor = functools.partial(compaction.compact_record, token_getter=lambda: token,
                                  sender=lambda bridge, text, tok: sent.append((bridge, text)) or (200, {}))
    return idle_watch.Deps(clock=clock, sleep=clock.sleep, environ={} if environ is None else environ,
                           sessions_dir=None, compactor=compactor, present=present)


def _answers(clock, *actions):
    """present() answering each toast in turn; "ignore" lets the toast run out."""
    seen, left = [], list(actions)

    def present(controller):
        model = controller.model()
        seen.append((model.get("stage"), model["kind"]))
        action = left.pop(0)
        if action == "ignore":
            clock.t = model["deadline"]
            controller.poll()
        else:
            controller.act(action)
    return present, seen


def _watch(clock, sent, present, sid="sess-a", environ=None):
    generation = idle_state.read_marker(sid)["generation"]
    return idle_watch.watch(sid, generation, _deps(clock, sent, present, environ))


# --- 1: both stages come ----------------------------------------------------

def test_1_an_idle_time_adds_an_early_toast_and_keeps_the_one_before_the_cache_expires(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    status, started = _arm(tmp_path)
    assert status["action"] == "armed" and len(started) == 1
    assert [(s["kind"], s["at"]) for s in idle_state.read_marker("sess-a")["stages"]] == [
        ("early", EARLY_AT), ("expiry", EXPIRY_AT)]


def test_1_dismissing_the_early_toast_leaves_the_later_one_to_come(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    _arm(tmp_path)
    clock, sent = Clock(), []
    present, seen = _answers(clock, "dismiss", "dismiss")
    outcome = _watch(clock, sent, present)
    assert seen == [("early", "ask"), ("expiry", "ask")]
    assert sent == []
    assert outcome["earlier"] == [{"stage": "early", "event": "dismissed"}]
    assert clock.t >= EXPIRY_AT


def test_1_an_early_toast_left_alone_closes_itself_and_the_later_one_still_comes(tmp_path):
    settings.save({"idle_seconds": 300, "early_toast_seconds": 60})
    _session()
    _arm(tmp_path)
    clock, sent = Clock(), []
    present, seen = _answers(clock, "ignore", "compact")
    outcome = _watch(clock, sent, present)
    assert seen == [("early", "ask"), ("expiry", "ask")]
    assert sent == [("bridge-sess-a", "/compact " + compaction.PROVENANCE_CLAUSE)]
    assert outcome["event"] == "compacted" and outcome["stage"] == "expiry"
    assert outcome["earlier"] == [{"stage": "early", "event": "timeout"}]


# --- 2: compacting early ends the watch -------------------------------------

def test_2_compacting_from_the_early_toast_stops_the_later_one(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    _arm(tmp_path)
    clock, sent = Clock(), []
    present, seen = _answers(clock, "compact")
    outcome = _watch(clock, sent, present)
    assert seen == [("early", "ask")]
    assert sent == [("bridge-sess-a", "/compact " + compaction.PROVENANCE_CLAUSE)]
    assert outcome["stage"] == "early" and clock.t < EXPIRY_AT
    assert idle_state.read_marker("sess-a") is None


# --- 3: silencing a session -------------------------------------------------

def test_3_silencing_a_session_stops_this_watch_and_the_next_ones(tmp_path):
    settings.save({"idle_seconds": 300, "mute_seconds": 86_400})
    _session()
    _arm(tmp_path)
    clock, sent = Clock(), []
    present, seen = _answers(clock, "mute")
    outcome = _watch(clock, sent, present)
    assert seen == [("early", "ask")] and sent == []
    assert outcome["event"] == "muted" and outcome["for_seconds"] == 86_400

    # the same turn end, later: still silenced
    status, started = _arm(tmp_path, now=EARLY_AT + 60)
    assert status["action"] == "skip" and "silenced" in status["reason"] and started == []

    # used again: the mute is spent and the session is watched as usual
    status, started = _arm(tmp_path, now=EARLY_AT + 120, last_call=EARLY_AT + 100)
    assert status["action"] == "armed" and len(started) == 1
    assert idle_state.read_mute("sess-a") is None


# --- 4: archived sessions ---------------------------------------------------

def _archive(tmp_path, host="local_a", archived=True):
    store = tmp_path / "app" / "Claude" / "claude-code-sessions" / "install" / "profile"
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{host}.json").write_text(json.dumps({"sessionId": host, "isArchived": archived}), encoding="utf-8")
    return {"APPDATA": str(tmp_path / "app")}


def test_4_a_session_the_user_archived_is_never_watched_or_compacted(tmp_path):
    _session(hostSessionId="local_a")
    environ = _archive(tmp_path)
    assert app_sessions.is_archived("local_a", environ) is True
    status, started = _arm(tmp_path, environ=environ)
    assert status == {"action": "skip", "reason": "the session is archived"} and started == []
    assert idle_state.read_marker("sess-a") is None


def test_4_archiving_after_the_turn_end_stands_the_watcher_down(tmp_path):
    _session(hostSessionId="local_a")
    environ = _archive(tmp_path, archived=False)
    assert _arm(tmp_path, environ=environ)[0]["action"] == "armed"
    _archive(tmp_path, archived=True)  # the user archives it while the session sits idle
    clock, sent, shown = Clock(), [], []
    # the watcher swallows what present() raises, so record the toasts and assert outside it
    outcome = _watch(clock, sent, shown.append, environ=environ)
    assert shown == []  # an archived session must not be toasted
    assert outcome["event"] == "archived" and sent == []


# --- 5: auto-compact per stage ----------------------------------------------

def test_5_auto_when_idle_compacts_at_the_early_stage_only(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    _arm(tmp_path)
    clock, sent = Clock(), []
    present, seen = _answers(clock, "auto")           # switched on from the early toast
    assert _watch(clock, sent, present)["stage"] == "early"
    assert idle_state.auto_mode("sess-a") == "early"

    _arm(tmp_path, now=EARLY_AT + 10, last_call=EARLY_AT)
    clock, sent, shown = Clock(EARLY_AT + 10), [], []
    outcome = _watch(clock, sent, shown.append)
    assert [(c.model()["stage"], c.model()["kind"]) for c in shown] == [("early", "notice")]  # told, not asked
    assert sent == [("bridge-sess-a", "/compact " + compaction.PROVENANCE_CLAUSE)] and outcome["event"] == "auto_compacted"


def test_5_auto_before_expiry_keeps_the_early_stage_silent(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    _arm(tmp_path)
    idle_state.set_auto("sess-a", "expiry")
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, shown.append)
    assert [(c.model()["stage"], c.model()["kind"]) for c in shown] == [("expiry", "notice")]
    assert sent == [("bridge-sess-a", "/compact " + compaction.PROVENANCE_CLAUSE)]
    assert outcome["stage"] == "expiry" and clock.t >= EXPIRY_AT
