"""Tests for conpact.cli: argument routing, dry-run, request, send and status paths."""
import json

import pytest

from conpact import cli
from conpact import bridge_client, compaction, session_registry, token_store

_RECORD = dict(name="Alpha", pid=1, status="idle",
               sessionId="sess-a", hostSessionId="local_a", bridgeSessionId="bridge_a")


@pytest.fixture(autouse=True)
def _token_status_uses_the_test_credentials_file(monkeypatch):
    """CLI tests exercise the file path on every host, including macOS."""
    real = token_store.token_status
    monkeypatch.setattr(token_store, "token_status", lambda: real(platform="win32"))


def _patch_resolve(monkeypatch, record=_RECORD):
    monkeypatch.setattr(session_registry, "resolve_target", lambda **k: dict(record))
    monkeypatch.setattr(session_registry, "resolve_self", lambda **k: dict(record))


def test_cli_dry_run_does_not_send(monkeypatch, capsys):
    _patch_resolve(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("dry run must not send")

    monkeypatch.setattr(bridge_client, "send_event", boom)
    monkeypatch.setattr(token_store, "get_access_token", boom)
    rc = cli.main(["--name", "Alpha", "--compact", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "/compact" in out
    assert "nothing sent" in out


def test_cli_compact_send_path(monkeypatch, capsys):
    _patch_resolve(monkeypatch)
    calls = []
    monkeypatch.setattr(token_store, "get_access_token", lambda **k: token_store.AccessToken("tok", False))
    monkeypatch.setattr(bridge_client, "send_event",
                        lambda bridge, text, token, **k: calls.append((bridge, text, token)) or (200, "{}"))
    rc = cli.main(["--self", "--compact", "--focus", "keep X"])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == [("bridge_a", "/compact keep X", "tok")]
    assert "used as stored" in out
    assert "HTTP 200" in out
    assert "tok" not in out.replace("token", "")


def test_cli_reports_a_refreshed_token(monkeypatch, capsys):
    _patch_resolve(monkeypatch)
    monkeypatch.setattr(token_store, "get_access_token", lambda **k: token_store.AccessToken("tok", True))
    monkeypatch.setattr(bridge_client, "send_event", lambda *a, **k: (200, "{}"))
    assert cli.main(["--self", "--compact"]) == 0
    assert "refreshed first" in capsys.readouterr().out


def test_cli_request_records_intent(monkeypatch, capsys, tmp_path):
    _patch_resolve(monkeypatch)
    written = {}
    monkeypatch.setattr(compaction, "request_compaction",
                        lambda sid, focus="", **k: written.update(sid=sid, focus=focus) or tmp_path / "r.json")
    rc = cli.main(["--self", "--request", "--focus", "keep X"])
    assert rc == 0
    assert written == {"sid": "sess-a", "focus": "keep X"}
    assert "recorded at" in capsys.readouterr().out


def test_cli_request_writes_a_real_request(monkeypatch):
    _patch_resolve(monkeypatch)
    assert cli.main(["--self", "--request"]) == 0
    assert compaction.consume_request("sess-a") is not None


def test_cli_nonzero_on_http_error(monkeypatch):
    _patch_resolve(monkeypatch)
    monkeypatch.setattr(token_store, "get_access_token", lambda **k: token_store.AccessToken("tok", False))
    monkeypatch.setattr(bridge_client, "send_event", lambda *a, **k: (401, '{"error":"nope"}'))
    rc = cli.main(["--self", "--compact"])
    assert rc == 1


def test_cli_nonzero_when_token_unavailable(monkeypatch, capsys):
    _patch_resolve(monkeypatch)

    def no_token(**k):
        raise token_store.TokenError("could not read the Claude credentials file")

    monkeypatch.setattr(token_store, "get_access_token", no_token)
    assert cli.main(["--self", "--compact"]) == 1
    assert "TokenError" in capsys.readouterr().err


def test_cli_nonzero_when_target_unresolvable(monkeypatch, capsys):
    def no_target(**k):
        raise session_registry.TargetError("no session record matched the current runtime identity")

    monkeypatch.setattr(session_registry, "resolve_self", no_target)
    assert cli.main(["--self", "--compact"]) == 1
    assert "no session record matched" in capsys.readouterr().err


def test_cli_explicit_selectors_reach_resolve_target(monkeypatch):
    seen = {}
    monkeypatch.setattr(session_registry, "resolve_target", lambda **k: seen.update(k) or dict(_RECORD))
    assert cli.main(["--pid", "1", "--session-id", "sess-a", "--compact", "--dry-run"]) == 0
    assert seen == {"name": None, "pid": 1, "host_session_id": None, "session_id": "sess-a"}


def _write_creds(expires_in_ms, refresh="ref"):
    oauth = {"accessToken": "SECRET-ACCESS", "expiresAt": 1}
    if refresh:
        oauth["refreshToken"] = "SECRET-REFRESH"
    import time
    oauth["expiresAt"] = int(time.time() * 1000) + expires_in_ms
    token_store.CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    token_store.CREDENTIALS.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")


def test_cli_token_status_fresh_never_prints_the_token(capsys):
    _write_creds(3600_000)
    assert cli.main(["--token-status"]) == 0
    out = capsys.readouterr().out
    assert "fresh" in out and "in " in out and "possible" in out
    assert "SECRET" not in out


def test_cli_token_status_expired(capsys):
    _write_creds(-3600_000, refresh=None)
    assert cli.main(["--token-status"]) == 0
    out = capsys.readouterr().out
    assert "EXPIRED" in out and "ago" in out and "NOT possible" in out


def test_cli_token_status_without_expiry(capsys):
    token_store.CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    token_store.CREDENTIALS.write_text(json.dumps({"claudeAiOauth": {"accessToken": "x"}}), encoding="utf-8")
    assert cli.main(["--token-status"]) == 0
    assert "not recorded" in capsys.readouterr().out


def test_cli_token_status_without_credentials(capsys):
    assert cli.main(["--token-status"]) == 1
    assert "could not read" in capsys.readouterr().err

def test_cli_prints_the_resolved_target_exactly(monkeypatch, capsys):
    _patch_resolve(monkeypatch)
    assert cli.main(["--name", "Alpha", "--compact", "--dry-run"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "target   : 'Alpha' pid=1 status=idle",
        "sessionId: sess-a",
        "host     : local_a",
        "bridge   : bridge_a",
        "text     : '/compact'",
        "dry-run  : nothing sent",
    ]


def test_cli_request_dry_run_says_so_exactly(monkeypatch, capsys):
    _patch_resolve(monkeypatch)
    assert cli.main(["--self", "--request", "--dry-run"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "dry-run  : request not recorded"


@pytest.mark.parametrize("refreshed,line", [(True, "token    : refreshed first"), (False, "token    : used as stored")])
def test_cli_send_output_is_exact_and_bounded(monkeypatch, capsys, refreshed, line):
    _patch_resolve(monkeypatch)
    monkeypatch.setattr(token_store, "get_access_token", lambda **k: token_store.AccessToken("tok", refreshed))
    monkeypatch.setattr(bridge_client, "send_event", lambda *a, **k: (200, "x" * 1000))
    assert cli.main(["--self", "--compact"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2:] == [line, "HTTP 200: " + "x" * 600]


@pytest.mark.parametrize("argv,message", [
    (["--self", "--name", "A", "--compact", "--dry-run"], "--self cannot be combined with an explicit selector"),
    (["--compact"], "choose a target: --self (or an explicit selector with --dry-run)"),
    (["--name", "A", "--compact"], "explicit selectors are inspection-only: add --dry-run, or use --self"),
])
def test_cli_usage_errors_say_why(capsys, argv, message):
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert capsys.readouterr().err.rstrip().endswith("error: " + message)


@pytest.mark.parametrize("status,lines", [
    ({"fresh": True, "expires_in_seconds": 0, "can_refresh": True},
     ["token    : fresh", "expiry   : in 0s", "refresh  : possible"]),
    ({"fresh": False, "expires_in_seconds": -5, "can_refresh": False},
     ["token    : EXPIRED - a send would refresh it first", "expiry   : 5s ago",
      "refresh  : NOT possible (no refresh token stored)"]),
    ({"fresh": True, "expires_in_seconds": None, "can_refresh": True},
     ["token    : fresh", "expiry   : not recorded", "refresh  : possible"]),
])
def test_cli_token_status_lines_are_exact(monkeypatch, capsys, status, lines):
    monkeypatch.setattr(token_store, "token_status", lambda: dict(status))
    assert cli.main(["--token-status"]) == 0
    assert capsys.readouterr().out.splitlines() == lines
