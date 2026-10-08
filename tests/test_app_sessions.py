"""Tests for conpact.app_sessions: has the user archived this session?"""
import json

import pytest

from conpact import app_sessions


def _store(tmp_path, archived=(), records=None, install="inst", profile="prof"):
    folder = tmp_path / "Claude" / "claude-code-sessions" / install / profile
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "archived-sessions.idx").write_text(json.dumps({"v": 1, "archived": list(archived)}),
                                                  encoding="utf-8")
    for host, flag in (records or {}).items():
        (folder / f"{host}.json").write_text(json.dumps({"sessionId": host, "isArchived": flag}),
                                             encoding="utf-8")
    return folder


def _env(tmp_path):
    return {"APPDATA": str(tmp_path)}


def test_the_store_lives_under_the_apps_session_folder(tmp_path):
    folder = _store(tmp_path)
    assert app_sessions.store_dirs(_env(tmp_path)) == [folder]


def test_no_store_means_no_folders(tmp_path):
    assert app_sessions.store_dirs(_env(tmp_path)) == []
    assert app_sessions.store_dirs({}) == []


def test_every_install_and_profile_is_read(tmp_path):
    first = _store(tmp_path, ["local_a"], install="i1", profile="p1")
    second = _store(tmp_path, ["local_b"], install="i2", profile="p2")
    assert set(app_sessions.store_dirs(_env(tmp_path))) == {first, second}
    assert app_sessions.archived_ids(_env(tmp_path)) == {"local_a", "local_b"}


def test_a_session_in_the_index_is_archived(tmp_path):
    _store(tmp_path, ["local_a", "local_b"])
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is True
    assert app_sessions.is_archived("local_c", _env(tmp_path)) is False


def test_a_record_saying_archived_counts_even_without_the_index(tmp_path):
    folder = _store(tmp_path, [], {"local_a": True, "local_b": False})
    (folder / "archived-sessions.idx").unlink()
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is True
    assert app_sessions.is_archived("local_b", _env(tmp_path)) is False


def test_the_record_wins_when_it_says_the_session_came_back(tmp_path):
    """Unarchiving rewrites the record; a stale index must not keep the session archived."""
    _store(tmp_path, ["local_a"], {"local_a": False})
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is False


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '{"v": 1}', '{"archived": "local_a"}'])
def test_an_unusable_index_reads_as_not_archived(tmp_path, raw):
    folder = _store(tmp_path, ["local_a"])
    (folder / "archived-sessions.idx").write_text(raw, encoding="utf-8")
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is False


def test_an_unusable_record_falls_back_to_the_index(tmp_path):
    folder = _store(tmp_path, ["local_a"])
    (folder / "local_a.json").write_text("not json", encoding="utf-8")
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is True


def test_nothing_readable_means_not_archived(tmp_path):
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is False
    assert app_sessions.is_archived("local_a", {}) is False


@pytest.mark.parametrize("host", [None, "", 7, "../x", "local_a/b", "a" * 200])
def test_only_a_plain_host_id_is_looked_up(tmp_path, host):
    _store(tmp_path, ["local_a"])
    assert app_sessions.is_archived(host, _env(tmp_path)) is False


def test_the_environment_defaults_to_the_real_one(monkeypatch, tmp_path):
    _store(tmp_path, ["local_a"])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert app_sessions.is_archived("local_a") is True


def test_a_store_that_cannot_be_listed_is_no_store(monkeypatch, tmp_path):
    import pathlib
    _store(tmp_path, ["local_a"])

    def refused(self, pattern):
        raise OSError("access denied")
    monkeypatch.setattr(pathlib.Path, "glob", refused)
    assert app_sessions.store_dirs(_env(tmp_path)) == []
    assert app_sessions.is_archived("local_a", _env(tmp_path)) is False


def test_archived_ids_skips_a_store_whose_index_is_unusable(tmp_path):
    folder = _store(tmp_path, ["local_a"], install="i1", profile="p1")
    _store(tmp_path, [], install="i2", profile="p2")
    (folder / "archived-sessions.idx").write_text("not json", encoding="utf-8")
    assert app_sessions.archived_ids(_env(tmp_path)) == set()


# --- the app's own link to a session ----------------------------------------

def _config(tmp_path, mode="epitaxy", body=None):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"preferences": {"sidebarMode": mode}} if body is None else body)
    path.write_text(text, encoding="utf-8")
    return {"APPDATA": str(tmp_path)}


def test_the_sidebar_mode_comes_from_the_apps_own_config(tmp_path):
    assert app_sessions.sidebar_mode(_config(tmp_path, "something-else")) == "something-else"


@pytest.mark.parametrize("body", [
    {}, {"preferences": {}}, {"preferences": {"sidebarMode": 7}}, {"preferences": {"sidebarMode": "../x"}},
    {"preferences": None}, [1, 2],
])
def test_an_unusable_config_falls_back_to_what_the_app_uses_today(tmp_path, body):
    assert app_sessions.sidebar_mode(_config(tmp_path, body=body)) == app_sessions.DEFAULT_SIDEBAR


def test_no_config_at_all_falls_back_too(tmp_path):
    assert app_sessions.sidebar_mode({"APPDATA": str(tmp_path)}) == app_sessions.DEFAULT_SIDEBAR
    assert app_sessions.sidebar_mode({}) == app_sessions.DEFAULT_SIDEBAR


def test_the_link_names_the_sidebar_and_the_session(tmp_path):
    environ = _config(tmp_path)
    assert app_sessions.session_link("local_a", environ) == "claude://claude.ai/epitaxy/local_a"


@pytest.mark.parametrize("host", [None, "", 7, "../x", "local_a/b", "a" * 200])
def test_no_link_is_made_for_an_id_we_would_not_look_up(tmp_path, host):
    assert app_sessions.session_link(host, _config(tmp_path)) is None


# --- where the app keeps its store, per platform ------------------------------

def test_appdata_wins_wherever_it_is_set(tmp_path):
    """Windows' own variable; a cygwin or msys Python on Windows sees it too."""
    for platform in ("win32", "cygwin", "darwin", "linux"):
        assert app_sessions.app_data({"APPDATA": str(tmp_path)}, platform) == tmp_path


def test_windows_without_appdata_has_nothing_to_read():
    assert app_sessions.app_data({}, "win32") is None
    assert app_sessions.store_dirs({}, "win32") == []


def test_macos_keeps_it_under_application_support(tmp_path):
    assert app_sessions.app_data({"HOME": str(tmp_path)}, "darwin") == \
        tmp_path / "Library" / "Application Support"


def test_linux_uses_the_xdg_config_folder(tmp_path):
    assert app_sessions.app_data({"HOME": str(tmp_path)}, "linux") == tmp_path / ".config"
    xdg = tmp_path / "xdg"
    assert app_sessions.app_data({"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(xdg)}, "linux") == xdg


@pytest.mark.parametrize("platform, parts", [
    ("darwin", ("Library", "Application Support")),
    ("linux", (".config",)),
])
def test_an_archive_is_seen_in_the_platforms_own_folder(tmp_path, platform, parts):
    store = tmp_path.joinpath(*parts, "Claude", "claude-code-sessions", "install", "profile")
    store.mkdir(parents=True)
    (store / "local_a.json").write_text(json.dumps({"isArchived": True}), encoding="utf-8")
    environ = {"HOME": str(tmp_path)}
    assert app_sessions.store_dirs(environ, platform) == [store]
    assert app_sessions.is_archived("local_a", environ, platform) is True
    assert app_sessions.archived_ids(environ, platform) == set()      # no index written


@pytest.mark.parametrize("platform, parts", [
    ("darwin", ("Library", "Application Support")),
    ("linux", (".config",)),
])
def test_the_sidebar_word_is_read_from_the_platforms_own_config(tmp_path, platform, parts):
    config = tmp_path.joinpath(*parts, "Claude")
    config.mkdir(parents=True)
    (config / "claude_desktop_config.json").write_text(
        json.dumps({"preferences": {"sidebarMode": "codeview"}}), encoding="utf-8")
    assert app_sessions.sidebar_mode({"HOME": str(tmp_path)}, platform) == "codeview"
