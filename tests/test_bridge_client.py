"""Tests for conpact.bridge_client: wire envelope shape and header wiring."""
import json

from conpact import bridge_client as bc


def test_build_event_has_top_level_event_type_and_payload():
    body = bc.build_event("bridge_x", "hello")
    assert list(body.keys()) == ["events"]
    event = body["events"][0]
    # The HTTP 400 fix: event_type lives at the event top level AND in payload.type.
    assert event["event_type"] == "user"
    payload = event["payload"]
    assert payload["type"] == "user"
    assert payload["session_id"] == "bridge_x"
    assert payload["parent_tool_use_id"] is None
    assert payload["message"] == {"role": "user", "content": "hello"}
    assert payload["uuid"]  # a fresh uuid is present


def test_build_event_unique_uuid_per_call():
    a = bc.build_event("b", "x")["events"][0]["payload"]["uuid"]
    b = bc.build_event("b", "x")["events"][0]["payload"]["uuid"]
    assert a != b


class _FakeResp:
    status = 200

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body.encode("utf-8")


def test_send_event_sets_human_platform_and_auth_header():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["data"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp('{"ok":true}')

    status, body = bc.send_event("bridge_x", "/compact", "tok-123", urlopen=fake_urlopen)
    assert status == 200
    assert captured["url"].endswith("/v1/code/sessions/bridge_x/events")
    # The decisive header: a human client-platform, not "cli".
    assert captured["headers"]["anthropic-client-platform"] == bc.HUMAN_CLIENT_PLATFORM
    assert captured["headers"]["authorization"] == "Bearer tok-123"
    assert captured["data"]["events"][0]["payload"]["message"]["content"] == "/compact"


def test_default_platform_is_a_human_value():
    assert bc.HUMAN_CLIENT_PLATFORM in {"ios", "android", "web_claude_ai", "desktop_app"}


# The real _urlopen, captured before the isolation fixture swaps it out.
_REAL_URLOPEN = bc._urlopen


def test_is_success_is_2xx_only():
    assert bc.is_success(200) and bc.is_success(204) and bc.is_success(299)
    assert not bc.is_success(199) and not bc.is_success(300) and not bc.is_success(401)
    assert not bc.is_success(None) and not bc.is_success("200")


def test_send_event_returns_http_error_status_and_body():
    import io
    import urllib.error

    def refused(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"expired"}'))

    status, body = bc.send_event("bridge_x", "/compact", "tok", urlopen=refused)
    assert (status, body) == (401, '{"error":"expired"}')


def test_send_event_uses_the_module_opener_by_default(monkeypatch):
    monkeypatch.setattr(bc, "_urlopen", lambda request, timeout: _FakeResp("{}"))
    assert bc.send_event("bridge_x", "/compact", "tok") == (200, "{}")


def test_urlopen_delegates_to_urllib(monkeypatch):
    seen = {}
    monkeypatch.setattr(bc.urllib.request, "urlopen", lambda request, timeout: seen.update(t=timeout) or "resp")
    assert _REAL_URLOPEN("req", 7) == "resp"
    assert seen == {"t": 7}


def test_send_event_wire_contract():
    """The exact request the live bridge accepted on 2026-09-19 (CU-20260919-001)."""
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(url=request.full_url, method=request.get_method(), timeout=timeout,
                        headers={k.lower(): v for k, v in request.header_items()},
                        data=json.loads(request.data.decode("utf-8")))
        return _FakeResp("{}")

    bc.send_event("bridge_x", "/compact", "tok-123", urlopen=fake_urlopen)
    assert captured["url"] == "https://api.anthropic.com/v1/code/sessions/bridge_x/events"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 30
    assert captured["headers"] == {
        "authorization": "Bearer tok-123",
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-client-platform": "web_claude_ai",
        "user-agent": "claude-code/2.1.275",
    }
    event = captured["data"]["events"][0]
    assert (event["event_type"], event["payload"]["type"]) == ("user", "user")


def test_send_event_tolerates_undecodable_bodies():
    import io
    import urllib.error

    class _Undecodable(_FakeResp):
        def read(self):
            return b"ok \xff"

    assert bc.send_event("b", "/compact", "t", urlopen=lambda r, t: _Undecodable("")) == (200, "ok �")

    def refused(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 500, "x", {}, io.BytesIO(b"bad \xff"))

    assert bc.send_event("b", "/compact", "t", urlopen=refused) == (500, "bad �")
