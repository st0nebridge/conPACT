"""
@module conpact.keychain
@description Claude Code's login, read from the macOS Keychain. On Windows and
             Linux Claude Code keeps it in ~/.claude/.credentials.json; on macOS
             it keeps the same JSON in the Keychain instead, and this module reads
             it back - and only reads. Writing is deliberately absent: a refresh
             rotates the refresh token, and conPACT writing a rotated token into
             the store Claude Code owns is a standing credential write this tool
             has no business making (D-20260922-046).

             Where the login lives was read from Claude Code's own binary
             (2026-09-22), not assumed:
             - service: "Claude Code" + the OAuth file suffix ("" in production)
               + "-credentials", plus "-" and the first 8 hex digits of the
               SHA-256 of the config directory when CLAUDE_CONFIG_DIR (or
               CLAUDE_SECURESTORAGE_CONFIG_DIR) names one;
             - account: "claude-code-user";
             - a login too large for one item is split: "<account>#m" holds
               {"n": chunks, "l": length}, "<account>#0".."#n-1" hold base64 text
               of that length, which decodes to the JSON.
             Releases before that account name used the macOS login name, which
             third-party tools document; it is tried second, because a stale
             login found there is still refused by the freshness check.

             The read goes through /usr/bin/security, so macOS may ask once
             whether to allow it. It is bounded, and no value it returns is ever
             logged, printed or put in an error.
@input      the process environment; a runner for the `security` command
@output     the credentials dict ({"claudeAiOauth": {...}}); KeychainError
@dependencies stdlib: base64, getpass, hashlib, json, os, subprocess, unicodedata
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import subprocess
import unicodedata

SECURITY = "/usr/bin/security"
SERVICE_PREFIX = "Claude Code"
OAUTH_FILE_SUFFIX = ""          # production; "-custom-oauth" / "-local-oauth" are not ours
SERVICE_KIND = "-credentials"
ACCOUNT = "claude-code-user"
META = "m"
CHUNK_CHARS = 2400
MAX_CHUNKS = 256
NOT_FOUND = 44                  # errSecItemNotFound, as `security` reports it
TIMEOUT = 45.0                  # long enough to answer macOS's prompt, short of the hook's 90 s


class KeychainError(RuntimeError):
    """The login could not be read from the Keychain. Never carries a value."""


def service_name(environ=None) -> str:
    """The Keychain service Claude Code files its login under, for this environment."""
    env = os.environ if environ is None else environ
    secure = env.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    config = env.get("CLAUDE_CONFIG_DIR")
    if secure is not None:
        plain, basis = not secure, secure
    else:
        plain = not config
        basis = config if config is not None else os.path.join(
            env.get("HOME") or os.path.expanduser("~"), ".claude")
    suffix = "" if plain else "-" + hashlib.sha256(
        unicodedata.normalize("NFC", basis).encode("utf-8")).hexdigest()[:8]
    return f"{SERVICE_PREFIX}{OAUTH_FILE_SUFFIX}{SERVICE_KIND}{suffix}"


def accounts(environ=None) -> list[str]:
    """The accounts to look under, current release first."""
    env = os.environ if environ is None else environ
    try:
        login = env.get("USER") or getpass.getuser()
    except (OSError, KeyError):
        login = None
    return [ACCOUNT] + ([login] if login and login != ACCOUNT else [])


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)


def find(service: str, account: str, runner=None):
    """One item's secret, or None when there is no such item."""
    try:
        done = (runner or _run)([SECURITY, "find-generic-password", "-s", service, "-a", account, "-w"])
    except subprocess.TimeoutExpired as exc:
        raise KeychainError("macOS did not release the login from the Keychain in time "
                            "(was its prompt left unanswered?)") from exc
    except OSError as exc:
        raise KeychainError("the macOS `security` command is not available") from exc
    if done.returncode == NOT_FOUND:
        return None
    if done.returncode != 0:
        raise KeychainError(f"macOS refused the Keychain read (security exit {done.returncode})")
    return (done.stdout or "").rstrip("\n")


def _chunk_header(text):
    """{"n", "l"} when the header is one Claude Code would have written, else None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    n, length = data.get("n"), data.get("l")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (n, length)):
        return None
    if not (0 < n <= MAX_CHUNKS and 0 < length <= n * CHUNK_CHARS):
        return None
    return n, length


def _parse(text):
    try:
        creds = json.loads(text)
    except ValueError as exc:
        raise KeychainError("the login in the Keychain is not the JSON Claude Code writes") from exc
    if not isinstance(creds, dict) or not isinstance(creds.get("claudeAiOauth"), dict):
        raise KeychainError("the login in the Keychain has no claudeAiOauth object")
    return creds


def _read_account(service: str, account: str, runner):
    whole = find(service, account, runner)
    if whole:
        return _parse(whole)
    header_text = find(service, f"{account}#{META}", runner)
    if header_text is None:
        return None
    header = _chunk_header(header_text)
    if header is None:
        raise KeychainError("the Keychain holds a split login whose header is not one Claude Code writes")
    count, length = header
    parts = [find(service, f"{account}#{index}", runner) for index in range(count)]
    joined = "".join(part for part in parts if part is not None)
    if any(part is None for part in parts) or len(joined) != length:
        raise KeychainError("the login in the Keychain is split and a part of it is missing")
    try:
        text = base64.b64decode(joined).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise KeychainError("the split login in the Keychain does not decode") from exc
    return _parse(text)


def read_credentials(environ=None, runner=None) -> dict | None:
    """Claude Code's credentials from the Keychain, or None when it holds none."""
    service = service_name(environ)
    for account in accounts(environ):
        creds = _read_account(service, account, runner)
        if creds is not None:
            return creds
    return None
