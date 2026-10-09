# Verification and evidence

Every claim conPACT makes about itself is either measured or observed, and each
is dated. Where a figure is older than the current code, this page says so
rather than restating it as current.

## Current status

Measured on Windows 2026-10-03; the Linux and macOS rows are older, as each says:

| | |
|---|---|
| **Test suite, Windows 11** | **2,547 passed**, 4 skipped with `python -m pytest -m "not real_ui" -q`; final affected suite **244 passed**; on-screen suite **9 passed**, 1 skipped |
| **Test suite, Linux** | **2,003 passed**, 28 skipped, 2 failed (WSL Debian, Python 3.13, 2026-09-25, before the Codex CLI contribution) |
| **Test suite, macOS** | **2,178 passed**, 17 skipped (Intel Mac, 2026-09-23, run by the contributor before the latest Windows changes) |

On Linux the 28 skips are the tests that need Tk, which that distribution did not
have installed, and the Windows-only probes, wrapper and window tests. The two
failures are the mutation tester's own tests, which need `pytest-cov`, and that
run had only pytest's pure-Python packages; both pass on Windows.
`tests/test_mcp_tools.py` was not run there: its `jsonschema` dependency needs a
compiled package. On macOS, the 17 skips are platform-specific tests; the Tk form
and layout tests ran against a real display.

The installed Windows wheel was checked in a fresh virtual environment: its MCP
entry point and Python module bound the correct test caller; its packaged
launcher compiled and ran Codex's `--version`. The wheel was built from the
source archive. The mod passed all **73 tests** and strict plugin validation.
The final Windows parent resolver measured **100% line and branch coverage**;
the CLI module measured **97% combined coverage**. Function coverage is not
reported by the Python coverage tool. Older coverage and mutation scores below
retain their dates; no fresh mutation sweep was run for these release fixes.

## Tests and coverage

Last measured before the ChatGPT Desktop platform was added, at **1,090 passed,
1 skipped** (1,084 plus the 6 on-screen tests, which `-m "not real_ui"`
deselects; the skip is one of those six, which stands itself down when the test
process does not own the foreground, because Windows lets only that process call
`SetForegroundWindow`). The README later recorded 99% branch coverage at 1,322
tests.

At 1,090 tests, branch coverage was **99%** (2,411 statements, 9 missed; 680
branches, 6 partial), and **`-m "not real_ui"` gave 1,085 passed and the
identical 99%: the same nine lines and the same six partial branches.** That was
deliberate: the six on-screen tests used to be the only
thing reaching the drawing and Win32 code, and afterwards they reached nothing
the rest of the suite did not. They stay, because what they prove (that a real
window appears, fades in and answers a click) is not what a headless test
proves.

The nine missed lines:

- four `__main__` guards (`closure_hook`, `mcp_server`, `session_ready`,
  `settings_cli`), which the Stop-wrapper and MCP-stdio tests do execute, in a
  subprocess, where coverage is not collected;
- the defensive `except tk.TclError` around a second destroy, in both
  `toast_view` and `settings_window` (two lines each);
- `detach`'s `return False` for a process handle Windows declines to open.

The three guards that used to be on that list (`idle_watch`, `settings_window`
and `toast_view`) are the ones something really does spawn as `python -m`, and
they are covered and killed now; `idle_watch` is at **100%**
line and branch. Neither window is proved only by a subprocess either:
`present()` and `run()` are both called in-process, with the calls that would map
a window stubbed out.

### Test isolation

The whole suite runs under a throwaway home: `HOME` and `USERPROFILE` point at
a temporary folder before any conPACT module is imported, so neither a test nor
any process a test starts can reach the real `~/.claude` or `~/.conpact`. On top
of that, an autouse fixture patches every path constant to a per-test folder and
guards the network, detached processes, toasts, windows and the Keychain. Each
guard records the breach as well as raising it, because code under test may
swallow the exception (the watcher does, so that a failing toast cannot crash
it), and the fixture fails the test at teardown if anything was recorded.

### Window tests and the desktop

A window test shares the desktop with whatever else is running, and with the
person using it. So it checks only what the code asks for, and any window it
does show is one that nothing else on the desktop acts on. What follows was
measured on 2026-09-23 and 2026-09-24, on a machine running PowerToys
FancyZones. For the second day, every window a Python process showed, and every
change of the window holding the keyboard, was logged from outside the test
process across a run of the window test files:

- **Where a shown window lands is not the code's to decide.** The test of
  `show()`'s centring mapped a real window off screen and read back where it
  landed. Once in about 120 runs it read (-1904, 16), 16 pixels inside the
  corner of the left-hand monitor. FancyZones, set to move newly created
  windows to the active monitor, moves every window a process shows onto the
  monitor under the cursor, from its own process, a moment later. Tk's own
  move usually lands after FancyZones' and wins; under load FancyZones' lands
  last. The two position tests now build the window as `run()` does,
  withdrawn first, record the calls that would show it and take the keyboard,
  and read the position from Tk's own record of what it was asked for. The
  first version of that fix built the window before withdrawing it, which
  showed it for a moment; it is never shown now.
- **A time limit times the window, not Python's start-up.** The on-screen test
  gave its child process 30 seconds. Under load, starting Python and importing
  conpact took 13 to 15 of them and creating Tk 5 more, and 3 of 24 runs were
  killed before their window had finished. `tests/window_process.py` now starts
  the 30 seconds once the child has imported what it needs, prints the child's
  stack if they run out, and keeps a 120-second backstop for a child that never
  gets going. The toast's on-screen tests use it too.
- **Nor Tk's start-up, nor a slow fade.** On a machine at 100% CPU, creating
  Tk in the child took up to 16 seconds and building the toast up to 15 more.
  The 30 seconds now start again, whole, once the child's first Tk root exists;
  creating it counts against the start-up backstop, which prints the child's
  stack too. The click test closes its toast if no click lands within 10
  seconds; that clock was read before Tk was created, so the toast closed at its
  first poll, before the click. It now starts when the toast is shown. With it
  fixed, a second race showed: the click, 900 ms after the toast was shown, came
  before the fade's eight 16 ms steps had run, which under the same load took
  up to 1.7 seconds. The click now comes 900 ms after the fade's last step, and
  still asserts the full opacity; a fade that never finishes sends no click and
  fails.
- **A test's window is a tool window, off every screen.** 32 of the tests'
  roots were ordinary windows, the kind FancyZones moves: with the cursor
  parked on the left-hand monitor, one landed on it at (-1904, 16). FancyZones
  never moves a tool window, or a popup without a sizing frame, and the toast
  tests' borderless roots, which are tool windows, stayed where they were put.
  Every test root now comes from `root()` in `tests/window_guard.py`: a tool
  window at (-4000, -4000), which Tk shows at its first update without
  activating it. The layout the tests read is identical on it: every widget's
  size, place, packing and look, for all four tabs of the settings window at
  two DPIs and for the toast at every stage.
- **Tk's first window takes the keyboard.** Tk activates the first window each
  thread creates, even one never shown. In every test process logged, the first
  test window took the keyboard from whatever the user was typing in; in one
  run it kept it for 33 seconds, until the user clicked elsewhere. A session fixture now has that
  happen before any test, on a window that is never shown, with the activation
  refused and the keyboard handed straight back.
- **Every test is held to both.** Round every test that is not `real_ui`, the
  conftest runs `window_guard.Guard`. It refuses any activation of the test's
  windows and records it, and records any window of the test that is shown
  without being a tool window or that lands on a screen, so the test fails. It
  found one more: a test of the settings window's focus called `show()` with
  the real work area, which put the window in the middle of the user's screen.
  It now gives `show()` an off-screen work area, as the other tests of it do.
- **The one window that must take the keyboard gets a desktop of its own.**
  The settings window takes the keyboard when it opens, because the user opened
  it to type, and its on-screen test shows it for real. On the user's desktop
  it took the keyboard from whatever they were typing in for about 1.2 seconds,
  and one keystroke in that time changed what the test saved: a digit made the
  first field's value one the save refused, and Escape closed the window before
  the save. Either left the default, now and then in a full run and never
  alone. The test's child now makes a Windows desktop of its own before Tk
  starts, where the window is still created, shown, focused and driven, and
  Windows sends it none of the user's input. The test asserts that it ran
  there. The toast never takes the keyboard, so its on-screen tests stay on the
  user's desktop.

Only the tests that click or hover, or read the width a widget was given, need
a shown window: Tk drops a pointer event sent to a widget that has never been
shown. The others are shown only because building a view lets Tk map a root
that is not withdrawn. They are left that way on purpose: showing a withdrawn
window later takes `deiconify`, which activates it, whereas Tk's own first
showing does not.

`tests/regression/test_window_tests_do_not_race_the_desktop.py` holds the
position tests and the time limit. It runs the position tests under a stand-in
window manager that, like FancyZones, is told by Windows of every window the
process shows and moves it; they pass and it moves none of theirs, and a
control proves it moves a window that is shown.
`tests/regression/test_test_windows_stay_off_the_desktop.py` holds the rest:
the test root, the first-window activation, and the guard, shown biting on
windows that are transparent, so nothing can be seen even for a moment.

### The toast and the keyboard

The toast itself had the same problem as the tests. It was measured in
production conditions: the real watcher was started as the Stop hook starts it,
detached, under a throwaway home, for a session whose toast could send nothing.
Its first toast took the keyboard from the app the user was working in. It did
so 20 seconds after the watcher started in one run and 10 minutes after in
another, while the window was still hidden, and it kept the keyboard until the
toast closed. A stand-in for the user's app, a window in a process of its own,
lost the keyboard for the toast's whole life. The cause is Tk's first-window
activation. The old hand-back read the foreground after it had happened, so it
read the toast itself.

A toast's windows are now made while a thread hook refuses every activation of
them. The keyboard is handed back the moment Tk has made the window, because
Windows can move the foreground to the process before it asks the hook: it did
in 2 of 4 runs, and the keyboard was back 1.2 and 3.1 ms later. Measured again
after the fix: the stand-in app was not deactivated. Real watchers showed their
first toast without any window of theirs becoming the foreground.
`tests/regression/test_the_first_toast_leaves_the_keyboard_alone.py` shows two
real toasts in a fresh process. It checks that neither toast's thread has an
active window, and that the process never holds the foreground or leaves it
empty. It also checks, from outside, that no window of the process ever becomes
the foreground.

That refusal then broke the toast's buttons, and the user noticed the same day:
the close button needed clicking again and again. With the user clicking a
test toast and every step logged inside it, 29 clicks in a row reached the
toast and none reached Tk. A click on a window that is not active first asks
whether to activate it; Tk leaves the answer to Windows, which says yes even
for a no-activate window; the refusal said no, and Windows dropped the click.
The toast's frame now answers that question itself - take the click, never
activate - so the refusal never meets a click. On the fixed toast the user's
first click closed it, and the keyboard stayed where it was.
`tests/regression/test_a_click_on_the_toast_is_never_dropped.py` checks the
answer for every button of a real toast; a real mouse cannot be used in a test
without taking the user's.

## Mutation

No mutation tool was installed, so a small AST mutator was written for this repo
and kept in it, so the numbers can be reproduced:
[`tools/mutate.py`](../tools/mutate.py). Its operators are comparison, boolean,
negation, constant, arithmetic, return-value and statement deletion; prose
strings and type annotations are skipped; each mutant runs first against the
tests that cover its line, with the on-screen tests deselected. That choice is
for speed, and it does not decide a survivor: a mutant those tests let through
is run again against the tests written for its module before it is recorded as
surviving ([below](#coverage-does-not-decide-a-survivor)).

It has been run in passes, as each part was built, so there is no single
repo-wide number. Each pass below is what was actually measured, and a later
pass supersedes an earlier one for the modules it covers.

| Pass | Modules and scores |
|---|---|
| Core, 2026-09-19: **97.2%**, 987 / 1015 | bridge_client 100, mcp_tools 100, session_registry 99.1, compaction 98.9, mcp_server 98.4, token_store 98.4, closure_hook 97.2, cli 91.6, context_meter 87.8 |
| compact_progress, 2026-09-19 | 100 (80 / 80) |
| Settings, 2026-09-19, re-measured after tests for the survivors | settings 98.0, settings_cli 90.1, settings_window 78.3 |
| The settings window, 2026-09-20 (re-measured after the timeout audit below): **97.6%**, 243 / 249 | settings_window 97.6 |
| The settings window on tabs, 2026-09-23, measured with survivors rechecked ([below](#coverage-does-not-decide-a-survivor)): **97.5%**, 346 / 355 (94.4% before the recheck) | settings_window 97.5 |
| Idle notifier, 2026-09-20 (re-measured after the fix described below): **99.0%**, 787 / 795 | app_sessions 100, idle_arming 100, idle_watch 99.4, toast_text 98.2, idle_state 97.5 |
| Remote Control toast, 2026-09-20: **97.6%**, 847 / 868 | app_sessions 100, idle_arming 100, session_registry 99.1, toast_text 98.4, idle_watch 95.5 |
| Hold and startup setting, 2026-09-20 (re-measured after tests for the survivors): **98.8%**, 925 / 936 | mcp_tools 99.1, idle_watch 99.0, idle_state 98.6, remote_startup 94.4 |
| UI and Win32, 2026-09-19, superseded below for the two UI modules | cache_window 92.6, detach 80.4 |
| The two UI modules, 2026-09-20 (after the changes described below, re-measured after the timeout audit): **98.0%**, 451 / 460 | desktop 100.0, toast_view 97.7 |
| ChatGPT Desktop platform, 2026-09-21 (re-measured after the wire protocol's tests were given literal assertions): **87.2%**, 321 / 368 | codex_home 93.0, codex_meter 92.5, codex_threads 87.8, platforms 85.5, codex_compact 82.4 |
| The Codex caller binding, 2026-09-25, re-measured after a missing rollout was passed over: **95.8%**, 113 / 118 (53.8% before it had tests of its own, 64 / 119) | codex_caller 95.8 |
| The Claude Code mod, 2026-10-02, with [`tools/mutate_mod.py`](../tools/mutate_mod.py), re-measured after tests for the survivors: **97.2%**, 382 / 393 (87.3% before, 344 / 394) | tools.js 100, run.js 100, rules.js 99.1, requests.js 98.2, files.js 95.0, register.js 84.6 |
| The mod in a session with no terminal (its `/compact`), 2026-10-07: **97.2%**, 493 / 507 (96.8% on the full pass, 491 / 507; its two survivors in the new code were then killed by tests for them, checked by hand) | handoff.js 100, rules.js 100, run.js 100, tools.js 100, requests.js 98.4, files.js 92.0, register.js 85.5 |
| A band drawn as the run ends, 2026-10-07: **96.7%**, 756 / 782; the new survivors are equivalent (the settle delay's exact value, the change count's start and step), the rest of the kinds below | run.js 100, tools.js 100, handoff.js 100, rules.js 99.2, band.js 98.7, requests.js 98.7, files.js 92.0, register.js 80.4 |
| A run lost in a reload, 2026-10-07: **97.3%**, 751 / 772; every survivor of the kinds below (a hook's `return result` after passing the event on, now on more lines of the compaction hook; `return undefined` as `return`; an error's words never shown; the turn end's pre-check; a missing start counted from 1 ms rather than 0) | run.js 100, tools.js 100, handoff.js 100, band.js 99.6, rules.js 99.2, requests.js 98.7, files.js 92.0, register.js 83.0 |
| The band above the prompt, 2026-10-07: **97.5%**, 735 / 754 (94.3% on the full pass, with 13 timeouts while the machine was busy; the survivors and timeouts were run again, idle, against tests added for the real ones) | band.js 100, handoff.js 100, tools.js 99.2, rules.js 99.2, requests.js 98.7, files.js 92.0, run.js 92.1, register.js 87.4 |
| The check after every compaction, 2026-10-09, re-measured after tests for the survivors: **81.9%**, 564 / 689 (69.5% before; the new tests found two real gaps, both fixed). Most survivors left in `provenance` are its command line's help text | provenance_match 85.2, provenance_transcript 83.2, provenance_items 82.8, provenance 78.9 |
| The mod with the provenance instruction on every compaction, 2026-10-09: **96.8%**, no survivor on a changed line | run.js 100, rules.js 99.2 |
| The idle toast through the mod, 2026-10-02: the mod **97.2%**, 478 / 492 (96.5% on the first pass, 471 / 488; one survivor of the second pass was killed afterwards by a test for it, checked by hand); the watcher's side, re-measured after tests for the survivors, **98.4%**, 671 / 682 (96.6% before, 659 / 682) | handoff.js 100, run.js 100, tools.js 100, rules.js 99.2, requests.js 98.4, files.js 92.0, register.js 83.6; idle_watch 98.5, mod_handoff 98.1 |

No module measured is below 60%, the floor this project holds every module to.
The sidecar, the turn-end hook and Codex Remote Control were built after the
last pass and have no mutation score yet; of the Codex MCP binding, only
`codex_caller` has one. The five mutants it lets through are equivalent. Four
rename the labels it gives the Codex surfaces, which never leave the process:
the tools compare a bound surface only with the same constant, and nothing
writes one down or shows it. The fifth replaces the empty default for a
missing parent command with other text that does not say "codex" either, so
the answer is the same.

The mod's pass uses the same operators on its JavaScript, with Claude Code's own
test host (`claude plugin test`) as the oracle: every mutant runs the mod's whole
suite. Its eleven survivors are equivalent. Eight make a hook that has already
passed the event on return nothing instead of the result it was handed, and
Claude Code keeps that result either way; a test asserts what each hook hands
back, and passes with or without them. Two write `return undefined` as `return`.
One returns `undefined` for `null` where the caller asks only whether it is a
number, and the last widens a pre-check at the turn end that the run itself
makes again before it acts.

The idle toast's hand-off added three more of the same kinds to the mod's list,
all equivalent: the `session.end` hook's `return next(e)` written as `return`
(the hooks' class above), `files.read`'s `return undefined` written as
`return`, and the text of two errors that are caught where they are raised and
never shown. On the watcher's side, `mod_handoff` lets through one: the name of
the temporary file a request is written to, which `os.replace` consumes
whatever it is called. Its two timeouts are mutants that make the wait for the
mod's answer never end (no sleep, or never give up); they are unfinished
measurements, not detections. `idle_watch`'s survivors are all on lines this
change did not touch.

The `/compact` a mod runs where it cannot compact in-process left two
survivors, both since killed by tests for them (each mutant re-run by hand): the words
the mod gives when `/compact` compacts nothing and says nothing, and the
clearing of its mark for its own `/compact`, without which the person's next
`/compact` would be taken for the mod's. What survives is the kinds above, one
more of them a hook's `return result` after it has passed the event on.

### The ChatGPT Desktop pass

The first pass measured entirely after timed-out mutants began to be re-run
against their own tests ([below](#a-timeout-is-not-a-detection)), so it is the
only one above with no unsettled mutants at all: 0 timeouts of 368.
Its first run scored 79.8% overall, with `platforms` at 62.7% and
`codex_compact` at 73.6%. The survivors all named the same cause: the tests
asserted Codex's method names against this repo's own constants, and so could
not see a rename. They now assert the literal names.

The earlier passes were measured before that fix and understate detection
wherever a module has many import-time constants. They are not regressions,
because those mutants had no verdict at all.

### What the survivors were

**Core.** The 28 survivors are equivalent in behaviour: CLI help text (13),
tail-reader tuning in `context_meter` (window size, growth factor, a read length
past EOF: 6), `__main__` guards in modules nothing spawns as `python -m` (4),
unused `reason` defaults (2), temp-file suffixes (2), JSON indent (1), and `-1`
vs `-2` as the "disqualified" score (1).

That fourth group used to read "`__main__` guards run only in subprocesses",
which was wrong wherever something *does* spawn the module:
`conpact.settings_window` (a toast's Settings link), `conpact.idle_watch` (every
armed session) and `conpact.toast_view` (`--demo`) each have a guard that is the
whole of what that command does, and all three are now tested through `runpy`.

**Settings.** `settings_cli`'s six are argparse help strings. `settings_window`'s
were Tk geometry (padding, widths, row and column numbers, deleted `.pack()`
calls) which no assertion *there* made. That was written as though it were a
property of Tk. It is not: the same module was re-measured on 2026-09-20 and went
to **97.6%**.

With its settings on tabs it was measured again on 2026-09-23: 335 of 355 killed,
94.4%. Twelve of the twenty survivors were on lines that run when the module is
imported (the tab names, the window's width, default arguments), and the tool
gave every such line only the `runpy` test, so those mutants never met the
window's own tests. This page first put the module at 97.7% after re-running the
twenty by hand, which was one too many: that recheck counted a kill on a line
nothing can see (below), and it called all twelve of its kills import-time when
two import-time survivors (the click prefixes) had survived and two of the kills
were on other lines. The tool now does the recheck itself, and measured with it the same day
the module is at **97.5%**, 346 / 355. Eleven of the twenty were killed on
recheck: ten import-time ones, and deleting `home.migrate()` from `main`, which
only the test that reads each entry point's source can see. The nine left change
nothing a user sees:

- three initial texts that the form overwrites as soon as the window is built;
- the build-time focus, which opening the window moves to the same box;
- the two internal click prefixes, built and read from the same constant;
- the X11 name for Shift+Tab, which Tk on Windows refuses either way;
- a geometry update with nothing left to do (its recheck did not finish in 300
  seconds, so it stays a survivor, not a kill);
- inserting a setting's text at index 1 rather than 0 into a box just emptied,
  where Tk clamps both to the same place. The hand recheck had counted this one
  as killed on a single failing test that passes with the mutant in place, so
  that kill was a flaky failure, not a detection.

**Idle notifier.** Reading `idle_watch`'s eleven survivors found that the
watcher's deliberate swallow of anything a toast raises was also
swallowing the tests' own assertions. The re-measure afterwards confirms the
repair, 96.4% to **99.4%**, with one survivor left (dropping
`super().__init__(reason)` from an exception whose message nothing reads:
equivalent). The remaining seven are equivalent too: a temp-file suffix, a retry
budget and a slot count in `idle_state`, and three in `toast_text`'s "1.3M"
branch, where wrapping the stripped characters in `XX` strips the same ones.

**Hold and startup setting.** This pass read its own survivors hardest: five of
the nineteen were real gaps, not equivalents, and each is now a test:

- a dismissed Remote Control toast coming back at the next stage;
- a failure reason that never reached the log;
- `hold_minutes_left` failing to separate "0 minutes, about to lapse" from "not
  held at all";
- a failed write leaving a `.tmp` behind in the user's `~/.claude`;
- that file coming back re-indented.

The eleven left are equivalent: temp-file names, a retry budget, `return False`
becoming `return None` where only truth is read, `super().__init__(reason)` on an
exception whose message nothing reads, and three messages whose tests assert a
substring the `XX` wrapping keeps intact.

**The two UI modules.** `desktop` and `toast_view` were once below the standard,
at 57.6% and 53.5%. The reason turned out not to be that a window is hard to
test (the suite has driven real Tk widgets off screen at -4000,-4000 all along).
It was that three kinds of code could not be reached by a mutation run at all:
calls that reach for `ctypes.windll` at call time, which only the deselected
on-screen tests execute; assertions no mutant could fail ("the answer is one of
the two allowed values"); and `present()` / `main()`, proved only in a
subprocess. A follow-up change removed all three causes, and the run then put `desktop` at
97.3% and `toast_view` at 76.0%.

The 94 survivors of that run were read rather than accepted, and they
were not the equivalents this project had assumed. Five were behaviour:

- `tick()` failing to book its own next tick, which stops the countdown, the bar
  and the polling for good;
- `_fill(1.0)` and `bar.coords(...)` deleted, so the bar never moves while a
  compaction runs;
- `span or 1`, the guard against a spanless model dividing by zero;
- `daemon=True` on the worker, without which a stuck bridge call holds the
  process open;
- `act_into`'s `"error"` state, the only thing between an exception on a worker
  thread and a toast that waits forever.

Forty more were the whole of `_build`. So **Tk geometry is not something "no
assertion can see"**: `pack_info()` gives the side, fill, expand and padding a
widget was packed with, `cget()` gives its font, colours and wraplength, a canvas
gives its item coordinates, and a widget that was built and never packed raises
`TclError`, which is the fault most worth catching. One test reading the built
tree back out of Tk killed every layout mutant in `_build`.
`settings_window`'s own survivors have not been re-measured against this.

The nine left are accounted for. Five are equivalent: `px()` clamps to a minimum
of 1, so `px(0)` and `px(1)` are the same pad; the work area's fallback left and
top are discarded by `_, _, right, bottom`; and deleting
`root.update_idletasks()` from `show()` changes nothing, because Tk computes a
window's requested size synchronously as widgets are packed. Three are argparse
help text. One is `sys.exit(main())` under the `__main__` guard. (Before these
features, the remediation branch alone had measured 96.7%, 535 / 553.)

### A timeout is not a detection

The tool used to count a timed-out mutant as killed, and this repo's numbers
inherited that. They should not have: a timeout says the run hit its limit, not
that any test failed. It happens exactly where it hides most, because a mutant
on a *module-level constant* is covered by the whole suite, which is what pushes
it past the limit in the first place.

All **39** timeouts behind the two UI passes and the settings window were re-run
one at a time against their own module's tests. **Eight were survivors.** One
silently disabled `python -m conpact.settings_window`, which is the whole of what
a toast's Settings link spawns; two more were paddings asserted nowhere; two were
assertions that computed their expectation from the constant they were meant to
be checking, so the mutant moved both sides and passed. Corrected, the published
figures had really been **97.0%** and **95.2%**, not 98.0% and 97.6%. Tests for
the eight (one is provably equivalent) put them back to **98.0%** and **97.6%**,
this time without a timeout counted as a kill.

`tools/mutate.py` no longer makes that mistake. A timed-out mutant is re-run
against its own module's tests at a 300-second limit, only `killed` counts
towards a score, and a timeout that still does not settle is listed with the
survivors (`tests/regression/test_timeout_is_not_detection.py`).

Known limits:

- One unsettled timeout is left, in `settings_window`: inverting its `__main__`
  guard makes *importing* the module open the window and sit in its main loop,
  so the suite hangs at collection instead of failing. Two other mutants used to
  hang the same way and no longer do: the tests that drive a Tk main loop now
  carry a five-second watchdog, so deleting the `show()` call that would have
  ended the loop fails in seconds.
- A mutant that makes the suite hang elsewhere still counts as detected (one
  does: deleting the watcher's sleep spins `wait_for` forever).
- A timed-out mutant is killed with its whole process tree, because a test that
  starts a real child (`test_detach` does) can leave one behind; that child once
  kept an inherited pipe open and wedged a run for 105 minutes, which is why the
  test process is now given no pipes at all.

**The passes other than those three still count their timeouts as kills**,
because they were measured before this was understood and have not been re-run.
The exposure: `mcp_tools` 106 of its 338 mutants in the hold-and-startup pass,
`toast_text` 26 in the Remote Control pass and 4 in the idle-notifier pass,
`ui_style` 11 of 83, `idle_watch` 5 across three passes, `context_meter` 2,
`compact_progress` 2, `idle_state` 2, `settings_cli` 1 and `remote_startup` 1.
Those rows are upper bounds until they are re-run, and on the measured rate (8 of
39) some of them will move.

### Coverage does not decide a survivor

Each mutant runs first against the tests whose coverage context names its line.
For most lines that is exact. For a line that runs when the module is imported
it is not. A module is imported once per test process, at collection, which is
no test at all, so the only context such a line collects is from a test that
runs the module again: for the settings window, the `runpy` test of
`python -m conpact.settings_window`. The map gave `WIDTH = 460` to that one test,
the mutant `460 -> 461` passed it, and it was recorded as a survivor although
`tests/test_settings_window.py` asserts the width. A test that reads a module's
source (the check that every entry point moves the state first) executes none of
it, so no context can name that test either.

So a survivor is no longer the map's verdict. Before a mutant is recorded as
surviving, `tools/mutate.py` runs it again against its module's own test file,
whole, and every regression test that imports the module or names it in a
string (`runpy`, a list of modules whose source is read), at the same 300-second
limit as the timeout retry. A failure there is a kill; a recheck that does not
finish leaves the mutant a survivor, never a kill. The row keeps the recheck's
own verdict under `recheck`. A mutant whose first run was the whole suite is not
asked again, and neither is a file that already ran whole
(`tests/regression/test_coverage_never_decides_a_survivor.py`).

Mapping every import-time line to the whole suite would have been the other
fix. It was rejected because the whole suite is what pushes such a mutant past
the first limit in the first place; rechecking only the survivors costs one run
each, and survivors are few. On the settings window, 20 of 355 mutants were
rechecked, and those rows took 5,308 of the run's 29,379 worker-seconds, first
runs included (about 90 minutes on six workers, mapping included).

Every pass above except the settings window's latest was scored before this,
so its survivors are the map's verdict. That can only have understated those
scores, and a survivor listed there as equivalent was never run against its
module's own tests.

## Observed live

### Claude Code

- **The mechanism** (2026-09-19), against a disposable "Hello" session: a
  plain-text probe landed as `origin:{"kind":"human"}` on the ordinary user
  queue, not peer-wrapped; `/compact` rendered as a real command and produced a
  `system/compact_boundary` event, `trigger:"manual"`, `preTokens 57592 →
  postTokens 7395`, plus an `isCompactSummary:true` replacement.
- **Self-targeting:** `--self --dry-run` bound the correct current session from
  the runtime's identifiers, not by name.
- **The Stop hook** (2026-09-19): a request queued with `--self --request` as a
  turn's last action was sent by the installed hook (HTTP 200). It waited in the
  session's queue until the turn had ended, then ran as a real `/compact`:
  `preTokens 656725 → postTokens 19111`. The hook's measured context size
  matched Claude Code's own `preTokens` exactly.
- **The MCP tools, from live sessions:** agents' `queue_compaction` calls have
  been fired by the hook in live sessions; for example the session building
  conPACT queued one at 11:07Z on 2026-09-22 and it compacted at 11:23:31Z from
  602,408 tokens.
- **The minimum refusing a live closure** (2026-09-22T18:12:09Z): the hook
  measured 138,243 tokens against a minimum of 200,000 and logged
  `below_threshold`, sending nothing.
- **The idle toast** (2026-09-19): armed at 21:19:44 for 417,226 tokens, it came
  5 minutes into an idle stretch (`idle_seconds` was 300), and **Compact now**
  compacted it for real, 417,226 → 19,483 tokens in 117.1 s.
- **The early stage** (2026-09-20): with `idle_seconds` 600 and `lead_seconds`
  300, the last reply was at 00:00:56 and the early toast came at 00:10:56, to
  the second. **Compact now** compacted 317,830 → 20,355 tokens in 108.0 s, and
  the log entry carries `"stage": "early"`. The expiry stage never came, because
  compacting ends the watch.
- **The expiry stage after an early toast was let go** (2026-09-20T04:03:12Z):
  the early toast timed out, and the expiry toast then compacted a 663,561-token
  session. The log entry records the early stage's timeout.
- **Archiving** (2026-09-19, from the app's own log): `LocalSessions.archive` at
  02:04:52 and `LocalSessions.unarchive` at 02:05:11 for a session that kept
  running throughout, so archiving does not stop a session and the notifier has
  to read the app's store. `archived-sessions.idx` is rewritten within a second
  of the event, and agrees with each record's `isArchived`.
- **The mod, with Remote Control off** (2026-10-02, Claude Code 2.1.284 in an
  interactive terminal session whose record had no `bridgeSessionId`): the mod
  answered `queue_compaction` with `"transport": "mod"`, the agent finished its
  answer, and 10 s after the turn the transcript gained a `compact_boundary`
  (`preTokens` 55,333) and the mod's line `conpact: compacted 55,333 to 3,964
  tokens`. A second session, which loaded the mod only from the `env` block of
  `~/.claude/settings.json`, as the Desktop app does, queued with a 1,000-token
  minimum and compacted 55,583 → 4,002 tokens. The boundary of a mod's
  compaction is recorded with `trigger: "manual"`.
- **The idle toast through the mod, with Remote Control off** (2026-10-02,
  Claude Code 2.1.284, an interactive terminal session loading the mod from a
  checkout through `--settings`, its record's `bridgeSessionId` empty): the
  mod's heartbeat appeared within seconds of the start; the watcher's Claude
  adapter, run against that session once it was idle, found it reachable
  through the mod and not over the bridge, left its request, and the mod took
  it: the transcript gained a `compact_boundary` (51,102 → 3,808 tokens, 7.1 s)
  and the line `conpact: compacted 51,102 to 3,808 tokens`, the watcher read
  the result from the transcript, and the request file was gone.
- **The mod in the Desktop app's Code tab** (2026-10-07, Claude Code 2.1.289):
  the app runs Claude Code as an SDK session, whose `session.start` says
  `isInteractive: false`, and there Claude Code refused the mod's in-process
  compaction outright: "not available in a headless (-p / SDK) session yet".
  A 308,000-token session's idle toast reported exactly that, and two
  agent-queued requests in other sessions sat waiting on it. In the same mode
  (`-p` with stream-json in and out), a mod that ran `/compact` with
  `$.command.run` reached Claude Code's own compaction, the event
  `session.compact` with the trigger `manual` and the command's text as its
  instructions, and the command resolved after it; that probe session had no
  messages yet, so the compaction was the engine's "Not enough messages to
  compact.". Then live, in a Desktop session of 285,423 tokens loading a check
  mod through hot reload: at the end of a turn that answered, the mod's
  `$.session.compact` was refused in those words, and its
  `$.command.run({ command: 'compact', args })` started the compaction 0.1 s
  later. The `session.compact` event carried the trigger `manual` and the args
  as its instructions, the transcript gained a `compact_boundary`
  (285,423 → 18,550 tokens, 84.7 s, trigger `manual`) whose summary followed
  those instructions, and the command resolved 14 ms after the compaction
  finished.
- **The band above the prompt, in a terminal** (2026-10-07, Claude Code
  2.1.289 run in a pseudo-console, signed out, the mod loaded from a copy of
  `src/mod` through `CLAUDE_CODE_PLUGIN_DIRS`): with a request, a running run,
  a compaction and a failure each set in the mod's store for the session, the
  row drew `◇ conPACT queued ≥ 150k · keep: …  cancel`, `◆ conPACT compacting
  keep: …`, `✓ conPACT 285.4k → 18.6k ━─── −93.5% 1m 25s  ×` and
  `✗ conPACT failed Not enough messages to compact.  ×` above the prompt; the
  README's pictures are those screens. The same run showed the old status
  line as a warning (`⚠ conpact: compaction queued for the end of this turn`)
  repeating the band, which is why it was dropped. An idle toast request left
  for that session was taken within the poll, and the mod's in-process call
  was answered `No messages to compact`, as a terminal session with nothing in
  it should be, not refused as the Desktop's is.
- **The band in the Desktop app's Code tab** (2026-10-07, 2.1.289, the drawing
  hot-reloaded into a session): each state drawn; the moving marks (queued,
  running) are drawn in a frame of their own, which went opaque white in a
  dark theme until the drawing declared both colour schemes (reproduced in a
  browser, a dark page framing the same SVG, and fixed there before it was
  checked again in the app).
- **A run lost in a reload** (2026-10-07, 2.1.289, a Desktop session whose
  queuing turn also removed a mod from its hot-reloaded folder): the reload
  dropped the mod's run after its `/compact` began. The compaction finished
  (466,356 → 17,717 tokens, 65 s) but the request stayed `executing`, the band
  read "compacting", and the next turn end after the stale bound compacted the
  session again (150,262 → 18,159, its second try). The same day's other
  session showed the transcript line drawn by the app as a block in the
  conversation repeating the band. The mod now ends such a request with the
  compaction it started and writes no transcript line; that fix is measured in
  the mod's suite, not yet in a live reload.
- **Requests stranded by the rename** (2026-09-22): MCP servers started
  before the project was renamed wrote to the old folder; the reader now
  looks there too, and the first stranded request fired at the next turn end.

### ChatGPT Desktop

- **Compacting a thread the desktop holds, through the sidecar** (2026-09-22):
  compacted in place from 91,485 to 11,956 tokens with a clean `task_complete`.
- **The turn-end hook** (2026-09-22): the sidecar armed a live thread from its
  `turn/completed`, 605 ms after the event (`idle-log.jsonl`: `codex_armed`,
  `via: sidecar turn/completed`, 10:20:02Z); the toast came, and the compaction
  it offered succeeded. It was the hook's first live observation.
- **The MCP binding:** a real Codex thread called `compaction_status` and was
  bound to itself. That call also found a gap, fixed the same
  day: it answered `context_tokens: null`, because the size was being read from
  Claude's transcript store.
- **This repository's macOS setup** (2026-09-23): this task called the installed
  MCP server from ChatGPT Desktop. `compaction_status` bound to the exact active
  task (`01a00000-0000-7000-8000-0000000000a3`) and measured 209,472 tokens. A
  queue call, status read-back and cancel all succeeded. A fourth immediate
  call caught the active-thread file between truncate and write; the file is
  now published by atomic replacement, with a concurrency regression at the
  replacement boundary.
- **A resumed Codex task whose sidecar missed `turn/started`** (2026-09-23):
  task `01a00000-0000-7000-8000-0000000000a2` recorded `task_started` at
  20:49:40Z and called conPACT 12 seconds later, but the sidecar record still
  named no in-flight turn, so `compaction_status` refused. The binding now uses
  the just-recorded code-mode conPACT invocation to select its recent running
  user rollout when the sidecar has no caller, then falls back to exact-one
  running. Regressions preserve refusal for stale markers, multiple callers and
  any ambiguity already reported by the sidecar. The full macOS suite passes
  2,151 tests with 17 platform skips.
- **Codex CLI caller binding alongside ChatGPT Desktop** (2026-09-23): the
  first live CLI probe exposed the real failure mode: three Desktop turns made
  the CLI call refuse, and a first fix incorrectly bound it to the one active
  Desktop task. The corrected server distinguishes its direct parent, ignores
  Desktop's sidecar record for a CLI call, and bound a second live
  `compaction_status` call to its own exact task
  (`01a00000-0000-7000-8000-0000000000a1`, 20,787 tokens). No compaction was
  queued. Queue and idle-hold calls refuse in a plain `codex` process because
  no reachable hook owns that task's app-server at turn end.
- **Codex CLI remote transport** (2026-09-23): Codex CLI 0.155.1 connected to
  conPACT's capability-token-protected loopback app-server through its
  `--remote` and `--remote-auth-token-env` options. A live interactive task
  returned `CONPACT_CLI_REMOTE_READY`; the reconnect line named task
  `01a00000-0000-7000-8000-0000000000a4` and the exact local endpoint. This
  proves the launcher topology before using it for a live queued compaction.
- **A Codex CLI task queueing and running its own compaction** (2026-09-23):
  `conpact-codex` task `01a00000-0000-7000-8000-0000000000a5` called
  `queue_compaction` at 22,212 measured tokens. At turn end its trusted Stop
  hook showed `Running queued conPACT compaction`, then Codex showed
  `Context compacted · 3s`. The rollout contains a native `type: compacted`
  record, the conPACT audit log records `codex_compacted` via `Codex Stop hook`,
  and a following status call reported no pending request. The same live CLI
  also called `compaction_status` successfully before the queue.
- **A thread queueing its own compaction** (2026-09-22): the thread queued it;
  when its turn ended the sidecar logged `codex_compacted` at 11:04:42Z, and the
  thread's rollout recorded the compaction at 11:04:51Z.

### Test-level observations of real components

- **The MCP server:** `tests/regression/test_mcp_queue.py` starts the real
  `tools/mcp_server.py` as a child process and speaks MCP to it over stdio:
  `initialize` (answered `2025-11-25`, the revision Claude Code 2.1.275's client
  prefers), `notifications/initialized`, `tools/list`, `tools/call`, which queued
  a request bound to the child's parent process. Stdout carried exactly the three
  replies.
- **The Stop wrapper:** `tests/regression/test_stop_wrapper.py` runs the real
  `stop_compact.cmd` through `cmd.exe` with hook JSON on stdin against a
  throwaway home: no request and the toast off, exit 0 without starting Python;
  a request, consumed, its outcome logged, exit 0; a large session, a detached
  watcher that is still running after the hook has returned, and stands down
  when its watch is cancelled. The hook must return within 15 seconds of
  starting the watcher. That is timed from the moment the hook records just
  before starting it, not from cmd.exe's launch: on a machine at 100% CPU,
  starting cmd.exe and Python and importing conpact took up to 36 seconds
  before the hook had done anything, and timed from the launch the test failed
  in 16 of 24 loaded runs.
- **Context size:** a real Claude Code 2.1.275 transcript records
  `message.usage` (`input_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `output_tokens`) on each assistant entry, with
  `isSidechain` marking subagent messages; the tests use that exact shape.

## Not yet observed

- conPACT's own mod running a queued request in a Desktop session through
  `/compact` from end to end: the live Desktop check ran the same call from a
  check mod, since a session already running keeps the mod code it started
  with.
- The mod's retry of a compaction refused because a new turn had already begun;
  it is tested through Claude Code's test host only.
- The idle toast's hand-off to the mod from a real toast: the live check ran
  the watcher's adapter, the part that decides the route and hands the
  compaction over, directly against an idle session, not a watch the Stop hook
  armed with a button pressed on screen. The heartbeat marked `ended` at a
  session's end, and a request the mod refused or let lapse, are tested only.
- A live archived session being skipped by the idle notifier.
- Reading a **Claude Code** login from a real macOS Keychain. This is not part of
  the Codex or ChatGPT Desktop integration: conPACT never reads their login.
  This Mac has no Claude Code Keychain entry, so there is nothing to authorize
  or test. The suite's isolation guard deliberately prevents a test from
  touching the user's Keychain; the entry's name and split-login format were
  read from Claude Code's own binary and tested against a fake `security`.
- On Linux, anything live: the suite passes there, but no real Claude Code or
  ChatGPT Desktop session has been driven on a Linux desktop. The toast's Tk
  windows have not been drawn on Linux at all.
- Where ChatGPT Desktop keeps its codex on Linux, on a real install. On macOS the
  live setup found it at `/Applications/ChatGPT.app/Contents/Resources/codex`,
  matching the rule read from the desktop's own code.
- Which Unix lock Codex takes on a thread. Both kinds are probed, so either
  answer is covered.

## How changes are recorded

- Every change has an entry in [`CHANGES.md`](../CHANGES.md) (82 so far),
  saying what changed, why, and how it was verified.
- Every settled design choice has an entry in [`DECISIONS.md`](../DECISIONS.md)
  (61 so far), with the reason for it.
- Every change that altered behaviour has a regression test under
  `tests/regression/` (47 so far), written first and observed failing before
  the change was made.
- Coverage and mutation are measured, above.
