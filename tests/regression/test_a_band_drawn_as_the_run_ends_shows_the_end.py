"""
Regression test for CU-20261007-102 (a band drawn as the run ends shows the end).

On 2026-10-07 the band above the prompt sometimes still read "compacting" once
a compaction had finished, and stayed so until something else redrew it. The
mod records a run's end 0.3 to 1 s after the compaction itself ends (the
session's compact_boundary at 14:26:25.855, the result at 14:26:26.164), and
the end of the compaction is when a surface asks for the band again (the turn
stops working). A drawing asked for in that gap reads the request still
running; the redraw the mod asks for as it records the end arrives while that
drawing is under way, and Claude Code folds it into the drawing (the test host
does the same: a drawing held part-way that reads once stands as
"compacting"). The contract (D-20261007-085):

  1. A drawing of the band reads the request and result again when the mod
     changed either while it read them (a count of this load's changes), up to
     three reads.
  2. Every change asks for the band again at once and once more SETTLE_MS
     later, for a surface that kept a drawing it asked for a moment before.
  3. Every change goes through that one path: the run, the tools, the idle
     toast's run, the compaction hook's superseding and the band's dismiss.
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


def test_1_a_drawing_reads_again_after_a_change():
    band = _read("band.js")
    settled = band[band.index("export async function settled(version, look, tries = 3)"):]
    settled = settled[:settled.index("\n}\n")]
    assert "} while (version() !== seen && --tries > 0)" in settled
    register = _read("register.js")
    assert "let changes = 0" in register
    assert "const shown = await band.settled(() => changes, async () => band.model(" in register


def test_2_every_change_asks_twice():
    assert "export const SETTLE_MS = 2_000" in _read("band.js")
    register = _read("register.js")
    changed = register[register.index("changed: () => {"):]
    changed = changed[:changed.index("\n      },")]
    order = [changed.index(s) for s in ("changes += 1", "$.ui.invalidate('ui.render')",
                                        "$.clock.after(band.SETTLE_MS, () => $.ui.invalidate('ui.render'))")]
    assert order == sorted(order)


def test_3_one_path_for_every_change():
    register = _read("register.js")
    assert register.count("$.ui.invalidate(") == 2
    assert register.count("host($).ui.changed()") == 2


def test_the_mods_tests_cover_it():
    names = " / ".join(n.replace("\'", "'") for n in re.findall(r"test\([`'](.+?)[`'], ",
                                                                 (TESTS / "band.test.ts").read_text(encoding="utf-8")))
    for phrase in ("a drawing under way as the run ends reads again, so it draws the end and not compacting",
                   "what it read is read again once it changed", "looked at three times, no more",
                   "asked for again SETTLE_MS after the run ends"):
        assert phrase in names, phrase
