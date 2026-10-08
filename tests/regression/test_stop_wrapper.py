"""
Regression test for CU-20260919-007 (Stop-hook wrapper), as changed by
CU-20260919-010 (idle notifier).

Runs the real tools/stop_compact.cmd the way Claude Code does - hook JSON on
stdin - against a throwaway home folder, with no network:

  1. With no pending request and the idle notifier switched off, it exits 0
     without starting Python at all (proved by running it with no Python on
     PATH: nothing complains).
  2. With a pending request, Python runs, the request is consumed and the outcome
     is logged, and it still exits 0. The outcome here is "error" because the
     throwaway home has no session records - which is also what guarantees
     nothing is sent.
  3. The first turn end after the upgrade moves what the old folder held into
     ~/.conpact/, and with the off switch moved, the next one starts no Python
     (D-20260923-048).
  4. With the notifier on (the default) and a large, bound session, the hook
     starts a real detached watcher and returns at once, silently, while the
     watcher keeps running on its own; the watcher stands down when its watch is
     cancelled. Nothing is ever shown or sent. "At once" is timed from when the
     hook started the watcher, not from cmd.exe's launch (CU-20260924-068).
"""
import datetime
import json
import os
import pathlib
import subprocess
import time

import pytest

from conpact import compaction, detach

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the Stop-hook wrapper is a Windows .cmd")

ROOT = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools" / "stop_compact.cmd"

# How long the hook may take to return once it has started its watcher. It is
# timed from the `armed_at` the hook writes to the watch just before it starts
# the watcher, so cmd.exe's and Python's start-up and conpact's imports, which
# come first, do not count: on a machine at 100% CPU they took up to 36 s
# (CU-20260924-068). The watcher itself waits most of an hour.
RETURNS_WITHIN = 15


def _run(home, path_env=None, hook=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("CLAUDE")}
    env["USERPROFILE"] = str(home)
    if path_env is not None:
        env["PATH"] = path_env
    cmd_exe = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")
    return subprocess.run(
        [cmd_exe, "/d", "/c", str(WRAPPER)],
        input=json.dumps(hook or {"session_id": "sess-a", "hook_event_name": "Stop"}),
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_notifier_off_and_no_pending_request_exits_without_starting_python(tmp_path):
    state = tmp_path / ".conpact"
    state.mkdir(parents=True)
    (state / "idle-notify.off").write_text("", encoding="utf-8")
    system32 = os.path.join(os.environ["SystemRoot"], "System32")
    proc = _run(tmp_path, path_env=system32)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")  # no "'python' is not recognized"
    assert sorted(p.name for p in state.iterdir()) == ["idle-notify.off"]


@pytest.mark.parametrize("folder", [(".claude", "conpact", "requests"),
                                    (".claude", "clautomatic", "requests")],
                         ids=["folder before the move", "pre-rename folder"])
def test_a_request_in_an_earlier_folder_still_starts_python(tmp_path, folder):
    """With the notifier off, the only thing that makes a turn end start Python is
    a pending request - and a server started before a move writes it to the
    old folder (D-20260922-044). Skipping it here would strand it in silence."""
    state = tmp_path / ".conpact"
    state.mkdir(parents=True)
    (state / "idle-notify.off").write_text("", encoding="utf-8")
    request = compaction.request_compaction("sess-a", requests_dir=tmp_path.joinpath(*folder))
    proc = _run(tmp_path)
    assert (proc.returncode, proc.stdout) == (0, "")
    assert not request.exists()                       # Python ran and claimed it
    entry = json.loads((state / "hook-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (entry["session_id"], entry["action"]) == ("sess-a", "error")


def test_the_first_turn_end_moves_the_old_folder_and_the_next_is_quiet(tmp_path):
    old = tmp_path / ".claude" / "conpact"
    old.mkdir(parents=True)
    (old / "idle-notify.off").write_text("", encoding="utf-8")
    (old / "settings.json").write_text('{"lead_seconds": 600}', encoding="utf-8")
    proc = _run(tmp_path)               # the off switch is not in the new home yet: Python runs
    assert (proc.returncode, proc.stdout) == (0, "")
    new = tmp_path / ".conpact"
    assert (new / "settings.json").read_text(encoding="utf-8") == '{"lead_seconds": 600}'
    assert (new / "idle-notify.off").exists()
    assert not old.exists()
    system32 = os.path.join(os.environ["SystemRoot"], "System32")
    proc = _run(tmp_path, path_env=system32)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_pending_request_is_consumed_and_logged(tmp_path):
    state = tmp_path / ".conpact"
    request = compaction.request_compaction("sess-a", requests_dir=state / "requests")
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert not request.exists()
    entry = json.loads((state / "hook-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["session_id"] == "sess-a"
    assert entry["action"] == "error"


def _log(state):
    path = state / "idle-log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_large_session_gets_a_detached_watcher_that_outlives_the_hook(tmp_path):
    claude = tmp_path / ".claude"
    (claude / "sessions").mkdir(parents=True)
    (claude / "sessions" / "4242.json").write_text(json.dumps({
        "pid": 4242, "sessionId": "sess-a", "bridgeSessionId": "session_x", "name": "Wrapper test",
        "status": "idle", "statusUpdatedAt": int(time.time() * 1000)}), encoding="utf-8")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "isSidechain": False, "timestamp": now,
        "message": {"model": "claude-opus-5", "usage": {
            "input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 200_000,
            "output_tokens": 50, "cache_creation": {"ephemeral_1h_input_tokens": 100,
                                                    "ephemeral_5m_input_tokens": 0}}}}) + "\n",
        encoding="utf-8")

    proc = _run(tmp_path, hook={"session_id": "sess-a", "transcript_path": str(transcript),
                                "hook_event_name": "Stop"})
    returned = time.time()
    state = tmp_path / ".conpact"
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    [armed] = _log(state)
    assert (armed["event"], armed["session_id"], armed["context_tokens"], armed["ttl"]) == (
        "armed", "sess-a", 200_152, 3600)
    pid = armed["watcher_pid"]
    watch = state / "idle" / "watch" / "sess-a.json"
    try:
        armed_at = json.loads(watch.read_text(encoding="utf-8"))["armed_at"]
        assert returned - armed_at < RETURNS_WITHIN  # returned without waiting for the watcher
        assert detach.pid_alive(pid)  # ...which is still running on its own
        watch.unlink()  # cancel the watch
        deadline = time.monotonic() + 20
        while len(_log(state)) < 2 and time.monotonic() < deadline:
            time.sleep(0.2)
        assert [e["event"] for e in _log(state)] == ["armed", "cancelled"]
    finally:
        if detach.pid_alive(pid):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
