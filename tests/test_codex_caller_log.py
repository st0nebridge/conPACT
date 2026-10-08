"""
@module tests.test_codex_caller_log
@description Refusal diagnostics stay bounded and never affect tool results.
@input Isolated conPACT state and simulated file failures
@output One replaceable diagnostic per helper, without call arguments or paths
@dependencies conpact.codex_caller_log, conpact.home; stdlib: json, os; pytest
"""
import json
import os

import pytest

from conpact import codex_caller_log, home


def test_refusal_records_only_bounded_identity_evidence():
    evidence = {"attempts": 3, "native": {"parent_pid": 41, "age_seconds": 1},
                "rollouts": [{"id": "thread", "calling": False, "age_seconds": 0}],
                "arguments": {"focus": "private"}, "source": "private", "path": "private"}
    assert codex_caller_log.record(41, "queue_compaction", "no caller", evidence, clock=lambda: 100)
    path = home.HOME / "codex-caller" / (str(os.getpid()) + ".json")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body == {"at": 100, "pid": os.getpid(), "parent_pid": 41,
                    "method": "queue_compaction", "reason": "no caller",
                    "evidence": {k: evidence[k] for k in ("attempts", "native", "rollouts")}}
    assert "private" not in path.read_text(encoding="utf-8")
    assert codex_caller_log.record(41, "compaction_status", "later", {})
    assert len(list(path.parent.glob("*.json"))) == 1
    assert json.loads(path.read_text())["reason"] == "later"


@pytest.mark.parametrize("operation", ["mkdir", "write_text", "replace"])
def test_diagnostic_failure_never_raises_or_leaves_a_temporary(monkeypatch, operation):
    from pathlib import Path
    def refuse(*args, **kwargs):
        raise OSError("denied")
    owner = os if operation == "replace" else Path
    monkeypatch.setattr(owner, operation, refuse)
    assert codex_caller_log.record(41, "queue_compaction", "no caller", {}) is False
    assert not list(home.HOME.glob("codex-caller/*.tmp"))


def test_diagnostic_record_has_a_size_limit():
    assert not codex_caller_log.record(41, "queue_compaction", "no caller",
                                      {"rollouts": ["x" * 9000]})
    assert not list(home.HOME.glob("codex-caller/*"))


def test_non_serializable_diagnostics_are_refused_without_creating_files():
    assert not codex_caller_log.record(41, "queue_compaction", "no caller", {"native": object()})
    assert not list(home.HOME.glob("codex-caller/*"))


def test_a_failed_temporary_cleanup_is_harmless_and_next_write_recovers(monkeypatch):
    from pathlib import Path
    def refuse(*args, **kwargs):
        raise OSError("denied")
    with monkeypatch.context() as blocked:
        blocked.setattr(os, "replace", refuse)
        blocked.setattr(Path, "unlink", refuse)
        assert not codex_caller_log.record(41, "queue_compaction", "no caller", {})
    assert len(list(home.HOME.glob("codex-caller/*.tmp"))) == 1
    assert codex_caller_log.record(41, "queue_compaction", "later", {})
    assert not list(home.HOME.glob("codex-caller/*.tmp"))
