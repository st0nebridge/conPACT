"""
Regression test for CU-20261002-083 (a Claude Code session compacts itself in-process).

Until 2026-10-02 a compaction an agent queued in Claude Code reached its session
one way only: the Stop hook claimed the request and sent `/compact` over the
Remote Control bridge, so a session with Remote Control off could not be
compacted at all, and the request was a file another process had to find.
Claude Code's mods can compact a session from inside it ($.session.compact, the
call /compact makes) once its turn is over. Measured live the same day: with
Remote Control off (the session record's bridgeSessionId empty), the mod in
src/mod answered queue_compaction, the agent finished its answer, and the
transcript gained a compact_boundary ten seconds later (55,333 tokens before)
and the mod's line "conpact: compacted 55,333 to 3,964 tokens". The contract
(D-20261002-064):

  1. Where the mod loads it answers the MCP server's queue, cancel and status
     tools itself, under the same names, taking the same arguments, refusing
     a throwaway worktree session in the same words, with the same limits,
     reading the same two settings - so an agent cannot tell which side
     answered except by the `transport` it is told.
  2. The early toast's hold stays the server's; the mod takes over nothing
     else, and where it does not load the server and the Stop hook answer
     exactly as before.
  3. The mod reaches only what it lists: no process, no network, no file
     written, no prompt submitted. Every call is spelled out in register.js,
     and no other module of it names the mods API at all. (D-20261002-066
     narrowed "no file written" for CU-20261002-084: the idle toast's beat and
     answers under ~/.conpact/mod/, and nothing else - its own anchor,
     test_the_idle_toast_reaches_the_mod.py, holds that line. D-20261007-081
     added one command for CU-20261007-098: /compact, run where Claude Code
     refuses $.session.compact - test_an_sdk_session_compacts_by_command.py.
     D-20261007-083 added the band above the prompt for CU-20261007-100: a
     render hook on AbovePrompt, drawn with the surface's own elements
     ($.ui.resolve) and redrawn as the request changes ($.ui.invalidate), in
     place of the pinned status line ($.ui.status, no longer called) -
     test_the_band_shows_the_compaction.py. D-20261007-084 dropped the
     transcript line ($.ui.log, no longer called) for CU-20261007-101 -
     test_a_lost_run_is_ended_by_its_compaction.py.)
  4. The mod's own tests - its rules, its tools and its turn-end run, fired
     through Claude Code's test host - pass, whenever a Claude Code that can
     load mods is here to run them.
  5. It installs as the plugin `conpact` from this repository's marketplace,
     at the package's version.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

import conpact
from conpact import compaction, mcp_tools, settings, spin_off

ROOT = pathlib.Path(__file__).resolve().parents[2]
MOD = ROOT / "src" / "mod"
HOOKS = MOD / "hooks"


def _js(name):
    return (HOOKS / name).read_text(encoding="utf-8")


def _code(text):
    """The text without its comments: a header may name what the code may not call."""
    return re.sub(r"(?m)^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _taken_over():
    return set(re.findall(r"on\('tool\.call', \{ tool: '(mcp__conpact__\w+)' \}", _js("register.js")))


def _tool(name):
    return next(tool for tool in mcp_tools.TOOLS if tool["name"] == name)


def test_1_the_mod_answers_the_servers_tools_by_their_names():
    assert _taken_over() == {"mcp__conpact__" + name
                             for name in (mcp_tools.QUEUE, mcp_tools.CANCEL, mcp_tools.STATUS)}


def test_1_the_mod_takes_the_arguments_the_server_takes():
    tools = _js("tools.js")
    queue_args = re.search(r"only\(args, \[([^\]]*)\], nothing\)", tools).group(1)
    assert set(re.findall(r"'(\w+)'", queue_args)) == set(_tool(mcp_tools.QUEUE)["inputSchema"]["properties"])
    for name in (mcp_tools.CANCEL, mcp_tools.STATUS):
        assert _tool(name)["inputSchema"]["properties"] == {}
    assert tools.count("only(argumentsOf(e), [],") == 2


def test_1_the_refusal_limits_and_settings_are_the_servers():
    tools, rules = _js("tools.js"), _js("rules.js")
    block = re.search(r"SPIN_OFF_REFUSAL = \((.*?)\n\)", tools, re.S).group(1)
    assert "".join(re.findall(r"'((?:[^'\\]|\\.)*)'", block)) == spin_off.REFUSAL
    assert f"MAX_FOCUS_CHARS = {compaction.MAX_FOCUS_CHARS}" in rules
    assert f"MAX_CONTEXT_TOKENS = {compaction.MAX_CONTEXT_TOKENS:_}" in rules
    for key in ("closure_min_context_tokens", settings.GUARD_SPIN_OFF):
        settings.get(key)                                   # raises for a key the Python side lacks
        assert f"data.{key}" in rules
    assert settings.defaults()[settings.GUARD_SPIN_OFF] is True
    assert "guardSpinOff: true" in rules


def test_2_the_hold_stays_the_servers():
    assert "mcp__conpact__" + mcp_tools.HOLD not in _taken_over()
    assert mcp_tools.HOLD not in "".join(_js(name) for name in ("register.js", "tools.js"))


def test_3_the_mod_reaches_only_what_it_lists():
    sources = {path.name: _code(path.read_text(encoding="utf-8")) for path in HOOKS.glob("*.js")}
    assert set(sources) == {"register.js", "rules.js", "requests.js", "files.js", "tools.js", "run.js",
                            "handoff.js", "band.js"}
    calls = set(re.findall(r"\$\.(\w+\.\w+)\(", sources["register.js"]))
    assert calls == {"clock.now", "clock.after", "clock.every", "session.id", "session.cwd", "session.usage",
                     "session.compact", "command.run", "env.get", "fs.read", "fs.write", "store.get", "store.set",
                     "store.delete", "store.keys", "ui.toast", "ui.invalidate", "ui.resolve"}
    for name, text in sources.items():
        if name != "register.js":
            assert "$." not in text.replace("${", ""), name


@pytest.fixture(scope="module")
def claude():
    found = os.environ.get("CONPACT_CLAUDE") or shutil.which("claude")
    if not found:
        pytest.skip("no Claude Code here to run the mod's tests with")
    return found


def test_4_the_mods_own_tests_pass(claude):
    env = {**os.environ, "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"}
    run = subprocess.run([claude, "plugin", "test"], cwd=MOD, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    out = run.stdout + run.stderr
    if "hooks modules are" in out and ("turned off" in out or "not turned on" in out):
        pytest.skip(out.strip().splitlines()[-1])
    assert run.returncode == 0, out
    assert re.search(r"\b0 fail\b", out), out
    assert int(re.search(r"(\d+) pass", out).group(1)) >= 40, out


def test_5_it_installs_as_conpact_at_the_packages_version():
    plugin = json.loads((MOD / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "conpact"
    assert plugin["version"] == conpact.__version__
    assert market["plugins"] == [{**market["plugins"][0], "name": "conpact", "source": "./src/mod"}]
    assert json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8")) == {"modules": ["./register.js"]}
