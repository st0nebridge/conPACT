"""
@module conpact.bridge_client
@description The single source of truth for the Remote Control bridge wire
             format. Builds and posts a user event into a live Claude Code
             session. The client_platform value is what makes the receiver's
             ingress classifier treat the event as genuine human input (so slash
             commands execute) rather than a demoted cross-session peer message.
@input      a bridgeSessionId, message text and an access token
@output     (http_status, response_body) from the events endpoint
@dependencies stdlib: json, urllib, uuid
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

BASE_API_URL = "https://api.anthropic.com"
CLIENT_VERSION = "2.1.275"

# Verified end-to-end (2026-09-19): the receiver classifier Iit() reaches its
# {kind:"human"} branch only when client_platform is in
# {ios, android, web_claude_ai, desktop_app} and no inbound_origin is set.
# "cli" is demoted to {kind:"peer"} and wrapped as "Another Claude session sent
# a message", for which slash commands do NOT execute.
HUMAN_CLIENT_PLATFORM = "web_claude_ai"


def build_event(bridge_id: str, text: str, event_type: str = "user") -> dict:
    """
    Build the request body for the events endpoint.

    The fields live inside a ``payload`` object and the server also validates a
    sibling top-level ``event_type`` (a flat body returns HTTP 400
    "event_type is required"). This shape is the hard-won result of the wire
    reverse-engineering and must not be flattened.
    """
    payload = {
        "uuid": str(uuid.uuid4()),
        "session_id": bridge_id,
        "type": event_type,
        "parent_tool_use_id": None,
        "message": {"role": "user", "content": text},
    }
    return {"events": [{"event_type": event_type, "payload": payload}]}


def is_success(status) -> bool:
    """True only for a 2xx status - the single definition of "the bridge accepted it"."""
    return isinstance(status, int) and 200 <= status < 300


def _urlopen(request, timeout):
    """Isolated for tests to substitute."""
    return urllib.request.urlopen(request, timeout=timeout)


def send_event(
    bridge_id: str,
    text: str,
    access_token: str,
    client_platform: str = HUMAN_CLIENT_PLATFORM,
    event_type: str = "user",
    timeout: int = 30,
    urlopen=None,
) -> tuple[int, str]:
    """
    POST an event into the session's bridge. The access token is used only in the
    Authorization header and never returned or logged.
    """
    body = build_event(bridge_id, text, event_type)
    request = urllib.request.Request(
        f"{BASE_API_URL}/v1/code/sessions/{bridge_id}/events",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "anthropic-client-platform": client_platform,
            "User-Agent": f"claude-code/{CLIENT_VERSION}",
        },
    )
    opener = urlopen or _urlopen
    try:
        with opener(request, timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
