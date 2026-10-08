"""Tests for conpact.token_store: freshness, on-expiry refresh, atomic write-back."""
import json
import time

import pytest

from conpact import token_store as ts


def _creds(**oauth_over):
    oauth = dict(
        accessToken="acc-old", refreshToken="ref-old",
        expiresAt=int(time.time() * 1000) + 3600_000,
        scopes=["user:inference", "user:profile"],
    )
    oauth.update(oauth_over)
    return {"claudeAiOauth": oauth, "otherKey": "preserved"}


def _write(tmp_path, creds):
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps(creds), encoding="utf-8")
    return p


def test_token_is_fresh_future_expiry():
    assert ts.token_is_fresh(_creds()["claudeAiOauth"]) is True


def test_token_is_fresh_expired():
    oauth = _creds(expiresAt=int(time.time() * 1000) - 1000)["claudeAiOauth"]
    assert ts.token_is_fresh(oauth) is False


def test_token_is_fresh_no_expiry_defaults_true():
    oauth = {"accessToken": "x"}
    assert ts.token_is_fresh(oauth) is True


def test_get_valid_token_uses_fresh_without_refresh(tmp_path):
    p = _write(tmp_path, _creds())

    def boom(_body):
        raise AssertionError("refresh must not be called for a fresh token")

    assert ts.get_valid_access_token(path=p, post=boom) == "acc-old"


def test_refresh_rotates_and_recomputes_expiry():
    oauth = _creds(expiresAt=1)["claudeAiOauth"]
    captured = {}

    def fake_post(body):
        captured.update(body)
        return {"access_token": "acc-new", "refresh_token": "ref-new",
                "expires_in": 100, "scope": "user:inference"}

    out = ts.refresh(oauth, post=fake_post, now_ms=10_000)
    assert captured["grant_type"] == "refresh_token"
    assert captured["refresh_token"] == "ref-old"
    assert captured["client_id"] == ts.CLIENT_ID
    assert out["accessToken"] == "acc-new"
    assert out["refreshToken"] == "ref-new"
    assert out["expiresAt"] == 10_000 + 100 * 1000
    assert out["scopes"] == ["user:inference"]


def test_get_valid_token_refreshes_and_persists(tmp_path):
    p = _write(tmp_path, _creds(expiresAt=int(time.time() * 1000) - 1000))

    def fake_post(_body):
        return {"access_token": "acc-new", "refresh_token": "ref-new", "expires_in": 3600}

    token = ts.get_valid_access_token(path=p, post=fake_post)
    assert token == "acc-new"
    # Written back, rotated, and unrelated keys preserved.
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["claudeAiOauth"]["accessToken"] == "acc-new"
    assert on_disk["claudeAiOauth"]["refreshToken"] == "ref-new"
    assert on_disk["otherKey"] == "preserved"


def test_get_valid_token_expired_no_refresh_allowed(tmp_path):
    p = _write(tmp_path, _creds(expiresAt=int(time.time() * 1000) - 1000))
    # allow_refresh False returns the (stale) token rather than rotating.
    assert ts.get_valid_access_token(path=p, allow_refresh=False) == "acc-old"


def test_refresh_without_refresh_token_errors():
    with pytest.raises(ts.TokenError):
        ts.refresh({"accessToken": "x"}, post=lambda b: {})


def test_read_credentials_missing_file(tmp_path):
    with pytest.raises(ts.TokenError):
        ts.read_credentials(tmp_path / "nope.json")


# The real _post_token, captured before the isolation fixture swaps it out.
_REAL_POST_TOKEN = ts._post_token


def test_get_access_token_reports_no_refresh_when_fresh(tmp_path):
    p = _write(tmp_path, _creds())
    token = ts.get_access_token(path=p)
    assert token == ts.AccessToken("acc-old", False)


def test_get_access_token_reports_refresh(tmp_path):
    p = _write(tmp_path, _creds(expiresAt=int(time.time() * 1000) - 1000))
    token = ts.get_access_token(path=p, post=lambda b: {"access_token": "acc-new", "expires_in": 60})
    assert token == ts.AccessToken("acc-new", True)


def test_access_token_repr_is_redacted():
    assert "acc-secret" not in repr(ts.AccessToken("acc-secret", False))


def test_expired_without_token_and_refresh_disabled_errors(tmp_path):
    p = _write(tmp_path, _creds(accessToken="", expiresAt=int(time.time() * 1000) - 1000))
    with pytest.raises(ts.TokenError):
        ts.get_access_token(path=p, allow_refresh=False)


def test_default_path_is_the_credentials_constant(monkeypatch):
    monkeypatch.setattr(ts.keychain, "read_credentials", lambda: None)
    ts.CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    ts.CREDENTIALS.write_text(json.dumps(_creds()), encoding="utf-8")
    assert ts.get_valid_access_token() == "acc-old"


def test_token_is_fresh_respects_margin():
    now = 1_000_000
    assert ts.token_is_fresh({"accessToken": "x", "expiresAt": now + 61_000}, now_ms=now) is True
    assert ts.token_is_fresh({"accessToken": "x", "expiresAt": now + 60_000}, now_ms=now) is False
    assert ts.token_is_fresh({"expiresAt": now + 10**9}, now_ms=now) is False


def test_token_status_reports_without_the_token(tmp_path):
    now = 5_000_000
    p = _write(tmp_path, _creds(expiresAt=now + 90_500))
    status = ts.token_status(path=p, now_ms=now)
    assert status == {"fresh": True, "expires_in_seconds": 90, "can_refresh": True, "source": "file"}
    assert "acc-old" not in json.dumps(status)


def test_token_status_expired_and_unrefreshable(tmp_path):
    now = 5_000_000
    p = _write(tmp_path, _creds(expiresAt=now - 30_000, refreshToken=None))
    assert ts.token_status(path=p, now_ms=now) == {"fresh": False, "expires_in_seconds": -30, "can_refresh": False,
                                                    "source": "file"}


def test_read_credentials_rejects_wrong_shape(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"other": 1}), encoding="utf-8")
    with pytest.raises(ts.TokenError):
        ts.read_credentials(p)


def test_refresh_response_without_access_token_errors():
    with pytest.raises(ts.TokenError):
        ts.refresh({"refreshToken": "r"}, post=lambda b: {"refresh_token": "r2"})


def test_refresh_keeps_fields_the_response_omits():
    oauth = _creds()["claudeAiOauth"]
    out = ts.refresh(oauth, post=lambda b: {"access_token": "acc-new"}, now_ms=1)
    assert out["accessToken"] == "acc-new"
    assert out["refreshToken"] == "ref-old"
    assert out["scopes"] == ["user:inference", "user:profile"]
    assert out["expiresAt"] == oauth["expiresAt"]
    assert oauth["accessToken"] == "acc-old"  # input not mutated


def test_refresh_uses_default_scopes_when_none_stored():
    captured = {}
    ts.refresh({"refreshToken": "r"}, post=lambda b: captured.update(b) or {"access_token": "a"})
    assert captured["scope"] == " ".join(ts.DEFAULT_SCOPES)


def test_write_failure_cleans_temp_and_raises_token_error(tmp_path, monkeypatch):
    p = _write(tmp_path, _creds())

    def refuse(src, dst):
        raise PermissionError("locked by another process")

    monkeypatch.setattr(ts.os, "replace", refuse)
    with pytest.raises(ts.TokenError, match=r"^refreshed credentials could not be saved; the stored refresh "
                                            r"token may now be stale and a fresh login may be needed$"):
        ts.write_credentials({"claudeAiOauth": {"accessToken": "new"}}, p)
    assert not (tmp_path / ".credentials.json.tmp").exists()
    assert json.loads(p.read_text(encoding="utf-8"))["claudeAiOauth"]["accessToken"] == "acc-old"


def test_write_failure_tolerates_missing_temp(tmp_path, monkeypatch):
    p = tmp_path / "missing-dir" / ".credentials.json"
    with pytest.raises(ts.TokenError):
        ts.write_credentials({"claudeAiOauth": {}}, p)


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body.encode("utf-8")


def test_post_token_posts_json_to_the_token_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(url=request.full_url, method=request.get_method(),
                        body=json.loads(request.data.decode("utf-8")), timeout=timeout)
        return _Resp(200, '{"access_token":"a"}')

    monkeypatch.setattr(ts.urllib.request, "urlopen", fake_urlopen)
    assert _REAL_POST_TOKEN({"grant_type": "refresh_token"}) == {"access_token": "a"}
    assert captured == {"url": ts.TOKEN_URL, "method": "POST",
                        "body": {"grant_type": "refresh_token"}, "timeout": 30}


def test_post_token_non_200_success_is_an_error(monkeypatch):
    monkeypatch.setattr(ts.urllib.request, "urlopen", lambda r, timeout: _Resp(204, ""))
    with pytest.raises(ts.TokenError, match="HTTP 204"):
        _REAL_POST_TOKEN({})


def test_post_token_http_error_becomes_token_error(monkeypatch):
    import io
    import urllib.error

    def refused(request, timeout):
        raise urllib.error.HTTPError(ts.TOKEN_URL, 400, "Bad Request", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(ts.urllib.request, "urlopen", refused)
    with pytest.raises(ts.TokenError, match="HTTP 400"):
        _REAL_POST_TOKEN({})


@pytest.mark.real_paths
def test_credentials_path_is_the_clis():
    import os
    import pathlib
    assert ts.CREDENTIALS == pathlib.Path(os.path.expanduser("~")) / ".claude" / ".credentials.json"


def test_refresh_endpoint_client_and_scopes_are_the_clis():
    # Verified present in the bundled CLI 2.1.275 on 2026-09-19 (D-20260919-007).
    assert ts.TOKEN_URL == "https://platform.claude.com/v1/oauth/token"
    assert ts.CLIENT_ID == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    assert ts.DEFAULT_SCOPES == ["user:inference", "user:profile"]


def test_token_is_fresh_one_millisecond_past_the_margin():
    now = 1_000_000
    assert ts.token_is_fresh({"accessToken": "x", "expiresAt": now + 60_001}, now_ms=now) is True


def test_token_status_whole_seconds(tmp_path):
    p = _write(tmp_path, _creds(expiresAt=5_000_000 + 3_600_000))
    assert ts.token_status(path=p, now_ms=5_000_000)["expires_in_seconds"] == 3600


def test_refresh_sends_the_stored_scopes():
    captured = {}
    ts.refresh({"refreshToken": "r", "scopes": ["a:b", "c:d"]},
               post=lambda b: captured.update(b) or {"access_token": "x"})
    assert captured["scope"] == "a:b c:d"


def test_refresh_computes_expiry_from_the_clock():
    before = int(time.time() * 1000)
    out = ts.refresh({"refreshToken": "r"}, post=lambda b: {"access_token": "x", "expires_in": 100})
    after = int(time.time() * 1000)
    assert before + 100_000 <= out["expiresAt"] <= after + 100_000


def test_expired_without_refresh_reports_not_refreshed(tmp_path):
    p = _write(tmp_path, _creds(expiresAt=int(time.time() * 1000) - 1000))
    assert ts.get_access_token(path=p, allow_refresh=False) == ts.AccessToken("acc-old", False)


def test_token_error_messages_are_exact(tmp_path):
    with pytest.raises(ts.TokenError, match=r"^could not read the Claude credentials file$"):
        ts.read_credentials(tmp_path / "absent.json")
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    with pytest.raises(ts.TokenError, match=r"^credentials file has no claudeAiOauth object$"):
        ts.read_credentials(p)
    with pytest.raises(ts.TokenError, match=r"^no refreshToken stored; cannot refresh$"):
        ts.refresh({"accessToken": "x"}, post=lambda b: {"access_token": "never"})
    with pytest.raises(ts.TokenError, match=r"^token refresh response had no access_token$"):
        ts.refresh({"refreshToken": "r"}, post=lambda b: {})
    expired = _write(tmp_path, _creds(accessToken="", expiresAt=1))
    with pytest.raises(ts.TokenError, match=r"^access token is expired and refresh is disabled$"):
        ts.get_access_token(path=expired, allow_refresh=False)


def test_post_token_sends_json(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update({k.lower(): v for k, v in request.header_items()})
        return _Resp(200, "{}")

    monkeypatch.setattr(ts.urllib.request, "urlopen", fake_urlopen)
    _REAL_POST_TOKEN({})
    # The headers of a refresh that works (a Node client's, sent with fetch's
    # defaults). Python's default
    # user agent got HTTP 403 and an invented claude-code/2.1.275 one got HTTP 429
    # when a refresh was first needed live (2026-09-19).
    assert captured == {"content-type": "application/json", "accept": "*/*", "accept-language": "*",
                        "sec-fetch-mode": "cors", "user-agent": "node"}


@pytest.mark.parametrize("code, body, message", [
    (403, b"error code: 1010", "token refresh returned HTTP 403: error code: 1010"),
    (400, b'{"error": "invalid_grant", "error_description": "revoked"}',
     "token refresh returned HTTP 400: invalid_grant: revoked"),
    (400, b'{"error": "invalid_grant"}', "token refresh returned HTTP 400: invalid_grant"),
    # The API's own error shape, which reached the toast as a raw dict (2026-09-19).
    (429, b'{"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited. Please try again later."}}',
     "token refresh returned HTTP 429: rate_limit_error: Rate limited. Please try again later."),
    (429, b'{"error": {"message": "slow down"}}', "token refresh returned HTTP 429: slow down"),
    (429, b'{"error": {}}', "token refresh returned HTTP 429"),
    (403, b"<!DOCTYPE html><html><body>Just a moment...</body></html>",
     "token refresh returned HTTP 403: an HTML page (a web firewall?)"),
    (500, b"  line one\n\tline two  ", "token refresh returned HTTP 500: line one line two"),
    (502, b"x" * 300, "token refresh returned HTTP 502: " + "x" * 119 + "…"),
    (400, b"{}", "token refresh returned HTTP 400"),
    (400, b"[1]", "token refresh returned HTTP 400: [1]"),
    (400, b"", "token refresh returned HTTP 400"),
])
def test_post_token_http_error_says_briefly_why(monkeypatch, code, body, message):
    import io
    import urllib.error

    def refused(request, timeout):
        raise urllib.error.HTTPError(ts.TOKEN_URL, code, "x", {}, io.BytesIO(body))

    monkeypatch.setattr(ts.urllib.request, "urlopen", refused)
    with pytest.raises(ts.TokenError) as info:
        _REAL_POST_TOKEN({})
    assert str(info.value) == message
