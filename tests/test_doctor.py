"""
@module tests.test_doctor
@description What each of the doctor's checks reports - its level, name and
             detail - on each of its real branches; the order checks() lists
             them in; and what main and `python -m conpact.doctor` print and
             exit with.
@input      conpact.doctor, with the environment, the runner and Codex's folder
            injected: no real Codex install, sidecar, app-server or Keychain is read
@output     assertions on every Check the report can carry
@dependencies conpact.doctor, conpact.claude_idle_compaction, conpact.claude_settings,
              conpact.codex_cli, conpact.codex_home, conpact.codex_host,
              conpact.codex_sidecar_install, conpact.codex_threads, conpact.settings,
              conpact.token_store; stdlib: dataclasses, json, os, platform, runpy,
              shutil, sqlite3, subprocess, types, warnings
"""
import dataclasses
import json
import os
import platform
import runpy
import shutil
import sqlite3
import subprocess
import types
import warnings

import pytest

from conpact import claude_idle_compaction as cic
from conpact import (claude_settings, codex_cli, codex_home, codex_host, codex_sidecar_install,
                     codex_threads, doctor, settings, token_store)

Check = doctor.Check


def test_lines_keep_codex_and_claude_credentials_distinct():
    report = doctor.lines([
        doctor.Check("OK", "Codex login", "Logged in using ChatGPT"),
        doctor.Check("INFO", "Claude Code login", "not configured; optional"),
    ])
    text = "\n".join(report)
    assert "Codex login: Logged in using ChatGPT" in text
    assert "Claude Code login: not configured; optional" in text


def test_a_failure_controls_the_exit_status(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "checks", lambda: [doctor.Check("FAIL", "x", "bad")])
    assert doctor.main() == 1
    assert "[FAIL] x: bad" in capsys.readouterr().out


def test_an_informational_missing_claude_login_is_not_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "checks", lambda: [
        doctor.Check("OK", "Codex login", "ready"),
        doctor.Check("INFO", "Claude Code login", "not configured"),
    ])
    assert doctor.main() == 0
    assert "[INFO] Claude Code login" in capsys.readouterr().out


def _switch(mode):
    path = cic.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cachedGrowthBookFeatures": {cic.FLAG: {"mode": mode}}}), encoding="utf-8")


def _opt_out():
    claude_settings.set_key("idleCompaction", False)


@pytest.mark.parametrize("mode, opted_out, toast, level, detail", [
    ("compact", False, True, "WARN", "on, beside conPACT's idle toast: Claude Code compacts large idle "
                                     "sessions without asking; choose one on the Claude Code tab of the settings"),
    ("compact", False, False, "OK", "on; conPACT's idle toast is off"),
    ("compact", True, True, "OK", "off (idleCompaction: false); Anthropic's switch on"),
    ("off", False, True, "OK", "not running; Anthropic's switch off"),
    ("log", False, True, "OK", "not running; Anthropic's switch logging only, not compacting"),
    (None, False, True, "INFO", "not running; Anthropic's switch not found"),
])
def test_the_report_says_whether_claude_codes_own_idle_compaction_runs(mode, opted_out, toast, level, detail):
    if mode:
        _switch(mode)
    if opted_out:
        _opt_out()
    if not toast:
        settings.save({settings.TOGGLE: False})
    check = doctor._claude_idle({})
    assert check == doctor.Check(level, "Claude Code idle compaction", detail)


def test_the_report_includes_it(monkeypatch):
    monkeypatch.setattr(doctor, "_codex_login", lambda runner: doctor.Check("OK", "Codex login", "x"))
    monkeypatch.setattr(doctor, "_mcp_config", lambda env: doctor.Check("OK", "MCP", "x"))
    monkeypatch.setattr(doctor, "_sidecar", lambda env: [])
    monkeypatch.setattr(doctor, "_codex_cli", lambda env: [])
    monkeypatch.setattr(doctor, "_codex_state", lambda env: doctor.Check("OK", "Codex state", "x"))
    _switch("compact")
    found = doctor.checks(environ={"DISABLE_AUTO_COMPACT": "1"})
    assert found[-1] == doctor.Check("OK", "Claude Code idle compaction", "not running; Anthropic's switch on")


def test_a_check_is_a_value_that_cannot_be_changed():
    check = Check("OK", "Codex login", "ready")
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.level = "FAIL"
    assert {check, Check("OK", "Codex login", "ready")} == {check}


# --- Codex login -----------------------------------------------------------

CODEX = "/opt/codex/bin/codex"


def _codex_on_path(monkeypatch, where=CODEX):
    """`shutil.which` finds codex alone, so a lookup under any other name finds nothing."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: where if name == "codex" else None)


class _Runner:
    """Stands in for subprocess.run: records each call, then raises or answers."""

    def __init__(self, returncode=0, stdout="", stderr="", error=None):
        self.calls = []
        self.answer = subprocess.CompletedProcess([CODEX], returncode, stdout, stderr)
        self.error = error

    def __call__(self, argv, **options):
        self.calls.append((argv, options))
        if self.error is not None:
            raise self.error
        return self.answer


def test_codex_login_fails_when_codex_is_not_on_path(monkeypatch):
    _codex_on_path(monkeypatch, None)
    runner = _Runner()
    assert doctor._codex_login(runner) == Check("FAIL", "Codex login", "codex is not on PATH")
    assert runner.calls == []


def test_codex_login_asks_the_codex_on_path_for_its_own_status(monkeypatch):
    _codex_on_path(monkeypatch)
    runner = _Runner(stdout="Logged in using ChatGPT\n")
    doctor._codex_login(runner)
    assert runner.calls == [([CODEX, "login", "status"],
                             {"capture_output": True, "text": True, "timeout": 30})]


@pytest.mark.parametrize("returncode, stdout, stderr, level, detail", [
    # Logged in: what codex printed, on one line; a warning on stderr is not the answer.
    (0, "Logged in using ChatGPT\n", "a warning", "OK", "Logged in using ChatGPT"),
    (0, "Logged in\n   using an API key  ", None, "OK", "Logged in using an API key"),
    (0, "", "", "OK", "authenticated (codex login status exited 0)"),
    (0, None, None, "OK", "authenticated (codex login status exited 0)"),
    # Not logged in: the error first, then anything it printed besides.
    (1, "Run codex login\n", "Not logged in\n", "FAIL", "Not logged in Run codex login"),
    (1, None, "Not logged in", "FAIL", "Not logged in"),
    (1, "Not logged in", None, "FAIL", "Not logged in"),
    (1, None, None, "FAIL", "codex login status exited 1"),
    (2, "", " \n", "FAIL", "codex login status exited 2"),
])
def test_codex_login_reports_what_codex_said(monkeypatch, returncode, stdout, stderr, level, detail):
    _codex_on_path(monkeypatch)
    check = doctor._codex_login(_Runner(returncode, stdout, stderr))
    assert check == Check(level, "Codex login", detail)


@pytest.mark.parametrize("error", [OSError("no such file"), subprocess.TimeoutExpired([CODEX], 30)])
def test_codex_login_fails_when_its_status_cannot_run(monkeypatch, error):
    _codex_on_path(monkeypatch)
    check = doctor._codex_login(_Runner(error=error))
    assert check == Check("FAIL", "Codex login", "codex login status could not run")


# --- Codex MCP -------------------------------------------------------------

CONFIGURED = Check("OK", "Codex MCP", "conpact is configured")
MISSING = Check("FAIL", "Codex MCP", "conpact is missing from config.toml")


def _codex_folder(tmp_path, config=None):
    """An environment whose CODEX_HOME is `tmp_path`, holding `config` as its config.toml."""
    if config is not None:
        (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    return {"CODEX_HOME": str(tmp_path)}


@pytest.mark.parametrize("config, expected", [
    ('[mcp_servers.conpact]\ncommand = "python"\nargs = ["-m", "conpact.mcp_server"]\n', CONFIGURED),
    (None, MISSING),                                                   # no config.toml
    ("[mcp_servers.conpact\n", MISSING),                               # not TOML
    ('model = "gpt-6"\n', MISSING),                                    # no MCP servers at all
    ('[mcp_servers.other]\ncommand = "python"\n', MISSING),            # another server only
    ('[mcp_servers.conpact]\nargs = ["-m", "conpact.mcp_server"]\n', MISSING),   # no command
    ('[mcp_servers.conpact]\ncommand = ""\n', MISSING),                # an empty command
    ('[mcp_servers]\nconpact = "python"\n', MISSING),                  # not a table
    ('mcp_servers = "python"\n', MISSING),                             # mcp_servers not a table
    ('mcp_servers = ["conpact"]\n', MISSING),                          # ... an array
    ('mcp_servers = 1\n', MISSING),                                    # ... a number
])
def test_codex_mcp_reads_conpacts_entry_in_codexs_config(tmp_path, config, expected):
    assert doctor._mcp_config(_codex_folder(tmp_path, config)) == expected


def test_codex_mcp_reads_the_codex_home_this_process_was_given(tmp_path, monkeypatch):
    _codex_folder(tmp_path, '[mcp_servers.conpact]\ncommand = "python"\n')
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert doctor._mcp_config() == CONFIGURED


# --- ChatGPT Desktop sidecar -----------------------------------------------

SELECTED = r"C:\Users\me\AppData\Local\OpenAI\Codex\bin\26.415.1\codex.exe"
OLDER = r"C:\Users\me\AppData\Local\OpenAI\Codex\bin\26.401.0\codex.exe"
HEALTHY = {"platform": "win32", "installed": True, "sidecar_running": True,
           "codex_selected": SELECTED, "codex_newest": SELECTED, "codex_bundle_version": "26.415.1",
           # Read only on macOS: Windows has one environment, so this is never reported there.
           "env_discrepancy": True, "derived_override_paths": []}
NOTHING = {"platform": "linux", "installed": False, "sidecar_running": False,
           "codex_selected": None, "codex_newest": None, "codex_bundle_version": None,
           "env_discrepancy": None, "derived_override_paths": None}


def _sidecar_status(monkeypatch, status):
    """codex_sidecar_install.status answers `status`; returns the environments it was asked with."""
    asked = []

    def fake(environ=None, **_):
        asked.append(environ)
        return status

    monkeypatch.setattr(codex_sidecar_install, "status", fake)
    return asked


def test_a_healthy_sidecar_reports_three_oks(monkeypatch):
    env = {"CODEX_HOME": "elsewhere"}
    asked = _sidecar_status(monkeypatch, HEALTHY)
    assert doctor._sidecar(env) == [
        Check("OK", "ChatGPT Desktop sidecar", "installed"),
        Check("OK", "ChatGPT Desktop connection", "sidecar is running"),
        Check("OK", "Bundled Codex", f"next launch selects 26.415.1: {SELECTED}"),
    ]
    assert asked == [env]


def test_no_sidecar_reports_what_to_do(monkeypatch):
    _sidecar_status(monkeypatch, NOTHING)
    assert doctor._sidecar({}) == [
        Check("FAIL", "ChatGPT Desktop sidecar", "not installed"),
        Check("FAIL", "ChatGPT Desktop connection", "sidecar is not running; restart ChatGPT Desktop"),
        Check("WARN", "Bundled Codex", "next launch does not select the newest installed build: not found"),
    ]


def test_an_older_bundled_codex_is_a_warning(monkeypatch):
    _sidecar_status(monkeypatch, {**HEALTHY, "codex_selected": OLDER})
    assert doctor._sidecar({})[2] == Check(
        "WARN", "Bundled Codex", f"next launch does not select the newest installed build: {OLDER}")


def test_a_bundled_codex_of_no_known_version_is_still_the_newest(monkeypatch):
    _sidecar_status(monkeypatch, {**HEALTHY, "codex_bundle_version": None})
    assert doctor._sidecar({})[2] == Check(
        "OK", "Bundled Codex", f"next launch selects unknown version: {SELECTED}")


@pytest.mark.parametrize("discrepancy, expected", [
    (True, Check("WARN", "Desktop environment", "persistent, caller and GUI bootstrap values differ")),
    (False, Check("OK", "Desktop environment", "persistent, caller and GUI bootstrap values agree")),
])
def test_on_macos_the_desktops_environment_is_reported(monkeypatch, discrepancy, expected):
    _sidecar_status(monkeypatch, {**HEALTHY, "platform": "darwin", "env_discrepancy": discrepancy})
    found = doctor._sidecar({})
    assert len(found) == 4
    assert found[3] == expected


def test_a_derived_codex_cli_path_left_behind_is_named_last(monkeypatch):
    left = [r"C:\Users\me\.codex\shim\codex.exe", "/usr/local/bin/codex-shim"]
    _sidecar_status(monkeypatch, {**HEALTHY, "platform": "darwin", "env_discrepancy": False,
                                  "derived_override_paths": left})
    found = doctor._sidecar({})
    assert [check.name for check in found] == [
        "ChatGPT Desktop sidecar", "ChatGPT Desktop connection", "Bundled Codex",
        "Desktop environment", "Derived CODEX_CLI_PATH"]
    assert found[-1] == Check("WARN", "Derived CODEX_CLI_PATH",
                              r"C:\Users\me\.codex\shim\codex.exe, /usr/local/bin/codex-shim")


# --- Codex state -----------------------------------------------------------

THREADS = """
create table threads (
    id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, cwd TEXT NOT NULL,
    name TEXT, title TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0, updated_at_ms INTEGER,
    thread_source TEXT, model TEXT, source TEXT NOT NULL DEFAULT '')
"""


def _state(tmp_path, count):
    """A stand-in for Codex's state database holding `count` threads."""
    env = {"CODEX_HOME": str(tmp_path)}
    con = sqlite3.connect(str(codex_home.state_db(env)))
    try:
        con.execute(THREADS)
        for n in range(count):
            con.execute("insert into threads (id, rollout_path, cwd, title) values (?, ?, ?, ?)",
                        (f"thread-{n}", f"rollout-{n}.jsonl", "C:\\src", f"Thread {n}"))
        con.commit()
    finally:
        con.close()
    return env


@pytest.mark.parametrize("count, expected", [
    (1, Check("OK", "Codex state", "1 thread readable")),
    (2, Check("OK", "Codex state", "2 threads readable")),
    (0, Check("FAIL", "Codex state", "no readable Codex threads")),
])
def test_codex_state_counts_the_threads_it_can_read(tmp_path, count, expected):
    assert doctor._codex_state(_state(tmp_path, count)) == expected


def test_no_state_database_is_a_failure(tmp_path):
    assert doctor._codex_state({"CODEX_HOME": str(tmp_path)}) == Check(
        "FAIL", "Codex state", "no readable Codex threads")


@pytest.mark.parametrize("answer", [None, RuntimeError("a schema we do not know")])
def test_a_store_that_answers_nothing_or_breaks_is_a_failure(monkeypatch, answer):
    def threads(environ=None):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(codex_threads, "threads", threads)
    assert doctor._codex_state({}) == Check("FAIL", "Codex state", "no readable Codex threads")


# --- Codex CLI -------------------------------------------------------------

def _stop_hook(tmp_path):
    """conPACT's own Stop hook, written into the hooks.json of a CODEX_HOME at `tmp_path`."""
    hooks = {"hooks": {"Stop": [{"hooks": [codex_cli.hook_handler()]}]}}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
    return {"CODEX_HOME": str(tmp_path)}


def test_codex_cli_with_nothing_set_up_says_what_to_run(tmp_path):
    # No hooks.json, and no record of an app-server this conPACT started.
    assert doctor._codex_cli({"CODEX_HOME": str(tmp_path)}) == [
        Check("WARN", "Codex CLI Stop hook", "not installed; run conpact-codex --install"),
        Check("INFO", "Codex CLI app-server", "not running; conpact-codex starts it automatically"),
    ]


def test_codex_cli_with_the_hook_and_a_ready_app_server(tmp_path, monkeypatch):
    env = _stop_hook(tmp_path)
    asked = []

    def running(environ=None, asker=None):
        asked.append(environ)
        return {"running": True, "ready": True, "port": 51234, "pid": 4242}

    monkeypatch.setattr(codex_host, "running", running)
    assert doctor._codex_cli(env) == [
        Check("OK", "Codex CLI Stop hook", "installed"),
        Check("OK", "Codex CLI app-server", "running on 127.0.0.1:51234"),
    ]
    assert asked == [env]


def test_an_app_server_that_is_alive_but_not_answering_is_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_host, "running",
                        lambda environ=None, asker=None: {"running": True, "ready": False,
                                                          "port": 51234, "pid": 4242})
    assert doctor._codex_cli(_stop_hook(tmp_path))[1] == Check(
        "INFO", "Codex CLI app-server", "not running; conpact-codex starts it automatically")


# --- Claude Code login -----------------------------------------------------

def _on(monkeypatch, name, version=(3, 12, 1)):
    """Run the doctor as if on `name` (sys.platform) under Python `version`."""
    monkeypatch.setattr(doctor, "sys", types.SimpleNamespace(platform=name, version_info=version))


def _token(monkeypatch, status):
    """token_store.token_status answers `status`, or raises it when it is an exception."""
    def token_status():
        if isinstance(status, Exception):
            raise status
        return status

    monkeypatch.setattr(token_store, "token_status", token_status)


@pytest.mark.parametrize("name", ["win32", "linux"])
def test_the_keychain_is_read_only_on_macos(monkeypatch, name):
    _on(monkeypatch, name)
    _token(monkeypatch, AssertionError("the Keychain was read off macOS"))
    assert doctor._claude_login() == Check("INFO", "Claude Code login", "Keychain check applies only on macOS")


@pytest.mark.parametrize("status, expected", [
    (token_store.TokenError("no Claude Code login found"),
     Check("INFO", "Claude Code login", "not configured; optional and not used by Codex or ChatGPT Desktop")),
    ({"source": "keychain", "fresh": True, "expires_in_seconds": 3600, "can_refresh": False},
     Check("OK", "Claude Code login", "keychain, fresh; not used by Codex or ChatGPT Desktop")),
    ({"source": "file", "fresh": False, "expires_in_seconds": -60, "can_refresh": True},
     Check("WARN", "Claude Code login", "file, expired; not used by Codex or ChatGPT Desktop")),
    ({}, Check("WARN", "Claude Code login", "unknown, expired; not used by Codex or ChatGPT Desktop")),
])
def test_on_macos_the_claude_code_login_is_reported_and_optional(monkeypatch, status, expected):
    _on(monkeypatch, "darwin")
    _token(monkeypatch, status)
    assert doctor._claude_login() == expected


# --- checks() --------------------------------------------------------------

def _every_check_faked(monkeypatch, version=(3, 12, 1)):
    """Each check answers with its own marker and records what it was handed."""
    handed = []

    def one(name, answer):
        def check(*given):
            handed.append((name, given))
            return answer
        monkeypatch.setattr(doctor, name, check)

    one("_codex_login", Check("OK", "login", "1"))
    one("_mcp_config", Check("OK", "mcp", "2"))
    one("_sidecar", [Check("OK", "sidecar", "3"), Check("OK", "connection", "4")])
    one("_codex_cli", [Check("WARN", "hook", "5"), Check("INFO", "app-server", "6")])
    one("_codex_state", Check("OK", "state", "7"))
    one("_claude_login", Check("INFO", "claude login", "8"))
    one("_claude_idle", Check("OK", "claude idle", "9"))
    _on(monkeypatch, "win32", version)
    monkeypatch.setattr(doctor, "platform", types.SimpleNamespace(python_version=lambda: "3.12.1",
                                                                  machine=lambda: "ARM64"))
    return handed


def test_checks_lists_every_check_in_order(monkeypatch):
    handed = _every_check_faked(monkeypatch)
    env, runner = {"CODEX_HOME": "elsewhere"}, object()
    assert doctor.checks(environ=env, runner=runner) == [
        Check("OK", "Python", "3.12.1 (ARM64)"),
        Check("OK", "login", "1"),
        Check("OK", "mcp", "2"),
        Check("OK", "sidecar", "3"), Check("OK", "connection", "4"),
        Check("WARN", "hook", "5"), Check("INFO", "app-server", "6"),
        Check("OK", "state", "7"),
        Check("INFO", "claude login", "8"),
        Check("OK", "claude idle", "9"),
    ]
    assert handed == [("_codex_login", (runner,)), ("_mcp_config", (env,)), ("_sidecar", (env,)),
                      ("_codex_cli", (env,)), ("_codex_state", (env,)), ("_claude_login", ()),
                      ("_claude_idle", (env,))]


def test_checks_reads_this_processs_environment_unless_handed_one(monkeypatch):
    handed = _every_check_faked(monkeypatch)
    empty = {}
    doctor.checks()
    doctor.checks(environ=empty)
    envs = [given[0] for name, given in handed if name not in ("_codex_login", "_claude_login")]
    assert len(envs) == 10
    assert all(env is os.environ for env in envs[:5])
    assert all(env is empty for env in envs[5:])


def test_checks_runs_codex_through_subprocess_unless_handed_a_runner(monkeypatch):
    handed = _every_check_faked(monkeypatch)
    doctor.checks()
    assert handed[0] == ("_codex_login", (subprocess.run,))


@pytest.mark.parametrize("version, level", [
    ((3, 10, 14), "FAIL"),
    ((3, 11, 0), "OK"),
    ((3, 13, 1), "OK"),
    ((4, 0, 0), "OK"),
])
def test_python_older_than_3_11_fails(monkeypatch, version, level):
    _every_check_faked(monkeypatch, version)
    assert doctor.checks({})[0] == Check(level, "Python", "3.12.1 (ARM64)")


# --- lines() and main() ----------------------------------------------------

REPORT = [Check("OK", "Codex login", "Logged in using ChatGPT"),
          Check("WARN", "Bundled Codex", "older"),
          Check("INFO", "Claude Code login", "not configured"),
          Check("FAIL", "Codex state", "no readable Codex threads")]


def test_lines_head_the_report_and_pad_every_level_to_one_width():
    assert doctor.lines(REPORT) == [
        "conPACT doctor (read-only)",
        "",
        "[OK  ] Codex login: Logged in using ChatGPT",
        "[WARN] Bundled Codex: older",
        "[INFO] Claude Code login: not configured",
        "[FAIL] Codex state: no readable Codex threads",
    ]


def test_main_prints_the_report_one_line_each_and_exits_0_with_nothing_failed(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "checks", lambda: REPORT[:3])
    assert doctor.main() == 0
    assert capsys.readouterr().out == (
        "conPACT doctor (read-only)\n"
        "\n"
        "[OK  ] Codex login: Logged in using ChatGPT\n"
        "[WARN] Bundled Codex: older\n"
        "[INFO] Claude Code login: not configured\n")


@pytest.mark.parametrize("found", [REPORT, REPORT[3:]], ids=["among others", "alone"])
def test_main_exits_1_when_any_check_failed(monkeypatch, capsys, found):
    monkeypatch.setattr(doctor, "checks", lambda: found)
    assert doctor.main() == 1
    assert capsys.readouterr().out.endswith("[FAIL] Codex state: no readable Codex threads\n")


def test_the_module_run_as_a_command_is_the_report(monkeypatch, capsys):
    """`python -m conpact.doctor` is the documented command (tools/doctor.py is the
    same main): the guard at the bottom runs the report and exits on its code.

    runpy builds a fresh namespace that a patch of doctor's own names would not
    reach, so what the checks read is patched where it lives: no codex on PATH, so
    none is run, and a sidecar status that reads nothing from this machine. Every
    other check reads the throwaway home and CODEX_HOME the suite runs under.
    """
    monkeypatch.setattr(shutil, "which", lambda name: None)
    _sidecar_status(monkeypatch, HEALTHY)
    _token(monkeypatch, token_store.TokenError("no Claude Code login found"))   # on a Mac
    with warnings.catch_warnings(), pytest.raises(SystemExit) as stopped:
        warnings.filterwarnings("ignore", "'conpact.doctor' found in sys.modules", RuntimeWarning)
        runpy.run_module("conpact.doctor", run_name="__main__")
    assert stopped.value.code == 1
    out = capsys.readouterr().out.splitlines()
    assert out[:4] == ["conPACT doctor (read-only)", "",
                       f"[OK  ] Python: {platform.python_version()} ({platform.machine()})",
                       "[FAIL] Codex login: codex is not on PATH"]
