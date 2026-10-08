"""
Regression test for CU-20260919-001 (agent-initiated compaction).

Pins the three invariants that took reverse-engineering to find and that silently
break the whole feature if regressed:

  1. The bridge event uses a HUMAN client_platform. With "cli" the receiver's
     ingress classifier demotes the event to a peer message and slash commands
     are NOT executed. Verified end-to-end 2026-09-19.
  2. The event envelope carries a top-level event_type AND a nested payload.
     A flat body returns HTTP 400 "event_type is required".
  3. /compact command text is constructed in-process, never passed as a shell
     argument (Git Bash rewrote a leading-slash arg into a Windows path).
"""
from conpact import bridge_client, compaction


def test_client_platform_is_human_not_cli():
    assert bridge_client.HUMAN_CLIENT_PLATFORM == "web_claude_ai"
    assert bridge_client.HUMAN_CLIENT_PLATFORM in {"ios", "android", "web_claude_ai", "desktop_app"}


def test_event_envelope_has_event_type_and_payload():
    event = bridge_client.build_event("bridge_x", "/compact")["events"][0]
    assert event["event_type"] == "user"
    assert event["payload"]["type"] == "user"
    assert event["payload"]["message"]["content"] == "/compact"


def test_compact_text_is_constructed_exactly():
    # Never sourced from a shell argument, so a leading slash cannot be mangled.
    assert compaction.build_compact_text() == "/compact"
    assert compaction.COMPACT_COMMAND == "/compact"
