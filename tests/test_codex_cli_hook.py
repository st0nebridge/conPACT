"""The Codex CLI Stop hook acts only below conPACT's own app-server."""
from conpact import codex_cli_hook, codex_host, codex_arming
from types import SimpleNamespace
import io

import pytest


def test_the_recorded_app_server_is_recognised_through_a_shell_parent():
    codex_host.write_record(5000, 41, "token")
    parents = {52: 41}
    assert codex_cli_hook.hosted_by_conpact(52, parents.get) is True


def test_an_unrelated_codex_app_server_is_ignored():
    codex_host.write_record(5000, 41, "token")
    assert codex_cli_hook.hosted_by_conpact(99, lambda _pid: None) is False


def test_non_stop_and_invalid_session_inputs_never_run_anything():
    codex_host.write_record(5000, 41, "token")
    never = lambda _session_id: (_ for _ in ()).throw(AssertionError("must not run"))
    assert codex_cli_hook.run(
        {"hook_event_name": "SessionStart", "session_id": "thread-123"},
        ppid=41, runner=never)["action"] == "skip"
    assert codex_cli_hook.run(
        {"hook_event_name": "Stop", "session_id": "../bad"},
        ppid=41, runner=never)["action"] == "error"


def test_desktop_stop_is_inert_even_with_a_valid_session():
    codex_host.write_record(5000, 41, "token")
    out = codex_cli_hook.run(
        {"hook_event_name": "Stop", "session_id": "thread-123"},
        ppid=90, parent_reader=lambda _pid: None,
        runner=lambda _session_id: (_ for _ in ()).throw(AssertionError("must not run")))
    assert out == {"action": "skip", "reason": "not conPACT's app-server"}


@pytest.mark.parametrize("payload,owned,action", [
    (None, True, "skip"), ({}, True, "skip"),
    ({"hook_event_name": "Stop", "session_id": "t-1"}, False, "skip"),
    ({"hook_event_name": "Stop", "session_id": "../bad"}, True, "error"),
])
def test_detached_stop_preserves_identity_and_input_guards(monkeypatch, payload, owned, action):
    monkeypatch.setattr(codex_cli_hook, "hosted_by_conpact", lambda **kw: owned)
    calls = []
    got = codex_cli_hook.detach_stop(payload, spawner=lambda *a, **k: calls.append(a))
    assert got["action"] == action and calls == []


def test_detach_failure_is_reported_without_blocking_the_hook(monkeypatch):
    monkeypatch.setattr(codex_cli_hook, "hosted_by_conpact", lambda **kw: True)
    def broken(*a, **k):
        raise OSError("could not start worker")
    got = codex_cli_hook.detach_stop({"hook_event_name": "Stop", "session_id": "t-1"}, broken)
    assert got["action"] == "error" and "could not start" in got["reason"]


def test_after_stop_wait_is_bounded_and_never_sends(monkeypatch):
    now, pauses = [0], []
    monkeypatch.setattr(codex_arming, "_turn_state", lambda *a, **k: "running")
    def sleep(seconds):
        pauses.append(seconds)
        now[0] += seconds
    assert codex_arming.wait_after_stop("t-1", lambda: now[0], sleep) is False
    assert 1.9 <= sum(pauses) <= 2.1


def test_after_stop_wait_returns_when_idle_is_recorded(monkeypatch):
    monkeypatch.setattr(codex_arming, "_turn_state", lambda *a, **k: "idle")
    pauses = []
    assert codex_arming.wait_after_stop("t-1", lambda: 0, pauses.append)
    assert pauses == []


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("output,expected", [("41\n", 41), ("0", None), ("unknown", None)])
def test_process_ancestry_queries_are_bounded_and_fail_closed(monkeypatch, platform, output, expected):
    calls = []
    monkeypatch.setattr(codex_cli_hook.sys, "platform", platform)
    monkeypatch.setattr(codex_cli_hook.subprocess, "run", lambda argv, **kw:
                        calls.append((argv, kw)) or SimpleNamespace(stdout=output))
    assert codex_cli_hook._parent_pid(52) == expected
    assert calls[0][1]["timeout"] == 3
    assert calls[0][0][0] == ("powershell" if platform == "win32" else "ps")


def test_missing_ancestry_and_a_chain_without_the_owner_are_inert(monkeypatch):
    def failed(*a, **k):
        raise OSError("process query failed")
    monkeypatch.setattr(codex_cli_hook.subprocess, "run", failed)
    assert codex_cli_hook._parent_pid(52) is None
    assert not codex_cli_hook.hosted_by_conpact(ppid=52, record=None)
    assert not codex_cli_hook.hosted_by_conpact(52, lambda pid: pid + 1, record={"pid": 41})


def test_detached_worker_keeps_the_validated_owner_and_source_environment(monkeypatch):
    codex_host.write_record(5000, 41, "token")
    monkeypatch.setattr(codex_cli_hook.os, "getppid", lambda: 41)
    monkeypatch.setenv("CONPACT_CODEX_OWNER_PID", "999")
    monkeypatch.setenv("PYTHONPATH", "existing-source")
    seen = []
    got = codex_cli_hook.detach_stop({"hook_event_name": "Stop", "session_id": "t-1"},
                                   lambda argv, env: seen.append((argv, env)) or 123)
    assert got["action"] == "detached" and seen[0][1]["CONPACT_CODEX_OWNER_PID"] == "41"
    assert seen[0][1]["PYTHONPATH"].endswith("existing-source")


def test_malformed_stop_input_returns_quietly(monkeypatch, capsys):
    monkeypatch.setattr(codex_cli_hook.sys, "stdin", io.StringIO("invalid"))
    assert codex_cli_hook.main() == 0 and capsys.readouterr().out == ""
