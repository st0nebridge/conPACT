"""Tests for conpact.idle_state: the idle notifier's off switch, markers, auto switches, log and toast slots."""
import json
import re

import pytest

from conpact import compaction, idle_state as st


def test_paths_live_under_conpacts_own_folder():
    base = compaction.STATE_DIR
    assert st.off_switch_path() == base / "idle-notify.off"
    assert st.log_path() == base / "idle-log.jsonl"
    assert st.watch_path("s1") == base / "idle" / "watch" / "s1.json"
    assert st.auto_path("s1") == base / "idle" / "auto" / "s1"
    assert st.slot_path(3) == base / "idle" / "toasts" / "slot-3"


@pytest.mark.parametrize("fn", [st.watch_path, st.auto_path])
def test_session_paths_reject_ids_that_are_not_plain(fn):
    with pytest.raises(ValueError):
        fn("../x")


def test_enabled_unless_the_off_switch_exists():
    assert st.is_enabled()
    st.off_switch_path().parent.mkdir(parents=True, exist_ok=True)
    st.off_switch_path().write_text("", encoding="utf-8")
    assert not st.is_enabled()


def test_write_marker_stores_a_fresh_generation_atomically():
    g1 = st.write_marker("s1", {"fire_at": 5})
    marker = st.read_marker("s1")
    assert marker == {"fire_at": 5, "generation": g1}
    assert re.fullmatch(r"[0-9a-f]{32}", g1)
    g2 = st.write_marker("s1", {"fire_at": 6})
    assert g2 != g1 and st.read_marker("s1") == {"fire_at": 6, "generation": g2}
    assert [p.name for p in st.watch_path("s1").parent.iterdir()] == ["s1.json"]


def test_read_marker_is_none_when_missing_or_unusable():
    assert st.read_marker("s1") is None
    assert st.read_marker("../x") is None
    st.watch_path("s1").parent.mkdir(parents=True)
    for raw in ("not json", "[1]"):
        st.watch_path("s1").write_text(raw, encoding="utf-8")
        assert st.read_marker("s1") is None


def test_clear_marker_only_removes_its_own_generation():
    generation = st.write_marker("s1", {})
    assert st.clear_marker("s1", "someone-else") is False
    assert st.read_marker("s1") is not None
    assert st.clear_marker("s1", generation) is True
    assert st.read_marker("s1") is None
    assert st.clear_marker("s1", generation) is False
    assert st.clear_marker("../x", generation) is False


def test_clear_marker_reports_a_marker_it_could_not_remove(monkeypatch):
    import pathlib
    generation = st.write_marker("s1", {})

    def locked(self, *a, **k):
        raise PermissionError("in use")
    monkeypatch.setattr(pathlib.Path, "unlink", locked)
    assert st.clear_marker("s1", generation) is False


def test_the_auto_switch_is_per_session_and_holds_which_stage():
    assert st.auto_mode("s1") is None
    st.set_auto("s1", "early")
    assert (st.auto_mode("s1"), st.auto_mode("s2")) == ("early", None)
    st.set_auto("s1", "expiry")
    assert st.auto_mode("s1") == "expiry"
    assert st.clear_auto("s1") is True
    assert st.auto_mode("s1") is None
    assert st.clear_auto("s1") is False


def test_the_auto_switch_takes_only_a_stage_it_knows():
    for mode in ("", "always", None, "EARLY"):
        with pytest.raises(ValueError, match="auto-compact mode"):
            st.set_auto("s1", mode)
    assert st.auto_mode("s1") is None


def test_a_switch_from_before_the_stages_means_before_the_cache_expires():
    st.auto_path("s1").parent.mkdir(parents=True, exist_ok=True)
    st.auto_path("s1").write_text("", encoding="utf-8")
    assert st.auto_mode("s1") == "expiry"
    st.auto_path("s1").write_text("nonsense", encoding="utf-8")
    assert st.auto_mode("s1") == "expiry"
    assert st.AUTO_MODES == ("early", "expiry")


def test_the_mute_lives_beside_the_other_state_and_holds_when_it_ends():
    assert st.mute_path("s1") == compaction.STATE_DIR / "idle" / "mute" / "s1.json"
    assert st.read_mute("s1") is None
    st.set_mute("s1", until=500.0, after_call=100.0)
    assert st.read_mute("s1") == {"until": 500.0, "after_call": 100.0}
    st.set_mute("s1", until=900.0, after_call=800.0)
    assert st.read_mute("s1") == {"until": 900.0, "after_call": 800.0}


def test_a_mute_is_per_session_and_can_be_cleared():
    st.set_mute("s1", until=500.0, after_call=100.0)
    assert st.read_mute("s2") is None
    assert st.clear_mute("s1") is True
    assert st.read_mute("s1") is None
    assert st.clear_mute("s1") is False


def test_the_hold_lives_beside_the_other_state_and_keeps_its_reason():
    assert st.hold_path("s1") == compaction.STATE_DIR / "idle" / "hold" / "s1.json"
    assert st.read_hold("s1") is None
    st.set_hold("s1", until=500.0, reason="waiting on a build")
    assert st.read_hold("s1") == {"until": 500.0, "reason": "waiting on a build"}
    st.set_hold("s1", until=900.0)
    assert st.read_hold("s1") == {"until": 900.0, "reason": None}


def test_a_hold_is_per_session_and_can_be_cleared():
    st.set_hold("s1", until=500.0)
    assert st.read_hold("s2") is None
    assert st.clear_hold("s1") is True
    assert st.read_hold("s1") is None
    assert st.clear_hold("s1") is False


@pytest.mark.parametrize("raw", ["not json", "[1]", '{"until": "soon"}', "{}", '{"until": true}'])
def test_an_unusable_hold_reads_as_none(raw):
    st.hold_path("s1").parent.mkdir(parents=True, exist_ok=True)
    st.hold_path("s1").write_text(raw, encoding="utf-8")
    assert st.read_hold("s1") is None


def test_a_hold_with_an_odd_reason_keeps_the_time_and_drops_the_reason():
    st.hold_path("s1").parent.mkdir(parents=True, exist_ok=True)
    st.hold_path("s1").write_text('{"until": 500.0, "reason": 7}', encoding="utf-8")
    assert st.read_hold("s1") == {"until": 500.0, "reason": None}


@pytest.mark.parametrize("raw", ["not json", "[1]", '{"until": "soon", "after_call": 1}',
                                 '{"until": 5}', '{"until": true, "after_call": 1}'])
def test_an_unusable_mute_reads_as_none(raw):
    st.mute_path("s1").parent.mkdir(parents=True, exist_ok=True)
    st.mute_path("s1").write_text(raw, encoding="utf-8")
    assert st.read_mute("s1") is None


def test_the_mute_rejects_ids_that_are_not_plain():
    with pytest.raises(ValueError):
        st.set_mute("../x", until=1.0, after_call=0.0)
    assert st.read_mute("../x") is None
    assert st.clear_mute("../x") is False


def test_setting_the_auto_switch_twice_is_fine():
    st.set_auto("s1", "expiry")
    st.set_auto("s1", "expiry")
    assert st.auto_mode("s1") == "expiry"


def test_the_auto_switch_rejects_ids_that_are_not_plain():
    with pytest.raises(ValueError):
        st.set_auto("../x", "early")
    assert st.auto_mode("../x") is None
    assert st.clear_auto("../x") is False


def test_append_log_writes_one_timestamped_line_per_entry():
    st.append_log({"event": "armed", "session_id": "s1"})
    st.append_log({"event": "expired", "session_id": "s1"})
    lines = [json.loads(line) for line in st.log_path().read_text(encoding="utf-8").splitlines()]
    assert [(e["event"], e["session_id"]) for e in lines] == [("armed", "s1"), ("expired", "s1")]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", lines[0]["ts"])


def test_append_log_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(st, "log_path", lambda: blocker / "log.jsonl")
    st.append_log({"event": "armed"})


def test_claim_slot_takes_the_lowest_free_slot():
    alive = lambda pid: True  # noqa: E731
    assert st.claim_slot(111, alive) == 0
    assert st.claim_slot(222, alive) == 1
    assert st.slot_path(1).read_text(encoding="utf-8") == "222"
    st.release_slot(0)
    assert st.claim_slot(333, alive) == 0


def test_claim_slot_reclaims_a_slot_left_by_a_dead_or_unknown_holder():
    st.slot_path(0).parent.mkdir(parents=True)
    st.slot_path(0).write_text("999", encoding="utf-8")
    assert st.claim_slot(111, lambda pid: pid != 999) == 0
    assert st.slot_path(0).read_text(encoding="utf-8") == "111"
    st.slot_path(1).write_text("garbage", encoding="utf-8")
    assert st.claim_slot(222, lambda pid: True) == 1


def test_claim_slot_gives_up_when_every_slot_is_held():
    # Four, written down. Looping to st.MAX_SLOTS instead would move the code's
    # limit and this test's expectation together, so no change to it could fail:
    # the toast stacks four deep up the right-hand edge, and the fifth waits.
    assert st.MAX_SLOTS == 4
    for n in range(4):
        assert st.claim_slot(100 + n, lambda pid: True) == n
    assert st.claim_slot(999, lambda pid: True) is None


def test_release_slot_is_quiet_when_there_is_nothing_to_release():
    st.release_slot(0)
    st.release_slot(None)
