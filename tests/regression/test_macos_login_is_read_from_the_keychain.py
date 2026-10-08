"""
Regression test for CU-20260922-056 (the macOS login, from the Keychain).

On macOS Claude Code keeps its login in the Keychain rather than in
~/.claude/.credentials.json, so a Mac had no token and could not send a
compaction at all. The token store now reads the Keychain there, ahead of the
file, as Claude Code does - and only reads it:

  1. On macOS the default lookup comes from the Keychain, and says so.
  2. A Keychain login that has expired is refused by name. It is never
     refreshed, because a refresh rotates the refresh token, and a rotated token
     that is not written back into the store Claude Code owns logs Claude Code
     out. Nothing is posted and nothing is written.
  3. With nothing in the Keychain, the file is used, and with neither the
     refusal names both places.
  4. Everywhere else, and wherever a caller names a file, the Keychain is not
     consulted at all.
"""
import json
import time

import pytest

from conpact import token_store


def _login(expires_in_s):
    return {"claudeAiOauth": {"accessToken": "acc", "refreshToken": "ref",
                              "expiresAt": int(time.time() * 1000) + expires_in_s * 1000}}


def _never(*_a, **_k):
    raise AssertionError("must not be called")


def test_on_macos_the_token_comes_from_the_keychain():
    token = token_store.get_access_token(platform="darwin", keychain_reader=lambda: _login(3600))
    assert token == ("acc", False)
    status = token_store.token_status(platform="darwin", keychain_reader=lambda: _login(3600))
    assert (status["source"], status["fresh"], status["can_refresh"]) == ("keychain", True, False)


def test_an_expired_keychain_login_is_refused_and_never_refreshed(monkeypatch):
    monkeypatch.setattr(token_store, "write_credentials", _never)
    with pytest.raises(token_store.TokenError) as raised:
        token_store.get_access_token(platform="darwin", keychain_reader=lambda: _login(-10), post=_never)
    assert str(raised.value) == token_store.KEYCHAIN_EXPIRED


def test_with_nothing_in_the_keychain_the_file_is_used(tmp_path, monkeypatch):
    path = tmp_path / ".credentials.json"
    path.write_text(json.dumps(_login(3600)), encoding="utf-8")
    monkeypatch.setattr(token_store, "CREDENTIALS", path)
    status = token_store.token_status(platform="darwin", keychain_reader=lambda: None)
    assert (status["source"], status["can_refresh"]) == ("file", True)


def test_with_neither_the_refusal_names_both_places(tmp_path, monkeypatch):
    monkeypatch.setattr(token_store, "CREDENTIALS", tmp_path / "absent.json")
    with pytest.raises(token_store.TokenError) as raised:
        token_store.read_credentials(platform="darwin", keychain_reader=lambda: None)
    assert str(raised.value) == token_store.MACOS_NO_LOGIN


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_elsewhere_the_keychain_is_never_consulted(tmp_path, monkeypatch, platform):
    path = tmp_path / ".credentials.json"
    path.write_text(json.dumps(_login(3600)), encoding="utf-8")
    monkeypatch.setattr(token_store, "CREDENTIALS", path)
    assert token_store.token_status(platform=platform, keychain_reader=_never)["source"] == "file"


def test_a_named_file_is_that_file_even_on_macos(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(_login(3600)), encoding="utf-8")
    assert token_store.token_status(path=path, platform="darwin", keychain_reader=_never)["source"] == "file"
