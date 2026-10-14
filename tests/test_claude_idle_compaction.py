"""Tests for conpact.claude_idle_compaction: Claude Code's own idle compaction, read and switched."""
import json

import pytest

from conpact import claude_idle_compaction as cic
from conpact import claude_settings, session_registry


def _config(body):
    path = cic.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def _switch(value):
    return _config({"numStartups": 9, "cachedGrowthBookFeatures": {"other_flag": True, cic.FLAG: value}})


def _settings(body):
    path = claude_settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def test_the_switch_is_read_from_claude_codes_own_config_next_to_its_folder():
    assert cic.config_path() == session_registry.CLAUDE_DIR.parent / ".claude.json"
    assert cic.FLAG == "tengu_sunny_locket" and cic.KEY == "idleCompaction"


# --- Anthropic's switch ----------------------------------------------------------

@pytest.mark.parametrize("value, mode", [
    ({"mode": "compact"}, "compact"),
    ({"mode": "log", "minTokens": 250_000}, "log"),
    ({"mode": "off"}, "off"),
    # Claude Code itself reads anything but "log" or "compact" as off.
    ({"mode": "COMPACT"}, "off"), ({"mode": None}, "off"), ({}, "off"), (None, "off"), ("compact", "off"),
    ([{"mode": "compact"}], "off"),
])
def test_the_switch_is_read_the_way_claude_code_reads_it(value, mode):
    _switch(value)
    assert cic.server_mode() == mode


@pytest.mark.parametrize("body", [
    {"numStartups": 9},                                   # no cached features at all
    {"cachedGrowthBookFeatures": {"other_flag": True}},   # never sent, or renamed since
    {"cachedGrowthBookFeatures": "corrupt"},
    "not json", "[1, 2]", "",
])
def test_a_switch_that_cannot_be_found_is_unknown_not_off(body):
    """Off is a claim about the account; a missing or renamed flag only says we cannot tell."""
    _config(body)
    assert cic.server_mode() is None


def test_no_config_file_is_unknown():
    assert cic.server_mode() is None


def test_a_config_that_cannot_be_opened_is_unknown(monkeypatch):
    _switch({"mode": "compact"})

    def refuse(*a, **k):
        raise OSError("locked")
    monkeypatch.setattr(cic.pathlib.Path, "read_text", refuse)
    assert cic.server_mode() is None


# --- the user's own setting --------------------------------------------------------

@pytest.mark.parametrize("body, allowed", [
    ({}, True), ({"idleCompaction": True}, True), ({"idleCompaction": False}, False),
    # Claude Code's schema takes a boolean; anything else is not an opt-out.
    ({"idleCompaction": "false"}, True), ({"idleCompaction": 0}, True), ({"idleCompaction": None}, True),
    # Claude Code skips a settings file it cannot parse, opt-out and all.
    ("not json", True), ("[1, 2]", True),
])
def test_claude_code_may_compact_idle_sessions_unless_the_user_said_false(body, allowed):
    _settings(body)
    assert cic.allowed() is allowed


def test_with_no_settings_file_it_is_allowed():
    assert cic.allowed() is True


# --- auto-compaction, which idle compaction needs ------------------------------------

def test_auto_compaction_is_on_by_default():
    assert cic.auto_compact_on({}) is True


def test_auto_compaction_switched_off_in_the_settings():
    _settings({"autoCompactEnabled": False})
    assert cic.auto_compact_on({}) is False
    _settings({"autoCompactEnabled": True})
    assert cic.auto_compact_on({}) is True


@pytest.mark.parametrize("name", ["DISABLE_AUTO_COMPACT", "DISABLE_COMPACT"])
@pytest.mark.parametrize("value, off", [("1", True), ("true", True), (" Yes ", True), ("ON", True),
                                        ("0", False), ("false", False), ("", False), ("2", False)])
def test_auto_compaction_switched_off_by_the_environment(name, value, off):
    assert cic.auto_compact_on({name: value}) is (not off)


def test_auto_compaction_switched_off_by_the_settings_own_environment_block():
    """Claude Code puts a settings file's env block into its sessions' environment."""
    _settings({"env": {"DISABLE_AUTO_COMPACT": "1"}})
    assert cic.auto_compact_on({}) is False
    _settings({"env": "not a block"})
    assert cic.auto_compact_on({}) is True


def test_an_unreadable_settings_file_leaves_auto_compaction_on():
    _settings("not json")
    assert cic.auto_compact_on({}) is True


def test_the_environment_defaults_to_this_process(monkeypatch):
    monkeypatch.setenv("DISABLE_COMPACT", "1")
    assert cic.auto_compact_on() is False


# --- the whole state ------------------------------------------------------------------

def test_it_is_active_only_when_anthropic_has_it_on_and_nothing_here_stops_it():
    _switch({"mode": "compact"})
    assert cic.state({}) == {"server": "compact", "allowed": True, "auto_compact": True, "active": True}


@pytest.mark.parametrize("switch, settings, environ", [
    ({"mode": "off"}, {}, {}),
    ({"mode": "log"}, {}, {}),
    (None, {}, {}),
    ({"mode": "compact"}, {"idleCompaction": False}, {}),
    ({"mode": "compact"}, {"autoCompactEnabled": False}, {}),
    ({"mode": "compact"}, {}, {"DISABLE_AUTO_COMPACT": "1"}),
])
def test_anything_short_of_that_is_not_active(switch, settings, environ):
    if switch is not None:
        _switch(switch)
    _settings(settings)
    assert cic.state(environ)["active"] is False


def test_an_unknown_switch_is_reported_as_such():
    assert cic.state({}) == {"server": None, "allowed": True, "auto_compact": True, "active": False}


# --- switching it ------------------------------------------------------------------------

def test_turning_it_off_writes_the_opt_out_and_keeps_the_rest():
    _settings({"model": "opus"})
    assert cic.set_allowed(False) is True
    assert json.loads(claude_settings.path().read_text(encoding="utf-8")) == {"model": "opus",
                                                                               "idleCompaction": False}
    assert cic.allowed() is False


def test_allowing_it_again_takes_the_opt_out_away_rather_than_writing_true():
    """True does not turn it on - Anthropic's switch decides - so the key just goes."""
    _settings({"model": "opus", "idleCompaction": False})
    assert cic.set_allowed(True) is True
    assert json.loads(claude_settings.path().read_text(encoding="utf-8")) == {"model": "opus"}
    assert cic.allowed() is True


def test_switching_to_where_it_already_is_writes_nothing():
    assert cic.set_allowed(True) is False
    assert not claude_settings.path().exists()
    _settings({"idleCompaction": False})
    assert cic.set_allowed(False) is False


def test_a_settings_file_that_cannot_be_read_is_refused_not_replaced():
    path = _settings("not json")
    with pytest.raises(ValueError):
        cic.set_allowed(False)
    assert path.read_text(encoding="utf-8") == "not json"


# --- in words --------------------------------------------------------------------------------

@pytest.mark.parametrize("mode, words", [
    ("compact", "on"), ("log", "logging only, not compacting"), ("off", "off"), (None, "not found"),
])
def test_the_switch_in_words(mode, words):
    assert cic.server_words(mode) == words


def test_a_mode_it_does_not_know_reads_as_not_found():
    assert cic.server_words("sometime") == "not found"
