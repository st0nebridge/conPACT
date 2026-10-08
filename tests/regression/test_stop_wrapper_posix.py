"""
Regression test for CU-20260922-055 (the Stop hook on macOS and Linux).

tools/stop_compact.cmd was the only way to run the Stop hook, so the whole of
conPACT's Claude Code side stopped at Windows. tools/stop_compact.sh is its twin,
and this runs the real script through a real `sh` the way Claude Code does - hook
JSON on stdin - against a throwaway home folder, with no network:

  1. With no pending request and the idle notifier switched off, it exits 0
     without starting Python (proved by naming an interpreter that does not
     exist: nothing complains).
  2. A request in any of the three requests folders - conPACT's own home, or
     the two that MCP servers started before a move may still write to
     (D-20260922-044, D-20260923-048) - makes it start Python, which claims the
     request and logs the outcome.
  3. It exits 0 whatever happens, and writes nothing to stdout.
  4. The first turn end after the upgrade moves what the old folder held into
     ~/.conpact/; with the off switch moved, the next one starts no Python.

On Linux and macOS `sh` is /bin/sh. On Windows it is Git's, when installed, which
is a real POSIX shell, so the script is exercised on every machine the suite
runs on rather than only on the platforms it is for.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from conpact import compaction

ROOT = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools" / "stop_compact.sh"


def _find_sh():
    found = shutil.which("sh")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if base:
            candidate = pathlib.Path(base) / "Git" / "bin" / "sh.exe"
            if candidate.is_file():
                return str(candidate)
    return None


SH = _find_sh()
pytestmark = pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")


def _run(home, python=None, hook=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "CONPACT"))}
    env["HOME"] = str(home)             # what the script reads
    env["USERPROFILE"] = str(home)      # what Python's expanduser reads on Windows
    env["CONPACT_PYTHON"] = python or sys.executable
    return subprocess.run(
        [SH, str(WRAPPER)],
        input=json.dumps(hook or {"session_id": "sess-a", "hook_event_name": "Stop"}),
        capture_output=True, text=True, env=env, timeout=60,
    )


def _silence_the_notifier(home):
    state = home / ".conpact"
    state.mkdir(parents=True, exist_ok=True)
    (state / "idle-notify.off").write_text("", encoding="utf-8")
    return state


def test_the_script_is_lf_only_and_executable_in_git():
    """A CR would make every line end in a stray character under sh, and a
    checkout without the executable bit could not be named as a hook command."""
    assert bytes([13]) not in WRAPPER.read_bytes()
    staged = subprocess.run(["git", "ls-files", "-s", str(WRAPPER.relative_to(ROOT))], cwd=ROOT,
                            capture_output=True, text=True)
    if staged.returncode != 0 or not staged.stdout:
        pytest.skip("not a git checkout")
    assert staged.stdout.split()[0] == "100755"


def test_notifier_off_and_no_pending_request_starts_no_python(tmp_path):
    state = _silence_the_notifier(tmp_path)
    proc = _run(tmp_path, python=str(tmp_path / "no-such-python"))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert sorted(p.name for p in state.iterdir()) == ["idle-notify.off"]


@pytest.mark.parametrize("folder", [(".conpact", "requests"), (".claude", "conpact", "requests"),
                                    (".claude", "clautomatic", "requests")],
                         ids=["home", "folder before the move", "pre-rename folder"])
def test_a_pending_request_in_any_folder_is_claimed_and_logged(tmp_path, folder):
    state = _silence_the_notifier(tmp_path)
    request = compaction.request_compaction("sess-a", requests_dir=tmp_path.joinpath(*folder))
    proc = _run(tmp_path)
    assert (proc.returncode, proc.stdout) == (0, "")
    assert not request.exists()
    entry = json.loads((state / "hook-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    # "error": the throwaway home has no session records, which is also what
    # guarantees nothing is sent anywhere.
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
    proc = _run(tmp_path, python=str(tmp_path / "no-such-python"))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_a_missing_interpreter_still_exits_zero(tmp_path):
    compaction.request_compaction("sess-a", requests_dir=tmp_path / ".conpact" / "requests")
    proc = _run(tmp_path, python=str(tmp_path / "no-such-python"))
    assert (proc.returncode, proc.stdout) == (0, "")
