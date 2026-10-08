"""
Regression test for CU-20261007-098 (a session with no terminal compacts by /compact).

From 2026-10-02 the mod was the route every agent-queued compaction took, and
it compacted with $.session.compact. The Desktop app's Code tab runs Claude
Code as an SDK session, and there Claude Code refuses that call outright:
"$.session.compact: not available in a headless (-p / SDK) session yet:
compaction here runs inside a turn (a /compact prompt)". So in every Desktop
session the mod took the request - the Stop hook no longer saw one - and then
failed to run it, and the idle toast's compaction failed in the same words
(measured 2026-10-07, Claude Code 2.1.289, a 308k-token Desktop session).
The same day, a mod in an SDK session (2.1.289, stream-json in and out) that
ran $.command.run({ command: 'compact', args }) reached the engine's own
compaction - the event session.compact, trigger 'manual', with those args as
its instructions - and the command resolved after it, with the engine's line
when it could not compact. The contract (D-20261007-081):

  1. In a session whose session.start says it is not interactive, the mod
     compacts by running /compact - the one command it runs - with the focus
     as its text; in an interactive session it still calls $.session.compact.
  2. Its own /compact's compaction is the outcome of the run (compacted with
     its sizes, or skipped), not another compaction that spends a queued
     request; a /compact that made none is a failure in the engine's words,
     tried at the next turn ends as a refused start is.
  3. The mod's tests for this, fired through Claude Code's test host, are
     among those the mod's own anchor runs (test_the_mod_compacts_in_process).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOKS = ROOT / "src" / "mod" / "hooks"
TESTS = ROOT / "src" / "mod" / "tests"


def _code(text):
    return re.sub(r"(?m)^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _register():
    return _code((HOOKS / "register.js").read_text(encoding="utf-8"))


def test_1_a_session_with_no_terminal_runs_compact_and_only_compact():
    code = _register()
    assert re.findall(r"\$\.command\.run\((.*?)\)", code) == ["{ command: 'compact', args: args?.instructions ?? '' }"]
    assert "headless = e.isInteractive === false" in code
    assert "compact: (args) => (headless ? compactByCommand($, args) : $.session.compact(args))" in code


def test_2_its_own_compaction_is_its_outcome_and_spends_nothing_else():
    code = _register()
    hook = code[code.index("on('session.compact'"):]
    own = hook.index("commanded !== null && e.trigger === 'manual'")
    assert own < hook.index("requests.finish"), "the mod's own /compact must be taken before a queued request is spent"
    assert "throw new Error(ran?.text ||" in code


def test_3_the_sdk_route_is_tested_through_the_test_host():
    text = (TESTS / "sdk.test.ts").read_text(encoding="utf-8")
    names = re.findall(r"^test\(['\"](.+?)['\"],", text, flags=re.M)
    assert len(names) >= 8
    for phrase in ("runs /compact with its focus", "terminal session still compacts in-process",
                   "fails in the engine's words", "own /compact in an SDK session still spends",
                   "idle toast runs /compact"):
        assert any(phrase in name for name in names), phrase
