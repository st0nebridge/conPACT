"""Tests for conpact.claude_settings: one key at a time in Claude Code's own user settings."""
import json

import pytest

from conpact import claude_settings, session_registry


def _settings(body):
    path = claude_settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body, indent=2), encoding="utf-8")
    return path


def _saved():
    return json.loads(claude_settings.path().read_text(encoding="utf-8"))


def test_the_file_is_the_users_own_settings_file():
    assert claude_settings.path() == session_registry.CLAUDE_DIR / "settings.json"


# --- reading -----------------------------------------------------------------

def test_reading_gives_the_object_in_the_file():
    _settings({"model": "opus", "idleCompaction": False})
    assert claude_settings.read() == {"model": "opus", "idleCompaction": False}


def test_no_file_reads_as_no_settings():
    assert claude_settings.read() == {}


@pytest.mark.parametrize("body", ["not json", "[1, 2]", '"a string"', ""])
def test_a_file_that_is_not_a_json_object_reads_as_unknown(body):
    _settings(body)
    assert claude_settings.read() is None


def test_a_file_that_cannot_be_opened_reads_as_unknown(monkeypatch):
    _settings({"model": "opus"})

    def refuse(*a, **k):
        raise OSError("locked")
    monkeypatch.setattr(claude_settings.pathlib.Path, "read_text", refuse)
    assert claude_settings.read() is None


def test_another_file_can_be_named():
    assert claude_settings.read(session_registry.CLAUDE_DIR / "nowhere.json") == {}


# --- setting a key -------------------------------------------------------------

def test_setting_a_key_keeps_every_other_setting_in_its_place():
    before = {"model": "opus[1m]", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x.cmd"}]}]},
              "permissions": {"allow": ["Bash(git *)"]}}
    _settings(before)
    assert claude_settings.set_key("idleCompaction", False) is True
    after = _saved()
    assert after == {**before, "idleCompaction": False}
    assert list(after)[:len(before)] == list(before)


def test_setting_a_key_to_the_value_it_has_changes_nothing():
    path = _settings({"idleCompaction": False})
    before = path.read_text(encoding="utf-8")
    assert claude_settings.set_key("idleCompaction", False) is False
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("had", [True, 0, "false", None])
def test_setting_a_key_replaces_a_different_value(had):
    """False and 0 are equal in Python; a setting is the same only if it is the same JSON."""
    _settings({"idleCompaction": had})
    assert claude_settings.set_key("idleCompaction", False) is True
    assert _saved() == {"idleCompaction": False}


def test_a_missing_file_is_created_with_just_that_key():
    assert claude_settings.set_key("idleCompaction", False) is True
    assert _saved() == {"idleCompaction": False}


def test_the_file_keeps_two_space_indentation_and_a_final_newline():
    _settings({"model": "opus"})
    claude_settings.set_key("idleCompaction", False)
    text = claude_settings.path().read_text(encoding="utf-8")
    assert '\n  "idleCompaction": false' in text and text.endswith("}\n")


@pytest.mark.parametrize("body", ["not json", "[1, 2]", '"a string"', ""])
def test_a_file_we_cannot_read_is_never_clobbered(body):
    path = _settings(body)
    with pytest.raises(ValueError, match="will not be written"):
        claude_settings.set_key("idleCompaction", False)
    with pytest.raises(ValueError, match="will not be written"):
        claude_settings.remove_key("idleCompaction")
    assert path.read_text(encoding="utf-8") == body


def test_a_write_that_fails_at_the_rename_leaves_the_file_and_no_temporary_one(monkeypatch):
    path = _settings({"model": "opus"})

    def refuse(*a, **k):
        raise OSError("the file is open in another program")
    monkeypatch.setattr(claude_settings.os, "replace", refuse)
    with pytest.raises(OSError):
        claude_settings.set_key("idleCompaction", False)
    assert sorted(p.name for p in path.parent.iterdir()) == ["settings.json"]
    assert _saved() == {"model": "opus"}


# --- removing a key ------------------------------------------------------------

def test_removing_a_key_keeps_everything_else():
    _settings({"model": "opus", "idleCompaction": False, "theme": "dark"})
    assert claude_settings.remove_key("idleCompaction") is True
    assert _saved() == {"model": "opus", "theme": "dark"}


def test_removing_a_key_that_is_not_there_writes_nothing():
    path = _settings({"model": "opus"})
    before = path.read_text(encoding="utf-8")
    assert claude_settings.remove_key("idleCompaction") is False
    assert path.read_text(encoding="utf-8") == before


def test_removing_a_key_from_no_file_creates_none():
    assert claude_settings.remove_key("idleCompaction") is False
    assert not claude_settings.path().exists()


def test_removing_the_last_key_leaves_an_empty_object_not_a_missing_file():
    _settings({"idleCompaction": False})
    assert claude_settings.remove_key("idleCompaction") is True
    assert claude_settings.path().read_text(encoding="utf-8") == "{}\n"


def test_a_settings_folder_that_does_not_exist_yet_is_made_whole(tmp_path):
    target = tmp_path / "a" / "b" / ".claude" / "settings.json"
    assert claude_settings.set_key("idleCompaction", False, target) is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"idleCompaction": False}


def test_the_new_contents_are_written_beside_the_file_and_moved_over_it(monkeypatch):
    _settings({"model": "opus"})
    moves = []
    real = claude_settings.os.replace

    def watch(source, target):
        moves.append((source.name, source.parent == target.parent))
        return real(source, target)
    monkeypatch.setattr(claude_settings.os, "replace", watch)
    claude_settings.set_key("idleCompaction", False)
    assert moves == [("settings.json.tmp", True)]
