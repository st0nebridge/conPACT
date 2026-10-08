"""
@module tests.test_codex_arming
@description The sweep that stands in for the Stop hook Codex does not have:
             which sessions it arms, every reason it refuses one, and the
             promise that sweeping again does not retire a watcher that is
             already counting down - which would mean a toast that never comes.
@input      conpact.codex_arming, against fabricated threads and a fake spawner
@output     assertions on consider / arm_thread / sweep and each refusal
@dependencies conpact.codex_arming, conpact.codex_meter, conpact.idle_state,
              conpact.settings
"""
import time

import pytest

from conpact import cache_window, codex_arming, codex_meter, idle_state, platforms
from conpact import settings as user_settings

NOW = 1_790_000_000.0
THREAD_ID = "01a00000-0000-7000-9000-000000000002"


@pytest.fixture
def settings():
    values = dict(user_settings.defaults())
    values["min_context_tokens"] = 300_000
    return values


@pytest.fixture(autouse=True)
def idle_between_turns(monkeypatch):
    monkeypatch.setattr(codex_meter, "turn_state",
                        lambda path, max_records=2000: codex_meter.IDLE)


def thread(**fields):
    return {"id": THREAD_ID, "kind": "user", "archived": False,
            "rollout_path": "/fake/rollout.jsonl",
            "label": "a long-running review thread", **fields}


def window(context=450_000, called=NOW - 120, ttl=3600):
    return cache_window.CacheWindow(called, ttl, context)


def arm(settings, monkeypatch, thread_record=None, win=None, now=NOW):
    started = []
    out = codex_arming.arm_thread(thread_record or thread(), settings, now,
                                  spawner=lambda argv, env=None: started.append(argv) or 4242,
                                  reader=lambda path: window() if win is None else win)
    return out, started


class TestWhatItArms:
    def test_a_large_idle_session_is_armed(self, settings, monkeypatch):
        out, started = arm(settings, monkeypatch)
        assert out["action"] == "armed"
        assert out["watcher_pid"] == 4242
        assert len(started) == 1

    def test_the_watcher_is_started_on_the_shared_module(self, settings, monkeypatch):
        _, started = arm(settings, monkeypatch)
        assert started[0][-3] == "conpact.idle_watch"
        assert started[0][-2] == THREAD_ID

    def test_the_marker_says_which_platform_so_the_watcher_knows(self, settings, monkeypatch):
        arm(settings, monkeypatch)
        marker = idle_state.read_marker(THREAD_ID)
        assert marker["platform"] == platforms.CODEX
        assert marker["ttl_is_modelled"] is True

    def test_the_marker_carries_what_the_toast_will_show(self, settings, monkeypatch):
        arm(settings, monkeypatch)
        marker = idle_state.read_marker(THREAD_ID)
        assert marker["name"] == "a long-running review thread"
        assert marker["context_tokens"] == 450_000
        assert marker["transcript_path"] == "/fake/rollout.jsonl"
        assert marker["stages"]


class TestWhatItRefuses:
    def test_a_session_smaller_than_the_minimum(self, settings, monkeypatch):
        out, started = arm(settings, monkeypatch, win=window(context=1_000))
        assert out["action"] == "skip" and "minimum" in out["reason"]
        assert started == []

    def test_a_session_whose_cache_has_already_gone(self, settings, monkeypatch):
        out, _ = arm(settings, monkeypatch, win=window(called=NOW - 7200))
        assert out["action"] == "skip" and "expired" in out["reason"]

    def test_a_rollout_that_shows_no_call(self, settings):
        out = codex_arming.arm_thread(thread(), settings, NOW,
                                      spawner=lambda argv, env=None: 1,
                                      reader=lambda path: None)
        assert out["action"] == "skip" and "no call" in out["reason"]

    def test_a_spin_off_is_never_touched(self, settings, monkeypatch):
        out, started = arm(settings, monkeypatch, thread_record=thread(kind="guardian_review"))
        assert out["action"] == "skip"
        assert started == []

    def test_an_archived_session_is_left_alone(self, settings, monkeypatch):
        out, _ = arm(settings, monkeypatch, thread_record=thread(archived=True))
        assert out["action"] == "skip"

    def test_a_session_mid_turn_is_not_idle(self, settings, monkeypatch):
        monkeypatch.setattr(codex_meter, "turn_state", lambda path, max_records=2000: "busy")
        out, _ = arm(settings, monkeypatch)
        assert out["action"] == "skip" and "turn" in out["reason"]

    def test_a_silenced_session_stays_silent(self, settings, monkeypatch):
        idle_state.set_mute(THREAD_ID, NOW + 3600, after_call=NOW - 120)
        out, started = arm(settings, monkeypatch)
        assert out["action"] == "skip" and "silenced" in out["reason"]
        assert started == []

    def test_a_watcher_that_will_not_start_is_reported_and_leaves_no_marker(self, settings):
        def refuse(argv, env=None):
            raise OSError("no process")
        out = codex_arming.arm_thread(thread(), settings, NOW, spawner=refuse,
                                      reader=lambda path: window())
        assert out["action"] == "error"
        assert idle_state.read_marker(THREAD_ID) is None


class TestSweepingAgainDoesNotRestartTheClock:
    def test_a_session_already_watched_is_left_alone(self, settings, monkeypatch):
        first, started = arm(settings, monkeypatch)
        assert first["action"] == "armed"
        again = codex_arming.arm_thread(thread(), settings, NOW + 5,
                                        spawner=lambda argv, env=None: started.append(argv) or 1,
                                        reader=lambda path: window())
        assert again["action"] == "skip" and "already watched" in again["reason"]
        assert len(started) == 1

    def test_a_session_used_since_is_armed_again_from_its_new_call(self, settings, monkeypatch):
        _, started = arm(settings, monkeypatch)
        moved = codex_arming.arm_thread(
            thread(), settings, NOW + 200,
            spawner=lambda argv, env=None: started.append(argv) or 2,
            reader=lambda path: window(called=NOW + 100))
        assert moved["action"] == "armed"
        assert len(started) == 2

    def test_a_watch_that_has_run_out_does_not_block_a_new_one(self, settings, monkeypatch):
        arm(settings, monkeypatch)
        later = codex_arming.arm_thread(
            thread(), settings, NOW + 10_000,
            spawner=lambda argv, env=None: 3,
            reader=lambda path: window(called=NOW + 9_900))
        assert later["action"] == "armed"


class TestTheSweep:
    def test_it_looks_at_every_session_and_reports_what_it_armed(self, settings, monkeypatch):
        monkeypatch.setattr(user_settings, "load", lambda: settings)
        started = []
        out = codex_arming.sweep(clock=lambda: NOW,
                                 spawner=lambda argv, env=None: started.append(argv) or 1,
                                 reader=lambda path: window(),
                                 threads=[thread(), thread(id="019e0000-0000-7000-a000-000000000001")])
        assert out["action"] == "swept"
        assert out["looked_at"] == 2
        assert len(out["armed"]) == 2
        assert len(started) == 2

    def test_one_bad_session_does_not_stop_the_sweep(self, settings, monkeypatch):
        monkeypatch.setattr(user_settings, "load", lambda: settings)

        def explode(path):
            if path == "/bad":
                raise RuntimeError("unreadable")
            return window()

        out = codex_arming.sweep(clock=lambda: NOW, spawner=lambda argv, env=None: 1,
                                 reader=explode,
                                 threads=[thread(rollout_path="/bad"),
                                          thread(id="019e0000-0000-7000-a000-000000000001")])
        assert [o["action"] for o in out["outcomes"]] == ["error", "armed"]

    def test_the_notifier_being_off_stops_everything(self, settings, monkeypatch):
        settings[user_settings.TOGGLE] = False
        monkeypatch.setattr(user_settings, "load", lambda: settings)
        started = []
        out = codex_arming.sweep(clock=lambda: NOW,
                                 spawner=lambda argv, env=None: started.append(argv),
                                 threads=[thread()])
        assert out["action"] == "skip"
        assert started == []

    def test_run_never_raises_because_it_runs_in_the_stop_hook(self, monkeypatch):
        monkeypatch.setattr(codex_arming, "sweep", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert codex_arming.run()["action"] == "error"


class TestTheHookIsObservable:
    """A sweep logs only what it did - its refusals are noise, since it looks at
    every session every time. A hook fires once per turn end, so a skip is a
    fact about one session at one moment and is exactly what goes missing."""

    def test_a_skip_is_logged_too(self, monkeypatch, tmp_path):
        logged = []
        monkeypatch.setattr(codex_arming.idle_state, "append_log", logged.append)
        monkeypatch.setattr(codex_arming, "arm_one",
                            lambda tid, **kw: {"action": "skip", "thread_id": tid,
                                               "reason": "prompt cache already expired"})

        codex_arming.run_one("t-1")

        assert len(logged) == 1
        assert logged[0]["event"] == "codex_skip"
        assert logged[0]["reason"] == "prompt cache already expired"
        assert logged[0]["via"] == "sidecar turn/completed"

    def test_an_arming_is_still_logged(self, monkeypatch):
        logged = []
        monkeypatch.setattr(codex_arming.idle_state, "append_log", logged.append)
        monkeypatch.setattr(codex_arming, "arm_one",
                            lambda tid, **kw: {"action": "armed", "thread_id": tid,
                                               "watcher_pid": 7, "reason": "started"})

        codex_arming.run_one("t-2")

        assert logged[0]["event"] == "codex_armed" and logged[0]["watcher_pid"] == 7

    def test_a_raise_inside_becomes_a_logged_error_not_a_crash(self, monkeypatch):
        logged = []
        monkeypatch.setattr(codex_arming.idle_state, "append_log", logged.append)
        def boom(tid, **kw):
            raise RuntimeError("rollout unreadable")
        monkeypatch.setattr(codex_arming, "arm_one", boom)

        status = codex_arming.run_one("t-3")

        assert status["action"] == "error"
        assert logged[0]["event"] == "codex_error"


class TestExactThreadArming:
    def test_only_the_named_thread_is_armed(self, settings, monkeypatch):
        monkeypatch.setattr(user_settings, 'load', lambda: settings)
        started = []
        out = codex_arming.arm_one(THREAD_ID, clock=lambda: NOW,
                                   threads=[thread(id='other'), thread()],
                                   reader=lambda _: window(),
                                   spawner=lambda argv, **kw: started.append(argv) or 7)
        assert out['action'] == 'armed' and out['watcher_pid'] == 7
        assert len(started) == 1
        assert started[0][-2] == THREAD_ID

    def test_an_absent_thread_is_not_substituted(self, settings, monkeypatch):
        monkeypatch.setattr(user_settings, 'load', lambda: settings)
        out = codex_arming.arm_one(THREAD_ID, threads=[thread(id='other')])
        assert out['action'] == 'skip' and 'cannot find' in out['reason']

    def test_switched_off_notifier_never_reads_threads(self, settings, monkeypatch):
        settings[user_settings.TOGGLE] = False
        monkeypatch.setattr(user_settings, 'load', lambda: settings)
        assert codex_arming.arm_one(THREAD_ID)['action'] == 'skip'

    def test_a_store_read_failure_is_reported(self, settings, monkeypatch):
        monkeypatch.setattr(user_settings, 'load', lambda: settings)
        def locked(_):
            raise OSError('store locked')
        monkeypatch.setattr(codex_arming.codex_threads, 'threads', locked)
        out = codex_arming.arm_one(THREAD_ID)
        assert out['action'] == 'error' and 'store locked' in out['reason']


class TestAQueuedCompactionRunsAtTheTurnEnd:
    """Codex's half of the intent/execution split: the MCP tool records the
    intent, the sidecar's turn end runs it. Claude's turn end is its Stop hook."""

    @pytest.fixture(autouse=True)
    def idle_thread(self, monkeypatch):
        monkeypatch.setattr(codex_arming, "_turn_state", lambda *_: codex_meter.IDLE)

    def test_a_queued_request_is_run_instead_of_arming(self, tmp_path, monkeypatch):
        from conpact import compaction
        compaction.request_compaction("t-1", focus="keep the design",
                                      requests_dir=tmp_path)
        ran = []
        monkeypatch.setattr(codex_arming, "arm_one",
                            lambda *a, **k: pytest.fail("must not arm after compacting"))

        out = codex_arming.run_one(
            "t-1", compacter=lambda tid: ran.append(tid) or {"compacted": True},
            requests_dir=tmp_path)

        assert out["action"] == "compacted" and ran == ["t-1"]

    def test_with_nothing_queued_it_arms_as_usual(self, tmp_path, monkeypatch):
        monkeypatch.setattr(codex_arming, "arm_one",
                            lambda tid, **k: {"action": "armed", "thread_id": tid,
                                              "reason": "watcher started"})
        out = codex_arming.run_one("t-2", requests_dir=tmp_path,
                                   compacter=lambda tid: pytest.fail("nothing to run"))
        assert out["action"] == "armed"

    def test_a_request_fires_at_most_once(self, tmp_path, monkeypatch):
        """Two turn endings can arrive together; the claim is what makes it one."""
        from conpact import compaction
        compaction.request_compaction("t-3", requests_dir=tmp_path)
        monkeypatch.setattr(codex_arming, "arm_one",
                            lambda tid, **k: {"action": "armed", "thread_id": tid,
                                              "reason": "watcher started"})
        runs = []
        first = codex_arming.run_one("t-3", requests_dir=tmp_path,
                                     compacter=lambda tid: runs.append(tid) or {"compacted": True})
        second = codex_arming.run_one("t-3", requests_dir=tmp_path,
                                      compacter=lambda tid: runs.append(tid) or {"compacted": True})
        assert first["action"] == "compacted"
        assert second["action"] == "armed", "the second turn end found nothing to claim"
        assert runs == ["t-3"]

    def test_a_compaction_that_fails_says_so_rather_than_claiming_success(self, tmp_path):
        from conpact import compaction
        compaction.request_compaction("t-4", requests_dir=tmp_path)
        out = codex_arming.run_one(
            "t-4", requests_dir=tmp_path,
            compacter=lambda tid: {"compacted": False, "reason": "a running app holds it"})
        assert out["action"] == "compaction_failed"
        assert "holds it" in out["reason"]

    def test_a_request_below_its_minimum_is_discarded_without_compacting(self, tmp_path):
        from conpact import compaction
        compaction.request_compaction("t-5", min_context_tokens=1000,
                                      requests_dir=tmp_path)
        out = codex_arming.run_one(
            "t-5", requests_dir=tmp_path, measurer=lambda *_: 999,
            compacter=lambda tid: pytest.fail("below minimum must not compact"))
        assert out["action"] == "skip"
        assert out["context_tokens"] == 999
        assert compaction.pending_request("t-5", requests_dir=tmp_path) is None

    def test_an_unmeasurable_minimum_fails_closed(self, tmp_path):
        from conpact import compaction
        compaction.request_compaction("t-6", min_context_tokens=1000,
                                      requests_dir=tmp_path)
        out = codex_arming.run_one(
            "t-6", requests_dir=tmp_path, measurer=lambda *_: None,
            compacter=lambda tid: pytest.fail("unknown size must not compact"))
        assert out["action"] == "skip"
        assert "unavailable" in out["reason"]
