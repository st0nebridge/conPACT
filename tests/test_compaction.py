"""Tests for conpact.compaction: command construction, request idempotency, sending."""
import pytest

from conpact import compaction as cx
from conpact import token_store as ts


def test_build_compact_text_plain():
    assert cx.build_compact_text() == "/compact"
    assert cx.build_compact_text("") == "/compact"
    assert cx.build_compact_text("   ") == "/compact"
    assert cx.build_compact_text(None) == "/compact"


def test_build_compact_text_with_focus():
    assert cx.build_compact_text("keep the API design") == "/compact keep the API design"


def test_normalize_focus_rejects_non_strings():
    assert cx.normalize_focus(42) == ""
    assert cx.normalize_focus(["a"]) == ""


def test_normalize_focus_trims_after_the_cap():
    focus = "a" * (cx.MAX_FOCUS_CHARS - 1) + " b"
    assert cx.normalize_focus(focus) == "a" * (cx.MAX_FOCUS_CHARS - 1)


@pytest.mark.parametrize("good", ["s1", "sess-1", "a_b", "0b6f2c1e-1111-4a4a-9c9c-123456789abc", "x" * 128])
def test_valid_session_ids(good):
    assert cx.is_valid_session_id(good)


def test_request_and_consume_roundtrip(tmp_path):
    cx.request_compaction("sess-1", focus="keep X", requests_dir=tmp_path)
    data = cx.consume_request("sess-1", requests_dir=tmp_path)
    assert data["session_id"] == "sess-1"
    assert data["focus"] == "keep X"


def test_request_write_leaves_no_temp_file(tmp_path):
    path = cx.request_compaction("sess-1", requests_dir=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_request_defaults_to_the_owned_requests_dir():
    path = cx.request_compaction("sess-1")
    assert path.parent == cx.REQUESTS_DIR
    assert cx.consume_request("sess-1") is not None


def test_consume_is_idempotent(tmp_path):
    cx.request_compaction("sess-1", requests_dir=tmp_path)
    assert cx.consume_request("sess-1", requests_dir=tmp_path) is not None
    # Second consume finds nothing - execution can only fire once.
    assert cx.consume_request("sess-1", requests_dir=tmp_path) is None


def test_requests_are_keyed_per_session(tmp_path):
    cx.request_compaction("sess-1", requests_dir=tmp_path)
    assert cx.consume_request("sess-2", requests_dir=tmp_path) is None
    assert cx.consume_request("sess-1", requests_dir=tmp_path) is not None


@pytest.mark.parametrize("content", ["not json", "[1, 2]", "null"])
def test_consume_tolerates_a_malformed_request(tmp_path, content):
    (tmp_path / "sess-1.json").write_text(content, encoding="utf-8")
    assert cx.consume_request("sess-1", requests_dir=tmp_path) == {"session_id": "sess-1", "focus": ""}
    assert not (tmp_path / "sess-1.json").exists()


def _record():
    return dict(name="Alpha", pid=1, sessionId="s", bridgeSessionId="bridge_a")


def test_compact_record_dry_run_does_not_send():
    def boom(*a, **k):
        raise AssertionError("dry run must not send")

    out = cx.compact_record(_record(), dry_run=True, token_getter=boom, sender=boom)
    assert out["sent"] is False
    assert out["dry_run"] is True
    assert out["text"] == "/compact " + cx.PROVENANCE_CLAUSE


def test_compact_record_sends_once_with_constructed_text():
    calls = []

    def fake_sender(bridge_id, text, token):
        calls.append((bridge_id, text, token))
        return 200, '{"ok":true}'

    out = cx.compact_record(
        _record(), focus="keep X",
        token_getter=lambda: ts.AccessToken("tok", False), sender=fake_sender,
    )
    assert out["sent"] is True
    assert out["http_status"] == 200
    assert out["token_refreshed"] is False
    assert out["response"] == '{"ok":true}'
    assert calls == [("bridge_a", "/compact keep X " + cx.PROVENANCE_CLAUSE, "tok")]
    assert "tok" not in {k: v for k, v in out.items() if k != "response"}.values()


def test_compact_record_default_token_getter_honours_allow_refresh(monkeypatch):
    seen = {}

    def fake_get_access_token(**kw):
        seen.update(kw)
        return ts.AccessToken("tok", True)

    monkeypatch.setattr(ts, "get_access_token", fake_get_access_token)
    out = cx.compact_record(_record(), allow_refresh=False, sender=lambda b, t, k: (200, ""))
    assert seen == {"allow_refresh": False}
    assert out["token_refreshed"] is True


def test_compact_self_resolves_then_sends(tmp_path):
    import json
    (tmp_path / "7.json").write_text(json.dumps(dict(
        name="Me", pid=7, sessionId="s7", hostSessionId="local_7", bridgeSessionId="bridge_7")), encoding="utf-8")
    env = {"CLAUDE_CODE_SESSION_ID": "s7", "CLAUDE_PID": "7"}
    out = cx.compact_self(environ=env, sessions_dir=tmp_path, dry_run=True)
    assert out["bridgeSessionId"] == "bridge_7"
    assert out["sent"] is False


@pytest.mark.parametrize("bad", [None, "", "../x"])
def test_pending_and_cancel_ignore_invalid_ids(tmp_path, bad):
    assert cx.pending_request(bad, requests_dir=tmp_path) is None
    assert cx.cancel_request(bad, requests_dir=tmp_path) is False


@pytest.mark.parametrize("content", ["not json", "[1]"])
def test_pending_request_ignores_a_malformed_file(tmp_path, content):
    (tmp_path / "sess-1.json").write_text(content, encoding="utf-8")
    assert cx.pending_request("sess-1", requests_dir=tmp_path) is None


def test_pending_request_does_not_claim(tmp_path):
    cx.request_compaction("sess-1", focus="f", min_context_tokens=5, requests_dir=tmp_path)
    assert cx.pending_request("sess-1", requests_dir=tmp_path)["min_context_tokens"] == 5
    assert cx.consume_request("sess-1", requests_dir=tmp_path) is not None


def test_cancel_request(tmp_path):
    cx.request_compaction("sess-1", requests_dir=tmp_path)
    assert cx.cancel_request("sess-1", requests_dir=tmp_path) is True
    assert cx.cancel_request("sess-1", requests_dir=tmp_path) is False
    assert cx.consume_request("sess-1", requests_dir=tmp_path) is None


def test_request_records_no_minimum_by_default(tmp_path):
    cx.request_compaction("sess-1", requests_dir=tmp_path)
    assert cx.pending_request("sess-1", requests_dir=tmp_path)["min_context_tokens"] is None

def test_focus_limit_is_500():
    assert cx.MAX_FOCUS_CHARS == 500


def test_request_records_empty_focus_and_a_timestamp_by_default(tmp_path):
    import json
    path = cx.request_compaction("sess-1", requests_dir=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["focus"] == ""
    assert isinstance(data["requested_at"], int) and data["requested_at"] > 1_700_000_000


def test_compact_record_reports_its_target():
    out = cx.compact_record(_record(), dry_run=True)
    assert {k: out[k] for k in ("name", "pid", "sessionId", "bridgeSessionId")} == {
        "name": "Alpha", "pid": 1, "sessionId": "s", "bridgeSessionId": "bridge_a"}


def test_compact_record_allows_refresh_by_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(ts, "get_access_token", lambda **kw: seen.update(kw) or ts.AccessToken("t", False))
    cx.compact_record(_record(), sender=lambda b, t, k: (200, ""))
    assert seen == {"allow_refresh": True}


def test_compact_self_without_focus_sends_only_the_provenance_clause(tmp_path):
    import json
    (tmp_path / "7.json").write_text(json.dumps(dict(
        name="Me", pid=7, sessionId="s7", hostSessionId="local_7", bridgeSessionId="bridge_7")), encoding="utf-8")
    out = cx.compact_self(environ={"CLAUDE_CODE_SESSION_ID": "s7", "CLAUDE_PID": "7"}, sessions_dir=tmp_path,
                          dry_run=True)
    assert out["text"] == "/compact " + cx.PROVENANCE_CLAUSE


def test_build_compact_text_adds_the_provenance_clause_only_when_asked():
    assert cx.build_compact_text("keep X") == "/compact keep X"
    assert cx.build_compact_text("keep X", provenance=True) == "/compact keep X " + cx.PROVENANCE_CLAUSE
    assert cx.build_compact_text("", provenance=True) == "/compact " + cx.PROVENANCE_CLAUSE


def test_the_provenance_clause_is_one_printable_line_outside_the_focus_limit():
    assert cx.normalize_focus(cx.PROVENANCE_CLAUSE) == cx.PROVENANCE_CLAUSE
    assert "\n" not in cx.PROVENANCE_CLAUSE and cx.PROVENANCE_CLAUSE.isprintable()
    text = cx.build_compact_text("x" * 5000, provenance=True)
    assert text == "/compact " + "x" * cx.MAX_FOCUS_CHARS + " " + cx.PROVENANCE_CLAUSE
