"""Tests for conpact.settings_cli: the settings command."""
import io
import json

import pytest

from conpact import idle_state, settings, settings_cli as sc


def _run(*argv, opener=None):
    out, err = io.StringIO(), io.StringIO()
    code = sc.main(list(argv), out=out, err=err, opener=opener or (lambda: None))
    return code, out.getvalue(), err.getvalue()


def test_show_lists_every_setting_with_its_value_and_what_it_accepts():
    code, out, err = _run("show")
    assert (code, err) == (0, "")
    assert out.splitlines()[0] == f"conPACT settings: {settings.settings_path()}"
    for s in settings.SETTINGS:
        assert f"  {s.key:<28} {settings.describe(s.key, s.default)}\n" in out
        assert f"      {s.help} Allowed: {settings.allowed(s.key)}.\n" in out
    assert "(default " not in out  # nothing changed, so no default is repeated


def test_show_marks_a_changed_value_with_its_default():
    settings.save({"min_context_tokens": 150_000, "idle_toast": False})
    _, out, _ = _run("show")
    assert "  min_context_tokens           150,000 tokens   (default 100,000 tokens)\n" in out
    assert "  idle_toast                   off   (default on)\n" in out


def test_set_changes_several_at_once_and_says_so():
    code, out, err = _run("set", "min_context_tokens", "150k", "idle_seconds", "60", "idle_toast", "off")
    assert (code, err) == (0, "")
    assert settings.load() == {**settings.defaults(), "min_context_tokens": 150_000, "idle_seconds": 60,
                               "idle_toast": False}
    assert out == ("Saved. New values apply from the next turn end.\n"
                   "  min_context_tokens           150,000 tokens   (default 100,000 tokens)\n"
                   "  idle_seconds                 60 s   (default off)\n"
                   "  idle_toast                   off   (default on)\n")


@pytest.mark.parametrize("argv, message", [
    (("set", "lead_seconds", "5"), "lead_seconds must be from 10 to 86,400 seconds"),
    (("set", "colour", "red"), "unknown setting 'colour'"),
    (("set", "lead_seconds"), "set needs KEY VALUE pairs"),
    (("set",), "set needs KEY VALUE pairs"),
    (("set", "min_context_tokens", "150k", "lead_seconds", "5"), "lead_seconds must be"),
])
def test_set_refuses_and_writes_nothing(argv, message):
    code, out, err = _run(*argv)
    assert (code, out) == (2, "")
    assert err.startswith("error: ") and message in err
    assert not settings.settings_path().exists()


def test_reset_some_or_all():
    settings.save({"min_context_tokens": 150_000, "lead_seconds": 600, "idle_toast": False})
    code, out, _ = _run("reset", "lead_seconds")
    assert code == 0 and out.startswith("Reset lead_seconds.\n")
    assert settings.load()["lead_seconds"] == 300 and settings.load()["min_context_tokens"] == 150_000
    code, out, _ = _run("reset")
    assert code == 0 and out.startswith("Reset every setting.\n")
    assert settings.load() == settings.defaults()
    assert not idle_state.off_switch_path().exists()


def test_reset_refuses_an_unknown_key():
    settings.save({"lead_seconds": 600})
    code, out, err = _run("reset", "lead_seconds", "colour")
    assert (code, out) == (2, "") and "unknown setting 'colour'" in err
    assert json.loads(settings.settings_path().read_text(encoding="utf-8")) == {"lead_seconds": 600}


@pytest.mark.parametrize("argv", [(), ("window",)])
def test_no_arguments_or_window_opens_the_window(argv):
    opened = []
    code, out, err = _run(*argv, opener=lambda: opened.append(True))
    assert (code, out, err, opened) == (0, "", "", [True])


def test_the_default_opener_is_the_settings_window(monkeypatch):
    from conpact import settings_window
    opened = []
    monkeypatch.setattr(settings_window, "run", lambda: opened.append(True))
    assert sc.main([], out=io.StringIO(), err=io.StringIO()) == 0 and opened == [True]


def test_an_unknown_command_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        sc.main(["frobnicate"], out=io.StringIO(), err=io.StringIO())
    assert exc.value.code == 2


def test_the_tool_wrapper_runs_the_command():
    import pathlib
    import subprocess
    import sys
    tool = pathlib.Path(__file__).resolve().parents[1] / "tools" / "settings.py"
    done = subprocess.run([sys.executable, str(tool), "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "show" in done.stdout and "reset" in done.stdout


def test_show_starts_with_the_file_and_a_blank_line():
    _, out, _ = _run("show")
    assert out.splitlines()[1] == ""


def test_set_explains_its_pairs():
    code, _, err = _run("set", "lead_seconds")
    assert err == "error: set needs KEY VALUE pairs, e.g. set min_context_tokens 150k\n"


def test_reset_names_the_keys_and_shows_the_result():
    settings.save({"min_context_tokens": 150_000, "lead_seconds": 600})
    code, out, _ = _run("reset", "lead_seconds", "min_context_tokens")
    lines = out.splitlines()
    assert lines[0] == "Reset lead_seconds, min_context_tokens."
    assert lines[1:] == sc.show_lines(settings.defaults())


def test_main_reads_sys_argv_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["settings.py", "show"])
    out = io.StringIO()
    assert sc.main(out=out, err=io.StringIO()) == 0 and out.getvalue().startswith("conPACT settings: ")


def test_help_names_the_tool_and_its_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        sc.main(["--help"])
    assert exc.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for words in ("usage: python tools/settings.py", "Show or change conPACT's settings. With no command, "
                  "opens the settings window.", "list every setting, its value and what it accepts",
                  "change settings: KEY VALUE [KEY VALUE ...] (all or none)",
                  "put the named settings (or all) back to their defaults", "open the settings window"):
        assert words in text, words
    with pytest.raises(SystemExit):
        sc.main(["set", "--help"])
    assert "KEY VALUE" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        sc.main(["reset", "--help"])
    assert "[KEY ...]" in capsys.readouterr().out
