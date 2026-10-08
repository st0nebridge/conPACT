from conpact import doctor


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
