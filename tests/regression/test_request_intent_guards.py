"""
Regression test for CU-20260919-003 (review findings 3 and 7).

  1. --dry-run is honoured by --request: nothing is recorded. It used to write a
     real request, so the next turn end compacted the session - the opposite of
     what an agent "testing safely" with --dry-run expects.
  2. --request refuses a target whose session id is missing or is not a plain id,
     instead of writing a request file named after "None" (or a path).
"""
from conpact import cli, compaction, session_registry


def _self_record(monkeypatch, **over):
    record = dict(name="Me", pid=1, status="busy",
                  sessionId="sess-a", hostSessionId="local_a", bridgeSessionId="bridge_a")
    record.update(over)
    monkeypatch.setattr(session_registry, "resolve_self", lambda **k: dict(record))


def test_request_dry_run_records_nothing(monkeypatch, tmp_path, capsys):
    _self_record(monkeypatch)
    monkeypatch.setattr(compaction, "REQUESTS_DIR", tmp_path)
    assert cli.main(["--self", "--request", "--dry-run"]) == 0
    assert list(tmp_path.iterdir()) == []
    assert "not recorded" in capsys.readouterr().out


def test_request_without_session_id_is_refused(monkeypatch, tmp_path):
    _self_record(monkeypatch, sessionId=None)
    monkeypatch.setattr(compaction, "REQUESTS_DIR", tmp_path)
    assert cli.main(["--self", "--request"]) == 1
    assert list(tmp_path.iterdir()) == []


def test_request_with_path_like_session_id_is_refused(monkeypatch, tmp_path):
    requests = tmp_path / "requests"
    _self_record(monkeypatch, sessionId="../escaped")
    monkeypatch.setattr(compaction, "REQUESTS_DIR", requests)
    assert cli.main(["--self", "--request"]) == 1
    assert list(tmp_path.iterdir()) == []
