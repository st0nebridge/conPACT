"""
@module conpact.token_store
@description Read the Claude OAuth access token, and refresh it on expiry using
             the same endpoint, client id and rotation the CLI itself uses. The
             token is only ever returned to a caller for use in an Authorization
             header; it is never printed, logged or embedded in output. Callers
             are told whether a refresh was needed, and can ask how fresh the
             stored token is without seeing it.
             Claude Code keeps the login in ~/.claude/.credentials.json on
             Windows and Linux, and in the Keychain on macOS, which it reads
             ahead of the file; so does this (conpact.keychain). The Keychain is
             read-only here: a login from it is used while it is fresh and is
             never refreshed, because a refresh rotates the refresh token and a
             rotated token that is not written back logs Claude Code out
             (D-20260922-046). Claude Code refreshes it on its own next request.
@input      the macOS Keychain, else ~/.claude/.credentials.json
            (claudeAiOauth.accessToken/refreshToken/expiresAt)
@output     a valid access token (with a refreshed flag), or a token status report;
            a refusal's error names the HTTP status and the server's short reason
@dependencies conpact.keychain; stdlib: json, os, pathlib, sys, time, typing, urllib
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import NamedTuple

from . import keychain

CLAUDE_DIR = pathlib.Path(os.path.expanduser("~")) / ".claude"
CREDENTIALS = CLAUDE_DIR / ".credentials.json"

# Verified from the bundled CLI (2.1.275): the refresh grant posts to this
# endpoint with this public client id. Rotation returns a new refresh token,
# which is written back so the credentials file stays the single source of truth
# (the same shape the CLI produces when it refreshes).
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
DEFAULT_SCOPES = ["user:inference", "user:profile"]

# The headers of a refresh that works: the ones a Node client sends with
# fetch's defaults. When a
# refresh was first needed live (2026-09-19), Python's default user agent got
# HTTP 403 and an invented "claude-code/2.1.275" got HTTP 429.
REFRESH_HEADERS = {"Content-Type": "application/json", "Accept": "*/*", "Accept-Language": "*",
                   "Sec-Fetch-Mode": "cors", "User-Agent": "node"}
REASON_CHARS = 120

# Refresh a little before the hard expiry so a call in flight cannot straddle it.
EXPIRY_MARGIN_SECONDS = 60


class TokenError(RuntimeError):
    """The access token could not be read or refreshed."""


class AccessToken(NamedTuple):
    """A usable access token, and whether it had to be refreshed to get it."""

    value: str
    refreshed: bool

    def __repr__(self) -> str:
        # Keep the secret out of tracebacks, debug prints and logs.
        return f"AccessToken(value=<redacted>, refreshed={self.refreshed})"


MACOS_NO_LOGIN = ("no Claude Code login found: none in the macOS Keychain, and no "
                  "~/.claude/.credentials.json")
KEYCHAIN_EXPIRED = ("the login token in the macOS Keychain has expired. conPACT reads the Keychain "
                    "but never writes to it, and a refresh would rotate the token, so refreshing is "
                    "left to Claude Code, which does it on its next request")
KEYCHAIN, FILE = "keychain", "file"


def _load(path=None, platform=None, keychain_reader=None) -> tuple[dict, str]:
    """The credentials, and where they came from: KEYCHAIN or FILE.

    The Keychain is consulted only for the default location on macOS, which is
    where Claude Code keeps the login there. A caller that names a file means
    that file.
    """
    on_mac = path is None and (platform or sys.platform) == "darwin"
    if on_mac:
        try:
            creds = (keychain_reader or keychain.read_credentials)()
        except keychain.KeychainError as exc:
            raise TokenError(str(exc)) from exc
        if creds is not None:
            return creds, KEYCHAIN
    p = path or CREDENTIALS
    try:
        creds = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TokenError(MACOS_NO_LOGIN if on_mac else "could not read the Claude credentials file") from exc
    except (OSError, ValueError) as exc:
        raise TokenError("could not read the Claude credentials file") from exc
    if not isinstance(creds, dict) or not isinstance(creds.get("claudeAiOauth"), dict):
        raise TokenError("credentials file has no claudeAiOauth object")
    return creds, FILE


def read_credentials(path: pathlib.Path | None = None, platform: str | None = None,
                     keychain_reader=None) -> dict:
    """The stored credentials: the Keychain's on macOS, else the file's."""
    return _load(path, platform, keychain_reader)[0]


def token_is_fresh(oauth: dict, now_ms: int | None = None, margin_seconds: int = EXPIRY_MARGIN_SECONDS) -> bool:
    """True when accessToken exists and expiresAt is far enough in the future."""
    if not oauth.get("accessToken"):
        return False
    expires_at = oauth.get("expiresAt")
    if not isinstance(expires_at, (int, float)):
        # No expiry recorded: treat as fresh and let the API be the arbiter.
        return True
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    return now < (expires_at - margin_seconds * 1000)


def token_status(path: pathlib.Path | None = None, now_ms: int | None = None,
                 platform: str | None = None, keychain_reader=None) -> dict:
    """
    How usable the stored token is, without revealing it: whether it is fresh,
    seconds until expiry (negative once expired, None if unrecorded), whether
    conPACT could refresh it, and where it is kept. Reads only; never refreshes.
    A Keychain login is never refreshed here, so it can never be refreshed.
    """
    creds, source = _load(path, platform, keychain_reader)
    oauth = creds["claudeAiOauth"]
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    expires_at = oauth.get("expiresAt")
    expires_in = int((expires_at - now) // 1000) if isinstance(expires_at, (int, float)) else None
    return {
        "fresh": token_is_fresh(oauth, now_ms=now),
        "expires_in_seconds": expires_in,
        "can_refresh": source == FILE and bool(oauth.get("refreshToken")),
        "source": source,
    }


def _why(body: bytes) -> str:
    """A short, readable reason from a refused token request's body (never a token:
    only error responses are read here)."""
    text = " ".join(body.decode("utf-8", "replace").split())
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        error, detail = data.get("error"), data.get("error_description")
        if isinstance(error, dict):  # the API's shape: {"type": "error", "error": {"type", "message"}}
            error, detail = error.get("type"), error.get("message")
        text = ": ".join(str(part) for part in (error, detail) if part)
    elif text.startswith("<"):
        text = "an HTML page (a web firewall?)"
    return text if len(text) <= REASON_CHARS else text[:REASON_CHARS - 1] + "…"


def _post_token(body: dict, timeout: int = 30) -> dict:
    """POST the OAuth token request. Isolated so tests can substitute it."""
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=dict(REFRESH_HEADERS),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise TokenError(f"token refresh returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        reason = _why(exc.read())
        raise TokenError(f"token refresh returned HTTP {exc.code}" + (f": {reason}" if reason else "")) from exc


def refresh(oauth: dict, post=None, now_ms: int | None = None) -> dict:
    """
    Refresh the access token from the stored refresh token.

    Returns a NEW oauth dict (the input is not mutated) carrying the rotated
    tokens and a recomputed expiresAt. Raises if no refresh token is stored.
    """
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        raise TokenError("no refreshToken stored; cannot refresh")
    scopes = oauth.get("scopes") or DEFAULT_SCOPES
    resp = (post or _post_token)({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "scope": " ".join(scopes),
    })
    if not resp.get("access_token"):
        raise TokenError("token refresh response had no access_token")
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    updated = dict(oauth)
    updated["accessToken"] = resp["access_token"]
    if resp.get("refresh_token"):
        updated["refreshToken"] = resp["refresh_token"]
    if resp.get("expires_in") is not None:
        updated["expiresAt"] = now + int(resp["expires_in"]) * 1000
    if resp.get("scope"):
        updated["scopes"] = resp["scope"].split()
    return updated


def write_credentials(creds: dict, path: pathlib.Path | None = None) -> None:
    """
    Atomically write credentials back (temp file + replace) to avoid a torn file.
    On failure the temp file - which holds live tokens - is removed, and the
    error says plainly that the rotated refresh token may now be lost.
    """
    p = path or CREDENTIALS
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(creds, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise TokenError(
            "refreshed credentials could not be saved; the stored refresh token "
            "may now be stale and a fresh login may be needed"
        ) from exc


def get_access_token(
    path: pathlib.Path | None = None,
    allow_refresh: bool = True,
    post=None,
    platform: str | None = None,
    keychain_reader=None,
) -> AccessToken:
    """
    Return a usable access token, refreshing (and persisting) only if it is
    within the expiry margin, and say whether that refresh happened. Refreshing
    is meant to be rare; the refreshed flag is what lets that be measured. A
    login read from the macOS Keychain is never refreshed: an expired one is
    refused, and Claude Code refreshes it itself.
    """
    creds, source = _load(path, platform, keychain_reader)
    oauth = creds["claudeAiOauth"]
    if token_is_fresh(oauth):
        return AccessToken(oauth["accessToken"], False)
    if not allow_refresh:
        token = oauth.get("accessToken")
        if not token:
            raise TokenError("access token is expired and refresh is disabled")
        return AccessToken(token, False)
    if source == KEYCHAIN:
        raise TokenError(KEYCHAIN_EXPIRED)
    updated = refresh(oauth, post=post)
    creds["claudeAiOauth"] = updated
    write_credentials(creds, path)
    return AccessToken(updated["accessToken"], True)


def get_valid_access_token(
    path: pathlib.Path | None = None,
    allow_refresh: bool = True,
    post=None,
) -> str:
    """The token string alone (see get_access_token)."""
    return get_access_token(path=path, allow_refresh=allow_refresh, post=post).value
