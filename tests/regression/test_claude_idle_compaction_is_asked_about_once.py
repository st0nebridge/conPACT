"""
Regression test for CU-20261014-118 (conPACT asks once which idle compaction
the user wants when Anthropic switches Claude Code's own on).

Since Claude Code 2.1.286 Anthropic can switch on, per account, an idle
compaction of Claude Code's own: a session of 200k tokens or more is compacted
at 90% of its one-hour cache - about 54 minutes, a minute before conPACT's
toast - without asking. conPACT then stood down (CU-20261009-111), so the user's
choices on its toast ("Not now", "Silence") were overridden without a word.
The contract:

  1. When Claude Code's cached copy of Anthropic's switch says "compact", the
     user has not opted out, auto-compaction is on and conPACT's idle toast is
     on, the next turn end starts one question, as its own process.
  2. The question offers either one: conPACT's (Claude Code's is turned off by
     writing "idleCompaction": false, every other setting kept), Claude Code's
     (conPACT's idle toast is turned off, Claude Code's settings untouched), or
     both (nothing changes).
  3. It is asked once. No later turn end asks again, whatever the answer was,
     with no answer at all, and when Anthropic switches it off and on again.
  4. It is not asked while the switch is off, only logging or cannot be found,
     when the user already opted out, when auto-compaction is off, or when
     conPACT's own idle toast is off.
  5. The settings window shows Anthropic's switch and turns the opt-out on and
     off, written only when saved; turning it back on takes the key out.
"""
import io
import json

import pytest

from conpact import (claude_idle_compaction, claude_idle_offer, claude_settings, closure_hook, detach,
                     idle_state, settings, settings_window, toast_view)

THE_USERS_OWN = {"model": "opus[1m]", "theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command",
                                                                                         "command": "stop.cmd"}]}]}}


def _anthropic(mode):
    path = claude_idle_compaction.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"numStartups": 40, "cachedGrowthBookFeatures": {
        "some_other_flag": {"x": 1}, "tengu_sunny_locket": {"mode": mode}}}), encoding="utf-8")


def _claude_settings(data=THE_USERS_OWN):
    path = claude_settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _turn_end(monkeypatch, started):
    """A real Stop hook run, with the detached process it would start recorded instead."""
    monkeypatch.setattr(detach, "spawn", lambda argv, env=None: started.append(argv) or 7000 + len(started))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "anchor-session"})))
    assert closure_hook.main() == 0


def _question(monkeypatch, answer):
    """The question's own process, answered as the user would."""
    def present(controller):
        if answer is not None:
            controller.act(answer)
    monkeypatch.setattr(toast_view, "present", present)
    return claude_idle_offer.main([])


def test_1_a_turn_end_after_anthropic_switches_it_on_starts_one_question(monkeypatch):
    _anthropic("compact")
    _claude_settings()
    started = []
    _turn_end(monkeypatch, started)
    assert [argv[1:] for argv in started] == [["-m", "conpact.claude_idle_offer"]]
    assert claude_idle_offer.read_record()["server"] == "compact"


@pytest.mark.parametrize("answer, allowed, toast", [
    ("use_conpact", False, True),
    ("use_claude", True, False),
    ("dismiss", True, True),         # "Keep both"
])
def test_2_each_answer_changes_only_what_it_says(monkeypatch, answer, allowed, toast):
    _anthropic("compact")
    path = _claude_settings()
    _turn_end(monkeypatch, [])
    _question(monkeypatch, answer)
    assert claude_idle_compaction.allowed() is allowed
    assert settings.load()[settings.TOGGLE] is toast
    expected = {**THE_USERS_OWN, "idleCompaction": False} if not allowed else THE_USERS_OWN
    assert json.loads(path.read_text(encoding="utf-8")) == expected


@pytest.mark.parametrize("answer", ["use_conpact", "use_claude", "dismiss", None])
def test_3_it_is_never_asked_again(monkeypatch, answer):
    _anthropic("compact")
    _claude_settings()
    first = []
    _turn_end(monkeypatch, first)
    _question(monkeypatch, answer)
    # Whatever was chosen, put things back the way they were when it was asked...
    claude_idle_compaction.set_allowed(True)
    settings.save({settings.TOGGLE: True})
    # ...and have Anthropic switch it off and on again.
    _anthropic("off")
    later = []
    _turn_end(monkeypatch, later)
    _anthropic("compact")
    for _ in range(3):
        _turn_end(monkeypatch, later)
    assert len(first) == 1 and later == []


@pytest.mark.parametrize("arrange", [
    lambda: _anthropic("off"),
    lambda: _anthropic("log"),
    lambda: None,                                                    # never cached, or renamed
    lambda: (_anthropic("compact"), _claude_settings({"idleCompaction": False})),
    lambda: (_anthropic("compact"), _claude_settings({"autoCompactEnabled": False})),
    lambda: (_anthropic("compact"), settings.save({settings.TOGGLE: False})),
])
def test_4_nothing_is_asked_while_there_is_nothing_to_choose(monkeypatch, arrange):
    arrange()
    started = []
    if settings.load()[settings.TOGGLE]:
        _turn_end(monkeypatch, started)
    else:
        # The Stop wrapper starts no Python at all then; asked directly, it still says no.
        assert claude_idle_offer.run(spawner=lambda argv, env=None: started.append(argv))["action"] == "skip"
    assert started == [] and claude_idle_offer.read_record() is None


def test_5_the_settings_window_shows_the_switch_and_writes_the_opt_out_only_when_saved():
    _anthropic("compact")
    path = _claude_settings()
    form = settings_window.Form()
    row = settings_window.setting_for(settings_window.CLAUDE_IDLE, form.server)
    assert row.help.endswith("Anthropic's switch for your account: on.")
    form.toggle(settings_window.CLAUDE_IDLE)
    assert claude_idle_compaction.allowed() is True              # not yet saved
    assert form.save() is True
    assert json.loads(path.read_text(encoding="utf-8")) == {**THE_USERS_OWN, "idleCompaction": False}
    form.toggle(settings_window.CLAUDE_IDLE)
    assert form.save() is True
    assert json.loads(path.read_text(encoding="utf-8")) == THE_USERS_OWN


def test_the_log_says_what_was_asked_and_answered(monkeypatch):
    _anthropic("compact")
    _claude_settings()
    _turn_end(monkeypatch, [])
    _question(monkeypatch, "use_conpact")
    lines = [json.loads(line) for line in idle_state.log_path().read_text(encoding="utf-8").splitlines()]
    events = [(e["event"], e.get("server"), e.get("answer")) for e in lines if e["event"].startswith("claude_idle")]
    assert events == [("claude_idle_offered", "compact", None), ("claude_idle_answered", None, "use_conpact")]
