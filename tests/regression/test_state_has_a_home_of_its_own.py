"""
Regression test for CU-20260923-058 (conPACT's state has a home of its own).

Everything conPACT owns lived in ~/.claude/conpact/, a folder inside Claude
Code's, although part of it belongs to ChatGPT Desktop threads, and a machine
with only ChatGPT Desktop got a ~/.claude folder for nothing but conPACT. It now
lives in ~/.conpact/, and where that is depends on neither app. The contract:

  1. Every file conPACT writes - requests, logs, settings, the idle state, the
     Codex records - is under ~/.conpact/, and the module that says so imports
     nothing but the standard library.
  2. What was in the old folder is moved once, by the first conPACT process to
     start after the upgrade: choices and records are moved, a log is appended
     to one already there, nothing in the new home is overwritten, and the old
     folder is removed once it is empty.
  3. A request queued by a process started before the move is still claimed and
     can still be withdrawn: requests are never moved, because the server that
     wrote one may yet cancel it where it put it.
  4. What a running process keeps writing in the old folder - a watch's marker,
     a toast's slot, the sidecar's heartbeat - is left to it, and removed once
     it is older than anything that could still be using it.
  5. The sidecar heartbeat is read from both folders; the fresher one wins.
  6. Both Stop wrappers look for a request in all three folders, and for the off
     switch in the new home.
  7. Every entry point that can be the first conPACT process on a machine makes
     the move before it reads anything.
  8. No test, and no process a test starts, sees the real home. The fixture's
     patched constants never reach a child process, and on 2026-09-23 one test
     that ran `tools/settings.py --help` did the move on the user's live folder.
"""
import ast
import json
import os
import pathlib
import sys
import time

import pytest

from conpact import (closure_hook, codex_active, codex_host, codex_inject, codex_sidecar, compaction,
                     home, idle_state, settings)

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "conpact"


# 1 -------------------------------------------------------------------------

@pytest.mark.real_paths
def test_1_every_state_path_is_under_dot_conpact():
    user = pathlib.Path(os.path.expanduser("~"))
    expected = user / ".conpact"
    assert home.HOME == expected
    assert compaction.STATE_DIR == expected
    assert compaction.REQUESTS_DIR == expected / "requests"
    for path in (settings.settings_path(), idle_state.off_switch_path(), idle_state.log_path(),
                 closure_hook.LOG_PATH, codex_host.record_path(), codex_inject.record_path(),
                 codex_active.record_path(), codex_sidecar.record_path()):
        assert path.parent == expected, path
    assert idle_state.auto_path("s1").parents[2] == expected
    assert (user / ".claude") not in expected.parents


def test_1_the_home_module_imports_only_the_standard_library():
    tree = ast.parse((SRC / "home.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "home.py must not import a conPACT module"
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


# 2 -------------------------------------------------------------------------

def _put(base, relative, text="x", age=0.0):
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if age:
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
    return path


def test_2_choices_records_and_logs_are_moved_and_the_old_folder_goes(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for relative in ("settings.json", "idle-notify.off", "hook-log.jsonl", "idle-log.jsonl",
                     "codex-host.json", "codex-sidecar.json", "idle/auto/s1", "idle/mute/s1.json",
                     "idle/hold/s1.json"):
        _put(old, relative, text=relative)
    moved = home.migrate(previous=old, home=new)
    assert sorted(moved) == sorted(["settings.json", "idle-notify.off", "hook-log.jsonl",
                                    "idle-log.jsonl", "codex-host.json", "codex-sidecar.json",
                                    "idle/auto/s1", "idle/mute/s1.json", "idle/hold/s1.json"])
    assert (new / "idle" / "mute" / "s1.json").read_text(encoding="utf-8") == "idle/mute/s1.json"
    assert not old.exists()


def test_2_nothing_in_the_new_home_is_overwritten(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _put(old, "settings.json", '{"lead_seconds": 600}')
    _put(new, "settings.json", '{"lead_seconds": 900}')
    _put(old, "idle/auto/s1", "early")
    _put(new, "idle/auto/s1", "expiry")
    home.migrate(previous=old, home=new)
    assert (new / "settings.json").read_text(encoding="utf-8") == '{"lead_seconds": 900}'
    assert (new / "idle" / "auto" / "s1").read_text(encoding="utf-8") == "expiry"
    assert not old.exists()                  # the superseded copies went with it


def test_2_a_log_already_in_the_new_home_gets_the_old_lines_appended(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _put(old, "idle-log.jsonl", '{"event": "armed"}\n')
    _put(new, "idle-log.jsonl", '{"event": "compacted"}\n')
    home.migrate(previous=old, home=new)
    assert (new / "idle-log.jsonl").read_text(encoding="utf-8").splitlines() == [
        '{"event": "compacted"}', '{"event": "armed"}']


def test_2_with_no_old_folder_nothing_happens(tmp_path):
    assert home.migrate(previous=tmp_path / "absent", home=tmp_path / "new") == []
    assert not (tmp_path / "new").exists()


def test_2_a_second_pass_finds_nothing_to_move(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _put(old, "settings.json")
    assert home.migrate(previous=old, home=new) == ["settings.json"]
    assert home.migrate(previous=old, home=new) == []


def test_2_it_never_raises(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    _put(old, "settings.json")

    def refuse(*_a, **_k):
        raise PermissionError("locked")
    monkeypatch.setattr(home.os, "link", refuse)
    monkeypatch.setattr(home.shutil, "copy2", refuse)
    assert home.migrate(previous=old, home=new) == []
    assert (old / "settings.json").exists()   # left where it was, to try again next time


# 3 -------------------------------------------------------------------------

def test_3_a_request_in_the_old_folder_is_left_there_and_still_claimed(tmp_path, monkeypatch):
    old = tmp_path / "old"
    monkeypatch.setattr(compaction, "PREVIOUS_REQUESTS_DIR", old / "requests")
    request = compaction.request_compaction("sess-a", focus="keep", requests_dir=old / "requests")
    home.migrate(previous=old, home=tmp_path / "new")
    assert request.exists()
    assert compaction.pending_request("sess-a")["focus"] == "keep"
    assert compaction.consume_request("sess-a")["focus"] == "keep"
    assert not request.exists()


def test_3_a_request_in_the_old_folder_can_still_be_withdrawn(tmp_path, monkeypatch):
    old = tmp_path / "old"
    monkeypatch.setattr(compaction, "PREVIOUS_REQUESTS_DIR", old / "requests")
    request = compaction.request_compaction("sess-a", requests_dir=old / "requests")
    assert compaction.cancel_request("sess-a") is True
    assert not request.exists()


# 4 -------------------------------------------------------------------------

@pytest.mark.parametrize("relative", ["idle/watch/s1.json", "idle/toasts/slot-0", "codex-active.json"])
def test_4_what_a_running_process_still_writes_is_left_to_it(tmp_path, relative):
    old, new = tmp_path / "old", tmp_path / "new"
    left = _put(old, relative)
    assert home.migrate(previous=old, home=new) == []
    assert left.exists()
    assert not (new / relative).exists()


@pytest.mark.parametrize("relative", ["idle/watch/s1.json", "idle/toasts/slot-0", "codex-active.json"])
def test_4_and_removed_once_nothing_could_still_be_using_it(tmp_path, relative):
    old = tmp_path / "old"
    _put(old, relative, age=home.STALE_AFTER + 60)
    home.migrate(previous=old, home=tmp_path / "new")
    assert not old.exists()


# 5 -------------------------------------------------------------------------

def test_5_the_fresher_heartbeat_wins(tmp_path, monkeypatch):
    new_home, old_home = tmp_path / "new", tmp_path / "old"
    monkeypatch.setattr(home, "HOME", new_home)
    monkeypatch.setattr(home, "PREVIOUS", old_home)
    monkeypatch.setattr(compaction, "STATE_DIR", new_home)
    now = time.time()
    _put(new_home, codex_active.RECORD, json.dumps({"threads": ["new"], "calling": [], "at": now - 600}))
    _put(old_home, codex_active.RECORD, json.dumps({"threads": ["old"], "calling": [], "at": now - 5}))
    assert codex_active.read()["threads"] == ["old"]      # a pre-upgrade sidecar, still running
    _put(new_home, codex_active.RECORD, json.dumps({"threads": ["new"], "calling": [], "at": now}))
    assert codex_active.read()["threads"] == ["new"]


# 6 -------------------------------------------------------------------------

def test_6_the_windows_wrapper_checks_all_three_folders_and_the_new_off_switch():
    text = (ROOT / "tools" / "stop_compact.cmd").read_text(encoding="utf-8")
    for folder in (r"%USERPROFILE%\.conpact\requests\*.json",
                   r"%USERPROFILE%\.claude\conpact\requests\*.json",
                   r"%USERPROFILE%\.claude\clautomatic\requests\*.json"):
        assert f'if not exist "{folder}"' in text, folder
    assert r'if exist "%USERPROFILE%\.conpact\idle-notify.off" exit /b 0' in text


def test_6_the_posix_wrapper_checks_all_three_folders_and_the_new_off_switch():
    text = (ROOT / "tools" / "stop_compact.sh").read_text(encoding="utf-8")
    for folder in ('"$HOME/.conpact/requests/"*.json', '"$HOME/.claude/conpact/requests/"*.json',
                   '"$HOME/.claude/clautomatic/requests/"*.json'):
        assert folder in text, folder
    assert '[ -e "$HOME/.conpact/idle-notify.off" ]' in text


# 7 -------------------------------------------------------------------------

ENTRY_POINTS = ["cli", "closure_hook", "codex_arming", "codex_remote_cli", "codex_sidecar",
                "mcp_server", "settings_cli", "settings_window"]


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_7_each_entry_point_moves_the_state_first(module):
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    [main] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    first = main.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        first = main.body[1]                                  # past a docstring
    call = first.value if isinstance(first, ast.Expr) else None
    assert isinstance(call, ast.Call) and ast.unparse(call.func) == "home.migrate", ast.unparse(first)


# 8 -------------------------------------------------------------------------

def test_8_no_process_a_test_starts_sees_the_real_home():
    """The move is the first thing every entry point does, so a child process
    that inherited the real home would move the user's live state - which one
    did, on 2026-09-23. The suite runs under a throwaway home instead."""
    import subprocess

    import conftest
    child = subprocess.run([sys.executable, "-c", "import os; print(os.path.expanduser('~'))"],
                           capture_output=True, text=True, timeout=60)
    seen = child.stdout.strip()
    assert os.path.normcase(seen) == os.path.normcase(conftest.FAKE_HOME)
    assert os.path.normcase(seen) != os.path.normcase(conftest.REAL_HOME)
    assert os.path.normcase(str(home.HOME.parent)) == os.path.normcase(conftest.FAKE_HOME) or \
        home.HOME.parent.name.startswith("home")          # the fixture's own isolation, per test
