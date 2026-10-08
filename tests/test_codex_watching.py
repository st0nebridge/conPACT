"""
@module tests.test_codex_watching
@description What the idle watcher does differently for a ChatGPT Desktop
             session: how "used since we armed" is read when there is no runtime
             record to read it from, why there is never a Remote Control toast
             on this side, and that a compaction goes through codex_compact and
             reports in the watcher's own shape.
@input      conpact.codex_watching, against fabricated threads
@output     assertions on resumed / reachable / ensure_idle / send
@dependencies conpact.codex_watching, conpact.codex_compact, conpact.codex_meter,
              conpact.codex_threads, conpact.codex_window, conpact.idle_watch
"""
import pytest

from conpact import (codex_compact, codex_meter, codex_threads, codex_watching,
                     codex_window, idle_watch, platforms)

NOW = 1_790_000_000.0
THREAD_ID = "01a00000-0000-7000-9000-000000000002"
MARKER = {"platform": "codex", "session_id": THREAD_ID, "last_call": NOW - 600,
          "context_tokens": 450_000, "expires_at": NOW + 3000}


class Deps:
    def __init__(self, clock=lambda: NOW):
        self.clock, self.environ, self.sessions_dir = clock, {}, None
        self.platform = codex_watching.platform()

    def side(self):
        return self.platform


@pytest.fixture
def idle(monkeypatch):
    """A thread that exists, is not archived, is between turns and has not moved."""
    monkeypatch.setattr(codex_threads, "thread",
                        lambda tid, env=None: {"id": tid, "archived": False,
                                               "rollout_path": "/fake/rollout.jsonl"})
    monkeypatch.setattr(codex_meter, "turn_state",
                        lambda path, max_records=2000: codex_meter.IDLE)
    monkeypatch.setattr(codex_window, "last_call",
                        lambda path, max_records=2000: MARKER["last_call"])


class TestHasItBeenUsedSince:
    def test_an_untouched_session_has_not(self, idle):
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) is None

    def test_a_session_mid_turn_has(self, idle, monkeypatch):
        monkeypatch.setattr(codex_meter, "turn_state", lambda path, max_records=2000: "busy")
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) == "resumed"

    def test_a_later_call_than_the_one_we_armed_against_has(self, idle, monkeypatch):
        monkeypatch.setattr(codex_window, "last_call",
                            lambda path, max_records=2000: MARKER["last_call"] + 300)
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) == "resumed"

    def test_the_same_call_to_the_second_has_not(self, idle, monkeypatch):
        """Timestamps are floats; a re-read must not look like a new call."""
        monkeypatch.setattr(codex_window, "last_call",
                            lambda path, max_records=2000: MARKER["last_call"] + 0.2)
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) is None

    def test_a_session_that_is_gone_closes_the_watch(self, monkeypatch):
        monkeypatch.setattr(codex_threads, "thread", lambda tid, env=None: None)
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) == "closed"

    def test_an_archived_session_closes_the_watch(self, idle, monkeypatch):
        monkeypatch.setattr(codex_threads, "thread",
                            lambda tid, env=None: {"id": tid, "archived": True,
                                                   "rollout_path": "/fake/rollout.jsonl"})
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) == "archived"

    def test_a_rollout_that_says_nothing_is_not_taken_as_activity(self, idle, monkeypatch):
        monkeypatch.setattr(codex_window, "last_call", lambda path, max_records=2000: None)
        assert codex_watching.resumed(THREAD_ID, MARKER, Deps()) is None


class TestThereIsNoBridgeOnThisSide:
    def test_a_codex_session_is_always_reachable(self):
        """Remote Control is Claude's relay. A Codex session is compacted through
        the sidecar, so there is no switch to be off and the toast never asks."""
        assert codex_watching.reachable(THREAD_ID, Deps()) is True


class TestCompacting:
    def test_a_compaction_is_reported_as_the_watcher_expects(self, idle, monkeypatch):
        monkeypatch.setattr(codex_compact, "compact",
                            lambda tid, env=None: {"compacted": True, "reason": None})
        sent = codex_watching.send(THREAD_ID, MARKER, Deps())
        assert sent["outcome"]["event"] == "compacted"
        assert sent["state"]["state"] == "sent"

    def test_there_is_no_progress_tracker_because_there_is_no_stream(self, idle, monkeypatch):
        """A Claude compaction is followed by tailing the transcript; Codex's is
        one call, so the notice says what happened instead of following it."""
        monkeypatch.setattr(codex_compact, "compact", lambda tid, env=None: {"compacted": True})
        assert codex_watching.send(THREAD_ID, MARKER, Deps()).get("tracker") is None
        assert idle_watch.follow(None, Deps()) == {"state": "untracked"}

    def test_a_refusal_is_reported_with_its_reason(self, idle, monkeypatch):
        monkeypatch.setattr(codex_compact, "compact",
                            lambda tid, env=None: {"compacted": False, "reason": "busy",
                                                   "message": "another app holds it"})
        sent = codex_watching.send(THREAD_ID, MARKER, Deps())
        assert sent["outcome"]["event"] == "failed"
        assert "another app holds it" in sent["outcome"]["reason"]

    def test_a_session_used_while_we_waited_is_never_compacted(self, idle, monkeypatch):
        monkeypatch.setattr(codex_meter, "turn_state", lambda path, max_records=2000: "busy")
        monkeypatch.setattr(codex_compact, "compact",
                            lambda tid, env=None: pytest.fail("must not compact a busy session"))
        sent = codex_watching.send(THREAD_ID, MARKER, Deps())
        assert sent["outcome"]["event"] == "resumed"
        assert sent["state"]["state"] == "closed"

    def test_a_compaction_that_raises_is_reported_not_propagated(self, idle, monkeypatch):
        def explode(tid, env=None):
            raise OSError("the app-server went away")
        monkeypatch.setattr(codex_compact, "compact", explode)
        sent = codex_watching.send(THREAD_ID, MARKER, Deps())
        assert sent["outcome"]["event"] == "error"
        assert "OSError" in sent["outcome"]["reason"]


class TestTheWatcherPicksThisUp:
    def test_the_adapter_is_the_codex_one(self):
        assert codex_watching.platform().name == platforms.CODEX

    def test_a_codex_marker_selects_it(self):
        assert idle_watch.platform_for({"platform": "codex"}).name == platforms.CODEX

    @pytest.mark.parametrize("marker", [None, {}, {"platform": "claude"}, {"platform": None}])
    def test_anything_else_stays_on_the_claude_path(self, marker):
        assert idle_watch.platform_for(marker) is None

    def test_every_platform_answer_the_watcher_needs_is_provided(self):
        side = codex_watching.platform()
        for question in ("resumed", "reachable", "ensure_idle", "send"):
            assert callable(getattr(side, question)), question
