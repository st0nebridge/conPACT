"""
Regression test for CU-20261007-101 (a run lost in a reload is ended by its compaction).

On 2026-10-07 a Desktop session queued a compaction in the same turn that
removed a mod from its hot-reloaded folder. The turn ended, the mod's run began
/compact, and the reload that followed threw the run away with the load that
made it. The compaction finished (466,356 to 17,717 tokens in 65 s) but nothing
was left to record it: the request stayed `executing`, the band said
"compacting" for good, and ten minutes on the next turn end ran it again and
compacted the session a second time. In the same session the desktop app drew
the mod's transcript line ("conpact: compacted 224,117 to 15,686 tokens") as a
block in the conversation that only repeated the band. The contract
(D-20261007-084):

  1. A compaction of the main session - the person's /compact, an automatic
     one, or the mod's own (trigger plugin, or /compact where the session has
     no terminal) - that finds the request `executing` with no run of the
     present load behind it ends the request with its outcome, as the run
     would have: compacted, before and after, the run's start, focus,
     minimum and try. It is not run again.
  2. A run of the present load records its own compaction: the load knows the
     sessions it is running (a module variable, which a reload starts empty),
     and a second run of a session it is running does nothing.
  3. A precompute, a subagent's compaction or a vetoed one adopts nothing, and
     the mod's own compaction never spends a queued request.
  4. A request still `executing` after STALE_RUN_MS shows in the band as
     waiting for its next try ("the last run did not finish"), not as
     compacting, and cancel - the band's or cancel_compaction - withdraws it.
  5. The mod writes no line into the transcript: the band shows every
     outcome, and a toast says when one failed.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOKS = ROOT / "src" / "mod" / "hooks"
TESTS = ROOT / "src" / "mod" / "tests"


def _code(text):
    return re.sub(r"(?m)^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _read(name):
    return _code((HOOKS / name).read_text(encoding="utf-8"))


def _names(name):
    """The suite's test names, quotes unescaped."""
    text = (TESTS / name).read_text(encoding="utf-8")
    return " / ".join(n.replace("\\'", "'") for n in re.findall(r"test\([`'](.+?)[`'], ", text))


def test_1_and_3_the_compaction_hook_adopts_a_lost_run_before_anything_else():
    register = _read("register.js")
    hook = register[register.index("on('session.compact'"):]
    assert "const asked = e.trigger === 'manual' || e.trigger === 'auto'" in hook
    assert "if (e.agentId !== undefined || (!asked && e.trigger !== 'plugin')) return result" in hook
    order = [hook.index(s) for s in ("commanded.result = result", "typeof result?.skip === 'string'",
                                     "if (await adopt(host($), id, result)) return result",
                                     "if (asked && (await requests.pending(host($), id))?.state === 'queued')")]
    assert order == sorted(order)
    run = _read("run.js")
    adopt = run[run.index("export async function adopt"):]
    adopt = adopt[:adopt.index("\n}\n")]
    assert "if (live.has(id)) return false" in adopt
    assert "if (request?.state !== 'executing') return false" in adopt
    assert "await requests.finish(host, id, {" in adopt and "action: 'compacted'" in adopt


def test_2_a_load_knows_the_runs_it_owns():
    run = _read("run.js")
    assert "const live = new Set()" in run
    execute = run[run.index("export async function execute"):]
    execute = execute[:execute.index("\n}\n")]
    assert execute.index("if (live.has(id)) return") < execute.index("live.add(id)") < execute.index("live.delete(id)")
    assert "finally" in execute


def test_4_a_stale_run_waits_and_can_be_withdrawn():
    band = _read("band.js")
    assert "now - (number(request.started_at) ?? 0) >= STALE_RUN_MS" in band
    assert "last: 'the last run did not finish'" in band
    tools = _read("tools.js")
    assert tools.count("requests.runnable(") == 2


def test_5_no_transcript_line():
    for path in HOOKS.glob("*.js"):
        code = _read(path.name)
        assert "ui.log" not in code, path.name


def test_the_mods_tests_cover_it():
    run, band = _names("run.test.ts"), _names("band.test.ts")
    for phrase in ("compaction a run lost in a reload started ends its request, and is not run again",
                   "reports no sizes is recorded without them", "leaves a lost run's request",
                   "while its run is live, is the run's to record", "adopts nothing"):
        assert phrase in run, phrase
    for phrase in ("not shown compacting for ever: it waits for its next try, and cancel withdraws it",
                   "a run lost in a reload, once its compaction ends, shows as compacted",
                   "drawn again as the run claims the request, and again as it ends"):
        assert phrase in band, phrase
