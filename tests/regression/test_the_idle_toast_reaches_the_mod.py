"""
Regression test for CU-20261002-084 (the idle toast compacts through the mod).

Until 2026-10-02 the idle toast (conpact.idle_watch, a detached process the Stop
hook starts) could compact a session only by sending /compact over the Remote
Control bridge, so a session with Remote Control off got the "turn on Remote
Control" toast (D-20260920-020) - even where conPACT's Claude Code mod
(CU-20261002-083) was running inside it and could compact it in-process. The
contract (D-20261002-066):

  1. Where the session's mod beats, the toast is offered as for a session with
     Remote Control, and "Compact now" and auto-compact hand the compaction to
     the mod: nothing is sent over the bridge, even where the bridge is there.
  2. Where no fresh beat is found, nothing changes: the bridge where Remote
     Control is on, the Remote Control toast where it is off.
  3. A request the mod has not taken by its lapse is reported as failed, and is
     never taken later - the watcher waits until past the lapse, the mod takes
     no lapsed request and no request id twice - so no compaction follows a
     failure the user was shown, and none is sent twice.
  4. The mod writes only its beat and its answers, under ~/.conpact/mod/: its
     one write is guarded in register.js (by rules.isWritable), and goes
     nowhere else.
  5. The two sides name the same files, fields and timings.
"""
import json
import pathlib
import re

from conpact import compaction, idle_state, idle_watch as iw, mod_handoff, session_registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOKS = ROOT / "src" / "mod" / "hooks"
ARMED = 1_800_000_000.0
FIRE = ARMED + 150


def _js(name):
    return (HOOKS / name).read_text(encoding="utf-8")


class Clock:
    def __init__(self, t=ARMED):
        self.t, self.on_sleep = t, None

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.on_sleep:
            self.on_sleep(self.t)


def _session(bridge):
    record = {"pid": 4242, "sessionId": "s1", "bridgeSessionId": bridge, "name": "conPACT", "status": "idle",
              "statusUpdatedAt": int((ARMED + 0.5) * 1000)}
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / "4242.json").write_text(json.dumps(record), encoding="utf-8")
    generation = idle_state.write_marker("s1", {
        "session_id": "s1", "armed_at": ARMED, "last_call": ARMED - 2, "ttl": 3600, "context_tokens": 500_000,
        "fire_at": FIRE, "expires_at": ARMED + 450, "name": "conPACT", "pid": 4242})
    return generation


def _beat():
    path = mod_handoff.beat_path("s1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": "s1", "at": FIRE, "ended": False}), encoding="utf-8")


def _mod(clock, action=None):
    """The mod, as the watcher meets it: it answers the ask a second in, or never."""
    asks = []

    def on_sleep(t):
        path = mod_handoff.ask_path("s1")
        if path.exists():
            ask = json.loads(path.read_text(encoding="utf-8"))
            if ask not in asks:
                asks.append(ask)
            if action and t >= ask["requested_at"] + 1:
                mod_handoff.answer_path("s1").parent.mkdir(parents=True, exist_ok=True)
                mod_handoff.answer_path("s1").write_text(json.dumps(
                    {"session_id": "s1", "request_id": ask["request_id"], "at": t, "action": action}),
                    encoding="utf-8")
    clock.on_sleep = on_sleep
    return asks


def _bridge(sent):
    def send(record, **kw):
        sent.append(record)
        return {"sent": True, "http_status": 200, "token_refreshed": False}
    return send


def _deps(clock, sent, present):
    return iw.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None, compactor=_bridge(sent),
                   present=present, opener=None)


def _press(action, kinds):
    def present(prompt):
        kinds.append(prompt.model()["kind"])
        if prompt.model()["kind"] == "ask":
            prompt.act(action)
    return present


def test_1_a_session_whose_mod_beats_is_compacted_through_it_without_remote_control():
    for bridge in (None, "session_x"):
        generation = _session(bridge)
        _beat()
        clock, sent, kinds = Clock(), [], []
        asks = _mod(clock, "claimed")
        outcome = iw.watch("s1", generation, _deps(clock, sent, _press("compact", kinds)))
        assert kinds == ["ask"]
        assert outcome["event"] == "compacted" and outcome["transport"] == "mod"
        assert [a["request_id"] for a in asks] == [outcome["request_id"]]
        assert sent == []


def test_1_auto_compact_goes_through_the_mod_too():
    generation = _session(None)
    _beat()
    idle_state.set_auto("s1", "expiry")
    clock, sent, notices = Clock(), [], []
    _mod(clock, "claimed")
    outcome = iw.watch("s1", generation, _deps(clock, sent, lambda notice: notices.append(notice.model()["kind"])))
    assert notices == ["notice"]
    assert outcome["event"] == "auto_compacted" and outcome["transport"] == "mod"
    assert sent == []


def test_2_without_a_fresh_beat_the_bridge_or_the_remote_control_toast_as_before():
    generation = _session("session_x")
    clock, sent, kinds = Clock(), [], []
    outcome = iw.watch("s1", generation, _deps(clock, sent, _press("compact", kinds)))
    assert kinds == ["ask"] and len(sent) == 1 and "transport" not in outcome
    generation = _session(None)
    clock, sent, kinds = Clock(), [], []
    iw.watch("s1", generation, _deps(clock, sent, _press("compact", kinds)))
    assert kinds == ["remote"] and sent == []
    assert not mod_handoff.ask_path("s1").exists()


def test_3_a_request_not_taken_is_failed_after_its_lapse_and_withdrawn():
    generation = _session("session_x")
    _beat()
    clock, sent, kinds = Clock(), [], []
    _mod(clock, None)
    outcome = iw.watch("s1", generation, _deps(clock, sent, _press("compact", kinds)))
    assert outcome["event"] == "failed" and outcome["reason"] == "the session's mod did not take the compaction"
    assert sent == []                                               # not sent over the bridge instead
    assert not mod_handoff.ask_path("s1").exists()
    assert mod_handoff.GRACE_SECONDS > 0                            # the watcher gives up only past the lapse


def test_3_the_mod_takes_no_lapsed_request_and_no_request_twice():
    handoff = _js("handoff.js")
    assert "now / 1000 > data.expires_at) return null" in handoff
    assert "await requests.isTaken(host, id, ask.request_id)) return null" in handoff
    assert re.search(r"await requests\.take\(host, id, ask\.request_id, now\)\s+return ask", handoff)
    # Taken before the compaction starts, so a later look cannot take it again.
    serve = handoff[handoff.index("export async function serve"):]
    assert serve.index("claim(") < serve.index("compact(host)")


def _writable():
    rules = _js("rules.js")
    pattern = re.search(r"const WRITABLE = /(.*)/\n", rules).group(1)
    upward = re.search(r"const UPWARD = /(.*)/\n", rules).group(1)
    assert "return typeof path === 'string' && WRITABLE.test(path) && !UPWARD.test(path)" in rules
    return re.compile(pattern), re.compile(upward)


def test_4_the_mod_writes_only_its_beat_and_answers_under_conpacts_folder():
    writable, upward = _writable()
    ok = lambda path: bool(writable.search(path)) and not upward.search(path)  # noqa: E731
    for path in ("C:/Users/a/.conpact/mod/beat/s1.json", "C:\\Users\\a\\.conpact\\mod\\answer\\s-1_x.json",
                 "/home/a/.conpact/mod/beat/s1.json"):
        assert ok(path), path
    for path in ("C:/Users/a/.conpact/mod/ask/s1.json", "C:/Users/a/.conpact/settings.json",
                 "C:/Users/a/.conpact/mod/beat/s1.json.bak", "C:/Users/a/.conpact/mod/beat/../../x/s1.json",
                 "C:/Users/a/.conpact/mod/beat/a/../s1.json", "C:/Users/a/.claude/settings.json",
                 "C:/Users/a/.conpact/mod/beat/.json", "C:/Users/a/x.conpact/mod/beat/s1.json"):
        assert not ok(path), path
    register = _js("register.js")
    assert register.count("$.fs.write(") == 1
    assert re.search(r"if \(!isWritable\(path\)\) throw .*\n\s+return \$\.fs\.write\(path, text\)", register)
    others = "".join(_js(name) for name in ("files.js", "handoff.js", "requests.js", "run.js", "tools.js",
                                            "rules.js"))
    assert others.count("host.fs.write(") == 1                     # files.write, the one way to write


def test_5_both_sides_name_the_same_files_fields_and_timings():
    handoff = _js("handoff.js")
    for kind in ("beat", "ask", "answer"):
        assert f"'mod/{kind}/' + id + '.json'" in handoff
        assert getattr(mod_handoff, f"{kind}_path")("s1") == compaction.STATE_DIR / "mod" / kind / "s1.json"
    assert f"BEAT_MS = {mod_handoff.BEAT_SECONDS * 1000:_}" in handoff
    assert f"POLL_MS = {mod_handoff.POLL_SECONDS * 1000:_}" in handoff
    assert mod_handoff.FRESH_SECONDS >= 3 * mod_handoff.BEAT_SECONDS
    assert mod_handoff.ASK_SECONDS >= 3 * mod_handoff.POLL_SECONDS
    for field in ("session_id", "request_id", "expires_at", "ended", "at"):
        assert field in handoff
    actions = set(re.findall(r"action: '(\w+)'", handoff))
    assert actions == set(mod_handoff.TAKEN + mod_handoff.REFUSED)
