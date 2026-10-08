"""Tests for conpact.idle_arming: the Stop hook's decision to watch a session."""
import json
import pathlib

import pytest

from conpact import cache_window, detach, idle_arming as ia, idle_state, session_registry, settings

NOW = 1_800_000_000.0
HOOK = {"session_id": "s1", "transcript_path": "t.jsonl", "hook_event_name": "Stop"}


def _window(tokens=200_000, ttl=3600, last_call=NOW - 5):
    return cache_window.CacheWindow(last_call, ttl, tokens)


def _record(**fields):
    record = {"pid": 4242, "sessionId": "s1", "bridgeSessionId": "session_x", "name": "Proj",
              "status": "busy", **fields}
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / "4242.json").write_text(json.dumps(record), encoding="utf-8")


def _spawner(calls, pid=777):
    def spawn(argv, env):
        calls.append((argv, env))
        return pid
    return spawn


def _never_spawn(argv, env):
    raise AssertionError("must not start a watcher")


def _arm(window=None, spawner=_never_spawn, hook=HOOK, environ=None, seen=None):
    def reader(path):
        if seen is not None:
            seen.append(path)
        return window if window is not None else _window()
    return ia.arm(hook, environ={} if environ is None else environ, clock=lambda: NOW,
                  spawner=spawner, reader=reader)


def test_constants():
    assert ia.WATCH_MODULE == "conpact.idle_watch"
    assert ia.MIN_FRACTION == 0.6
    assert pathlib.Path(ia.SRC_ROOT) == pathlib.Path(__file__).resolve().parents[1] / "src"


def test_one_stage_before_the_cache_expires_by_default():
    assert ia.stages(_window(ttl=3600, last_call=1000), settings.defaults()) == [
        {"kind": "expiry", "at": 1000 + 3300, "until": 1000 + 3600}]


def test_a_stage_never_comes_before_sixty_percent_of_the_lifetime():
    assert ia.stages(_window(ttl=300, last_call=1000), settings.defaults())[0]["at"] == 1000 + 180
    values = {**settings.defaults(), "lead_seconds": 3000}
    assert ia.stages(_window(ttl=3600, last_call=1000), values)[0]["at"] == 1000 + 2160


def test_a_fixed_idle_time_adds_an_early_stage_and_keeps_the_later_one():
    values = {**settings.defaults(), "idle_seconds": 180}
    assert ia.stages(_window(ttl=3600, last_call=1000), values) == [
        {"kind": "early", "at": 1180, "until": 1180 + 120},
        {"kind": "expiry", "at": 1000 + 3300, "until": 1000 + 3600}]


def test_the_early_stage_ends_where_the_next_one_starts():
    values = {**settings.defaults(), "idle_seconds": 180, "early_toast_seconds": 86_400}
    early, expiry = ia.stages(_window(ttl=3600, last_call=1000), values)
    assert early["until"] == expiry["at"] == 1000 + 3300


@pytest.mark.parametrize("idle_seconds", [3300, 3400, 3600, 7200])
def test_an_early_stage_at_or_after_the_later_one_is_dropped(idle_seconds):
    values = {**settings.defaults(), "idle_seconds": idle_seconds}
    assert [s["kind"] for s in ia.stages(_window(ttl=3600, last_call=1000), values)] == ["expiry"]


def test_arm_records_a_watch_and_starts_a_detached_watcher():
    _record()
    calls, seen = [], []
    status = _arm(spawner=_spawner(calls), environ={"CLAUDE_CODE_SESSION_ID": "s1", "OTHER": "x"}, seen=seen)
    marker = idle_state.read_marker("s1")
    assert marker == {"session_id": "s1", "armed_at": NOW, "last_call": NOW - 5, "ttl": 3600,
                      "context_tokens": 200_000, "fire_at": NOW - 5 + 3300, "expires_at": NOW - 5 + 3600,
                      "stages": [{"kind": "expiry", "at": NOW - 5 + 3300, "until": NOW - 5 + 3600}],
                      "name": "Proj", "pid": 4242, "transcript_path": "t.jsonl", "host_session_id": None,
                      "generation": marker["generation"]}
    [(argv, env)] = calls
    assert argv == [detach.windowless_python(), "-m", "conpact.idle_watch", "s1", marker["generation"]]
    assert env == {"CLAUDE_CODE_SESSION_ID": "s1", "OTHER": "x", "PYTHONPATH": ia.SRC_ROOT}
    assert seen == ["t.jsonl"]
    assert status == {"action": "armed", "reason": "watcher started; acts in 3295 s if the session stays idle",
                      "watcher_pid": 777, "context_tokens": 200_000, "ttl": 3600,
                      "fire_at": NOW - 5 + 3300, "expires_at": NOW - 5 + 3600}


def test_arm_passes_no_transcript_when_the_hook_gave_none():
    _record()
    seen = []
    _arm(hook={"session_id": "s1", "transcript_path": 7}, spawner=_spawner([]), seen=seen)
    assert seen == [None]


def test_arm_uses_the_process_environment_by_default(monkeypatch):
    _record()
    for name in (session_registry.ENV_HOST, session_registry.ENV_SESSION, session_registry.ENV_PID):
        monkeypatch.delenv(name, raising=False)
    calls = []
    monkeypatch.setenv("CONPACT_TEST_MARK", "yes")
    ia.arm(HOOK, clock=lambda: NOW, spawner=_spawner(calls), reader=lambda path: _window())
    assert calls[0][1]["CONPACT_TEST_MARK"] == "yes"


@pytest.mark.parametrize("hook", [{}, {"session_id": "../x"}, {"session_id": 5}])
def test_skip_without_a_usable_session_id(hook):
    assert _arm(hook=hook) == {"action": "skip", "reason": "no usable session_id"}


def test_skip_when_switched_off():
    idle_state.off_switch_path().parent.mkdir(parents=True, exist_ok=True)
    idle_state.off_switch_path().write_text("", encoding="utf-8")
    assert _arm() == {"action": "skip", "reason": "idle notifier is switched off"}


def test_skip_when_the_transcript_shows_no_cache_window():
    status = ia.arm(HOOK, environ={}, clock=lambda: NOW, spawner=_never_spawn, reader=lambda path: None)
    assert status == {"action": "skip", "reason": "transcript shows no context size and cache lifetime"}


def test_skip_below_the_minimum_and_arm_at_it():
    _record()
    assert _arm(window=_window(tokens=99_999)) == {
        "action": "skip", "reason": "context 99999 tokens < minimum 100000"}
    assert _arm(window=_window(tokens=100_000), spawner=_spawner([]))["action"] == "armed"


def test_the_saved_settings_decide_the_minimum_and_the_timing():
    _record()
    settings.save({"min_context_tokens": 150_000, "lead_seconds": 600})
    assert _arm(window=_window(tokens=149_999))["reason"] == "context 149999 tokens < minimum 150000"
    assert _arm(window=_window(tokens=150_000), spawner=_spawner([]))["fire_at"] == NOW - 5 + 3000


def test_skip_when_switched_off_in_the_settings():
    settings.save({"idle_toast": False})
    assert _arm() == {"action": "skip", "reason": "idle notifier is switched off"}


def test_skip_when_the_cache_has_already_expired():
    assert _arm(window=_window(last_call=NOW - 3600)) == {
        "action": "skip", "reason": "prompt cache already expired"}


def test_an_early_time_past_the_cache_still_arms_the_stage_before_it_expires():
    _record()
    settings.save({"idle_seconds": 3600})
    status = _arm(spawner=_spawner([]))
    assert status["action"] == "armed" and status["fire_at"] == NOW - 5 + 3300
    assert [s["kind"] for s in idle_state.read_marker("s1")["stages"]] == ["expiry"]


def test_both_stages_are_armed_when_an_early_time_is_set():
    _record()
    settings.save({"idle_seconds": 300})
    status = _arm(spawner=_spawner([]))
    assert status["fire_at"] == NOW - 5 + 300
    assert status["reason"] == "watcher started; acts in 295 s if the session stays idle"
    assert [s["kind"] for s in idle_state.read_marker("s1")["stages"]] == ["early", "expiry"]


def test_a_muted_session_is_skipped_until_its_mute_runs_out():
    _record()
    idle_state.set_mute("s1", until=NOW + 60, after_call=NOW - 5)
    assert _arm() == {"action": "skip", "reason": "silenced for this session for another 60 s"}
    assert idle_state.read_marker("s1") is None
    idle_state.set_mute("s1", until=NOW - 1, after_call=NOW - 5)
    assert _arm(spawner=_spawner([]))["action"] == "armed"
    assert idle_state.read_mute("s1") is None


def test_using_the_session_again_ends_the_mute():
    _record()
    idle_state.set_mute("s1", until=NOW + 86_400, after_call=NOW - 60)
    status = _arm(window=_window(last_call=NOW - 5), spawner=_spawner([]))
    assert status["action"] == "armed"
    assert idle_state.read_mute("s1") is None


def test_an_archived_session_is_never_watched(tmp_path):
    _record(hostSessionId="local_a")
    store = tmp_path / "Claude" / "claude-code-sessions" / "i" / "p"
    store.mkdir(parents=True)
    (store / "archived-sessions.idx").write_text(json.dumps({"v": 1, "archived": ["local_a"]}), encoding="utf-8")
    environ = {"APPDATA": str(tmp_path)}
    assert _arm(environ=environ) == {"action": "skip", "reason": "the session is archived"}
    assert idle_state.read_marker("s1") is None
    (store / "archived-sessions.idx").write_text(json.dumps({"v": 1, "archived": []}), encoding="utf-8")
    assert _arm(environ=environ, spawner=_spawner([]))["action"] == "armed"


def test_not_armed_when_no_record_matches_the_runtime():
    status = _arm()
    assert status == {"action": "not_armed",
                      "reason": "session not bound: no session record matched the current runtime identity"}
    assert idle_state.read_marker("s1") is None


def test_a_session_with_remote_control_off_is_armed_to_ask_for_it():
    """Before, the turn end said "not bound" and the user was never told again."""
    _record(bridgeSessionId=None, hostSessionId="local_a")
    status = _arm(spawner=_spawner([]))
    assert status["action"] == "armed"
    assert status["reason"].endswith("; Remote Control is off, so the toast will ask for it "
                                     "rather than offer to compact")
    assert idle_state.read_marker("s1")["host_session_id"] == "local_a"


def test_an_armed_session_with_remote_control_on_says_nothing_about_it():
    _record(hostSessionId="local_a")
    assert "Remote Control" not in _arm(spawner=_spawner([]))["reason"]


def test_error_and_no_marker_when_the_watcher_cannot_start():
    _record()

    def failing(argv, env):
        raise OSError("nope")
    assert _arm(spawner=failing) == {"action": "error", "reason": "watcher did not start: nope"}
    assert idle_state.read_marker("s1") is None


def _log():
    path = idle_state.log_path()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_run_logs_what_it_armed(monkeypatch):
    monkeypatch.setattr(ia, "arm", lambda hook_input, **kw: {"action": "armed", "reason": "r", "ttl": 3600})
    assert ia.run(HOOK)["action"] == "armed"
    [entry] = _log()
    assert {k: v for k, v in entry.items() if k != "ts"} == {
        "event": "armed", "session_id": "s1", "reason": "r", "ttl": 3600}


def test_run_logs_refusals_and_errors_but_not_routine_skips(monkeypatch):
    for status in ({"action": "skip", "reason": "a"}, {"action": "not_armed", "reason": "b"},
                   {"action": "error", "reason": "c"}):
        monkeypatch.setattr(ia, "arm", lambda hook_input, s=status, **kw: s)
        assert ia.run(HOOK) == status
    assert [(e["event"], e["reason"]) for e in _log()] == [("not_armed", "b"), ("error", "c")]


def test_run_never_raises(monkeypatch):
    def boom(hook_input, **kw):
        raise RuntimeError("bad")
    monkeypatch.setattr(ia, "arm", boom)
    assert ia.run(HOOK) == {"action": "error", "reason": "RuntimeError: bad"}
    assert _log()[0]["event"] == "error"


def test_run_passes_its_options_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(ia, "arm", lambda hook_input, **kw: seen.update(kw) or {"action": "skip"})
    ia.run(HOOK, environ={"A": "1"})
    assert seen == {"environ": {"A": "1"}}
