"""Tests for conpact.remote_startup: Claude Code's own "Remote Control at startup" setting."""
import json

import pytest

from conpact import remote_startup, session_registry


def _settings(body):
    path = remote_startup.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body, indent=2), encoding="utf-8")
    return path


def test_the_setting_lives_in_the_users_own_settings_file():
    assert remote_startup.settings_path() == session_registry.CLAUDE_DIR / "settings.json"
    assert remote_startup.KEY == "remoteControlAtStartup"


# --- reading -----------------------------------------------------------------

def test_it_is_on_only_when_the_setting_says_true():
    _settings({"remoteControlAtStartup": True})
    assert remote_startup.is_on() is True


@pytest.mark.parametrize("body", [
    {}, {"remoteControlAtStartup": False}, {"remoteControlAtStartup": "yes"},
    {"remoteControlAtStartup": 1}, {"other": True}, "not json", "[1, 2]", "",
])
def test_anything_else_reads_as_off(body):
    _settings(body)
    assert remote_startup.is_on() is False


def test_no_settings_file_at_all_reads_as_off():
    assert remote_startup.is_on() is False


# --- writing -----------------------------------------------------------------

def test_turning_it_on_keeps_every_other_setting():
    before = {"model": "opus[1m]", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x.cmd"}]}]},
              "permissions": {"allow": ["Bash(git *)"], "additionalDirectories": []}}
    path = _settings(before)
    assert remote_startup.turn_on() is True
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after == {**before, "remoteControlAtStartup": True}
    assert list(after)[:len(before)] == list(before)   # nothing reordered
    assert remote_startup.is_on() is True


def test_turning_it_on_when_it_is_already_on_changes_nothing():
    path = _settings({"model": "opus", "remoteControlAtStartup": True})
    before = path.read_text(encoding="utf-8")
    assert remote_startup.turn_on() is False
    assert path.read_text(encoding="utf-8") == before


def test_it_replaces_a_setting_that_was_switched_off():
    path = _settings({"remoteControlAtStartup": False, "model": "opus"})
    assert remote_startup.turn_on() is True
    assert json.loads(path.read_text(encoding="utf-8")) == {"remoteControlAtStartup": True, "model": "opus"}


def test_a_missing_settings_file_is_created_with_just_this_setting():
    assert remote_startup.turn_on() is True
    assert json.loads(remote_startup.settings_path().read_text(encoding="utf-8")) == {
        "remoteControlAtStartup": True}


def test_the_file_ends_with_a_newline_as_an_editor_would_leave_it():
    _settings({"model": "opus"})
    remote_startup.turn_on()
    assert remote_startup.settings_path().read_text(encoding="utf-8").endswith("}\n")


@pytest.mark.parametrize("body", ["not json", "[1, 2]", '"a string"', ""])
def test_a_file_we_cannot_read_is_never_clobbered(body):
    """Refusing to write is the whole point: these are the user's own settings."""
    path = _settings(body)
    with pytest.raises(ValueError):
        remote_startup.turn_on()
    assert path.read_text(encoding="utf-8") == body


def test_the_write_leaves_no_temporary_file_behind():
    _settings({"model": "opus"})
    remote_startup.turn_on()
    assert sorted(p.name for p in remote_startup.settings_path().parent.iterdir()) == ["settings.json"]


def test_it_keeps_claude_codes_own_two_space_indentation():
    """This is the user's file, opened in their editor: it should not come back reformatted."""
    _settings({"model": "opus"})
    remote_startup.turn_on()
    assert '\n  "remoteControlAtStartup": true' in remote_startup.settings_path().read_text(encoding="utf-8")


def test_a_write_that_fails_says_so(monkeypatch):
    _settings({"model": "opus"})

    def refuse(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(remote_startup.pathlib.Path, "write_text", refuse)
    with pytest.raises(OSError):
        remote_startup.turn_on()


def test_a_write_that_fails_at_the_rename_leaves_no_temporary_file_behind(monkeypatch):
    """The other failure: the temporary file is already written when the rename fails."""
    path = _settings({"model": "opus"})

    def refuse(*a, **k):
        raise OSError("the file is open in another program")
    monkeypatch.setattr(remote_startup.os, "replace", refuse)
    with pytest.raises(OSError):
        remote_startup.turn_on()
    assert sorted(p.name for p in path.parent.iterdir()) == ["settings.json"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"model": "opus"}
