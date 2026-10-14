"""Tests for conpact.claude_idle_offer: asking once which idle compaction the user wants."""
import json

import pytest

from conpact import claude_idle_compaction as cic
from conpact import claude_idle_offer as offer
from conpact import claude_settings, idle_state, settings, toast_view

NOW = 1_800_000_000.0


def _switch(mode):
    path = cic.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cachedGrowthBookFeatures": {cic.FLAG: {"mode": mode}}}), encoding="utf-8")


def _claude_settings(data):
    path = claude_settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _log():
    path = idle_state.log_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Spawner:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, argv, env=None):
        if self.fail:
            raise self.fail
        self.calls.append((argv, env))
        return 4242


def test_the_record_lives_in_conpacts_own_home():
    assert offer.record_path() == offer.compaction.STATE_DIR / "claude-idle-offer.json"


# --- when to ask ---------------------------------------------------------------------

def test_it_asks_when_anthropic_has_switched_it_on_and_conpacts_toast_is_on():
    _switch("compact")
    spawner = Spawner()
    status = offer.offer(environ={"KEEP": "me"}, clock=lambda: NOW, spawner=spawner)
    assert status == {"action": "offered", "pid": 4242, "server": "compact"}
    (argv, env), = spawner.calls
    assert argv[1:] == ["-m", "conpact.claude_idle_offer"]
    assert env == {"KEEP": "me", "PYTHONPATH": offer.SRC_ROOT}
    assert offer.read_record() == {"asked_at": NOW, "server": "compact"}


@pytest.mark.parametrize("mode", ["off", "log", None])
def test_it_does_not_ask_while_anthropic_has_it_off_or_only_logging(mode):
    if mode:
        _switch(mode)
    status = offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())
    assert status == {"action": "skip", "reason": "Claude Code's idle compaction is not active"}
    assert offer.read_record() is None


def test_it_does_not_ask_someone_who_already_turned_claude_codes_off():
    _switch("compact")
    _claude_settings({"idleCompaction": False})
    status = offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())
    assert status["action"] == "skip" and offer.read_record() is None


def test_it_does_not_ask_while_auto_compaction_is_off_anyway():
    _switch("compact")
    status = offer.offer(environ={"DISABLE_AUTO_COMPACT": "1"}, clock=lambda: NOW, spawner=Spawner())
    assert status["action"] == "skip"


def test_it_does_not_ask_when_conpacts_own_idle_toast_is_off():
    """Then there is nothing of ours to keep: Claude Code's is all the user has."""
    _switch("compact")
    settings.save({settings.TOGGLE: False})
    status = offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())
    assert status == {"action": "skip", "reason": "conPACT's idle toast is off"}
    assert offer.read_record() is None


def test_it_asks_only_once_whatever_happened_after():
    _switch("compact")
    first, second = Spawner(), Spawner()
    assert offer.offer(environ={}, clock=lambda: NOW, spawner=first)["action"] == "offered"
    assert offer.offer(environ={}, clock=lambda: NOW + 86_400, spawner=second) == {
        "action": "skip", "reason": "already asked"}
    assert second.calls == []


def test_once_asked_a_turn_end_reads_nothing_more(monkeypatch):
    """Every turn end of every session passes through here; after the one
    question it costs a single look at the record."""
    _switch("compact")
    offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())
    monkeypatch.setattr(offer.claude_idle_compaction, "state", lambda environ=None: pytest.fail("read again"))
    monkeypatch.setattr(offer.idle_state, "is_enabled", lambda: pytest.fail("read again"))
    assert offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner()) == {"action": "skip",
                                                                            "reason": "already asked"}


def test_with_conpacts_toast_off_claude_codes_config_is_not_read(monkeypatch):
    settings.save({settings.TOGGLE: False})
    monkeypatch.setattr(offer.claude_idle_compaction, "state", lambda environ=None: pytest.fail("read"))
    assert offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())["reason"] == "conPACT's idle toast is off"


def test_it_does_not_ask_again_when_anthropic_switches_it_off_and_on_again():
    _switch("compact")
    offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())
    _switch("off")
    offer.offer(environ={}, clock=lambda: NOW + 1, spawner=Spawner())
    _switch("compact")
    again = Spawner()
    assert offer.offer(environ={}, clock=lambda: NOW + 2, spawner=again)["action"] == "skip"
    assert again.calls == []


def test_two_turn_ends_at_once_ask_once(monkeypatch):
    """Two sessions can stop in the same moment; the record is claimed, not just checked."""
    _switch("compact")
    real = offer.claim
    beaten = []

    def late(now, found):
        beaten.append(real(now, found))        # the other turn end got there first
        return real(now, found)
    monkeypatch.setattr(offer, "claim", late)
    spawner = Spawner()
    assert offer.offer(environ={}, clock=lambda: NOW, spawner=spawner) == {"action": "skip",
                                                                          "reason": "already asked"}
    assert beaten == [True] and spawner.calls == []


def test_a_question_that_could_not_be_shown_was_not_asked():
    _switch("compact")
    status = offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner(fail=OSError("no python")))
    assert status == {"action": "error", "reason": "the question did not start: no python"}
    assert offer.read_record() is None          # so a later turn end asks after all


def test_an_unreadable_record_counts_as_asked():
    """It exists, so the user was asked; a damaged answer is no reason to ask twice."""
    _switch("compact")
    offer.record_path().parent.mkdir(parents=True, exist_ok=True)
    offer.record_path().write_text("not json", encoding="utf-8")
    assert offer.offer(environ={}, clock=lambda: NOW, spawner=Spawner())["action"] == "skip"
    assert offer.read_record() == {}


# --- run, from the Stop hook ------------------------------------------------------------

def test_run_logs_an_offer_and_stays_quiet_on_a_skip():
    _switch("compact")
    assert offer.run(environ={}, clock=lambda: NOW, spawner=Spawner())["action"] == "offered"
    assert offer.run(environ={}, clock=lambda: NOW, spawner=Spawner())["action"] == "skip"
    assert [(e["event"], e.get("server")) for e in _log()] == [("claude_idle_offered", "compact")]


def test_run_never_raises(monkeypatch):
    def broken(environ=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(offer.claude_idle_compaction, "state", broken)
    status = offer.run(environ={})
    assert status == {"action": "error", "reason": "RuntimeError: boom"}
    assert [e["event"] for e in _log()] == ["claude_idle_offer_error"]


def test_run_reads_the_hooks_own_environment_by_default(monkeypatch):
    _switch("compact")
    monkeypatch.setenv("DISABLE_COMPACT", "true")
    assert offer.run(spawner=Spawner())["action"] == "skip"


# --- the toast's controller ---------------------------------------------------------------

def test_the_toast_waits_for_an_answer_since_it_is_asked_only_once():
    asked = offer.Offer()
    assert asked.model() == {"kind": "claude_idle", "deadline": None, "span": None}
    assert asked.poll() is None
    assert asked.progress() == {"state": "untracked"}


def test_using_conpacts_turns_claude_codes_off():
    _claude_settings({"model": "opus"})
    asked = offer.Offer()
    assert asked.act("use_conpact") == {"state": "claude_idle_off"}
    assert cic.allowed() is False
    assert json.loads(claude_settings.path().read_text(encoding="utf-8")) == {"model": "opus",
                                                                               "idleCompaction": False}
    assert asked.outcome == {"event": "claude_idle_answered", "answer": "use_conpact"}
    assert settings.load()[settings.TOGGLE] is True


def test_using_claude_codes_turns_conpacts_idle_toast_off_and_leaves_claude_code_alone():
    _claude_settings({"model": "opus"})
    asked = offer.Offer()
    assert asked.act("use_claude") == {"state": "conpact_idle_off"}
    assert settings.load()[settings.TOGGLE] is False
    assert json.loads(claude_settings.path().read_text(encoding="utf-8")) == {"model": "opus"}
    assert asked.outcome == {"event": "claude_idle_answered", "answer": "use_claude"}


def test_keeping_both_changes_nothing():
    _claude_settings({"model": "opus"})
    asked = offer.Offer()
    assert asked.act("dismiss") == {"state": "closed"}
    assert asked.outcome == {"event": "claude_idle_answered", "answer": "keep_both"}
    assert cic.allowed() is True and settings.load()[settings.TOGGLE] is True


def test_only_the_first_answer_counts():
    asked = offer.Offer()
    asked.act("dismiss")
    assert asked.act("use_conpact") == {"state": "closed"}
    assert cic.allowed() is True and asked.outcome["answer"] == "keep_both"


@pytest.mark.parametrize("action", ["compact", "auto", "always_on", "settings", ""])
def test_anything_else_closes_and_changes_nothing(action):
    asked = offer.Offer()
    assert asked.act(action) == {"state": "closed"}
    assert asked.outcome is None and cic.allowed() is True


def test_a_claude_code_settings_file_that_cannot_be_read_is_reported_not_replaced():
    path = claude_settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    asked = offer.Offer()
    state = asked.act("use_conpact")
    assert state["state"] == "setting_failed" and "will not be written" in state["detail"]
    assert path.read_text(encoding="utf-8") == "not json"
    assert asked.outcome["event"] == "claude_idle_failed" and asked.outcome["answer"] == "use_conpact"
    assert asked.outcome["reason"].startswith("ValueError: ")


def test_conpacts_own_settings_that_cannot_be_written_are_reported(monkeypatch):
    def refuse(changes):
        raise OSError("read-only")
    monkeypatch.setattr(offer.user_settings, "save", refuse)
    asked = offer.Offer()
    assert asked.act("use_claude") == {"state": "setting_failed", "detail": "read-only"}
    assert asked.outcome == {"event": "claude_idle_failed", "answer": "use_claude", "reason": "OSError: read-only"}


# --- the detached process -------------------------------------------------------------------

def test_main_shows_the_question_and_records_the_answer(monkeypatch):
    _switch("compact")
    offer.claim(NOW, cic.state({}))
    shown = []

    def present(controller):
        shown.append(controller.model()["kind"])
        controller.act("use_conpact")
    monkeypatch.setattr(toast_view, "present", present)
    assert offer.main([], clock=lambda: NOW + 5) == 0
    assert shown == ["claude_idle"]
    assert offer.read_record() == {"asked_at": NOW, "server": "compact", "answer": "use_conpact",
                                   "answered_at": NOW + 5}
    assert [(e["event"], e.get("answer")) for e in _log()] == [("claude_idle_answered", "use_conpact")]


def test_main_records_a_question_closed_without_an_answer(monkeypatch):
    _switch("compact")
    offer.claim(NOW, cic.state({}))
    monkeypatch.setattr(toast_view, "present", lambda controller: None)
    offer.main([], clock=lambda: NOW + 5)
    assert offer.read_record()["answer"] == "none"
    assert _log()[-1]["event"] == "claude_idle_unanswered"


def test_main_reports_a_toast_that_failed_and_still_counts_it_as_asked(monkeypatch):
    _switch("compact")
    offer.claim(NOW, cic.state({}))

    def broken(controller):
        raise RuntimeError("no display")
    monkeypatch.setattr(toast_view, "present", broken)
    assert offer.main([], clock=lambda: NOW + 5) == 0
    assert _log()[-1] == {**_log()[-1], "event": "claude_idle_offer_error", "reason": "RuntimeError: no display"}
    assert offer.read_record()["answer"] == "none"


def test_main_does_not_ask_about_something_that_stopped_being_true_meanwhile(monkeypatch):
    """Between the turn end and the toast the user may have switched it off by hand."""
    _switch("compact")
    offer.claim(NOW, cic.state({}))
    _claude_settings({"idleCompaction": False})
    monkeypatch.setattr(toast_view, "present", lambda controller: pytest.fail("asked about nothing"))
    assert offer.main([], clock=lambda: NOW + 5) == 0
    assert offer.read_record() is None          # not asked, so not used up
    assert _log()[-1]["event"] == "claude_idle_moot"


# --- the details the log and the files keep ---------------------------------------------------

def test_the_child_is_handed_the_root_the_package_imports_from():
    assert (offer.pathlib.Path(offer.SRC_ROOT) / "conpact" / "claude_idle_offer.py").is_file()


def test_a_claim_says_whether_it_won_and_makes_its_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(offer.compaction, "STATE_DIR", tmp_path / "not" / "yet" / ".conpact")
    assert offer.claim(NOW, {"server": "compact"}) is True
    assert offer.claim(NOW, {"server": "compact"}) is False
    assert offer.read_record() == {"asked_at": NOW, "server": "compact"}


def test_the_answer_is_written_beside_the_record_and_moved_over_it(monkeypatch):
    _switch("compact")
    offer.claim(NOW, cic.state({}))
    monkeypatch.setattr(toast_view, "present", lambda controller: controller.act("dismiss"))
    moves = []
    real = offer.os.replace

    def watch(source, target):
        moves.append((source.name, target.name))
        return real(source, target)
    monkeypatch.setattr(offer.os, "replace", watch)
    offer.main([], clock=lambda: NOW + 5)
    assert moves == [("claude-idle-offer.json.tmp", "claude-idle-offer.json")]


def test_the_log_keeps_the_pid_of_the_question_and_the_reason_of_an_error():
    _switch("compact")
    offer.run(environ={}, clock=lambda: NOW, spawner=Spawner())
    offer.record_path().unlink()
    offer.run(environ={}, clock=lambda: NOW, spawner=Spawner(fail=OSError("no python")))
    first, second = _log()
    assert (first["event"], first["pid"]) == ("claude_idle_offered", 4242)
    assert (second["event"], second["reason"]) == ("claude_idle_offer_error",
                                                   "the question did not start: no python")


def test_main_with_nothing_to_ask_and_nothing_claimed_just_logs_it(monkeypatch):
    """`python -m conpact.claude_idle_offer` run by hand, with nothing to ask about."""
    _switch("off")
    monkeypatch.setattr(toast_view, "present", lambda controller: pytest.fail("asked about nothing"))
    assert offer.main([]) == 0
    assert _log()[-1] == {**_log()[-1], "event": "claude_idle_moot", "server": "off"}
    assert offer.read_record() is None


def test_the_module_run_as_a_command_is_the_question(monkeypatch):
    import runpy
    import warnings
    monkeypatch.setattr("sys.argv", ["conpact.claude_idle_offer"])
    with warnings.catch_warnings(), pytest.raises(SystemExit) as stopped:
        warnings.filterwarnings("ignore", "'conpact.claude_idle_offer' found in sys.modules", RuntimeWarning)
        runpy.run_module("conpact.claude_idle_offer", run_name="__main__")
    assert stopped.value.code == 0
    assert _log()[-1]["event"] == "claude_idle_moot"
