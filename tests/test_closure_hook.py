"""Tests for conpact.closure_hook: consume-once execution driven by hook stdin."""
import io
import json

import pytest

from conpact import closure_hook as ch
from conpact import compaction as cx


def test_read_hook_input_parses_json():
    data = ch.read_hook_input(io.StringIO(json.dumps({"session_id": "s1"})))
    assert data["session_id"] == "s1"


def test_read_hook_input_tolerates_garbage():
    assert ch.read_hook_input(io.StringIO("not json")) == {}
    assert ch.read_hook_input(io.StringIO("")) == {}
    assert ch.read_hook_input(io.StringIO("[1, 2]")) == {}


def test_read_hook_input_tolerates_unreadable_stream():
    class Broken:
        def read(self):
            raise OSError("closed")

    assert ch.read_hook_input(Broken()) == {}


def test_run_skips_without_session_id(tmp_path):
    status = ch.run({}, requests_dir=tmp_path)
    assert status["action"] == "skip"


def test_run_skips_without_request(tmp_path):
    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path)
    assert status["action"] == "skip"


def test_run_consumes_request_and_compacts(tmp_path):
    cx.request_compaction("s1", focus="keep X", requests_dir=tmp_path)
    seen = {}

    def fake_compact(**kw):
        seen.update(kw)
        return {"sent": True, "text": "/compact keep X", "http_status": 200}

    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=fake_compact)
    assert status["action"] == "compacted"
    assert seen["focus"] == "keep X"
    assert seen["session_id"] == "s1"
    # Request consumed: a second Stop does nothing.
    status2 = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=fake_compact)
    assert status2["action"] == "skip"


def test_run_passes_sessions_dir_to_the_compactor(tmp_path):
    cx.request_compaction("s1", requests_dir=tmp_path / "req")
    seen = {}

    def fake_compact(**kw):
        seen.update(kw)
        return {"http_status": 200}

    ch.run({"session_id": "s1"}, sessions_dir=tmp_path / "sess",
           requests_dir=tmp_path / "req", compactor=fake_compact)
    assert seen["sessions_dir"] == tmp_path / "sess"


def test_run_reports_resolution_error(tmp_path):
    cx.request_compaction("s1", requests_dir=tmp_path)

    def raising(**kw):
        from conpact import session_registry
        raise session_registry.TargetError("no record")

    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=raising)
    assert status["action"] == "error"
    assert "no record" in status["reason"]


def test_run_default_compactor_resolves_the_real_session(tmp_path, monkeypatch):
    # No compactor injected: the default path (compact_self) runs, finds no
    # session record in the isolated home, and reports it as an error.
    cx.request_compaction("s1", requests_dir=tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path)
    assert status["action"] == "error"
    assert "TargetError" in status["reason"]


def test_record_outcome_survives_an_unwritable_log(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    ch.record_outcome({"action": "error", "reason": "r"}, "s1", log_path=blocker / "log.jsonl")


def test_main_is_silent_when_nothing_was_claimed(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert ch.main() == 0
    assert capsys.readouterr() == ("", "")


def test_skip_statuses_are_exact(tmp_path):
    assert ch.run({}, requests_dir=tmp_path) == {"action": "skip", "reason": "no session_id in hook input"}
    assert ch.run({"session_id": "s1"}, requests_dir=tmp_path) == {
        "action": "skip", "reason": "no compaction request for this session"}


def test_a_request_without_focus_compacts_without_one(tmp_path):
    (tmp_path / "s1.json").write_text(json.dumps({"session_id": "s1"}), encoding="utf-8")
    seen = {}
    ch.run({"session_id": "s1"}, requests_dir=tmp_path,
           compactor=lambda **kw: seen.update(kw) or {"http_status": 200})
    assert seen["focus"] == ""


def test_fired_statuses_carry_reason_and_result(tmp_path):
    for code, action in ((200, "compacted"), (503, "failed")):
        cx.request_compaction("s1", requests_dir=tmp_path)
        result = {"http_status": code}
        status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=lambda **kw: result)
        assert (status["action"], status["reason"], status["result"]) == (
            action, f"bridge returned HTTP {code}", result)


def test_log_entry_shape_and_folder_creation(tmp_path):
    import re
    log = tmp_path / "deep" / "er" / "hook-log.jsonl"
    ch.record_outcome({"action": "failed", "reason": "bridge returned HTTP 401",
                       "result": {"http_status": 401, "token_refreshed": True}}, "s1", log_path=log)
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["ts"])
    assert {k: entry[k] for k in ("session_id", "action", "reason", "http_status", "token_refreshed")} == {
        "session_id": "s1", "action": "failed", "reason": "bridge returned HTTP 401",
        "http_status": 401, "token_refreshed": True}


def test_main_reports_a_claimed_request_on_stderr_and_nothing_else(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    assert ch.main() == 0
    assert capsys.readouterr() == ("", "")
    monkeypatch.setattr(ch, "run", lambda hook_input: {"action": "failed", "reason": "bridge returned HTTP 503"})
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    assert ch.main() == 0
    assert capsys.readouterr() == ("", "[conpact.closure_hook] failed: bridge returned HTTP 503\n")


@pytest.mark.parametrize("action, armed", [("skip", True), ("failed", True), ("error", True),
                                           ("below_threshold", True), ("compacted", False)])
def test_main_hands_the_turn_end_to_the_idle_notifier_unless_it_compacted(monkeypatch, action, armed):
    from conpact import idle_arming
    seen = []
    monkeypatch.setattr(ch, "run", lambda hook_input: {"action": action, "reason": "r"})
    monkeypatch.setattr(idle_arming, "run", lambda hook_input: seen.append(hook_input) or {"action": "skip"})
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1", "transcript_path": "t"})))
    assert ch.main() == 0
    assert seen == ([{"session_id": "s1", "transcript_path": "t"}] if armed else [])


def _fired(**kw):
    return {"sent": True, "text": "/compact", "http_status": 200}


def test_a_request_without_a_minimum_uses_the_users_default(tmp_path):
    from conpact import settings
    settings.save({"closure_min_context_tokens": 150_000})
    cx.request_compaction("s1", requests_dir=tmp_path)
    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=_fired, measure=lambda path: 149_999)
    assert status == {"action": "below_threshold", "reason": "context 149999 tokens < minimum 150000; not compacting",
                      "context_tokens": 149_999, "min_context_tokens": 150_000}
    cx.request_compaction("s1", requests_dir=tmp_path)
    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=_fired, measure=lambda path: 150_000)
    assert (status["action"], status["min_context_tokens"]) == ("compacted", 150_000)


def test_the_agents_own_minimum_wins_over_the_default(tmp_path):
    from conpact import settings
    settings.save({"closure_min_context_tokens": 150_000})
    cx.request_compaction("s1", min_context_tokens=50_000, requests_dir=tmp_path)
    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=_fired, measure=lambda path: 60_000)
    assert (status["action"], status["min_context_tokens"]) == ("compacted", 50_000)


def test_with_no_default_a_request_without_a_minimum_always_compacts(tmp_path):
    cx.request_compaction("s1", requests_dir=tmp_path)
    status = ch.run({"session_id": "s1"}, requests_dir=tmp_path, compactor=_fired, measure=lambda path: None)
    assert (status["action"], status["min_context_tokens"]) == ("compacted", None)
