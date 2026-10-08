"""
@module tests.test_keychain
@description Reading Claude Code's login from the macOS Keychain: where it is
             filed, how a split login is put back together, and that nothing it
             reads can leak through an error. Every `security` call is a fake;
             the real Keychain is guarded off in conftest.
@input      conpact.keychain
@output     assertions on the service name, the accounts tried, the reassembly
            and the refusals
@dependencies conpact.keychain; stdlib: base64, hashlib, json, subprocess
"""
import base64
import hashlib
import json
import subprocess

import pytest

from conpact import keychain

# The real runner, captured before the isolation fixture swaps it out.
_REAL_RUN = keychain._run

LOGIN = {"claudeAiOauth": {"accessToken": "sk-ant-oat-secret", "refreshToken": "sk-ant-ort-secret",
                           "expiresAt": 1_900_000_000_000}}


class Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout = returncode, stdout


def keychain_holding(items):
    """A fake `security` answering from {(service, account): secret}."""
    calls = []

    def run(argv):
        calls.append(argv)
        service, account = argv[argv.index("-s") + 1], argv[argv.index("-a") + 1]
        if (service, account) in items:
            return Done(0, items[(service, account)] + "\n")
        return Done(keychain.NOT_FOUND, "")
    return run, calls


SERVICE = "Claude Code-credentials"


class TestWhereTheLoginIsFiled:
    def test_the_default_service_has_no_suffix(self):
        assert keychain.service_name({"HOME": "/Users/me"}) == SERVICE

    def test_a_config_dir_adds_the_first_eight_hex_digits_of_its_hash(self):
        expected = hashlib.sha256(b"/Users/me/alt-claude").hexdigest()[:8]
        assert keychain.service_name({"CLAUDE_CONFIG_DIR": "/Users/me/alt-claude"}) == \
            f"{SERVICE}-{expected}"

    def test_an_empty_config_dir_counts_as_none(self):
        assert keychain.service_name({"CLAUDE_CONFIG_DIR": ""}) == SERVICE

    def test_the_secure_storage_override_wins_over_the_config_dir(self):
        expected = hashlib.sha256(b"/elsewhere").hexdigest()[:8]
        env = {"CLAUDE_CONFIG_DIR": "/Users/me/alt", "CLAUDE_SECURESTORAGE_CONFIG_DIR": "/elsewhere"}
        assert keychain.service_name(env) == f"{SERVICE}-{expected}"

    def test_an_empty_secure_storage_override_means_no_suffix_even_with_a_config_dir(self):
        env = {"CLAUDE_CONFIG_DIR": "/Users/me/alt", "CLAUDE_SECURESTORAGE_CONFIG_DIR": ""}
        assert keychain.service_name(env) == SERVICE

    def test_the_path_is_hashed_in_its_composed_unicode_form(self):
        """Claude Code normalises to NFC first; a decomposed é must hash the same."""
        decomposed, composed = "/Users/rémy", "/Users/rémy"
        assert keychain.service_name({"CLAUDE_CONFIG_DIR": decomposed}) == \
            keychain.service_name({"CLAUDE_CONFIG_DIR": composed})

    def test_the_current_account_is_tried_first_then_the_login_name(self):
        assert keychain.accounts({"USER": "me"}) == ["claude-code-user", "me"]
        assert keychain.accounts({"USER": "claude-code-user"}) == ["claude-code-user"]


class TestReading:
    def test_a_whole_login_is_read_and_parsed(self):
        run, calls = keychain_holding({(SERVICE, "claude-code-user"): json.dumps(LOGIN)})
        assert keychain.read_credentials({"USER": "me"}, runner=run) == LOGIN
        assert calls == [[keychain.SECURITY, "find-generic-password", "-s", SERVICE,
                          "-a", "claude-code-user", "-w"]]

    def test_an_older_release_filed_under_the_login_name_is_found(self):
        run, _ = keychain_holding({(SERVICE, "me"): json.dumps(LOGIN)})
        assert keychain.read_credentials({"USER": "me"}, runner=run) == LOGIN

    def test_no_login_anywhere_is_none_not_an_error(self):
        run, _ = keychain_holding({})
        assert keychain.read_credentials({"USER": "me"}, runner=run) is None

    def test_a_split_login_is_put_back_together(self):
        text = base64.b64encode(json.dumps(LOGIN).encode("utf-8")).decode("ascii")
        parts = [text[i:i + 40] for i in range(0, len(text), 40)]
        items = {(SERVICE, "claude-code-user#m"): json.dumps({"n": len(parts), "l": len(text)})}
        items.update({(SERVICE, f"claude-code-user#{i}"): part for i, part in enumerate(parts)})
        run, _ = keychain_holding(items)
        assert keychain.read_credentials({"USER": "me"}, runner=run) == LOGIN

    def test_a_split_login_with_a_part_missing_is_refused(self):
        items = {(SERVICE, "claude-code-user#m"): json.dumps({"n": 2, "l": 10}),
                 (SERVICE, "claude-code-user#0"): "abcde"}
        run, _ = keychain_holding(items)
        with pytest.raises(keychain.KeychainError, match="part of it is missing"):
            keychain.read_credentials({"USER": "me"}, runner=run)

    @pytest.mark.parametrize("header", ['{"n": 0, "l": 1}', '{"n": 257, "l": 1}', '{"n": 1, "l": 2401}',
                                        '{"n": true, "l": 1}', '[1, 2]', 'not json'])
    def test_a_header_claude_code_would_not_write_is_refused(self, header):
        run, _ = keychain_holding({(SERVICE, "claude-code-user#m"): header})
        with pytest.raises(keychain.KeychainError, match="header"):
            keychain.read_credentials({"USER": "me"}, runner=run)

    @pytest.mark.parametrize("stored", ["not json", "[]", '{"other": 1}'])
    def test_something_that_is_not_a_login_is_refused_without_repeating_it(self, stored):
        run, _ = keychain_holding({(SERVICE, "claude-code-user"): stored})
        with pytest.raises(keychain.KeychainError) as raised:
            keychain.read_credentials({"USER": "me"}, runner=run)
        assert stored not in str(raised.value)


class TestRefusals:
    def test_macos_refusing_is_reported_by_its_exit_code(self):
        run = lambda argv: Done(128, "")                          # noqa: E731 - the user said no
        with pytest.raises(keychain.KeychainError, match="security exit 128"):
            keychain.find(SERVICE, "claude-code-user", run)

    def test_an_unanswered_prompt_is_a_timeout_not_a_hang(self):
        def run(argv):
            raise subprocess.TimeoutExpired(argv, keychain.TIMEOUT)
        with pytest.raises(keychain.KeychainError, match="in time"):
            keychain.find(SERVICE, "claude-code-user", run)

    def test_no_security_command_is_named(self):
        def run(argv):
            raise FileNotFoundError(argv[0])
        with pytest.raises(keychain.KeychainError, match="not available"):
            keychain.find(SERVICE, "claude-code-user", run)

    def test_no_secret_reaches_an_error(self):
        """Every refusal is built from constants and exit codes, never from output."""
        run, _ = keychain_holding({(SERVICE, "claude-code-user"): '{"claudeAiOauth": "sk-ant-oat-secret"}'})
        with pytest.raises(keychain.KeychainError) as raised:
            keychain.read_credentials({"USER": "me"}, runner=run)
        assert "sk-ant" not in str(raised.value)


def test_the_real_runner_is_bounded_and_captures(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return Done()
    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    _REAL_RUN(["security"])
    assert seen == {"argv": ["security"], "capture_output": True, "text": True, "timeout": keychain.TIMEOUT}


def test_the_security_command_is_the_system_one():
    """An absolute path, so nothing earlier on PATH can stand in for it."""
    assert keychain.SECURITY == "/usr/bin/security"
