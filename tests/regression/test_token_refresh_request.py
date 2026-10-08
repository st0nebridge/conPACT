"""
Regression test for CU-20260919-012 and CU-20260919-013 (the token refresh request).

Seen 2026-09-19: the stored access token had expired (the Desktop app keeps its
own and never rewrites the credentials file), so the idle toast's send needed
its first live refresh. With Python's default user agent the token endpoint
answered HTTP 403; with the CLI's ("claude-code/2.1.275") it answered HTTP 429
rate_limit_error. With the headers a Node client sends by default (fetch's
defaults) it succeeded (17:23Z). The contract:

  1. The refresh request carries exactly those headers, and the API's nested
     error shape is read as "type: message".
  2. A refusal says why in a few words (the server's error, or that an HTML page
     came back), so the next failure explains itself in the toast and the log.
"""
import io
import urllib.error

import pytest

from conpact import bridge_client, token_store

# The real _post_token, captured at import, before the isolation fixture swaps it out.
_REAL_POST_TOKEN = token_store._post_token


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def test_1_the_refresh_request_carries_the_working_refreshs_headers(monkeypatch):
    headers = {}

    def fake_urlopen(request, timeout):
        headers.update({k.lower(): v for k, v in request.header_items()})
        return _Resp()
    monkeypatch.setattr(token_store.urllib.request, "urlopen", fake_urlopen)
    _REAL_POST_TOKEN({})
    assert headers == {"content-type": "application/json", "accept": "*/*", "accept-language": "*",
                       "sec-fetch-mode": "cors", "user-agent": "node"}
    assert headers["user-agent"] != f"claude-code/{bridge_client.CLIENT_VERSION}"  # got HTTP 429


def test_1_the_api_error_shape_is_readable(monkeypatch):
    body = b'{"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited. Please try again later."}}'

    def refused(request, timeout):
        raise urllib.error.HTTPError(token_store.TOKEN_URL, 429, "Too Many Requests", {}, io.BytesIO(body))
    monkeypatch.setattr(token_store.urllib.request, "urlopen", refused)
    with pytest.raises(token_store.TokenError,
                       match=r"^token refresh returned HTTP 429: rate_limit_error: Rate limited\. Please try again later\.$"):
        _REAL_POST_TOKEN({})


def test_2_a_refusal_says_why(monkeypatch):
    def refused(request, timeout):
        raise urllib.error.HTTPError(token_store.TOKEN_URL, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))
    monkeypatch.setattr(token_store.urllib.request, "urlopen", refused)
    with pytest.raises(token_store.TokenError, match=r"^token refresh returned HTTP 403: error code: 1010$"):
        _REAL_POST_TOKEN({})
