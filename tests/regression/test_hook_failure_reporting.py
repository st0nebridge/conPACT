"""
Regression test for CU-20260919-006 (review findings 4, 5 and 8).

  1. A send the bridge rejects (e.g. HTTP 401 from an expired token) is reported
     as "failed", never as "compacted".
  2. Any failure while firing - login, network, file access, bad data, target
     resolution - is reported as "error" instead of escaping as a traceback, and
     main() always returns 0.
  3. Every consumed request leaves one line in the hook log recording the outcome
     and whether the token had to be refreshed - and never the token itself.
     Turns with no request are not logged.
"""
import io
import json
import sys
import urllib.error

import pytest

from conpact import closure_hook, compaction, session_registry, token_store

_RECORD = dict(name="Me", pid=1, sessionId="sess-a", bridgeSessionId="bridge_a")


def _compactor(status, refreshed=False):
    def fire(**kw):
        return compaction.compact_record(
            _RECORD, focus=kw["focus"],
            token_getter=lambda: token_store.AccessToken("SECRET-TOKEN", refreshed),
            sender=lambda bridge_id, text, token: (status, '{"error":"x"}'),
        )
    return fire


def test_rejected_send_is_failed_not_compacted(tmp_path):
    compaction.request_compaction("sess-a", requests_dir=tmp_path)
    status = closure_hook.run({"session_id": "sess-a"}, requests_dir=tmp_path, compactor=_compactor(401))
    assert status["action"] == "failed"
    assert "401" in status["reason"]


def test_accepted_send_is_compacted(tmp_path):
    compaction.request_compaction("sess-a", requests_dir=tmp_path)
    status = closure_hook.run({"session_id": "sess-a"}, requests_dir=tmp_path, compactor=_compactor(200))
    assert status["action"] == "compacted"


@pytest.mark.parametrize("exc", [
    token_store.TokenError("could not read the Claude credentials file"),
    urllib.error.URLError("no network"),
    PermissionError("credentials file locked"),
    ValueError("bad json"),
    session_registry.TargetError("no record"),
])
def test_any_firing_failure_is_reported_not_raised(tmp_path, exc):
    compaction.request_compaction("sess-a", requests_dir=tmp_path)

    def raising(**kw):
        raise exc

    status = closure_hook.run({"session_id": "sess-a"}, requests_dir=tmp_path, compactor=raising)
    assert status["action"] == "error"
    assert type(exc).__name__ in status["reason"]


def test_main_never_raises(tmp_path, monkeypatch):
    log = tmp_path / "hook-log.jsonl"
    monkeypatch.setattr(closure_hook, "LOG_PATH", log)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "sess-a"})))

    def exploding_run(hook_input, **kw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(closure_hook, "run", exploding_run)
    assert closure_hook.main() == 0
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["action"] == "error"
    assert "RuntimeError" in entry["reason"]


def test_log_records_refresh_but_never_the_token(tmp_path, monkeypatch):
    log = tmp_path / "hook-log.jsonl"
    compaction.request_compaction("sess-a", requests_dir=tmp_path)
    monkeypatch.setattr(closure_hook, "LOG_PATH", log)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "sess-a"})))
    real_run = closure_hook.run
    monkeypatch.setattr(
        closure_hook, "run",
        lambda hook_input, **kw: real_run(hook_input, requests_dir=tmp_path,
                                          compactor=_compactor(200, refreshed=True)),
    )
    assert closure_hook.main() == 0
    raw = log.read_text(encoding="utf-8")
    entry = json.loads(raw.splitlines()[-1])
    assert entry["action"] == "compacted"
    assert entry["session_id"] == "sess-a"
    assert entry["http_status"] == 200
    assert entry["token_refreshed"] is True
    assert "SECRET-TOKEN" not in raw


def test_turns_without_a_request_are_not_logged(tmp_path, monkeypatch):
    log = tmp_path / "hook-log.jsonl"
    monkeypatch.setattr(closure_hook, "LOG_PATH", log)
    monkeypatch.setattr(compaction, "REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "sess-a"})))
    assert closure_hook.main() == 0
    assert not log.exists()
