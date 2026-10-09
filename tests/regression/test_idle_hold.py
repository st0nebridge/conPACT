"""
Regression test for CU-20260920-022 (an agent can hold its own early toast).

A long run is idle without being finished: a test run waits 5 to 35 minutes on
a build or a test suite, ends its turn, and comes back. The early toast is wrong
there - the session is not abandoned - but the one before the prompt cache
expires is still worth having, because the context really is about to go cold.

The contract, end to end through the real modules:

  1. The MCP tool holds only this session's *early* toast, for a time it names.
     It never sends anything and never compacts.
  2. The toast before the cache expires still comes while a hold is in force.
  3. A hold survives the session being used again - unlike "Silence 24 h", which
     is for a session the user is done with. A run takes many turns.
  4. It runs out by itself, and can be released early with 0 minutes.
  5. It wins over auto-compact at the early stage - the agent saying "I am coming
     back" outranks "compact this session when it goes idle" - and that session
     is then compacted before the cache expires instead, because by then the
     context really is about to go cold.
"""
import datetime
import functools
import json

import pytest

from conpact import compaction, idle_arming, idle_state, idle_watch, mcp_tools, session_registry, settings, \
    token_store

T0 = 1_800_000_000.0
TTL = 3600
EARLY_AT = T0 + 300
EXPIRY_AT = T0 + TTL - 300


@pytest.fixture(autouse=True)
def _one_clock(monkeypatch):
    """The tool stamps the hold with the real clock and the watcher reads its own.
    In a session both are the same clock; here the test's has to be both."""
    monkeypatch.setattr(idle_watch.time, "time", lambda: T0 + 1)
    monkeypatch.setattr(mcp_tools.time, "time", lambda: T0 + 1)


class Clock:
    def __init__(self, t=T0 + 1):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _session(sid="sess-a", pid=4242, status="idle", changed=T0 + 1):
    session_registry.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (session_registry.SESSIONS_DIR / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": sid, "bridgeSessionId": f"bridge-{sid}", "name": "Anchor",
        "status": status, "statusUpdatedAt": int(changed * 1000)}), encoding="utf-8")


def _transcript(tmp_path, last_call=T0):
    stamp = datetime.datetime.fromtimestamp(last_call, datetime.timezone.utc).isoformat()
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "assistant", "isSidechain": False, "timestamp": stamp, "message": {
        "model": "claude-opus-5", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 200_000,
            "output_tokens": 0, "cache_creation": {"ephemeral_1h_input_tokens": 10}}}}) + "\n", encoding="utf-8")
    return str(path)


def _arm(tmp_path, now=T0 + 1, last_call=T0):
    started = []
    status = idle_arming.arm({"session_id": "sess-a", "transcript_path": _transcript(tmp_path, last_call)},
                             environ={}, clock=lambda: now, spawner=lambda argv, env: started.append(argv) or 99)
    return status, started


def _deps(clock, sent, present):
    token = token_store.AccessToken("tok", False)
    compactor = functools.partial(compaction.compact_record, token_getter=lambda: token,
                                  sender=lambda bridge, text, tok: sent.append((bridge, text)) or (200, {}))
    return idle_watch.Deps(clock=clock, sleep=clock.sleep, environ={}, sessions_dir=None,
                           compactor=compactor, present=present, opener=None)


def _watch(clock, sent, present):
    generation = idle_state.read_marker("sess-a")["generation"]
    return idle_watch.watch("sess-a", generation, _deps(clock, sent, present))


def _ctx(tmp_path):
    return mcp_tools.Context(environ={"CLAUDE_CODE_SESSION_ID": "sess-a"}, ppid=4242,
                             sessions_dir=session_registry.SESSIONS_DIR, requests_dir=tmp_path / "requests",
                             projects_dir=tmp_path / "projects")


def _hold(tmp_path, **arguments):
    return mcp_tools.call_tool(mcp_tools.HOLD, arguments, _ctx(tmp_path))


# --- 1 and 2: the early toast is held, the expiry one still comes ------------

def test_1_the_tool_holds_this_sessions_early_toast_and_sends_nothing(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    result = _hold(tmp_path, minutes=30)
    assert result["isError"] is False
    assert result["structuredContent"]["held"] is True
    assert result["structuredContent"]["session_id"] == "sess-a"
    assert idle_state.read_hold("sess-a") is not None


def test_2_the_toast_before_the_cache_expires_still_comes(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    _hold(tmp_path, minutes=30)
    _arm(tmp_path)
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, lambda c: shown.append(c.model()["stage"]) or c.act("compact"))
    assert shown == ["expiry"]                      # the early one was held, not shown
    assert outcome["earlier"] == [{"stage": "early", "event": "held"}]
    assert sent == [("bridge-sess-a", "/compact " + compaction.PROVENANCE_CLAUSE)]


# --- 3: it survives the session being used again -----------------------------

def test_3_a_hold_is_not_spent_by_using_the_session(tmp_path):
    """The mute ends when you come back; a hold is *for* a run that keeps coming back."""
    settings.save({"idle_seconds": 300})
    _session()
    _hold(tmp_path, minutes=30)
    for turn in range(3):                            # three turns of a long run
        _arm(tmp_path, now=T0 + 1 + turn, last_call=T0 + turn)
        assert idle_state.read_hold("sess-a") is not None
    clock, sent, shown = Clock(), [], []
    _watch(clock, sent, lambda c: shown.append(c.model()["stage"]) or c.act("dismiss"))
    assert shown == ["expiry"]


# --- 4: it ends by itself, and can be released -------------------------------

def test_4_a_spent_hold_lets_the_early_toast_through_again(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    idle_state.set_hold("sess-a", until=EARLY_AT - 1)   # runs out before the early stage
    _arm(tmp_path)
    clock, sent, shown = Clock(), [], []
    _watch(clock, sent, lambda c: shown.append(c.model()["stage"]) or c.act("dismiss"))
    assert shown == ["early", "expiry"]
    assert idle_state.read_hold("sess-a") is None      # and the spent hold is tidied away


def test_4_zero_minutes_releases_it(tmp_path):
    _session()
    _hold(tmp_path, minutes=30)
    result = _hold(tmp_path, minutes=0)
    assert result["structuredContent"]["held"] is False
    assert idle_state.read_hold("sess-a") is None


# --- 5: a hold outranks auto-compact at the early stage ----------------------

def test_5_a_held_auto_compaction_happens_before_the_cache_expires_instead(tmp_path):
    settings.save({"idle_seconds": 300})
    _session()
    idle_state.set_auto("sess-a", "early")            # "always compact this session when idle"
    _hold(tmp_path, minutes=30)
    _arm(tmp_path)
    clock, sent, shown = Clock(), [], []
    outcome = _watch(clock, sent, shown.append)
    assert [c.model()["stage"] for c in shown] == ["expiry"]     # told, not asked
    assert sent == [("bridge-sess-a", "/compact " + compaction.PROVENANCE_CLAUSE)]              # not at the early stage: at the last one
    assert outcome["event"] == "auto_compacted"
    assert outcome["earlier"] == [{"stage": "early", "event": "held"}]
