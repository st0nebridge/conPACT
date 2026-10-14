import json

import pytest

from conpact import claude_idle_compaction as cic
from conpact import claude_settings, doctor, settings


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
