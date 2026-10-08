"""
Regression test for CU-20260924-074 (queued compaction works in Codex CLI through a reachable owning app-server).

The Codex CLI Stop hook that `conpact-codex --install` adds runs the one session Codex
names on its stdin, and only below the app-server conPACT recorded. Contributed by
Lance Sandino (pull request #2 of the public repository); moved here from
tests/test_codex_cli_hook.py when it was brought into this history, unchanged.
"""
from conpact import codex_cli_hook, codex_host


def test_stop_runs_the_exact_session_the_hook_supplied():
    codex_host.write_record(5000, 41, "token")
    seen = []
    def record(session_id, **options):
        seen.append((session_id, options))
        return {"action": "armed"}

    out = codex_cli_hook.run(
        {"hook_event_name": "Stop", "session_id": "thread-123"},
        ppid=41, parent_reader=lambda _pid: None,
        runner=record)
    assert seen == [("thread-123", {"via": "Codex Stop hook"})]
    assert out["action"] == "armed"
