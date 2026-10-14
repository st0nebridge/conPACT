"""
Regression test for CU-20261014-121 (the doctor reports a Codex config.toml
whose mcp_servers is not a table, rather than stopping on it).

Found on 2026-10-14 by the tests that raised the doctor's mutation score
(CU-20261014-120): with `mcp_servers = "python"` in Codex's config.toml, the
doctor's Codex MCP check called .get("conpact") on a string. The
AttributeError was not among the errors it caught, so `python -m
conpact.doctor` stopped with a traceback, and no check after it was printed.
The contract:

  1. An mcp_servers of any value that is not a table - a string, an array, a
     number, a boolean - is reported as the Codex MCP check failing:
     "conpact is missing from config.toml".
  2. The report goes on past it: every other check is still printed, and the
     doctor exits 1 because a check failed.
"""
import pytest

from conpact import doctor
from conpact.doctor import Check

MISSING = Check("FAIL", "Codex MCP", "conpact is missing from config.toml")


def _codex_home(tmp_path, value):
    (tmp_path / "config.toml").write_text(f"mcp_servers = {value}\n", encoding="utf-8")
    return {"CODEX_HOME": str(tmp_path)}


@pytest.mark.parametrize("value", ['"python"', '["conpact"]', "1", "true"])
def test_an_mcp_servers_that_is_not_a_table_is_a_failed_check(tmp_path, value):
    assert doctor._mcp_config(_codex_home(tmp_path, value)) == MISSING


def test_the_report_goes_on_past_it_and_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", _codex_home(tmp_path, '"python"')["CODEX_HOME"])
    for name in ("_codex_login", "_codex_state", "_claude_login", "_claude_idle"):
        monkeypatch.setattr(doctor, name, lambda *_, name=name: Check("OK", name, "stood in"))
    for name in ("_sidecar", "_codex_cli"):
        monkeypatch.setattr(doctor, name, lambda *_, name=name: [Check("OK", name, "stood in")])
    assert doctor.main() == 1
    printed = capsys.readouterr().out.splitlines()
    assert "[FAIL] Codex MCP: conpact is missing from config.toml" in printed
    assert printed[-1] == "[OK  ] _claude_idle: stood in"
