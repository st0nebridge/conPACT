"""
The idle toast reaches ChatGPT Desktop sessions, anchored.

Before CU-20260922-043 it did not, and nothing said so: `codex_compact` had no
caller anywhere in the package, so the compaction engine was live-verified and
unreachable at the same time. Every module in the idle path - idle_watch,
idle_arming, idle_state, toast_view, closure_hook - held zero references to
Codex. These tests are what stops that being true again.

The structural ones matter as much as the behavioural ones: "the sweep is
called from somewhere" and "codex_compact has a caller" are exactly the facts
that were quietly false.
"""
import pathlib

import pytest

from conpact import (cache_window, closure_hook, codex_arming, codex_compact,
                     codex_meter, codex_threads, codex_watching, codex_window,
                     idle_state, idle_watch, platforms)
from conpact import settings as user_settings

NOW = 1_790_000_000.0
THREAD_ID = "01a00000-0000-7000-9000-000000000002"
PACKAGE = pathlib.Path(idle_watch.__file__).parent


def source(name: str) -> str:
    return (PACKAGE / f"{name}.py").read_text(encoding="utf-8")


class TestTheEngineIsReachable:
    def test_codex_compact_has_a_caller_in_the_package(self):
        """It had none: compaction worked and nothing could ask for it."""
        callers = [p.name for p in PACKAGE.glob("*.py")
                   if p.name != "codex_compact.py" and "codex_compact" in
                   p.read_text(encoding="utf-8")]
        assert callers, "codex_compact is unreachable: nothing imports it"

    def test_the_sweep_is_called_from_the_stop_hook(self):
        """Codex has no turn end of its own (D-20260921-031), so if nothing
        calls the sweep, no Codex session is ever watched."""
        assert "codex_arming.run()" in source("closure_hook")

    def test_the_sweep_can_also_be_run_on_its_own(self):
        """A machine with only ChatGPT Desktop has no Stop hook at all."""
        assert callable(codex_arming.main)
        assert '__main__' in source("codex_arming")


class TestAnArmedSessionIsWatchedAndCompacted:
    @pytest.fixture
    def armed(self, monkeypatch):
        settings = dict(user_settings.defaults())
        settings["min_context_tokens"] = 300_000
        monkeypatch.setattr(user_settings, "load", lambda: settings)
        monkeypatch.setattr(codex_meter, "turn_state",
                            lambda path, max_records=2000: codex_meter.IDLE)
        monkeypatch.setattr(codex_window, "last_call",
                            lambda path, max_records=2000: NOW - 120)
        monkeypatch.setattr(codex_threads, "thread",
                            lambda tid, env=None: {"id": tid, "archived": False,
                                                   "rollout_path": "/fake/rollout.jsonl"})
        thread = {"id": THREAD_ID, "kind": "user", "archived": False,
                  "rollout_path": "/fake/rollout.jsonl", "label": "a long-running session"}
        out = codex_arming.arm_thread(
            thread, settings, NOW, spawner=lambda argv, env=None: 4242,
            reader=lambda path: cache_window.CacheWindow(NOW - 120, 3600, 450_000))
        assert out["action"] == "armed"
        return idle_state.read_marker(THREAD_ID)

    def test_the_watcher_the_arming_starts_drives_the_codex_side(self, armed):
        """The marker the sweep wrote is what tells the shared watcher which
        platform it is on - this is the join between the two halves."""
        assert armed["platform"] == platforms.CODEX
        assert idle_watch.platform_for(armed).name == platforms.CODEX

    def test_the_toast_is_answered_by_compacting_the_session(self, armed, monkeypatch):
        compacted = []
        monkeypatch.setattr(codex_compact, "compact",
                            lambda tid, env=None: compacted.append(tid) or {"compacted": True})

        class Deps:
            clock, environ, sessions_dir = staticmethod(lambda: NOW), {}, None
            platform = codex_watching.platform()

            def side(self):
                return self.platform

        sent = idle_watch.Deps.side(Deps()).send(THREAD_ID, armed, Deps())
        assert compacted == [THREAD_ID]
        assert sent["outcome"]["event"] == "compacted"


class TestTheGuardsStillHold:
    """Reaching a new platform must not reach past the refusals that platform
    already had (D-20260921-030, D-20260921-031)."""

    def _armed(self, thread, settings):
        return codex_arming.arm_thread(
            thread, settings, NOW, spawner=lambda argv, env=None: 1,
            reader=lambda path: cache_window.CacheWindow(NOW - 120, 3600, 450_000))

    @pytest.fixture
    def settings(self, monkeypatch):
        monkeypatch.setattr(codex_meter, "turn_state",
                            lambda path, max_records=2000: codex_meter.IDLE)
        values = dict(user_settings.defaults())
        values["min_context_tokens"] = 300_000
        return values

    @pytest.mark.parametrize("kind", ["guardian_review", "subagent"])
    def test_a_spin_off_is_never_armed(self, settings, kind):
        out = self._armed({"id": THREAD_ID, "kind": kind, "archived": False,
                           "rollout_path": "/fake/rollout.jsonl"}, settings)
        assert out["action"] == "skip"

    def test_an_archived_session_is_never_armed(self, settings):
        out = self._armed({"id": THREAD_ID, "kind": "user", "archived": True,
                           "rollout_path": "/fake/rollout.jsonl"}, settings)
        assert out["action"] == "skip"

    def test_a_busy_session_is_never_armed(self, settings, monkeypatch):
        monkeypatch.setattr(codex_meter, "turn_state", lambda path, max_records=2000: "busy")
        out = self._armed({"id": THREAD_ID, "kind": "user", "archived": False,
                           "rollout_path": "/fake/rollout.jsonl"}, settings)
        assert out["action"] == "skip"


class TestTheClaudePathIsUntouched:
    def test_a_marker_with_no_platform_still_means_claude(self):
        assert idle_watch.platform_for({"session_id": "s1"}) is None

    def test_the_claude_adapter_is_the_default(self):
        assert idle_watch.Deps(clock=None, sleep=None, environ=None, sessions_dir=None,
                               compactor=None, present=None).side().name == "claude"

    def test_the_stop_hook_still_arms_the_claude_session_first(self):
        body = source("closure_hook")
        assert body.index("idle_arming.run(hook_input)") < body.index("codex_arming.run()")
