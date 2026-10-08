"""
Regression test for CU-20261007-100 (the band above the prompt shows the compaction).

Until 2026-10-07 everything the mod showed was a line of text: a pinned status
line while a request waited or ran, a dim transcript line once it had run, a
toast when it failed. Nothing said what the request would keep, how large the
context was, or what the compaction came to at a glance, and nothing on screen
could withdraw a request. The contract (D-20261007-083):

  1. The mod draws one row in the band above the prompt (a ui.render hook
     on AbovePrompt): the request while it waits (the context now, its
     minimum, its try and focus, cancel), while it runs (the size it is
     compacting), and what it came to (before -> after, a meter of what was
     kept, the saving and the time, or why it did not compact, a dismiss
     mark), for at most SHOW_MS after it ran.
  2. It draws above whatever the plugins beneath drew there, yields to a
     survey, and on any fault draws nothing of its own rather than failing
     the band.
  3. The mark and meter are Unicode on the terminal and a small drawing (Svg)
     on every other surface, animated only while queued or running; mod.band
     is handed the surface's elements, never $.
  4. Cancel withdraws only a request that has not begun, as cancel_compaction
     does (since D-20261007-084, a lost run's request too, which waits for its
     next try); Dismiss marks only the result it was drawn for.
  5. The band follows the request without being asked: every change of the
     request or the last result redraws it (since D-20261007-085, a drawing
     under way reads again, and a second redraw follows). It replaces the
     pinned status line, which the CLI drew as a warning repeating the band.
  6. The idle toast's compaction shows too: running while it runs (over a
     request still waiting, which it leaves alone), then as the last result.
  7. The toast stays, for a compaction that failed. (The transcript line
     stayed too until D-20261007-084 dropped it for CU-20261007-101: the
     desktop app drew it as a block in the conversation repeating the band.)
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


def test_1_and_2_the_band_is_drawn_above_what_is_beneath_and_yields():
    register = _read("register.js")
    hook = register[register.index("on('ui.render', { component: 'AbovePrompt' }"):]
    hook = hook[:hook.index("on('session.compact'")]
    assert "const below = await next(e)" in hook
    assert "if (e.props.hasSurvey) return below" in hook
    assert "if (shown === null) return below" in hook
    assert re.search(r"catch \{\s*return below\s*\}", hook)
    assert "band.draw($.ui.resolve(e), e.surface, shown, {" in hook
    band = _read("band.js")
    assert "export const SHOW_MS = 15 * 60_000" in band
    assert "now - at > SHOW_MS" in band
    assert "below === null || below === undefined ? ours" in band


def test_3_bars_by_surface_and_no_dollar_in_the_band():
    band = _read("band.js")
    assert "const drawn = surface !== 'terminal'" in band
    assert "el.Svg({ source: picture(m.kind, share), alt" in band
    assert "...(moving ? { isInteractive: true } : {})" in band
    assert "'━'.repeat(" in band
    assert "$." not in band.replace("${", "")


def test_4_cancel_and_dismiss_act_only_on_what_they_were_drawn_for():
    tools = _read("tools.js")
    withdraw = tools[tools.index("export async function withdraw"):]
    assert withdraw.index("if (!requests.runnable(") < withdraw.index("await requests.drop(host, id)")
    requests = _read("requests.js")
    dismiss = requests[requests.index("export async function dismiss"):]
    assert "result !== null && result.at === at" in dismiss[:300]
    register = _read("register.js")
    assert "cancel: () => withdraw(host($), id)" in register
    assert "await requests.dismiss(host($), id, shown.at)" in register


def test_5_every_change_redraws_the_band_and_no_status_line_is_pinned():
    register = _read("register.js")
    changed = register[register.index("changed: () => {"):]
    assert "$.ui.invalidate('ui.render')" in changed[:changed.index("\n      },")]
    assert "$.ui.status" not in register
    for name in ("tools.js", "run.js", "handoff.js"):
        code = _read(name)
        assert "host.ui.status" not in code, name
        assert "host.ui.changed()" in code, name


def test_6_the_toast_compaction_is_shown_and_leaves_a_waiting_request():
    handoff = _read("handoff.js")
    serve = handoff[handoff.index("export async function serve"):]
    assert serve.index("await requests.mark(host, id, started)") < serve.index("const outcome = await compact(host)")
    assert "await requests.record(host, id, { ...outcome," in serve
    requests = _read("requests.js")
    record = requests[requests.index("export async function record"):]
    record = record[:record.index("\n}\n")]
    assert "RESULT + id" in record and "RUNNING + id" in record and "drop(" not in record
    band = _read("band.js")
    assert "now - begun < STALE_RUN_MS" in band


def test_7_the_toast_stays_and_the_tests_cover_both_surfaces():
    run = _read("run.js")
    assert "host.ui.toast(" in run and "host.ui.log(" not in run
    names = re.findall(r"test\('([^']+)'", (TESTS / "band.test.ts").read_text(encoding="utf-8"))
    joined = " / ".join(names)
    for phrase in ("cancel withdraws it", "until dismissed", "red with its reason", "keeps the band clear",
                   "without being asked to redraw", "cancel on a request that has begun withdraws nothing",
                   "replaced since it was drawn leaves the new one", "what the plugins beneath draw stays",
                   "a toast compaction run through the mod ends in the band as its result"):
        assert phrase in joined, phrase
    assert "const SURFACES = ['terminal', 'desktop'] as const" in (TESTS / "band.test.ts").read_text(encoding="utf-8")
