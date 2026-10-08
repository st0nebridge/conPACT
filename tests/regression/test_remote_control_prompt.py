"""
Regression test for CU-20260920-020 (a toast for a session whose Remote
Control is off).

The contract, end to end through the real modules (clock, toast, opener and
bridge faked):

  1. A session that is worth compacting but has no bridgeSessionId is still
     watched. Before, the turn end logged "not_armed: session not bound" and
     nothing more was ever said, so the session silently never got a toast.
  2. At the notify time it gets a different toast: Remote Control is off, with
     the session's name and size. Nothing is sent - there is nowhere to send to.
     It is asked once per idle stretch, not at every stage: unlike "compact now
     or later", the answer does not change as the cache runs down.
  3. "Open the session" hands the app its own link to that session, so the
     switch is one click away. That is as far as it goes: conPACT never
     turns Remote Control on itself (D-020).
  4. If Remote Control was turned on while the session sat idle, the normal
     compact toast comes instead - the watcher reads the record at the notify
     time, not at the turn end.
  5. "Silence 24 h" works the same as on the compact toast, and a silenced
     session is not armed again until it is used.
  6. The toast also offers to turn Remote Control on for *every new session* -
     Claude Code's own remoteControlAtStartup setting - and nothing is written
     unless that button is clicked. The offer is not made when it is already on,
     and everything else in the settings file is kept (D-021).
"""
import datetime
import functools
import json

from conpact import (app_sessions, compaction, idle_arming, idle_state, idle_watch, remote_startup,
                         session_registry, settings, token_store)

T0 = 1_800_000_000.0
TTL = 3600
EXPIRY_AT = T0 + TTL - 300
HOST = "local_93dfc8f5"


class Clock:
    def __init__(self, t=T0 + 1):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _session(bridge=None, sid="sess-a", pid=4242, status="idle", changed=T0 + 1):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    body = {"pid": pid, "sessionId": sid, "name": "Lighthouse", "status": status,
            "statusUpdatedAt": int(changed * 1000), "hostSessionId": HOST}
    if bridge:
        body["bridgeSessionId"] = bridge
    (session_registry.SESSIONS_DIR / f"{pid}.json").write_text(json.dumps(body), encoding="utf-8")


def _transcript(tmp_path, tokens=200_000, last_call=T0):
    stamp = datetime.datetime.fromtimestamp(last_call, datetime.timezone.utc).isoformat()
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "assistant", "isSidechain": False, "timestamp": stamp, "message": {
        "model": "claude-opus-5", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 10, "cache_read_input_tokens": tokens - 10,
            "output_tokens": 0, "cache_creation": {"ephemeral_1h_input_tokens": 10}}}}) + "\n", encoding="utf-8")
    return str(path)


def _arm(tmp_path, sid="sess-a", now=T0 + 1, last_call=T0):
    started = []
    status = idle_arming.arm({"session_id": sid, "transcript_path": _transcript(tmp_path, last_call=last_call)},
                             environ={}, clock=lambda: now, spawner=lambda argv, env: started.append(argv) or 99)
    return status, started


def _deps(clock, sent, present, opened):
    token = token_store.AccessToken("tok", False)
    compactor = functools.partial(compaction.compact_record, token_getter=lambda: token,
                                  sender=lambda bridge, text, tok: sent.append((bridge, text)) or (200, {}))
    return idle_watch.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None,
                           compactor=compactor, present=present, opener=opened.append)


def _watch(clock, sent, present, opened=None, sid="sess-a"):
    generation = idle_state.read_marker(sid)["generation"]
    return idle_watch.watch(sid, generation, _deps(clock, sent, present, opened if opened is not None else []))


# --- 1: an unbound session is watched, not dropped --------------------------

def test_1_a_session_without_remote_control_is_still_watched(tmp_path):
    _session(bridge=None)
    status, started = _arm(tmp_path)
    assert status["action"] == "armed" and len(started) == 1
    assert "Remote Control" in status["reason"]
    assert idle_state.read_marker("sess-a")["host_session_id"] == HOST


def test_1_a_session_too_small_to_compact_is_still_left_alone(tmp_path):
    settings.save({"min_context_tokens": 500_000})
    _session(bridge=None)
    status, started = _arm(tmp_path)
    assert status["action"] == "skip" and started == []


# --- 2 and 3: the toast, and how far it goes --------------------------------

def test_2_the_question_is_asked_once_an_idle_stretch_not_at_every_stage(tmp_path):
    """The compact toast has two stages; this one does not - the answer never changes."""
    settings.save({"idle_seconds": 300})
    _session(bridge=None)
    _arm(tmp_path)
    assert [s["kind"] for s in idle_state.read_marker("sess-a")["stages"]] == ["early", "expiry"]
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, lambda c: shown.append(c.model()["kind"]))
    assert shown == ["remote"]                      # not ["remote", "remote"]
    assert outcome["stage"] == "early" and "earlier" not in outcome


def test_2_dismissing_it_does_not_bring_it_back_before_the_cache_expires(tmp_path):
    """A dismissed *compact* toast comes back at the next stage, because by then the
    answer may have changed. This one is dismissed for the whole idle stretch:
    "Remote Control is off" is exactly as true five minutes later."""
    settings.save({"idle_seconds": 300})
    _session(bridge=None)
    _arm(tmp_path)
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, lambda c: shown.append(c.model()["stage"]) or c.act("dismiss"))
    assert shown == ["early"]                       # not ["early", "expiry"]
    assert outcome["event"] == "dismissed" and "earlier" not in outcome


def test_2_the_toast_says_remote_control_is_off_and_sends_nothing(tmp_path):
    _session(bridge=None)
    _arm(tmp_path)
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, shown.append)
    [prompt] = shown
    model = prompt.model()
    assert (model["kind"], model["name"], model["context_tokens"]) == ("remote", "Lighthouse", 200_000)
    assert sent == []
    assert outcome["event"] == "closed" and clock.t >= EXPIRY_AT


def test_3_open_the_session_hands_the_app_its_own_link_and_nothing_else(tmp_path):
    _session(bridge=None)
    _arm(tmp_path)
    clock, sent, opened = Clock(), [], []
    outcome = _watch(clock, sent, lambda c: c.act("open_session"), opened)
    assert opened == [app_sessions.session_link(HOST, {})]
    assert opened[0].endswith(HOST) and opened[0].startswith("claude://")
    assert outcome["event"] == "remote_opened" and sent == []


def test_3_the_toast_can_never_send_whatever_it_is_asked(tmp_path):
    """The compact actions do not exist on this toast, and would do nothing."""
    _session(bridge=None)
    _arm(tmp_path)
    clock, sent, opened, states = Clock(), [], [], []
    # the watcher swallows what present() raises, so record and assert outside it
    _watch(clock, sent, lambda c: states.extend(c.act(a) for a in ("compact", "auto", "launch")), opened)
    assert states == [{"state": "closed"}] * 3
    assert sent == [] and opened == []


# --- 4: turned on while it sat idle -----------------------------------------

def test_4_remote_control_turned_on_while_idle_gets_the_normal_toast(tmp_path):
    _session(bridge=None)
    _arm(tmp_path)
    _session(bridge="bridge-a")  # the user turns it on while the session sits idle
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, lambda c: shown.append(c.model()["kind"]) or c.act("compact"))
    assert shown == ["ask"]
    assert sent == [("bridge-a", "/compact")] and outcome["event"] == "compacted"


# --- 5: silencing works the same --------------------------------------------

def test_5_silence_stops_the_prompt_for_this_session_until_it_is_used(tmp_path):
    settings.save({"mute_seconds": 86_400})
    _session(bridge=None)
    _arm(tmp_path)
    clock, sent, opened = Clock(), [], []
    outcome = _watch(clock, sent, lambda c: c.act("mute"), opened)
    assert outcome["event"] == "muted" and opened == []

    status, started = _arm(tmp_path, now=EXPIRY_AT)
    assert status["action"] == "skip" and "silenced" in status["reason"] and started == []


# --- 6: the offer to turn it on for every new session ------------------------

def _claude_settings(body):
    path = remote_startup.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def test_6_the_toast_writes_the_setting_only_when_that_button_is_clicked(tmp_path):
    kept = {"model": "opus[1m]", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "stop.cmd"}]}]}}
    path = _claude_settings(kept)
    _session(bridge=None)
    _arm(tmp_path)

    # dismissing it changes nothing
    _watch(Clock(), [], lambda c: c.act("dismiss"))
    assert json.loads(path.read_text(encoding="utf-8")) == kept

    _arm(tmp_path, now=T0 + 2)
    outcome = _watch(Clock(), [], lambda c: c.act("always_on"))
    assert outcome["event"] == "remote_startup_on"
    assert json.loads(path.read_text(encoding="utf-8")) == {**kept, "remoteControlAtStartup": True}


def test_6_a_session_whose_setting_is_already_on_is_not_offered_it(tmp_path):
    _claude_settings({"remoteControlAtStartup": True})
    _session(bridge=None)
    _arm(tmp_path)
    shown = []
    _watch(Clock(), [], lambda c: shown.append(c.model()))
    assert shown[0]["offer_always_on"] is False


def test_6_settings_we_cannot_parse_are_refused_not_replaced(tmp_path):
    path = remote_startup.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    _session(bridge=None)
    _arm(tmp_path)
    states = []
    outcome = _watch(Clock(), [], lambda c: states.append(c.act("always_on")))
    assert states[0]["state"] == "startup_failed"
    assert outcome["event"] == "remote_startup_failed"
    assert "not readable as JSON" in outcome["reason"]   # the log says which file and why
    assert path.read_text(encoding="utf-8") == "{ not json"
