"""
Regression test for CU-20260919-016 (the user's settings, and where each one takes effect).

Requested 2026-09-19: the idle toast's test delay (idle_seconds 60) had to be
set by hand in a JSON file, and other values (the default minimum for an agent's
compaction, how long a result stays up) could not be set at all. The contract,
through the real modules (only the transcript reader, the watcher start and the
bridge are faked):

  1. A value set with the settings command reaches the part it controls: the
     toast's minimum and timing (idle_arming), the default minimum for a
     compaction an agent queued without one (closure_hook), and how long a
     result stays up (toast_view).
  2. Switching the toast off writes the off switch that the Stop wrapper checks
     before starting Python, so a turn end with the toast off still starts none.
  3. A refused value writes nothing, and nothing is on by default that only
     testing needs (idle_seconds is off).
"""
import io
import json
import pathlib

from conpact import (cache_window, closure_hook, compaction, idle_arming, idle_state, session_registry,
                         settings, settings_cli, toast_view)

NOW = 1_800_000_000.0
CMD = pathlib.Path(__file__).resolve().parents[2] / "tools" / "stop_compact.cmd"


def _command(*argv):
    out, err = io.StringIO(), io.StringIO()
    return settings_cli.main(list(argv), out=out, err=err), err.getvalue()


def _arm(tokens):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / "4242.json").write_text(json.dumps({
        "pid": 4242, "sessionId": "s1", "bridgeSessionId": "session_x", "status": "busy"}), encoding="utf-8")
    window = cache_window.CacheWindow(NOW - 5, 3600, tokens)
    return idle_arming.arm({"session_id": "s1", "transcript_path": "t.jsonl"}, environ={}, clock=lambda: NOW,
                           spawner=lambda argv, env: 1, reader=lambda path: window)


def test_1_each_setting_reaches_what_it_controls(tmp_path):
    assert _command("set", "min_context_tokens", "150k", "lead_seconds", "600",
                    "closure_min_context_tokens", "200k", "result_seconds", "20") == (0, "")
    assert _arm(149_999)["reason"] == "context 149999 tokens < minimum 150000"
    assert _arm(150_000)["fire_at"] == NOW - 5 + 3600 - 600
    compaction.request_compaction("s1", requests_dir=tmp_path)
    status = closure_hook.run({"session_id": "s1"}, requests_dir=tmp_path, measure=lambda path: 199_999,
                              compactor=lambda **kw: {"http_status": 200})
    assert (status["action"], status["min_context_tokens"]) == ("below_threshold", 200_000)
    assert toast_view.options()["close_after"]["compacted"] == 20_000
    assert _command("set", "idle_seconds", "60") == (0, "")
    assert _arm(150_000)["fire_at"] == NOW - 5 + 60


def test_2_the_toast_switch_is_the_file_the_stop_wrapper_checks():
    assert _command("set", "idle_toast", "off") == (0, "")
    assert _arm(500_000) == {"action": "skip", "reason": "idle notifier is switched off"}
    switch = idle_state.off_switch_path()
    assert switch.exists()
    assert switch.parent == compaction.STATE_DIR
    wrapper = CMD.read_text(encoding="utf-8")
    assert f'if exist "%USERPROFILE%\\.conpact\\{switch.name}" exit /b 0' in wrapper
    assert _command("set", "idle_toast", "on") == (0, "")
    assert not switch.exists()


def test_3_a_refused_value_writes_nothing_and_testing_values_are_off_by_default():
    code, err = _command("set", "min_context_tokens", "150k", "idle_seconds", "5")
    assert code == 2 and "idle_seconds must be from 10 to 86,400 seconds, or off" in err
    assert not settings.settings_path().exists()
    assert settings.load()["idle_seconds"] is None
