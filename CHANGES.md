# Change Log

Change Log Entries. Newest first.

```yaml
id: CU-20261008-109
type: release
title: "conPACT 1.3.2: the first public release, on a new root"
description: >
  The user asked on 2026-10-08 for the repository to be made fit to go public
  and for its published history to be flattened into one new commit. conPACT
  1.3.2 is that commit, built from the scrubbed tree (CU-20261008-108); the
  earlier public commits, tags and releases are replaced by it (D-20261008-088).
  The version is 1.3.2 in src/conpact/__init__.py and the mod's plugin.json.
impact: none
affected_modules: [src/conpact/__init__.py, src/mod/.claude-plugin/plugin.json]
related_tests: [tests/regression/test_the_mod_compacts_in_process.py, tests/test_mcp_server.py, tests/regression/test_the_published_tree_is_clean.py]
commit_ref: "feature/public-scrub"
author: "Brandon Stonebridge"
timestamp: "2026-10-08T11:00:00+00:00"
verification: >
  The release scan, run strictly over the tree, the commit and the tag, finds
  nothing to fix and nothing to review; the same configuration finds 90
  findings to fix on the development tree. The release is built, tested and
  installed from its own export before it is pushed.
```

```yaml
id: CU-20261008-108
type: fix
title: "The published tree names no private session, codebase or project, and no real thread id"
description: >
  A review of the published tree before it went public found what each
  publish's scan of new lines had let through, since it was there before:
  1. A private session's name in the change log and five test files: it is
     an invented session name now.
  2. Another private codebase, named in token_store's comment, two tests, the
     change log and a decision as the source of the token refresh's headers:
     they now say what the headers are, those a Node client sends with fetch's
     defaults. The headers and the refresh are unchanged.
  3. A contributor's private project, in two change entries and a test: "a
     Codex project".
  4. Real Codex thread ids in the change log, docs/verification.md and the
     incident note, and a session id's first eight digits in the change log
     and two tests: placeholders.
  5. Test fixtures that copied the maintainer's checkout path: C:\src.
  6. The maintainer named as narrator in the change log and the decisions:
     "the maintainer".
  7. The private workflow's name for a regression test, in test docstrings,
     the change log and the mutation tester: "regression test".
  8. A test that spelled out a machine name to prove the detector finds one:
     it proves it with an invented name.
  The tree test's private words (tests/private_words.py) now include the
  session, gateway and company names, as digests. The README credits the
  outside contributions by name, since the new root folds their commits in.
impact: low
affected_modules: [src/conpact/token_store.py, CHANGES.md, DECISIONS.md, README.md, docs/verification.md, docs/incidents/2026-10-07-chatgpt-desktop-codex-cli-path.md, tests/private_words.py]
related_tests: [tests/regression/test_the_published_tree_is_clean.py, tests/regression/test_the_docs_stand_on_their_own.py]
commit_ref: "feature/public-scrub"
author: "Brandon Stonebridge"
timestamp: "2026-10-08T10:45:00+00:00"
verification: >
  The release scan over the scrubbed tree, with the private words and the
  allowed findings in a configuration outside the repository, exits 0 with
  nothing to fix or review. Line endings are unchanged (git ls-files --eol,
  before and after). The full Windows suite and the mod's suite pass on the
  scrubbed tree.
```

```yaml
id: CU-20261008-107
type: release
title: "conPACT 1.3.1: the macOS sidecar after a ChatGPT Desktop update, and large Codex compaction records"
description: >
  The user asked on 2026-10-08 for the remote's changes to be pulled and a
  new release tagged. The release carries the two fixes merged on GitHub
  (CU-20261007-104 and CU-20261007-105) and their integration
  (CU-20261008-106). The version is 1.3.1 in src/conpact/__init__.py and the
  mod's plugin.json, and the README's Windows test line reads the run of this
  tree.
impact: none
affected_modules: [src/conpact/__init__.py, src/mod/.claude-plugin/plugin.json, README.md]
related_tests: [tests/regression/test_the_mod_compacts_in_process.py, tests/test_mcp_server.py, tests/regression/test_the_published_tree_is_clean.py]
commit_ref: "feature/pull-lance-pr3-pr4"
author: "Brandon Stonebridge"
timestamp: "2026-10-08T09:30:00+00:00"
verification: >
  The full Windows suite passes on this tree; the release is built from the
  publish commit and installed in a fresh environment before it is uploaded.
```

```yaml
id: CU-20261008-106
type: fix
title: "The contributed macOS tests run on Windows, and their entries name no private workflow"
description: >
  The two pull requests merged on GitHub on 2026-10-08 were brought into this
  history as a three-way patch of the last publish to the remote's main; the
  result matched the remote's tree. On Windows 34 of the new macOS tests
  failed: the launchd code asks for os.getuid(), which Windows does not
  have, and the macOS tests run on every platform with launchctl faked. The
  test setup now gives os a stand-in uid (501) only where the OS has none.
  The product is unchanged: it calls getuid only on macOS. The two entries'
  verification named the private structure check by its acronym, which the
  published-tree check refuses; they now say "structure check". CU-20261007-105
  was appended at the end of this log and now stands at its top.
impact: none
affected_modules: [tests/conftest.py, CHANGES.md]
related_tests: [tests/test_codex_env.py, tests/test_codex_sidecar_install.py, tests/regression/test_the_published_tree_is_clean.py]
commit_ref: "feature/pull-lance-pr3-pr4"
author: "Brandon Stonebridge"
timestamp: "2026-10-08T09:25:00+00:00"
verification: >
  Before the stand-in: 35 failed, 2,790 passed (34 macOS tests, and the
  published-tree check). With it, the affected suites pass 235 tests and the
  published-tree check passes 3. Before the merge the two files passed 110 on
  Windows.
```

```yaml
id: CU-20261007-105
type: fix
title: "Large Codex compaction histories no longer hide successful completion"
description: >
  A completed compaction of a Codex project wrote a 15,474,577-byte compacted
  record. The completion observer stopped at its 8 MiB partial-record limit
  and reported failure despite the matching turn having completed. Oversized
  compacted envelopes now validate incrementally: string contents are checked
  and discarded, and stdlib JSON validates the bounded remaining structure.
  The observed timestamp/ordinal/type/payload envelope is recognized exactly;
  unrelated oversized records, malformed JSON, additional envelope fields,
  excessive structure, and a different turn still cannot certify completion.
  Success still requires the matching turn's task_complete record.
impact: medium
affected_modules: [src/conpact/codex_completion.py, src/conpact/codex_completion_record.py]
related_tests: [tests/test_codex_completion.py::test_large_compaction_history_is_observed_with_a_bounded_buffer, tests/test_codex_completion.py::test_partial_large_compaction_is_not_evidence_until_its_record_ends, tests/test_codex_completion.py::test_large_history_from_another_turn_cannot_confirm_our_compaction, tests/test_codex_completion_record.py, tests/regression/test_codex_compaction_finishes_before_success.py]
commit_ref: "feature/codex-large-compaction-records"
author: "Lance Sandino"
timestamp: "2026-10-07T23:13:34+00:00"
verification: >
  Reproduced the original observation-limit error by replaying the real rollout
  read-only. The updated observer recognizes the same completed turn in 60 polls,
  with its largest retained buffer below 8 MiB. The recorded context dropped
  from 195,208 to 70,736 tokens. The affected observer, transport, compaction,
  watcher and arming suites pass 196 tests. Native coverage measures 100% lines
  and 95.5% branches in codex_completion and 100% lines and branches in the new
  record validator. The structure check scores 100.0 / 100. A read-only thread/loaded/list
  query to the currently running Desktop sidecar succeeds. No new compaction
  was submitted to that project. The earlier notification came from a
  watcher started before the checkout update and sidecar restart; its older
  generic failure log does not establish the exact transport cause. The
  current Codex daemon session has no owned sidecar and refuses self-binding.
```

```yaml
id: CU-20261007-104
type: fix
title: "The macOS sidecar follows the active Desktop app and its GUI environment"
description: >
  ChatGPT Desktop 26.930.41038 moved its bundled executable from
  Contents/Resources/codex to the signed
  Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex while still
  honoring CODEX_CLI_PATH. A sidecar installed against 26.917.71314 could therefore
  retain a marker to the removed flat path and exit 127 after the update,
  or select that flat executable from a renamed rollback app. The macOS resolver
  now recognizes both layouts only in the active ChatGPT.app, records its bundle
  version in diagnostics, and refuses an automatic marker outside it. Install
  and uninstall now target and verify the gui/<uid> launchd bootstrap as well as
  the caller domain and durable LaunchAgent. Status exposes discrepancies and
  reports generated Codex configuration that still names CODEX_CLI_PATH.
impact: high
affected_modules: [src/conpact/codex_appserver.py, src/conpact/codex_env.py, src/conpact/codex_sidecar_install.py, src/conpact/doctor.py, tools/codex_sidecar.py]
related_tests: [tests/regression/test_sidecar_follows_codex_updates.py::test_a_macos_sidecar_follows_codex_into_the_nested_desktop_bundle, tests/regression/test_sidecar_follows_codex_updates.py::test_macos_does_not_fall_back_to_a_marker_outside_the_active_app, tests/test_codex_env.py::TestMacOS::test_clearing_reaches_a_stale_gui_value_when_the_caller_has_none, tests/test_codex_sidecar_install.py::TestStatus::test_macos_status_exposes_each_bootstrap_domain]
commit_ref: "fix/macos-nested-codex-bundle"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T22:19:34+00:00"
verification: >
  The new regression test failed against 1.3.0 by selecting the old marker,
  then passed with the resolver change. The affected non-GUI resolver,
  environment, installer, status and doctor suites pass 235 tests; the two
  update/status regression files pass 9 tests. A wheel built as conpact 1.3.0
  and contains the changed modules. A live uninstall removed CODEX_CLI_PATH
  from gui/<uid>, persistent state and the marker; reinstall restored the GUI
  value and selected ChatGPT.app 26.1002.52244 with codex-cli 0.162.0-alpha.2.
  Initialization and configRequirements/read then succeeded through the shim
  with requirements null. The structure check scores 100.0 / 100. A whole-suite attempt is
  not claimed: five mutation-helper tests lacked pytest-cov before Tk aborted
  in a window test with exit 134.
```

```yaml
id: CU-20261007-103
type: release
title: "conPACT 1.3.0: the band above the prompt, and Desktop sessions compact again"
description: >
  The user asked for a push and a release tag on 2026-10-07. The package and
  the mod read 1.2.0, the number of the release of 2026-10-03, although a
  Desktop session's compaction through /compact, the band above the prompt,
  the later request stamp, the end of a run lost in a reload and the band's
  read again as a run ends have been added since (CU-20261003-096 through
  CU-20261007-102). The version is 1.3.0 in src/conpact/__init__.py and the
  mod's plugin.json, and the README's Windows test line reads the last full
  run.
impact: none
affected_modules: [src/conpact/__init__.py, src/mod/.claude-plugin/plugin.json, README.md]
related_tests: [tests/regression/test_the_mod_compacts_in_process.py, tests/test_mcp_server.py, tests/regression/test_the_published_tree_is_clean.py]
commit_ref: "feature/release-1.3.0"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T17:40:00+00:00"
verification: >
  The version tests (the mod installs at the package's version, the MCP
  server reports it), the published-tree and docs checks and the release
  installation tests pass; the release is built from the publish commit and
  installed in a fresh environment before it is uploaded.
```

```yaml
id: CU-20261007-102
type: fix
title: "A band drawn as the run ends shows the end, not compacting"
description: >
  The band above the prompt sometimes still read "compacting" once a
  compaction had finished, until something else redrew it. The mod records a
  run's end a moment (0.3 to 1 s) after the compaction itself ends, and the
  end of the compaction is when the surface asks for the band again: that
  drawing read the request still running, and the redraw the mod asked for
  as it recorded the end was folded into the drawing already under way. A
  drawing of the band now reads the request and result again when the mod
  changed either while it read them (band.settled, up to three reads), and
  every change asks for the band once more SETTLE_MS (2 s) later, for a
  surface that kept a drawing begun before the change. The compaction hook's
  superseding and the band's dismiss redraw through the same path.
impact: low
affected_modules: [src/mod/hooks/band.js, src/mod/hooks/register.js, src/mod/tests/band.test.ts, src/mod/tests/world.ts]
related_tests: [tests/regression/test_a_band_drawn_as_the_run_ends_shows_the_end.py, tests/regression/test_the_band_shows_the_compaction.py, src/mod/tests/band.test.ts]
commit_ref: "feature/band-settle"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T16:45:00+00:00"
verification: >
  The mod's suite through Claude Code 2.1.289's test host: 127 pass, 0 fail.
  A drawing held part-way while the run ends reads "compacting" with a
  single read and the result with the fix (the test host folds the end's
  redraw into the drawing, as the Desktop app did); each new test fails with
  the fix taken out. claude plugin validate --strict passes. Mutation
  (tools/mutate_mod.py): 96.7%, 756 / 782, run.js, tools.js and handoff.js
  100%, register.js 80.4%; the new survivors are equivalent (the settle
  delay's exact value, the change count's start and step). Python: 2,788
  passed, 5 skipped. Structure check 100.0 / 100. In the Desktop app the
  band's queued and not-compacted rows were captured from a live session.
```

```yaml
id: CU-20261007-101
type: fix
title: "A compaction the mod lost in a reload ends its request, and the transcript line goes"
description: >
  A reload of the mod while its compaction ran (a hot-reloaded plugin folder
  changing in the turn that queued it) threw the run away with the load that
  made it. The compaction finished, but the request stayed executing: the band
  read "compacting" for ten minutes, and the next turn end then compacted the
  session a second time. Now the load of the mod keeps the runs it owns, and a
  main-session compaction (manual, automatic or the mod's own) that finds the
  request executing with no run of the present load behind it ends the request
  with its outcome, as the run would have (run.adopt). A request still
  executing after the stale bound shows in the band as waiting for its next
  try ("the last run did not finish") rather than compacting, and cancel - the
  band's or cancel_compaction - withdraws it. The mod no longer writes a line
  into the transcript, which the Desktop app drew as a block in the
  conversation repeating the band; a failed compaction still raises a toast.
impact: medium
affected_modules: [src/mod/hooks/run.js, src/mod/hooks/register.js, src/mod/hooks/band.js, src/mod/hooks/tools.js, src/mod/hooks/requests.js, src/mod/tests/run.test.ts, src/mod/tests/band.test.ts, src/mod/tests/tools.test.ts, src/mod/tests/sdk.test.ts, src/mod/tests/handoff.test.ts, docs/claude-code-mod.md]
related_tests: [tests/regression/test_a_lost_run_is_ended_by_its_compaction.py, tests/regression/test_the_band_shows_the_compaction.py, tests/regression/test_the_mod_compacts_in_process.py, src/mod/tests/run.test.ts, src/mod/tests/band.test.ts]
commit_ref: "feature/band-lost-run"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T14:30:00+00:00"
verification: >
  The mod's suite through Claude Code 2.1.289's test host: 123 pass, 0 fail,
  among them a lost run adopted by a manual, a plugin and an automatic
  compaction and not run again, a live run's own compaction left to it, and
  the band read mid-run (a compaction held open) as the run claims, releases
  and ends a request. claude plugin validate --strict passes and no longer
  lists $.ui.log. Mutation (tools/mutate_mod.py): 97.3%, 751 / 772, run.js
  and tools.js 100%; the survivors are the equivalent kinds recorded in
  docs/verification.md. Python: 2,784 passed, 5 skipped.
  Structure check 100.0 / 100. The failure it fixes was seen live in this
  repository's own session; the fix has not yet been seen in a live reload.
```

```yaml
id: CU-20261007-100
type: feature
title: "The mod shows the compaction in a band above the prompt"
description: >
  Everything the mod showed was text: a status line while a request waited or
  ran, a dim transcript line once it had run, a toast when it failed. It now
  also draws one row in the band above the prompt (mod.band), on the terminal
  and in the Desktop app's Code tab: a queued request with the context now,
  its minimum, its try and focus, and cancel; a running one with the size it
  is compacting; and once it has run, before -> after, a meter of what was
  kept, the saving and the time, or why it did not compact, with a dismiss
  mark. The mark and meter are Unicode on the terminal and a small SVG
  elsewhere (a pulsing dot, a turning ring, a check or a cross). A result
  stays 15 minutes or until dismissed. The band is drawn again whenever the
  request or result changes, sits above whatever other plugins draw there and
  yields to a survey. It replaces the pinned status line, which the CLI drew
  as a warning repeating the band. The idle toast's compaction now shows in
  the band too (a running mark, then the session's last result, a waiting
  request left alone). Results record when their run began (started_at).
impact: medium
affected_modules: [src/mod/hooks/band.js, src/mod/hooks/register.js, src/mod/hooks/requests.js, src/mod/hooks/tools.js, src/mod/hooks/run.js, src/mod/tests/band.test.ts, src/mod/tests/world.ts]
related_tests: [tests/regression/test_the_band_shows_the_compaction.py, tests/regression/test_the_mod_compacts_in_process.py, src/mod/tests/band.test.ts, tests/test_mutate_mod.py]
commit_ref: "feature/mod-band"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T10:00:00+00:00"
verification: >
  The mod's suite through Claude Code 2.1.289's test host: 110 pass, 0 fail,
  every band drawing checked on the terminal and the desktop. claude plugin
  validate --strict passes; it lists $.ui.resolve and $.ui.invalidate, and no
  longer $.ui.status. Mutation (tools/mutate_mod.py): 97.5%, 735 / 754, band.js
  100%. In the CLI (2.1.289 in a pseudo-console, the mod loaded from a copy of
  src/mod): all four states drawn above the prompt from the mod's store, and
  an idle toast request taken and compacted in-process ("No messages to
  compact", an empty session). In the Desktop app: each state drawn, and the
  moving marks' white frame in a dark theme reproduced in a browser and fixed.
  Python: 2,779 passed, 5 skipped. Structure check 100.0 / 100.
```

```yaml
id: CU-20261007-099
type: fix
title: "A replacement compaction request is always stamped later than the one it replaces"
description: >
  A request's requested_at_ns is how a Codex turn-end worker tells a request
  recorded before its turn ended from a newer generation (D-20261003-068).
  Python 3.11 reads the wall clock on Windows every 15.6 ms, so a request that
  replaced another within one tick carried the same stamp, and a worker whose
  turn end had that stamp claimed and ran the replacement. request_compaction
  now stamps a replacement at least one nanosecond after the request it
  replaces, read the way the claim reads it; a first request, or one replacing
  an unreadable file, keeps the clock reading.
impact: medium
affected_modules: [src/conpact/compaction.py]
related_tests: [tests/regression/test_a_replacement_request_is_strictly_newer.py, tests/regression/test_codex_request_waits_for_idle.py]
commit_ref: "feature/replacement-request-stamps-newer"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T08:00:00+00:00"
verification: >
  Measured first: time.get_clock_info("time") on this machine reports
  GetSystemTimeAsFileTime at 0.015625 s. The replaced-request test, looped
  2,000 times with the stamp as it was: 490 failures; with the fix: 0. The new
  anchor (a stopped clock) failed 3 of its 5 tests before the fix and passes
  after. Mutation (tools/mutate.py, compaction.py): 97.1%, 102 / 105, every
  mutant on the new lines killed; the three survivors are a temp-file suffix,
  `return None` -> `return`, and a stat() in the existing not_after_ns claim
  path. Python: 2,773 passed, 5 skipped. Structure check 100.0 / 100.
```

```yaml
id: CU-20261007-098
type: fix
title: "A Desktop session compacts again: where Claude Code refuses the mod's in-process call, the mod runs /compact"
description: >
  The Desktop app's Code tab runs Claude Code as an SDK session, and Claude
  Code 2.1.289 refuses a mod's $.session.compact there outright ("not
  available in a headless (-p / SDK) session yet"). Since the mod became the
  default path it took every agent-queued compaction in a Desktop session -
  the Stop hook no longer saw one - and could not run it, and the idle toast's
  compaction through the mod failed in the same words. The mod now reads
  session.start's isInteractive; where it is false it compacts by running
  /compact ($.command.run, command `compact`, the focus as its text), the one
  command it runs, and takes the outcome from the compaction that command makes
  (session.compact, trigger `manual`, during its own run), which spends no
  queued request. A /compact that made no compaction fails in Claude Code's own
  words and is tried again at the next turn ends, as a refused start is. An
  interactive session is unchanged.
impact: high
affected_modules: [src/mod/hooks/register.js, src/mod/tests/sdk.test.ts, src/mod/tests/world.ts]
related_tests: [tests/regression/test_an_sdk_session_compacts_by_command.py, tests/regression/test_the_mod_compacts_in_process.py, src/mod/tests/sdk.test.ts]
commit_ref: "feature/mod-compacts-sdk-sessions"
author: "Brandon Stonebridge"
timestamp: "2026-10-07T07:00:00+00:00"
verification: >
  Measured first: in the failing 308k-token Desktop session the mod's answer
  file held Claude Code's refusal word for word, and a live check mod in a
  Desktop session read isInteractive false. Probe in the same mode (2.1.289,
  -p with stream-json in and out): $.session.compact refused,
  $.command.run({ command: 'compact', args }) reached session.compact with
  trigger manual and the args as instructions, resolving after it. The mod's
  own suite, through Claude Code 2.1.289's test host: 83 pass, 0 fail; the
  ten new SDK tests include five that failed against the old register.js.
  claude plugin validate --strict passes and lists $.command.run. Mutation
  (tools/mutate_mod.py, every mutant through the whole suite): 96.8%,
  491 / 507, then 97.2%, 493 / 507 once the two survivors in the new code were
  killed by tests for them (re-run by hand); register.js 85.5%, the 14 left
  equivalent as documented. Python: 2,758 passed, 4 skipped, 1 failed - a
  Codex claim test that fails about one run in three on its own, in code this
  change does not touch, flagged separately. Structure check 100.0/100.
  Live, in this Desktop session (285,423 tokens, a hot-reloaded check mod
  making the same calls at a turn end): $.session.compact refused, then
  $.command.run started session.compact (trigger manual, the focus as its
  instructions), a compact_boundary of 285,423 -> 18,550 tokens in 84.7 s,
  and the command resolved after it.
```

```yaml
id: CU-20261004-097
type: fix
title: "Exclude routine read-only answers from compaction guidance"
description: >
  The MCP initialization and queue descriptions now distinguish verified,
  saved implementation closure from a completed answer. Routine questions,
  read-only investigations, status reports and intermediate results do not
  queue compaction even with large context; an explicit user request remains
  eligible. The deferred-tool guidance uses the client's actual tool catalog.
  Two read-only answers in one reported chat had each queued an unconditional
  compaction; neither request supplied a minimum and the default minimum was off.
impact: low
affected_modules: [src/conpact/mcp_server.py, src/conpact/mcp_tools.py]
related_tests: [tests/test_mcp_server.py::test_agent_instructions_exclude_routine_read_only_answers, tests/regression/test_closure_instructions.py]
commit_ref: "codex/compaction-connection-lifecycle"
author: "Brandon Stonebridge"
timestamp: "2026-10-04T02:56:39.343470+00:00"
verification: >
  The new discovery-surface contract failed before the wording repair.
  Final affected MCP/caller, closure, documentation, publication and test-hygiene
  checks passed 299 tests in 19.83 s. Server statements/lines measured 98.77%,
  native branches 97.06%; tools statements/lines 100%, native branches 97.92%.
  Structure fitness measured 100/100. Function coverage is unsupported;
  mutation and a new agent-behavior trial were not measured.
```

```yaml
id: CU-20261003-096
type: fix
title: "Bind the current Codex call without requiring an older turn marker"
description: >
  A valid current tool call was ignored when a long turn's start lay beyond
  the bounded turn-state scan. Method-specific binding now reads the current
  open literal call directly, keeps the 200-record bound, and rejects turn
  boundaries and final answers before an older call. It avoids the deeper
  diagnostic history scan during the half-second persistence settling window.
  Missing, unreadable, foreign and ambiguous evidence still refuses. Each MCP
  helper retains only its latest bounded refusal diagnostic in conPACT state;
  it records identity evidence, never tool arguments, source or rollout paths.
impact: medium
affected_modules: [src/conpact/codex_caller.py, src/conpact/codex_caller_log.py, src/conpact/mcp_tools.py]
related_tests: [tests/regression/test_codex_current_call_binding.py, tests/test_codex_caller_log.py]
commit_ref: "codex/compaction-connection-lifecycle"
author: "Brandon Stonebridge"
timestamp: "2026-10-03T16:04:04.178075+00:00"
verification: >
  Eight current-call regressions failed before repair. Final affected caller,
  MCP, identity regression and test-hygiene checks passed 267 tests; public-tree
  and documentation checks passed 29. Changed modules measured 100% statements
  and lines, with native branches 99.09%, 100% and 97.92%. Structure fitness
  measured 100/100. Function coverage is unsupported; fresh mutation and native
  Unix measurements were not taken. Live client activation follows separately.
```

```yaml
id: CU-20261003-095
type: fix
title: "Dismiss pending compaction toasts without losing the worker's outcome"
description: >
  The close button was ignored while a click's worker was busy. Codex's send
  waits for recorded completion, leaving its toast undismissable throughout
  that wait. Dismissal now withdraws the window immediately and retains the
  event loop until the worker returns, then closes without rendering another
  result. The watcher retains the result for its log, and no operation is
  cancelled, repeated or submitted by closing the toast. Closed views stop
  scheduling their result drain. Other action clicks remain blocked while busy.
impact: medium
affected_modules:
  - src/conpact/toast_view.py
  - docs/idle-toast.md
related_tests:
  - tests/test_toast_view.py::test_close_hides_a_pending_send_without_abandoning_its_result
  - tests/test_toast_view.py::test_a_closed_view_never_reschedules_its_worker_drain
  - tests/test_toast_view.py::test_while_working_it_says_so_and_ignores_more_clicks
verification: >
  All four pending-send close cases failed before repair. The relevant toast,
  watcher, Codex adapter, test-hygiene and documentation suite passed 236 tests
  with 4 on-screen tests deselected; final close regressions passed 5 tests.
  Toast statement/line coverage is 99.26% and native branch coverage 100%.
  A fresh toast process on a private Windows desktop, using an isolated profile
  and simulated send, changed from visible to hidden on the close-button event,
  retained the pending worker, and returned only after its result. No real
  compaction or user desktop input was submitted by that probe.
```

```yaml
id: CU-20261003-094
type: finding
title: "A fresh MCP connection activates the caller repair without restarting Desktop"
description: >
  Native configuration reload accepted the source update but reused unchanged
  conPACT processes, and a fresh batch probe still returned the old refusal.
  A backed-up local MCP configuration added only CONPACT_MCP_REVISION to this
  server's environment, giving Codex a changed client identity. Reload replaced
  its conPACT processes; a real awaited Promise.allSettled status call then
  bound the exact investigation chat and reported nothing pending. Refreshed
  tool instructions also contain the per-call refusal guidance. The owning
  app-server stayed running, and no model prompt or thread action was sent.
impact: none
affected_modules:
  - docs/chatgpt-desktop.md
related_tests:
  - tests/regression/test_codex_call_wrappers.py
  - tests/test_mcp_server.py
verification: >
  Configuration parsed before and after with semantic equality except for
  the revision stamp. Exact-owner reload and own-thread MCP status succeeded;
  old-process replacement, fresh instruction metadata and actual batch-call
  binding verified activation. Source gate remains 2731 passed, 4 skipped,
  10 deselected; structure fitness 100/100. Acceptance is not compaction.
```

```yaml
id: CU-20261003-093
type: fix
title: "Serialize compaction request consumers before their generation rename"
description: >
  The broad binding-repair run exposed a concurrent claim losing its renamed
  file. A 300-round temporary-file probe reproduced disappearing claims and
  occasional zero winners. Consumers now hold a nonblocking process-shared
  lease before the rename: a path-keyed Windows mutex or a retained Unix flock
  inode under conPACT's own state. Busy or unavailable leases touch no request;
  the OS releases a lease when its process exits. Existing generation cutoff,
  newer-request restoration and delete-before-execute rules remain intact.
impact: high
affected_modules:
  - src/conpact/compaction_claim.py
  - src/conpact/compaction_claim_lock.py
related_tests:
  - tests/test_compaction_claim.py
  - tests/test_compaction_claim_lock.py
verification: >
  The held-rename regression failed before serialization. Final full suite:
  2731 passed, 4 skipped, 10 deselected; final affected suite: 227 passed.
  A native Windows 1000-round stress probe produced exactly one claim per
  round with no errors. Claim/lease branches: 100%; lease statements/lines:
  96.77%. Structure fitness: 100/100. Native Unix execution is unmeasured.
```

```yaml
id: CU-20261003-092
type: fix
title: "Codex caller binding recognizes awaited batches and briefly waits for identity"
description: >
  A live read-only compaction_status call through Promise.allSettled reproduced
  refusal in the investigation chat: only direct awaited tool calls were
  recognized from rollouts. Literal immediate calls in awaited Promise.all and
  Promise.allSettled arrays now identify the exact method; quotes, comments,
  deferred callbacks and unrecognized wrappers still refuse. Desktop shares
  the CLI's 0.5-second read-only settling window for a call record to appear;
  explicit caller ambiguity and foreign ownership still refuse immediately.
  Refusal guidance applies to the current call rather than disabling future
  closures. Refreshed server instructions also require a fresh status check
  rather than carrying a historical refusal forward. The latest report-chat
  warning carried a 05:52 BST status refusal
  into its final answer without a fresh tool call after the repair/restart.
impact: medium
affected_modules:
  - src/conpact/codex_caller.py
  - src/conpact/mcp_tools.py
  - src/conpact/mcp_server.py
related_tests:
  - tests/regression/test_codex_call_wrappers.py
  - tests/test_codex_caller.py
verification: >
  Live old-code Promise.allSettled status call refused with four running
  rollouts. New isolated regressions reproduced eight failures before repair.
  Final full suite: 2731 passed, 4 skipped, 10 deselected; affected suite:
  227 passed; documentation/privacy: 29 passed. Caller statements/lines: 100%,
  native branches: 98.91%. Structure fitness: 100/100. Activation evidence is
  recorded separately from source validation.
```

> **A note on the name.** This project was called *Clautomatic* until
> CU-20260922-041 renamed it **conPACT**. Entries below that one name the module
> paths, environment variables and MCP tools as they were at the time, which is
> what a change log is for; nothing in them has been rewritten, except that
> CU-20261002-081 reworded the maintainer's private workflow vocabulary out of
> them. Everywhere else in the repository the current names apply.

---

```yaml
id: CU-20261003-091
type: finding
title: "Desktop restart activates the HTTP repair for existing histories"
description: >
  The restarted owner-bound app-server reads the HTTP-only provider with native
  ChatGPT sign-in. Existing histories show the HTTP provider in thread metadata.
  Read-only telemetry for the exact new process records eight successful HTTP
  response-endpoint requests for the investigation chat, with continuing model
  and tool progress, no WebSocket attempts and no idle-timeout/fallback records.
  Account and usage reads succeed. This verifies live activation without sending
  the separate authenticated test prompt rejected by automatic approval review.
impact: none
related_tests:
  - tests/test_codex_transport.py
  - tests/regression/test_codex_http_probe.py
verification: >
  Exact-owner config/read, account/read and thread/read; live get_usage_limits;
  native logs filtered by the new full process UUID and startup timestamp.
  Prior repair suite remains 2689 passed, 4 skipped and 10 deselected; the native
  fake-backend response, compaction and repeated-resume probe passed. Fresh live
  large-context compaction completion is not claimed by HTTP acceptance alone.
affected_modules:
  - HANDOFF.md
  - CHANGES.md
```

```yaml
id: CU-20261003-090
type: fix
title: "Explicit HTTP transport selection also reaches existing OpenAI histories"
description: >
  Native resume preserves a history's saved provider when Desktop sends a null
  provider, even after the global default changes. With the explicit default-
  endpoint native-auth openai-http opt-in, the sidecar snapshots read-only native
  metadata at launch and selects that provider only on Desktop resume/fork
  requests for known OpenAI histories. Target paths must corroborate the record;
  explicit providers and configuration overrides are preserved. No disk reads,
  RPC waits, thread actions or retries are added to the input pump. Missing or
  invalid configuration/metadata leaves the original bytes unchanged.
impact: medium
related_tests:
  - tests/test_codex_transport.py
  - tests/test_codex_sidecar.py
  - tests/regression/test_codex_http_probe.py
affected_modules:
  - src/conpact/codex_transport.py
  - src/conpact/codex_sidecar.py
verification: >
  Native resume without the selector reproduced the old-provider retention.
  The repaired selector passed 121 targeted tests and the full isolated suite
  passed 2689 tests, with 4 skipped and 10 on-screen tests deselected. Existing
  history resumed under HTTP, completed inference and recorded compaction with
  two HTTP POSTs and zero WebSocket upgrades, and retained HTTP selection after
  a second native restart/resume. The WebSocket control failed its upgrade
  assertion as intended. Changed modules measured 90.58/98.33 percent lines and
  88.54/95.83 percent native branches; structure fitness measured 100/100.
  The selector recognized the exact live history and corroborated path in an
  in-memory check with no request dispatched. Desktop activation and real
  inference verification remain pending; automatic approval review refused the
  real authenticated test without explicit permission for its payload.
```

```yaml
id: CU-20261003-089
type: fix
title: "An explicit HTTP-only Codex provider avoids stalled WebSocket retries"
description: >
  The local Codex configuration uses a custom openai-http provider with native
  OpenAI authentication and WebSocket support disabled. The default endpoint,
  existing sign-in, model and reasoning settings are preserved. Current Codex
  rejects overrides to reserved built-in provider IDs, so this is a separate
  provider rather than an invalid override of openai. A documented configuration
  fragment and opt-in native regression probe retain the workaround and its
  wire-level proof. conPACT does not change its default proxy or launch flags.
impact: medium
related_tests:
  - tests/regression/test_codex_http_probe.py
verification: >
  Installed native Codex accepted the custom provider. A WebSocket-enabled
  control violated the zero-upgrade assertion; HTTP-only normal inference and
  manual compaction completed against a local fake SSE backend, with exactly
  two HTTP POSTs, no WebSocket upgrades and recorded rollout compaction.
  The probe uses synthetic file credentials and run-owned state and endpoints.
  User configuration was backed up and applied atomically; config/read reports
  the HTTP provider, account/read reports ChatGPT sign-in and model/list retains
  the selected model. Ongoing turns retain their original provider snapshot;
  CU-20261003-090 covers Desktop resume of existing histories. Live inference
  activation after Desktop restart is still pending.
files:
  - docs/codex-http.toml
  - docs/chatgpt-desktop.md
  - tests/regression/test_codex_http_probe.py
  - HANDOFF.md
```

```yaml
id: CU-20261003-088
type: finding
title: "Native Codex compaction stalls on WebSockets before a successful HTTP fallback"
description: >
  A context-limit compaction connected successfully and received backend progress
  events, then exhausted three five-minute WebSocket idle waits. Codex fell back
  to HTTP after 16 minutes 40 seconds; that path recorded compaction 142 seconds
  later and resumed ordinary output in the same turn. Other chats also recorded
  ordinary-response WebSocket failures. The current executable was explicitly
  enabled in the local filtering firewall, with no runtime socket-permission
  denial recorded. This identifies the failing transport and delayed fallback,
  but does not distinguish a backend defect from silent network-path drops.
  No pending sidecar compaction caused this automatic context-limit operation.
impact: none
verification: >
  Read-only native connection/retry logs, exact rollout compaction and token
  records, process launch arguments, firewall application profile and live chat
  progress. No transport settings or runtime source changed; no paid test request
  was issued. A sidecar-requested manual compaction remains separately unverified.
files:
  - HANDOFF.md
  - CHANGES.md
```

```yaml
id: CU-20261003-087
type: fix
title: "Codex compaction waits for recorded completion and isolates control replies"
description: >
  A start acknowledgement is no longer logged as completed compaction.
  The exact target rollout must record a new compaction and its matching turn
  completion. Interrupted, unreadable and timed-out operations stay unconfirmed;
  an attempted sidecar request never falls through to another executor.
  Loaded threads compact directly; only the explicit not-loaded refusal permits
  a metadata-only resume. Control replies use a bounded per-client sender queue
  outside Desktop's stdout pump. Buffered unrelated replies cannot extend a
  deadline, and aborted rollout turns are recognized as idle. CLI Stop hooks
  detach the worker so waiting for completion cannot hold the turn being ended.
  Sidecar addresses are recorded per owning app-server; turn-end and CLI workers
  carry that owner and never use another server's overwritten global address.
  An unavailable control registry leaves Desktop traffic running, and RPC
  connection, resume, compaction and observation share one overall deadline.
  Listener connections and CLI workers retain the owner validated before a
  concurrent record replacement, so they cannot be redirected during startup.
impact: medium
related_tests:
  - tests/regression/test_codex_compaction_finishes_before_success.py
verification: >
  Thirteen fault reproductions observed failing before fixes. Final broad run:
  python -m pytest -m 'not real_ui' -q --tb=short --cov=conpact --cov-branch
  --cov-report=json:compaction-coverage.json --cov-report=term:skip-covered;
  2644 passed, 4 skipped, 10 deselected, exit 0. Changed modules measured
  90.49-100% statements/lines and 86.36-100% native branches. Structure fitness
  100/100. Function coverage unsupported; mutation score unmeasured. Restarted
  Desktop uses the automatically selected current build with its helper present;
  usage, history and exact-chat binding tools returned successfully. A completed
  live compaction and resolution of upstream WebSocket timeouts remain unverified.
```

```yaml
id: CU-20261003-086
type: fix
title: "Release installs carry the launcher and keep hooks bound to their installation"
description: >
  Wheel and source distributions carry the native launcher sources as package
  data, with installed build output in writable per-install user state.
  Checkout hooks use an absolute bootstrap and reinstall upgrades recognized
  legacy handlers while preserving their neighbours. Windows MCP parent binding
  unwraps only this installation's transparent Python and console launchers,
  with matching OS command lines and bounded ancestry. Invalid authentication
  bytes are refused without stopping the sidecar listener. The mutation coverage
  map owns its database even when an outer run sets COVERAGE_FILE.
impact: medium
related_tests:
  - tests/regression/test_release_installation.py
  - tests/test_runtime_parent.py
  - tests/test_codex_cli.py::test_install_repairs_legacy_hook_without_removing_neighbours
  - tests/regression/test_coverage_never_decides_a_survivor.py::test_coverage_map_owns_its_database
verification: >
  Four release regressions, hook upgrade and inherited coverage database
  observed failing before their fixes. Combined Windows suite: 2,547 passed,
  4 skipped, 10 on-screen tests deselected. Final affected suite: 244 passed.
  On-screen tests: 9 passed, 1 skipped. Mod: 73 passed and strict validation
  passed. The final parent resolver has 100% measured line/branch coverage;
  CLI coverage is 97% combined. Structure fitness: 100/100.
  Wheel built from the source archive, installed in a fresh virtual environment:
  both MCP launch methods bound the fake caller and queued its request; the
  packaged launcher compiled with LLVM and ran the real Codex --version.
  No live session was compacted by these probes. Current Linux/macOS suites
  and a fresh mutation sweep have not been run.
```

```yaml
id: CU-20261003-085
type: fix
title: "Codex compaction requires a caller, its own turn end and bounded sidecar traffic"
description: >
  A sole running thread no longer identifies an MCP caller. Native call records
  require the MCP parent's app-server pid; rollout fallback requires an awaited
  invocation of the current conPACT method, excluding comments and strings.
  A known foreign app-server owner refuses before rollout fallback.
  Turn completion clears outstanding call identity. Queued compactions leave
  requests pending while turn state is running or unknown. Detached workers
  carry the observed end time and cannot spend a newer request.
  An atomic claim isolates request generations and preserves replacement intent;
  deferring a current request never fires an older state-folder copy instead.
  State is checked again before sending. Existing minimum-context settings remain unchanged.
  Stdio and WebSocket RPC waits use a monotonic overall deadline, so unrelated
  notifications cannot keep a request alive forever. Desktop and injected
  requests are buffered to complete JSON lines before sharing the child pipe;
  a split read can no longer splice an injection into an account request.
  Control authentication and reply sends have finite socket deadlines.
  Reply lifting checks the response id, preventing payload text containing the
  control tag from stealing a Desktop response.
impact: behaviour
related_tests:
  - tests/regression/test_codex_compaction_requires_its_caller.py
  - tests/regression/test_codex_request_waits_for_idle.py
  - tests/regression/test_codex_rpc_waits_have_deadlines.py
  - tests/regression/test_sidecar_keeps_requests_whole.py
  - tests/test_compaction_claim.py
verification: >
  Twelve fault-reproducing cases observed failing before fixes.
  python -m pytest -m "not real_ui" -q: 2,439 passed, 4 skipped,
  10 on-screen tests deselected. Final affected suite after the foreign-owner
  and legacy-generation refinements: 545 passed. Additional handshake deadline
  and test hygiene check: 78 passed. Changed modules have line coverage
  90-100% and native branch coverage 81-100%; function coverage is not reported
  by coverage.py. Structure fitness: 100/100. After Desktop restart, the live
  sidecar runs cached build be3fd7e5c1969ff6 and publishes owning process identity.
  compaction_status binds the exact calling thread; get_usage_limits and
  read_thread return successfully without the missing tool-host error.
  The previous queued request logged a skip at 207240 tokens below its 300000
  minimum. A completed live compaction and on-screen UI checks remain unobserved.
files: >
  src/conpact/codex_caller.py, src/conpact/codex_active.py,
  src/conpact/codex_turns.py, src/conpact/mcp_tools.py,
  src/conpact/codex_arming.py, src/conpact/compaction.py,
  src/conpact/codex_appserver.py, src/conpact/codex_sidecar.py,
  src/conpact/codex_ws.py, src/conpact/compaction_claim.py
```

```yaml
id: CU-20261003-084
type: fix
title: "The Codex sidecar follows installed updates before an old build loses its tool host"
description: >
  The install-time marker still named c6fe824d725f02d7 after the Desktop moved
  to be3fd7e5c1969ff6. The older folder now holds only codex.exe; its code-mode
  host and command runner have been pruned. CU-20261002-082 refused a marker
  only once the build was hollow, so it could launch an older complete build
  which Codex pruned later while that app-server was still running.
  The marker is now a fallback when no installed build is discoverable.
  selected_build resolves the explicit CONPACT_CODEX_REAL pin, then the newest
  installed build, then the marker on every launch, shared by the sidecar and
  conPACT's own resolver. A complete older marker no longer holds either path
  back. Explicit environment pins remain unchanged.
  Inspection of Desktop 26.930.2377.0's bundled resolver also found that the
  CODEX_CLI_PATH override returns before normal Codex bundle relocation. Cache
  discovery alone can therefore miss the newly installed Desktop binary.
  Windows detection compares the cache with installed OpenAI app resources,
  preferring the cached binary when its timestamp matches. Unreadable app
  directories do not prevent cache discovery.
  Status shows codex_selected and codex_selection for the next launch; doctor
  checks that selection instead of treating the recorded marker as the build
  that will run. Already running app-servers need a Desktop restart if their
  helpers have been pruned; their executable cannot be replaced in place.
impact: behaviour
verification: >
  Both stale-marker and uncached-bundle regressions observed failing before
  implementation. Final focused suite: 181 passed, resolver branch-inclusive
  coverage 92%. Broader suite before the bundle-discovery extension: 2,388
  passed, 4 skipped, 10 on-screen tests deselected. Read-only live selection names
  be3fd7e5c1969ff6 and confirms its code-mode host, command runner and Windows
  sandbox setup are present. The packaged fallback executes --version as
  codex-cli 0.159.0-alpha.12.1. Desktop UI/history tools have not been driven.
anchor: tests/regression/test_sidecar_follows_codex_updates.py
files: >
  src/conpact/codex_appserver.py, src/conpact/codex_sidecar.py,
  src/conpact/codex_sidecar_install.py, src/conpact/doctor.py,
  tools/codex_sidecar.py, tests/regression/test_sidecar_follows_codex_updates.py,
  tests/regression/test_a_hollow_build_is_not_run.py,
  tests/regression/test_sidecar_status_names_its_codex.py,
  docs/chatgpt-desktop.md, CHANGES.md, DECISIONS.md
```

```yaml
id: CU-20261002-084
type: feature
title: "The idle toast compacts through the mod: a session the conPACT mod runs in needs no Remote Control for the toast either"
description: >
  The mod (CU-20261002-083) made Remote Control unnecessary for a compaction an
  agent queues, but the idle toast is a separate process (conpact.idle_watch,
  started by the Stop hook) and could still reach a session only over the
  Remote Control bridge; a session with Remote Control off got the "turn on
  Remote Control" toast even with the mod running inside it. The two now meet
  in three small files per session under ~/.conpact/mod/: the mod writes a
  heartbeat (beat/<id>.json) at the session's start, every 30 s, and once more
  marked ended when the session ends; the watcher's Claude adapter
  (watching.Platform) treats a heartbeat younger than 90 s as reachable, and
  ahead of the bridge where both are there. "Compact now" and auto-compact then
  bind the idle session (without requiring a bridge), leave a request
  (ask/<id>.json: an id and a lapse 10 s out) and wait for the mod's answer
  (answer/<id>.json). The mod looks every 2 s ($.clock.every), takes a request
  only once - it keeps the id in its store as handoff:<id>, since a mod cannot
  delete the file - and never after its lapse, answers `claimed`, compacts the
  session with $.session.compact (no instructions, as the bridge's /compact had
  none) and answers `compacted`, `skipped` or `error`, with the usual
  "conpact: compacted ..." line. The watcher removes the request once answered
  or lapsed, follows the compaction in the transcript as before, ends the
  toast's progress early with "Couldn't compact: ..." when the mod answers
  skipped or error, and reports a request not taken by 3 s past its lapse as
  failed, without sending over the bridge instead, so a slow mod cannot
  compact twice or after a reported failure. A session with neither route still
  gets the Remote Control toast. New: conpact.mod_handoff (the watcher's side)
  and src/mod/hooks/handoff.js (the mod's); the mod's only write call,
  host.fs.write in register.js, refuses any path but a beat or an answer under
  ~/.conpact/mod/ (rules.isWritable). The watcher clears these files once a
  week old; the mod clears week-old handoff:<id> records with its others.
impact: behaviour
verification: >
  Live, Claude Code 2.1.284, an interactive terminal session with Remote
  Control off (its record's bridgeSessionId empty) loading the mod from this
  branch through --settings: the beat appeared within seconds of the start;
  the watcher's Claude adapter, run against the idle session, found it
  reachable through the mod and not over the bridge, left its request, and
  the mod took it - the transcript gained a compact_boundary (51,102 -> 3,808
  tokens, 7.1 s) and the line "conpact: compacted 51,102 to 3,808 tokens",
  the adapter read that result from the transcript, and the request file was
  gone. Red first: the new Python tests failed (no conpact.mod_handoff, and
  the watcher still offered the Remote Control toast), and the anchor failed
  against main. Mod suite (claude plugin test): 73 pass. Python: watcher and
  hand-off tests 163 pass; anchors 21 pass. Mutation, tools/mutate_mod.py:
  96.5% (471 of 488) first, then 97.2% (478 of 492) after the write guard's
  test moved into rules.isWritable and a test for claim's null (that last
  mutant checked by hand); handoff.js 100%, the 14 left equivalent
  (docs/verification.md says why). tools/mutate.py on idle_watch and
  mod_handoff: 96.6% (659 of 682), then 98.4% (671 of 682) after tests for the
  survivors; mod_handoff 98.1%, idle_watch 98.5%, nothing surviving in the new
  code but one equivalent temp-file name and two timeouts that hang the wait.
  Full suite, Windows: 2,468 passed, 5 skipped. Structure check 100.0.
  Not observed: a real on-screen toast pressed against a mod-reached session
  (the adapter was driven directly), the `ended` beat at a real session's end,
  and a refusal or a lapse live. Linux and macOS not run.
anchor: tests/regression/test_the_idle_toast_reaches_the_mod.py
files: >
  src/conpact/mod_handoff.py (new), src/conpact/idle_watch.py,
  src/mod/hooks/handoff.js (new), src/mod/hooks/register.js,
  src/mod/hooks/files.js, src/mod/hooks/requests.js, src/mod/hooks/rules.js,
  src/mod/hooks/run.js, src/mod/tests/handoff.test.ts (new),
  src/mod/tests/world.ts, src/mod/tests/rules.test.ts,
  tests/test_mod_handoff.py (new), tests/test_idle_watch.py,
  tests/test_mutate_mod.py,
  tests/regression/test_the_idle_toast_reaches_the_mod.py (new),
  tests/regression/test_the_mod_compacts_in_process.py, README.md,
  docs/claude-code-mod.md, docs/idle-toast.md, docs/security.md,
  docs/setup.md, docs/how-it-works.md, docs/architecture.md,
  docs/verification.md, HANDOFF.md,
  CHANGES.md, DECISIONS.md (D-20261002-066)
```

```yaml
id: CU-20261002-083
type: feature
title: "A Claude Code session compacts itself in-process: the conPACT mod answers the queue tools and compacts at the turn end, with no Remote Control"
description: >
  Claude Code's mods (in-process plugins, early access in 2.1.284, on by default
  from 2.1.287) can compact the session they run in, between turns, through the
  call /compact makes ($.session.compact). conPACT now ships one, in src/mod,
  installable as conpact@conpact from the repository's own marketplace
  (.claude-plugin/marketplace.json) or loaded from a checkout through
  CLAUDE_CODE_PLUGIN_DIRS. Where it loads it is the route every agent-queued
  compaction takes: it answers the MCP server's queue_compaction,
  cancel_compaction and compaction_status itself, under their names and with
  the server's arguments, refusals and words (adding "transport": "mod" to the
  data), keeps one request per session in its own store, and once a main-loop
  turn has ended with an answer it compacts the session with the focus as the
  instructions - checking the minimum (the request's own, else
  closure_min_context_tokens) once, refusing a throwaway worktree session
  unless guard_spin_off_sessions is off, and showing the outcome as a
  transcript line or, on failure, a toast. A run Claude Code refused to start
  goes back in the queue, up to three tries; a manual or automatic compaction
  while a request waits spends it. hold_idle_toast and all of Codex stay the
  server's, and where the mod does not load the server and the Stop hook act as
  before. The plan this follows proposed the mod registering its own tools and
  the server being removed; that was adapted because mods are switched off by
  Anthropic's rollout on this machine's 2.1.287 and are early access on the
  2.1.284 the Desktop app bundles, so the old route has to take over by itself
  wherever the mod is absent. Also: tools/mutate_mod.py, the mutation tester
  for the mod with `claude plugin test` as its oracle; the version is 1.2.0;
  .js and .ts files are kept with LF endings.
impact: behaviour
verification: >
  Live, Claude Code 2.1.284, interactive terminal sessions with Remote Control
  off (the session record's bridgeSessionId empty): the mod answered
  queue_compaction with transport "mod", the agent finished its answer, and
  the transcript gained a compact_boundary 10 s after the turn (preTokens
  55,333) and the line "conpact: compacted 55,333 to 3,964 tokens"; the
  legacy hook log has no line for that session. A second session that loaded
  the mod only from ~/.claude/settings.json's env block queued with a
  1,000-token minimum and compacted 55,583 -> 4,002. The marketplace route was
  checked in a throwaway config folder: `claude plugin marketplace add` on the
  checkout and `claude plugin install conpact@conpact` installed 1.2.0, enabled.
  `claude plugin validate --strict src/mod` passes on 2.1.284 and 2.1.287 and
  lists no process, network, file-write or prompt call. Mod suite (claude
  plugin test): 58 pass; red first, 34 of 44 failing before the modules
  existed. Mutation, tools/mutate_mod.py: 87.3% (344 of 394) on the first pass;
  after tests for the survivors 97.2% (382 of 393), the eleven left equivalent
  (docs/verification.md says why). Python anchor 7 pass; tools/mutate_mod.py's
  own tests 7 pass. Full suite, Windows: 2,393 passed, 5 skipped. Structure check 100.0.
  Not observed: a Desktop app Code tab session using the mod (none started
  since the env block was set), the busy-session retry live, and anything on
  2.1.287+, where mods report the rollout switch off here. Linux and macOS not
  run.
anchor: tests/regression/test_the_mod_compacts_in_process.py
files: >
  src/mod/ (new: .claude-plugin/plugin.json, hooks/hooks.json, hooks/register.js,
  hooks/tools.js, hooks/run.js, hooks/requests.js, hooks/files.js,
  hooks/rules.js, tests/world.ts, tests/rules.test.ts, tests/tools.test.ts,
  tests/run.test.ts, tests/requests.test.ts), .claude-plugin/marketplace.json
  (new), tools/mutate_mod.py (new), tests/test_mutate_mod.py (new),
  tests/regression/test_the_mod_compacts_in_process.py (new),
  src/conpact/__init__.py, .gitattributes, README.md, docs/claude-code-mod.md
  (new), docs/README.md, docs/setup.md, docs/how-it-works.md, docs/security.md,
  docs/architecture.md, docs/verification.md, CHANGES.md, DECISIONS.md
  (D-20261002-064, D-20261002-065), HANDOFF.md
```

```yaml
id: CU-20261002-082
type: fix
title: "A codex build that Codex has hollowed out is never run: the sidecar and conPACT's own tooling pass over a marker naming one"
description: >
  On 2026-10-02 ChatGPT Desktop could run no command at all. Every exec in a
  Codex thread failed with "failed to spawn code-mode host
  ...in\ca9abb0b4d8ac692\codex-code-mode-host.exe: The system cannot find
  the file specified", and Codex reported its command runner missing.
  The desktop starts the sidecar, and the sidecar ran the build its marker
  (real-codex.txt) named. That marker was written at install, and Codex had
  installed a newer build (c6fe824d725f02d7) on 2026-09-30 and pruned the old
  one - but the old codex.exe was held open by a running app-server, so the
  prune deleted its helpers and left the bare executable. The marker still
  named a file, which is all D-20260922-041 asked of it, so the desktop kept
  being handed a codex that cannot spawn the code-mode host or the command
  runner. The folder vanished on its own once the desktop was restarted and
  nothing held the executable any more.
  `codex_appserver.hollow` now calls a build hollow when the newest install
  holds a file beside its codex that the named build's folder lacks, and
  `codex_appserver.usable` - a file, and not hollow - is the test both the
  sidecar's `real_codex` and `codex_appserver`'s marker lookup apply to the
  marker before trusting it; a hollow one gives way to the newest install. An
  older build that is whole is still honoured, so a marker written on purpose
  remains a pin, and CONPACT_CODEX_REAL is still not second-guessed.
impact: behaviour
verification: >
  Diagnosed live: the running app-server's command line named the
  ca9abb0b4d8ac692 build, whose folder held codex.exe alone, and Codex's own
  log carried the spawn failure above. After a restart of the desktop the
  sidecar ran c6fe824d725f02d7's codex (codex-cli 0.159.2) and the app-server
  logged no error. Red first: the new regression file failed on its four
  hollow-build cases and passed its five pin cases before the change. Full
  suite, Windows: 2,375 passed, 5 skipped; the anchor then gained two cases
  for the mutants the first run left in the new code (11 pass). Mutation,
  codex_appserver: 88.5% (123 of 139), none surviving in the new functions.
  Structure check 100.0.
  Linux and macOS not run.
anchor: tests/regression/test_a_hollow_build_is_not_run.py
files: >
  src/conpact/codex_appserver.py, src/conpact/codex_sidecar.py,
  tests/regression/test_a_hollow_build_is_not_run.py (new), CHANGES.md,
  DECISIONS.md (D-20261002-063)
```

```yaml
id: CU-20261002-081
type: release
title: "conPACT 1.1.0: the package builds where it says it does, the contributor steps are complete, and the published tree names nothing from the maintainer's private setup"
description: >
  A release check on 2026-10-02 found the code ready (2,363 passed, 5
  skipped; structure check 100.0) and five things in the way. The user asked
  for all of them to be fixed and the result pushed.
  1. pyproject.toml asked for setuptools 68 or later, but `license = "MIT"`
     with `license-files` is read only from setuptools 77: 68.2.2 and 76.1.0
     refuse the file, 77.0.3 builds it. A plain `pip install` never showed it,
     because build isolation fetches the newest setuptools. The minimum is 77.
  2. The version still read 1.0.0, the number of the first publish
     (2026-09-23), although the Codex CLI support, the read-only doctor, the
     toast's click and keyboard fixes and the Codex caller module have shipped
     since. It is 1.1.0, and the release gets a tag.
  3. The README's test line was a week old (2,142 on Windows).
  4. Contributing said `pip install pytest jsonschema`; the mutation tester's
     own tests also need pytest-cov, so a fresh clone failed two tests (as it
     did on this machine when the project moved here on 2026-09-30).
  5. Outside the user-facing pages, which were already clean, the tree carried
     the maintainer's private workflow vocabulary: 37 scores in this log quoted
     under a private acronym, the old server instructions quoted word for word
     in two entries, a decision and two test docstrings, the acronyms in five
     more test docstrings, a source comment and .gitignore, the maintainer's
     name in three test docstrings, a private project name and session id in
     two entries, and the maintainer's machine name in test data. Each is
     reworded to say what the step was, with numbers and meaning unchanged.
     The working notes (HANDOFF.md, also brought up to date) and the commit
     manifest (logs/) stay tracked and are left out of the published tree
     (D-20261002-062). tests/private_words.py keeps the vocabulary as digests,
     so the test that keeps it out does not carry it, and the docs test uses
     the same list.
impact: low
verification: >
  Red first: the new tree test failed on the one file not yet converted (the
  docs test, which spelled the words out) and on nothing else; with the old
  wording of a structure-check score appended to docs/setup.md it failed
  naming that file.
  setuptools 76.1.0 refuses pyproject.toml and 77.0.3 builds
  conpact-1.1.0-py3-none-any.whl, as does an isolated build with the newest.
  Full suite, Windows: 2,366 passed, 5 skipped, in 6 min 55 s. Structure
  check 100.0. Linux and macOS not run.
files: >
  pyproject.toml, src/conpact/__init__.py, README.md, docs/verification.md,
  CHANGES.md, DECISIONS.md (D-20260923-047 amended, D-20261002-062), HANDOFF.md,
  .gitignore, src/conpact/watching.py, tests/private_words.py (new),
  tests/regression/test_the_published_tree_is_clean.py (new),
  tests/regression/test_the_docs_stand_on_their_own.py, and the docstrings or
  data of nine other test files
```

```yaml
id: CU-20260926-080
type: fix
title: "The settings window's on-screen test runs on a desktop of its own, where nothing the user types can reach it"
description: >
  test_the_real_window_shows_saves_and_closes failed now and then in full runs
  and never alone (CU-20260922-056, CU-20260923-058): its script typed "150k"
  into the real window, saved and closed, and the child printed "saved 100000",
  the default. The user asked for the real cause, probed rather than guessed.
  The script was instrumented - every save, close, key and button event, focus
  change and file write, timestamped, with the foreground window at each step -
  and run 30 times with all eight cores spinning: 30 passed. The save timer
  always fired before the close (100-113 ms and 300-341 ms after scheduling)
  and the write took about 7 ms, so neither load, nor timer order, nor the write
  was it, and nothing on the machine sends the window messages. What the logs
  did show: the window takes the foreground from whatever the user is working
  in - their browser, in one full run - and holds it for about 1.2 s, first on
  the window itself (where Return saves and Escape closes) and then in the first
  field, then min_context_fill. On Windows Tk's `wm deiconify` alone takes it,
  before `focus_force` runs. One keystroke posted to the window's own HWND,
  through Tk's real Windows message path, reproduced the failure exactly: a "7"
  made "50" read "507", which the save refused ("Must be from 1 to 100
  percent."), and Escape closed the window before the save ran. Both ended
  "saved 100000" with exit 0. A full run takes six minutes or more, ample time
  for the user to be typing elsewhere; a few seconds alone is not.
  CU-20260924-062 later found a second cause of this test's intermittent
  failures, a time limit that counted Python's start-up; this is the first.
  The fix is to the test, not the window. The real window takes the keyboard
  because the user opened it to type, and that stays (it is proved off screen by
  test_show_raises_the_window_and_puts_the_cursor_in_the_first_field). The
  script now gives itself a Windows desktop of its own before Tk starts
  (CreateDesktop and SetThreadDesktop, on the thread that then runs the
  window). Windows sends user input only to the desktop the user is on, so the
  window is still created, mapped, focused and driven for real while nobody can
  reach it - and the user no longer loses their keyboard to a test run. The
  test asserts that the script really is on that desktop. Its focus check also
  checked nothing: it compared the focus with min_context_tokens, which show()
  never focuses, so it printed False every time and no assertion read it. It
  now names the focused field and asserts it is the first one, as show()
  intends. On Linux and macOS the script runs on the display as before; the
  Linux runs have no Tk, so no Tk test runs there.
  Written on 2026-09-23 in a parallel session as CU-20260923-059, with
  D-20260923-049, and merged three days later under new ids, since main had
  given both to the settings window's tabs. By then the window had tabs and
  the test ran its child through tests/window_process.py, so the desktop is
  made in the child's start-up code, before the window's clock and before any
  Tk root, and the first field it asserts is the first tab's, lead_seconds.
impact: none
verification: >
  On the parallel branch, before: the unchanged script took the user's
  foreground in every run made while the desktop was unlocked, and the posted
  "7" and Escape each gave "saved 100000". After: the test's own script passed
  40 of 40 with all eight cores spinning, every assertion checked each time. A
  watcher polling the user's foreground every 5 ms saw only the user's own app
  throughout a run on the separate desktop, and the settings window take over
  in a run of the old script.
  Ported onto main: the child prints "desktop conpact-test-<pid>", "mapped 1
  focus lead_seconds" and "saved 150000" on its own desktop; the same script
  without the desktop prints the last two on the user's. The test then
  passed 10 of 10, run one at a time on a loaded machine (5.5 to 43 s each).
  Full suite, Windows: 2,363 passed, 5 skipped, in 23 minutes. No
  regression test: the window's behaviour is unchanged, and the test itself
  now asserts the part that fixes it, that its script runs on a desktop of its
  own. Structure check 100.0.
files: >
  tests/test_settings_window.py, DECISIONS.md (D-20260926-061),
  docs/verification.md
```

```yaml
id: CU-20260925-079
type: fix
title: "A thread whose rollout is not there is passed over, and a recent rollout that cannot be read refuses rather than dropping a possible caller"
description: >
  When the sidecar names nobody, and always for the CLI, the Codex caller is
  bound from Codex's own rollouts, exactly one or none (D-20260922-043,
  D-20260924-057). recent_threads read every listed thread's rollout inside
  one guard, so a single thread whose rollout file was missing emptied the
  whole scan and the tool refused a caller that could be told exactly.
  Measured with rows [a thread whose file is gone, a thread with a fresh
  running rollout]: the scan found nothing; without the first row it found the
  second. A missing rollout records no turn, as an empty one does, which the
  fallback already treats as not running, so it can never be a candidate.
  Looking at that found the opposite fault beside it: a recent rollout that is
  there but cannot be opened was read as one with no turn marker, because
  codex_meter.turn_state and context_meter.entries_from_end swallow the open
  error, so a thread that might be the caller dropped out and the other one
  was bound. Skipping every row that cannot be read, the obvious fix for the
  first fault, is the second fault: it can turn two candidates into one.
  Fixed, and recorded as D-20260925-060. Each row's rollout is now looked at
  on its own: its age first, so a rollout too old to be in flight is passed
  over whether or not it can be read; then it is opened once before the
  readers run. No such file, or a path through a file, passes that row over,
  including a file that goes between the two looks. Any other failure to open
  it, or any failure of turn_state or rollout_is_calling_conpact on it,
  reaches the outer guard, so the whole scan answers nothing and the tool
  refuses, as it still does for a store that cannot be read. The readers still
  take a file they cannot open for one with no marker; the look just before
  them is what tells the two apart.
impact: behaviour
verification: >
  Anchor tests/regression/test_a_missing_rollout_hides_no_caller.py, through
  mcp_tools._bind_session for ChatGPT Desktop's app-server and for the CLI,
  written first and run in a fresh process against the code before the fix: 8
  failed, 2 passed (the two old unreadable rollouts, passed over already
  because the age came first); after it, 10 passed. Unit cases in
  tests/test_codex_caller.py, 7 items: a rollout that is not there (no such
  file, a path through a file), one that goes between its age and its reading,
  a recent one that cannot be opened (a folder stands in), an old one that
  cannot be opened, and a reader failing on one rollout (turn_state,
  rollout_is_calling_conpact). Mutation (tools/mutate.py, -m "not real_ui"),
  the whole of codex_caller.py, run from a scratch directory against a clean
  detached worktree. Before, at CU-20260925-078: 117 mutants - 112 killed, 5
  survived, all equivalent: 95.7%. After: 118 mutants, the one more being the
  mode the new open reads with - 103 killed, 3 survived, 12 timed out, in
  12,706 s on a loaded machine, where each timeout took 467 to 556 s. The 12,
  and the "cli" survivor, whose recheck had also timed out, were then run in
  one pytest process against the module's own tests, the two binding
  regressions and tests/test_mcp_tools.py, each mutant executed into the
  loaded module and the original put back, with the unmutated source passing
  first: all 13 failed a test. Ten of those are real kills. The three surface
  labels ("cli", "desktop", "unknown") failed only because the surface tests'
  parameters were collected from the unmutated constants before the mutant
  went in. Run in fresh processes against a copy with the mutant written into
  the file, "desktop" and "unknown" pass all 11 of those tests, so they
  survive, while Eq->NotEq on line 101 fails the same 5 tests it failed in the
  single process. After: 113 killed, 5 survived, the same five equivalents as
  before: 95.8%. Structure check 100.0 / 100; testability 115.8 (59 of 65 modules
  with a matching test file, 47 regression tests). Windows: full suite, with
  CU-20260924-065 below it, in one run on a loaded machine (1 h 45 min, about
  five times its usual length): 2,359 passed, 5 skipped, 4 failed, each a
  child process running out of time (two on-screen toasts still starting Tk at
  30 s, the Stop hook's watcher and its .cmd at 60 s). None of the four
  imports the MCP server, the only way to recent_threads, and run again alone
  on the same tree they passed (4 passed in 86 s): 2,363 in all, main's 2,341
  with the 17 new items here and the 5 of CU-20260924-065.
anchor: tests/regression/test_a_missing_rollout_hides_no_caller.py
files: >
  src/conpact/codex_caller.py, tests/test_codex_caller.py,
  tests/regression/test_a_missing_rollout_hides_no_caller.py (new),
  DECISIONS.md, docs/chatgpt-desktop.md, docs/security.md,
  docs/verification.md, CHANGES.md
```

```yaml
id: CU-20260925-078
type: test
title: "codex_caller has tests of its own: its mutation score goes from 53.8% to 95.7%, and the five mutants left are equivalent"
description: >
  The Codex caller binding, moved into codex_caller by CU-20260925-077, was
  tested only through mcp_tools and the binding regression file, and was under
  the 60% mutation standard, as it had been inside mcp_tools.
  tests/test_codex_caller.py calls each function directly, with a stand-in
  context, a recording runner in place of PowerShell or ps, a scripted clock
  and hand-written rollouts. It pins the exact command process_command asks
  to run on each platform and what it makes of the answer (an empty answer, a
  failed lookup, and a pid that is not a number, which never reaches the
  script); the surface each parent names, including conPACT's own recorded
  app-server against another; every binding and refusal of bind_desktop and
  bind_cli_rollout, word for word; the CLI's settle window (it waits for a
  call marker, polls at its interval and stops when the window closes); which
  thread rows the rollout scan passes over; and the 200-record bound on the
  tool-call marker scan. The stand-ins record what they were asked and the
  tests assert afterwards, never inside them (D-20260920-018). Two source
  changes, neither of them a change in behaviour. process_command takes the
  runner that starts PowerShell or ps, runner=subprocess.run, in the style
  D-20260920-023 sets out; nothing else it does changed. bind_desktop's
  running-turn fallback sat under `elif "will not guess" not in str(why)`,
  which could never be false: it repeats the condition that must already
  hold to reach it, and `why` is not reassigned in between. Its string
  mutant therefore survived every test of the module (209, run by hand) and
  was equivalent; the branch is now a plain elif chain.
  test_context_from_runtime_uses_the_parent_process no longer starts a real
  PowerShell, whose 5-second limit under load decided what the coverage map
  saw: it stands in process_command, keeps its two assertions and adds that
  the parent's pid is asked for and the answer kept. The stdio end-to-end
  test (tests/regression/test_mcp_queue.py) still starts the real server,
  whose start-up still makes the real lookup; its verdict does not depend on
  it, since that server is a Claude one. Found and not changed, because it
  would change behaviour: when the store lists a thread whose rollout file is
  missing, recent_threads returns nothing for every thread, not just that
  one, so the fallback refuses (it fails closed, but its docstring says an
  unreadable row is ignored).
impact: none
verification: >
  Mutation (tools/mutate.py, -m "not real_ui"), the whole of codex_caller.py.
  Before, at CU-20260925-077: 119 mutants - 64 killed, 27 survived, 23
  uncovered and 5 timeouts, which were settled by hand as survived: 53.8%.
  After: 117 mutants (the two on the removed condition are gone) - 112
  killed, 5 survived, 0 uncovered, 0 timeouts: 95.7%. Every survivor and
  uncovered mutant in process_command (20), bind_cli_rollout (18),
  rollout_is_calling_conpact (3), recent_running_threads (2), recent_threads
  (2) and MAX_CALL_MARKER_RECORDS is killed; so are two of surface's three
  survivors and one of bind_desktop's two. The five that survive are
  equivalent. Four rename the surface labels (cli, desktop, conpact_host,
  unknown), which never leave the process: mcp_tools compares a bound
  surface only with the same constant, and nothing writes one down or shows
  it. The fifth changes surface's "" default for a missing parent command to
  "XXXX", which says "codex" no more than "" does. With _bind_codex's eight
  mutants, which were not re-run because mcp_tools was not touched (6 killed,
  2 survived), the scope measured before goes from 70 of 127 (55.1%) to 118
  of 125 (94.4%). A run between these found one test fault: once its script
  ran out, the stand-in clock answered "infinitely late" and the stand-in
  scan "nothing found", so the mutant that turns the settle loop's < into >=
  waited forever and timed out instead of failing. The scan now answers an
  unexpected caller once its script runs out, which ends any wait, and that
  mutant fails six tests in under a minute. No test in the new file starts a
  process: run with process creation refused after start-up, 69 passed and
  none was started. Structure check 100.0 / 100 before and after; testability
  114.2 -> 115.8 (58 -> 59 of 65 modules with a matching test file). Tests
  the change touches (the new file, the binding regression, MCP tools and
  server, the stdio queue, test hygiene): 211 passed. Windows: full suite
  2341 passed, 5 skipped, as on main with the 68 new tests added.
anchor: none (no behaviour changed; tests/regression/test_codex_mcp_binds_the_asking_thread.py holds the binding)
files: >
  src/conpact/codex_caller.py, tests/test_codex_caller.py,
  tests/test_mcp_tools.py, docs/verification.md, CHANGES.md
```

```yaml
id: CU-20260925-077
type: refactor
title: "The Codex caller binding has a module of its own: codex_caller, moved out of mcp_tools unchanged"
description: >
  CU-20260924-075 brought in Lance Sandino's Codex CLI contribution, which put
  the Codex caller binding inside mcp_tools and left that module at 607 lines,
  the only one over the 400 the module-size check counts. The binding now has
  a module of its own, conpact.codex_caller, with the standard header:
  process_command (was _process_command), surface (was _codex_host, renamed so
  it does not shadow the codex_host module it imports), bind_cli_rollout,
  recent_threads, recent_running_threads and rollout_is_calling_conpact (the
  same names without mcp_tools' leading underscore and redundant "codex"), the
  CODEX_CLI, CODEX_DESKTOP, CODEX_HOST and CODEX_UNKNOWN constants and the
  three settle and scan limits, and bind_desktop, which is the sidecar-first,
  rollout-second fallback that sat inside _bind_codex. Every body was moved
  from mcp_tools' own lines, unchanged but for the names. mcp_tools keeps its
  tool handlers, its Context and a _bind_codex that asks codex_caller for the
  surface and the binding, raising the same refusal and returning the same
  record on both paths; its header and docs/architecture.md name the new
  dependency. No behaviour changes. The binding regression file patches and
  reads the moved names on codex_caller instead of mcp_tools (seven places);
  no assertion changed. mcp_tools.py is 442 lines and codex_caller.py 199.
impact: none
verification: >
  Structure check 100.0 / 100 before and after; module size 98.4 -> 100.0 (1 of 64
  files over 400 lines -> 0 of 65), fan-out 96.9 -> 98.5, testability 115.6 ->
  114.2 (codex_caller has no test file of its own: its tests are the binding
  regression file's). Mutation (tools/mutate.py, -m "not real_ui"), the moved
  code before and after, each run with every other mcp_tools mutant recorded
  as done so only the moving lines ran: before, in mcp_tools, 133 mutants - 72
  killed, 33 survived, 28 uncovered (54.1%); after, codex_caller and the new
  _bind_codex, 127 - 70 killed, 29 survived, 23 uncovered and 5 timed out. The
  five were codex_caller's import-time constants, which the tool retries only
  against a module's own test file, and codex_caller has none; run by hand
  against the binding regression file and tests/test_mcp_tools.py they
  survived, as they had before, so 70 killed, 34 survived, 23 uncovered
  (55.1%). Matched mutant by mutant, the six functions moved unchanged have
  identical verdicts; _bind_codex's 31 mutants became 25 across it and
  bind_desktop, one refusal path instead of two (23 killed before, 21 after);
  four of process_command's went from uncovered to survived only because its
  one test starts PowerShell with a 5-second limit, which had run out under
  load in the before map. Both figures are under the 60% standard, as the
  contribution was; that is left to a task of its own. Tests the change
  touches (binding regression, MCP tools and server, idle hold, Codex CLI and
  its hook, doctor): 151 passed. Windows: full suite 2273 passed, 5 skipped
  (four need fcntl, and the desktop's on-screen test stood itself down for the
  foreground lock): one more than main, because the check that no module
  imports a platform-only module at module scope runs once per module and now
  runs on codex_caller.py too, and passes.
anchor: none (a refactor; tests/regression/test_codex_mcp_binds_the_asking_thread.py holds the binding)
files: >
  src/conpact/codex_caller.py (new), src/conpact/mcp_tools.py,
  tests/regression/test_codex_mcp_binds_the_asking_thread.py,
  docs/architecture.md, docs/verification.md, CHANGES.md
```

```yaml
id: CU-20260924-076
type: fix
title: "A click on the toast is never dropped: its frame answers a click with MA_NOACTIVATE, so the activation refusal of CU-20260924-064 never meets one"
description: >
  Reported by the user the same day: the toast's close button was rather
  unresponsive - nothing happened, and a later click closed it. Measured
  before changing anything, on a labelled test toast shown through the real
  present() under a throwaway home, with the user clicking its close button
  and every step logged from inside the toast's thread: 29 clicks in a row
  reached the thread (WM_LBUTTONDOWN retrieved), each was followed by
  WM_MOUSEACTIVATE answered MA_ACTIVATE and an activation request, marked as
  caused by the mouse, which CU-20260924-064's refusal turned down - and no
  press reached Tk. The 30th, after a pause of nine seconds, got through.
  Cause: a click on a window that is not active first asks it whether to
  activate it. Tk passes the question to Windows' default handler (tkWinWm.c,
  WM_MOUSEACTIVATE, when no grab excludes the window), which answers
  MA_ACTIVATE even for a no-activate tool window, as measured; Windows then
  asks to activate the toast, NoActivation refuses, and Windows drops the
  click. Before CU-20260924-064 the first toast of a process was its thread's
  active window, so its clicks never asked; that change made the toast never
  active, so every click asked. Fixed: show_without_focus() puts a window
  procedure in front of Tk's on the toast's frame
  (desktop.answer_clicks_without_activating) that answers WM_MOUSEACTIVATE
  with MA_NOACTIVATE - take the click, never ask for activation - and hands
  every other message to Tk's own procedure. The toast's children pass the
  question to the frame, so every button is covered, and it is in place before
  the window is shown. The refusal stays: it now never meets a click. The
  procedure is kept for the life of the process, since Windows may call it for
  as long as the window exists.
impact: behaviour
verification: >
  Live, on the same kind of test toast with the fix, the user clicking once:
  MA_NOACTIVATE from the frame and every child, no activation asked of the
  refusal, Tk's press 1 ms after the button went down, and the toast closed
  177 ms after the click, the keyboard never leaving the user's app. New
  anchor tests/regression/test_a_click_on_the_toast_is_never_dropped.py,
  observed failing first: with desktop.py's fix stashed, a real toast shown by
  present() in a fresh process answered MA_ACTIVATE (1) for its close button
  and all three buttons; with the fix, MA_NOACTIVATE (3) for each. Six new
  tests in tests/test_desktop.py: the answer is MA_NOACTIVATE and never Tk's,
  every other message goes on to the procedure it replaced, the procedure is
  kept alive, the real window api is a private typed copy, and on a real Tk
  window off every screen the question is answered MA_NOACTIVATE while Tk
  still hears its frame move; show_without_focus is asserted to install the
  answer before it shows the window. Windows: full suite 2272 passed, 5
  skipped (four need fcntl, and the desktop's on-screen test stood itself down
  while another app held the foreground lock). Mutation, applied by hand in a
  copy, because a tools/mutate.py run of desktop.py could not finish while
  other programs held the machine at 100%: nine mutants of the new code - the
  comparison negated, the answer dropped, the delegation's value dropped, the
  procedure not kept, the procedure not installed, show_without_focus skipping
  it, MA_NOACTIVATE and GWLP_WNDPROC changed, and the 64-bit getter's name
  changed - were all killed by the desktop tests and the anchor. Structure check
  100.0 / 100.
anchor: tests/regression/test_a_click_on_the_toast_is_never_dropped.py
files: >
  src/conpact/desktop.py, tests/test_desktop.py,
  tests/regression/test_a_click_on_the_toast_is_never_dropped.py (new),
  docs/verification.md, DECISIONS.md, HANDOFF.md, CHANGES.md
```

```yaml
id: CU-20260924-075
type: chore
title: "The public repository's two pull requests are brought into this history: Codex CLI support, macOS fixes and a doctor, renumbered into this log"
description: >
  The public repository (st0nebridge/conPACT) had moved on from its 1.0.0
  release: Lance Sandino's pull requests #1 and #2, merged there on 2026-09-23
  and 24, added six commits - the suite passing on a real Mac, Codex thread
  identity published atomically, the sidecar's status naming its Codex build,
  a resumed Codex task identifying itself when the sidecar missed its turn,
  Codex CLI calls binding to the CLI task, and full Codex CLI compaction
  through `conpact-codex` and a Codex Stop hook, with a read-only doctor. The
  public release has no history in common with this one, but its tree is
  exactly this history's 96733fc, so the contribution was applied as a
  three-way patch of bb08e1b..4235c45 onto main. Reviewed before applying, as
  code the Stop hook and MCP server would run: nothing new is sent anywhere;
  the Codex Stop hook is installed only by an explicit `conpact-codex
  --install`, merged into the user's hooks without replacing any, and acts
  only below the app-server conPACT recorded; the capability token is passed
  by variable name; the doctor reads only. Brought into this history's
  conventions: the six entries, numbered CU-20260923-061 to 066 there, are
  CU-20260924-069 to 074 here (061 and the 062-to-066 sequence were taken),
  each saying where it came from; its two decisions, D-20260923-051 and 052
  there, are D-20260924-057 and 058, and D-20260921-031 is marked as
  superseded where 058 says it is; the four anchors that sat in ordinary test
  files are moved, unchanged, under tests/regression/, and the test file left
  empty by one move is removed; the three new modules carry the standard
  module header, and mcp_tools' header names its new imports. One conflict was
  decided: both sides had rewritten the settings window's two position tests
  to stop reading back where a window landed. This history's versions are
  kept, because they assert the same placement and also that the window is
  never shown, which this history's window guard (D-20260924-053) would fail
  the contribution's versions for. The verification page keeps this machine's
  Windows and Linux figures and gains the contribution's macOS row, dated.
  Left as found: mcp_tools.py is 607 lines, over the 400 the module-size check
  counts, since the Codex caller binding was added to it.
impact: none
verification: >
  The contribution's anchors, run against this history's main before it: the
  Codex CLI Stop hook's fails (its module does not exist), the sidecar status
  anchor fails (no build named), the atomic-publication anchor fails (the
  record is written in place, never replaced), and the binding regression file
  fails at collection (no CLI or Desktop surface to tell apart). The POSIX
  lock-probe anchor skips on Windows, as it needs fcntl; the contributor saw
  it on a Mac. After the integration, the Codex, MCP, CLI, doctor, token-store
  and settings-window tests with those anchors and the docs test: 934 passed,
  4 skipped. Full suite on Windows: 2264 passed, 5 skipped - four need fcntl,
  which Windows lacks (the three Unix lock tests and the moved lock-probe
  anchor), and the desktop's on-screen test stood itself down because the
  foreground lock was on. Structure check 100.0 / 100.
anchor: none (the six contributed entries carry their own anchors)
files: >
  CHANGES.md, DECISIONS.md, docs/verification.md, src/conpact/codex_cli.py,
  src/conpact/codex_cli_hook.py, src/conpact/doctor.py,
  src/conpact/mcp_tools.py,
  tests/regression/test_codex_cli_stop_runs_the_session_codex_names.py (new),
  tests/regression/test_sidecar_status_names_its_codex.py (new),
  tests/regression/test_codex_identity_is_published_whole.py (new),
  tests/regression/test_the_posix_lock_probe_releases_flock_first.py (new),
  tests/test_codex_cli_hook.py, tests/test_codex_active.py,
  tests/test_codex_threads.py, tests/test_codex_sidecar_tool.py (removed), and
  the contribution's own files
```

```yaml
id: CU-20260924-074
type: feature
title: "Queued compaction works in Codex CLI through a reachable owning app-server"
description: >
  Contributed by Lance Sandino in pull request #2 of the public repository,
  where this entry was CU-20260923-066; brought into this history on
  2026-09-24. Added `conpact-codex`, an opt-in launcher that connects Codex's
  interactive terminal UI to conPACT's existing token-protected loopback
  app-server. A narrowly merged Codex Stop hook receives the exact session id
  and either executes that session's queued compaction on the same lock-owning
  server or arms its idle watch. Plain `codex` is unchanged and continues to
  refuse queue and hold. Existing hooks are preserved, the original file is
  backed up once, and Codex's hook trust review is not bypassed. Codex queued
  compactions now also enforce their requested or configured minimum context
  size.
impact: behaviour
verification: >
  A live Codex 0.155.1 TUI connected through the capability-token endpoint and
  returned CONPACT_CLI_REMOTE_READY. A wrapped live CLI task then queued its
  own compaction at 22,212 measured tokens; the Stop hook ran it, Codex showed
  `Context compacted · 3s`, the rollout recorded `type: compacted`, and the
  conPACT audit log recorded `codex_compacted` via `Codex Stop hook`. The
  focused launcher, hook, MCP binding, app-server routing and arming suite
  passes 66 tests. The full Intel-macOS suite passes 2,178 tests with 17
  platform skips.
anchor: tests/regression/test_codex_cli_stop_runs_the_session_codex_names.py
files: >
  src/conpact/codex_cli.py, src/conpact/codex_cli_hook.py,
  src/conpact/codex_compact.py, src/conpact/codex_arming.py,
  src/conpact/mcp_tools.py, src/conpact/doctor.py, tools/codex_cli.py,
  pyproject.toml, tests/test_codex_cli.py, tests/test_codex_cli_hook.py,
  tests/test_codex_compact.py, tests/test_codex_arming.py,
  tests/regression/test_codex_mcp_binds_the_asking_thread.py, README.md,
  docs/setup.md, docs/commands.md, docs/chatgpt-desktop.md,
  docs/architecture.md, docs/security.md, docs/verification.md, DECISIONS.md
```

```yaml
id: CU-20260924-073
type: fix
title: "Codex CLI calls bind to the CLI task, never an active Desktop task"
description: >
  Contributed by Lance Sandino in pull request #2 of the public repository,
  where this entry was CU-20260923-065; brought into this history on
  2026-09-24. Codex CLI and ChatGPT Desktop share the MCP configuration but
  not the Desktop sidecar. With several Desktop turns active, a CLI
  compaction_status call first refused; an initial rollout fallback then
  exposed the more serious case by binding to the active Desktop task. The MCP
  server now records its direct parent's command at startup, treats `codex ...
  app-server` as Desktop and `codex`/`codex exec` as CLI, and binds a CLI call
  only from its own recent rollout. Queue and idle-hold refuse in CLI rather
  than recording work that no sidecar can execute. A read-only doctor command
  now separates Codex's own login from the optional Claude Code Keychain
  login.
impact: behaviour
verification: >
  A live Codex CLI compaction_status call while ChatGPT Desktop was active
  bound to its own exact task, 01a00000-0000-7000-8000-0000000000a1, and
  measured 20,787 tokens. The macOS suite passes 2,162 tests with 17 platform
  skips: 1,989 non-GUI and 173 Tk/UI tests. `python tools/doctor.py` reports
  the ChatGPT login, MCP registration, running sidecar, newest bundled Codex
  build and readable state; the absent Claude login is informational.
anchor: tests/regression/test_codex_mcp_binds_the_asking_thread.py::TestTheRolloutIsTheFallbackWhenTheSidecarMissesATurn::test_cli_ignores_unrelated_desktop_ambiguity
files: >
  src/conpact/mcp_tools.py, src/conpact/doctor.py, tools/doctor.py,
  tests/regression/test_codex_mcp_binds_the_asking_thread.py,
  tests/test_doctor.py, README.md, docs/setup.md, docs/chatgpt-desktop.md,
  docs/security.md, docs/verification.md, docs/architecture.md, DECISIONS.md,
  docs/commands.md
```

```yaml
id: CU-20260924-072
type: fix
title: "A resumed Codex task can identify itself when its turn notification is absent"
description: >
  Contributed by Lance Sandino in pull request #2 of the public repository,
  where this entry was CU-20260923-064; brought into this history on
  2026-09-24. A live, older Codex task discovered and called
  compaction_status, but the desktop did not forward that task's turn/started
  notification through the sidecar stream. The sidecar therefore published an
  empty in-flight set even though Codex's own rollout had already recorded
  task_started, and the MCP server refused the caller. The sidecar remains the
  primary identity source. When it has no caller, the MCP server now consults
  Codex's own rollout turn markers. Exactly one newly recorded conPACT
  invocation identifies its task among other running tasks; otherwise exactly
  one recent, non-archived running user task is required. A stale marker, two
  callers, or sidecar ambiguity still refuses rather than guessing.
impact: behaviour
verification: >
  The live failure is recorded in task 01a00000-0000-7000-8000-0000000000a2:
  task_started preceded the conpact MCP call by 12 seconds, while the tool
  received "no turn is in flight". Seven new regressions prove the single
  recent fallback, concurrent caller recognition, multiple-caller refusal,
  completed-call rejection, stale-marker refusal, and that sidecar ambiguity
  can never be overridden. The full macOS suite passes 2,151 tests with 17
  platform skips.
anchor: tests/regression/test_codex_mcp_binds_the_asking_thread.py::TestTheRolloutIsTheFallbackWhenTheSidecarMissesATurn
files: >
  src/conpact/mcp_tools.py,
  tests/regression/test_codex_mcp_binds_the_asking_thread.py,
  docs/chatgpt-desktop.md, docs/security.md, docs/verification.md, CHANGES.md
```

```yaml
id: CU-20260924-071
type: improvement
title: "Sidecar status shows which Codex build it will run"
description: >
  Contributed by Lance Sandino in pull request #2 of the public repository,
  where this entry was CU-20260923-063; brought into this history on
  2026-09-24. The sidecar status model already calculated the pinned Codex
  executable, the newest installed executable and whether they matched, and
  the documentation promised those values. The text-mode status command
  omitted them. It now prints all three so a stale desktop build is visible
  during setup checks.
impact: behaviour
verification: >
  A command-line regression supplies distinct pinned and newest builds and
  proves that status prints both paths and says the pin is not newest.
anchor: tests/regression/test_sidecar_status_names_its_codex.py
files: >
  tools/codex_sidecar.py, tests/regression/test_sidecar_status_names_its_codex.py, CHANGES.md
```

```yaml
id: CU-20260924-070
type: fix
title: "Codex thread identity is published atomically"
description: >
  Contributed by Lance Sandino in pull request #2 of the public repository,
  where this entry was CU-20260923-062; brought into this history on
  2026-09-24. A live queue, status and cancel cycle from ChatGPT Desktop
  worked, but an immediate fourth MCP call briefly reported that the sidecar
  had not seen a turn. The sidecar rewrote codex-active.json in place while
  independent MCP processes read it, leaving a small window in which a reader
  could see an empty or partial JSON document. Publishing now writes a
  complete temporary file beside the record and atomically replaces the old
  record.
impact: behaviour
verification: >
  The regression pauses at the replacement boundary and proves a concurrent
  reader still sees the complete old record, then sees the complete new one. A
  live ChatGPT Desktop MCP call identified this task as
  01a00000-0000-7000-8000-0000000000a3; queue, status read-back and cancel all
  succeeded against that exact task. The full Mac suite passes 2,144 tests
  with 17 platform skips after this fix and the status-display improvement.
anchor: tests/regression/test_codex_identity_is_published_whole.py
files: >
  src/conpact/codex_active.py, tests/test_codex_active.py, CHANGES.md
```

```yaml
id: CU-20260924-069
type: fix
title: "The full suite passes on a real Mac"
description: >
  Contributed by Lance Sandino in pull request #1 of the public repository,
  where this entry was CU-20260923-061; brought into this history on
  2026-09-24. The repository said macOS was supported but had never been run
  on a real Mac. The first run on an Intel Mac found three portability gaps.
  The POSIX lock probe took flock and lockf on the same descriptor at once;
  macOS makes those two locks conflict, so an unlocked Codex thread was
  reported as held. The probes now release each lock before trying the other.
  Codex executable lookup fell through from an explicit, empty LOCALAPPDATA
  into the Mac's /Applications folder and used the host process's PATH instead
  of the supplied environment; isolated lookups now remain isolated. Finally,
  credential and window-position tests assumed Linux/Windows behavior: they
  reached the Mac Keychain instead of their throwaway credentials, and
  expected the macOS window manager to honor deliberately off-screen
  coordinates. The tests now select their intended credential source and
  assert the requested Tk geometry rather than a platform window manager's
  clamped result.
impact: behaviour
verification: >
  On an Intel Mac, Python 3.13.15 with Tk 9.0: the focused portability set
  passed 381 tests with 4 platform skips; the full suite passed 2,142 tests
  with 17 platform skips. New anchors prove an empty explicit LOCALAPPDATA
  never scans a host app bundle, a supplied PATH is respected, and flock is
  released before lockf. The live setup also found ChatGPT's bundled codex at
  /Applications/ChatGPT.app/Contents/Resources/codex, installed the generated
  sidecar shim and registered the conpact MCP server.
anchor: tests/regression/test_the_posix_lock_probe_releases_flock_first.py
files: >
  src/conpact/codex_appserver.py, src/conpact/codex_threads.py,
  tests/test_cli.py, tests/test_token_store.py, tests/test_codex_appserver.py,
  tests/test_codex_sidecar.py, tests/test_codex_sidecar_install.py,
  tests/test_codex_threads.py, tests/test_settings_window.py, README.md,
  docs/setup.md, docs/verification.md, CHANGES.md
```

```yaml
id: CU-20260924-068
type: fix
title: "The Stop-wrapper test times the hook from the moment it starts its watcher, not from cmd.exe's launch: start-up no longer fails it, and a hook that waits still does"
description: >
  tests/regression/test_stop_wrapper.py::test_a_large_session_gets_a_detached_watcher_that_outlives_the_hook
  runs the real tools/stop_compact.cmd through cmd.exe and checked that it
  returned within 15 seconds of being launched, to show that the hook does not
  wait for the watcher it starts. On 2026-09-24, on a machine at 100% CPU, it
  failed in 16 of 24 copies of the suite ("assert 23.125 < 15"). Measured before
  changing anything. The load was 24 copies of the suite (on-screen tests
  deselected) from a snapshot of main, tagged so that only they could be ended
  afterwards, 24 CPU burners (48 for the last rounds), and other sessions'
  work, with all 8 hardware
  threads at 100%. The wrapper was replayed 98 times under it. 78 replays were
  the real wrapper, timed as the test times it, with the hook's own `armed_at`
  read from the watch; `armed_at` is written just before the hook starts the
  watcher. 20 were a copy whose python line ran a shim that timed every phase,
  with the Python process's exit read from its own handle.
  Timed from the launch, a turn end took 3.6 to 44.1 seconds (median 14.8) and
  was over 15 in 47 of 98. Before the hook had started its watcher, cmd.exe and Python's
  start-up took 1.9 to 19.0 seconds, the imports 0.6 to 21.2, and the real
  wrapper up to 36.0 in all. From `armed_at` to the wrapper's return took 0.9 to
  21.2 seconds, median 3.8. It was over 15 once in 98, 21.2 seconds in a real run
  not instrumented to say where. In the instrumented runs that span was
  starting the watcher (up to 1.0 s), Python's own exit (up to 2.7) and
  cmd.exe's (up to 1.9); the hook's own code after the spawn took under 0.4,
  except once, when 9.1 seconds passed between the spawn and the next call, a
  stall of the whole process. Of the before rounds of the test file under the
  load, 8 of 18 failed: the first 3, while extra replays ran beside them, and
  all 5 run once 24 more burners had been added; the other 10 passed.
  Fixed, in the test. It times the hook from `armed_at` to the moment the
  wrapper has returned, and keeps the 15 seconds (RETURNS_WITHIN). The rest is
  unchanged: exit 0 and silent, the armed log line, the watcher still running
  after the hook returned, and standing down when its watch is cancelled.
  Unbounded waits were caught already and still are: a hook that waited for
  the watcher to end, or a watcher left holding the hook's output, would keep
  subprocess.run from returning until its 60-second limit, because the watcher
  waits most of an hour and is only cancelled once the hook has returned.
  Considered and not done: a larger limit, to cover the one 21-second run. It
  would stop catching a hook that waits a few seconds on its watcher, and that
  run's time was the hook's own, which the limit is there to bound.
impact: none
verification: >
  Red first: the new anchor, run against main's test in a copy of the tree
  under the load, failed its slow-start-up test ("assert 38.67 < 15"). There,
  the wrapper spends 16 seconds pinging before it starts Python. Its guard
  errored, because RETURNS_WITHIN is new. Green under the load: the anchor and
  the wrapper tests, 8 passed. The guard runs the real test with a hook that
  sleeps 16 seconds after starting its watcher, and the test fails on its limit.
  After the fix, 10 rounds of the test file under the same load, interleaved
  with the second set of rounds before it: 10 of 10 passed, 4 of them beside
  the 5 rounds of the unchanged test that all failed. Every replay scored both measures on the
  same run, since the hook itself is unchanged.
  Windows, on the tree rebased onto main's 4fe4f4c: full suite 2229 passed,
  4 skipped (the 3 Unix lock tests, and
  test_desktop's on-screen focus test, which stands itself down when the test
  process may not set the foreground window). Structure check 100.0 / 100. Linux and macOS not run: the
  test and its anchor are skipped off Windows, where there is no .cmd wrapper;
  tools/stop_compact.sh has its own tests, which were not changed.
anchor: tests/regression/test_the_stop_hook_is_timed_from_its_watcher.py
files: >
  tests/regression/test_stop_wrapper.py,
  tests/regression/test_the_stop_hook_is_timed_from_its_watcher.py (new),
  docs/verification.md, DECISIONS.md
```

```yaml
id: CU-20260924-067
type: test
title: "desktop's cross-platform theme code is tested where its mutants survived: what desktop_of reads when it is given no platform, what a theme query asks to capture, a run with no stdout, and the characters stripped from gsettings' answer"
description: >
  A mutation run on 2026-09-24 left 10 surviving mutants in
  src/conpact/desktop.py, all in the cross-platform theme code of f9cce95 and
  none in the NoActivation code of CU-20260924-064. Each group had its own
  gap. Five were on desktop_of's POSIX line (`"darwin" if sys.platform ==
  "darwin" else "linux"`): its return dropped, == swapped for !=, and each of
  its three strings. No test gave desktop_of an os name other than "nt", so
  the line ran only under theme(os_name="posix") with a query that could not
  run, which reads as dark whatever the line returned. One was desktop_of()
  losing its return when given nothing, which no test called. Two were _ask's
  capture_output=True and text=True: every test runner took **kwargs and read
  none of them, although without the first the real subprocess.run leaves no
  stdout to read, and without the second it is bytes, which never equal
  "dark". One was the "" in `(done.stdout or "")`. No theme answer can show
  that one: "XXXX" is not "dark" and holds neither "prefer-light" nor
  "default", so _ask itself is asked. The last was the strip set `"'\""` on
  gsettings' answer. A quoted 'default' was already tested and was not the
  gap: the mutant only adds X to the characters stripped, so only a letter X
  next to a quote tells the two apart. Added to tests/test_desktop.py: the
  linux theme cases now include a double-quoted "default" (light) and
  'Xdefault' (dark: only a quote comes off); a theme query on either platform
  is asked with exactly capture_output, text and the query timeout; _ask
  answers a run with no stdout with "" and strips what a run printed; and
  desktop_of, given no platform, is checked against what this really is
  (win32, darwin, linux, freebsd14) when given nothing, a POSIX os name, or
  "nt". That last test stands in for desktop's own `sys` through monkeypatch
  instead of passing an argument, because the read it tests has none. The rule
  it implements is that a POSIX os name is macOS only when this really is a
  Mac, and a platform argument takes the other branch. The interpreter's
  sys.platform is never changed. No mutant proved equivalent, so no source
  changed.
impact: none
verification: >
  Red first, by hand: each of the 10 mutants was applied to a scratch copy
  with tools/mutate.py's own apply() and run against tests/test_desktop.py
  with main's test file and with the new one; all 10 survived the first and
  were killed by the second. Then tools/mutate.py on desktop.py, run from a
  scratch folder with PYTEST_ADDOPTS='-m "not real_ui"', once on main and
  once with the new tests, 3 workers each: 92.8% (128 / 138, the same 10
  survivors, each rechecked against the module's own tests and surviving
  that too) -> 100.0% (138 / 138, 0 survivors, 0 timeouts). On main the
  lines are 67, 68, 75, 78 and 111; CU-20260924-064 moves them to 73, 74, 81,
  84 and 117 and changes none of them. tests/test_desktop.py 57 passed, 1
  deselected (real_ui); merged by `git merge-file` with CU-20260924-064's
  uncommitted copy of the file, without conflict, it gives 72 passed against
  that change's desktop.py. Windows: full suite (`python -m pytest -q`, real_ui
  included) 2204 passed, 4 skipped. Structure check 100.0 / 100.
files: >
  tests/test_desktop.py
```

```yaml
id: CU-20260924-066
type: fix
title: "The on-screen tests time their window, not Tk's start-up or the machine's load: the click test's close clock starts at show(), its click follows the fade, and window_process's limit starts again once Tk exists"
description: >
  test_a_shown_toast_fades_in_fully_and_its_buttons_respond failed on a
  heavily loaded machine: the child printed "acted []" instead of "alpha
  0.98" and "acted ['compact']". Reproduced on 2026-09-24 before changing
  anything. The load was 24 copies of the suite (on-screen tests deselected)
  from a snapshot of HEAD, 24 CPU burners, and other sessions' mutation runs,
  with all 8 hardware threads at 100%. Under it each suite copy took 1.5 to 1.75
  hours. Six rounds of the five on-screen tests of test_toast_view.py and
  test_settings_window.py failed the click test 6 times in 6, and
  test_a_real_toast_stays_up_while_compacting_then_shows_the_result 3 times in
  6. The other three passed every round, the settings window's included; its
  one failure in the user's full run did not recur. A replay of each child that
  logged every phase showed the causes. Creating Tk took 7.7 to 16.0 seconds,
  and building the toast's card up to 14.6 more. Three things counted that
  against the window.
  First, the click test's close clock (C.opened) was read when its controller
  class was defined, before present() created Tk. The toast's first poll came
  12.0 seconds after the clock started and closed it before the click.
  Second, window_process's 30 seconds ran from the child's imports. The
  compaction-progress child was stopped inside mainloop() about 8 seconds after
  its toast appeared, having spent 13.2 on Tk and 8.1 on the card.
  Third, with the clock fixed, the click came 900 ms after show(), which is
  before the fade's eight 16 ms steps had run: under the same load they took up
  to 1.7 seconds. Two of six replays printed "alpha 0.73" and "alpha 0.61",
  and the first anchor run printed "alpha 0.61". Before the fix this was hidden,
  because the toast was already closed.
  Fixed, in the tests only. The click test's close clock starts when show()
  runs. Its click comes 900 ms after the fade's last step, so it still follows
  the toast's first poll, as before. window_process starts the window's 30
  seconds again, whole, when the child's first Tk root has been created. While
  that root is being created only the start-up limit applies: the 120 seconds
  from the child's launch, which now also prints the child's stack. Later roots
  do not restart the clock. The assertions are unchanged: the full fade (alpha
  0.98 at the click), the click and the close. A fade that never finishes still
  fails, because then no click is sent and the 10-second close clock ends the
  toast with "acted []". A fade that overshoots or stops short of 0.98 prints
  the wrong alpha.
  Considered and not done: starting the limit at show() rather than at Tk's
  first root. Tk's first root is a point every child reaches without a hook of
  its own, and building the window is code under test that the limit should
  still bound. Found alongside, not changed here:
  tests/regression/test_stop_wrapper.py::test_a_large_session_gets_a_detached_watcher_that_outlives_the_hook
  failed in 16 of the 24 loaded suite copies ("assert 23.125 < 15"), a fixed
  15-second limit of its own.
impact: none
verification: >
  Red first: the new anchor, run against HEAD's tests in a copy of the tree
  under the same load, failed 4 tests. The click test under a Tk start-up that
  seemed 11 seconds long printed "acted []". Under a fade slowed to 150 ms a
  step it printed "alpha 0.24" and "acted []". The slow-Tk limit test was
  killed at its 2 seconds ("Timeout (0:00:02)!"). The start-up-limit test
  errored, because start_seconds is new. Its two guards, a window that never
  closes and a root made every second, passed on both. Green: the anchor and
  CU-20260924-062's anchor, 11 passed under the load. After the fix, six rounds
  under the same load: 30 of 30 passed. Three ran first; then the load was
  stopped for a while, because the disk had filled (another project's temp
  files, not these runs), and three more ran once it was restored, with six
  copies of the first load still running: 30 suite copies in all. The three
  rounds run meanwhile, under the other sessions' load alone, passed too (15 of
  15). Replays of the fixed children under the load, 12 of 12. The slowest,
  the compaction-progress child, used 21.8 of its 30 seconds counted from Tk's
  root; 3 of its 4 runs would have gone past 30 counted from the imports (31.0,
  34.6 and 35.1 seconds).
  Windows: full suite 2201 passed, 4 skipped, under the other sessions' load
  alone: the 3 Unix lock tests, and test_desktop's on-screen focus test,
  which stands itself down when the test process may not set the foreground
  window. Structure check 100.0 / 100. Linux not run. Its Python has no
  tkinter, so the new tests skip there as the window tests do, and
  window_process imports tkinter only if it can, so CU-20260924-062's limit
  tests are unaffected there.
anchor: tests/regression/test_on_screen_tests_time_the_window.py
files: >
  tests/window_process.py, tests/test_toast_view.py,
  tests/regression/test_on_screen_tests_time_the_window.py (new),
  docs/verification.md, DECISIONS.md, HANDOFF.md
```

```yaml
id: CU-20260924-065
type: test
title: "toast_view's defer and demo code is tested: choosing to wait takes the rows away at once, and the demo's early sample and its answers that send nothing are checked"
description: >
  A mutation run of toast_view left survivors in code added after the module
  was last measured (2026-09-20). ToastView.click takes both rows away itself
  when the choice is "defer" or "auto_expiry" (CU-20260920-028), before the
  worker's answer comes back. The one test of those choices pumped the event
  loop until the answer was shown, and show_state takes the rows away too, so
  deleting the click's own call, or turning its `in` into `not in`, changed
  nothing it could see. The --demo sample "early" was checked nowhere: not its
  model, and not by main(), whose test runs every sample it offers except that
  one. The demo's answers to "defer" and "auto_expiry" were never asked for, so
  their return line never ran; it was the only line of the module no test
  executed apart from present()'s ignored TclError. ("always_on" was already
  asked for, by
  test_the_demo_remote_toast_shows_the_same_words_and_opens_nothing, and its
  return was covered.) New: a test clicks each of the two choices with the
  timers held, so the answer cannot be shown, and reads that both rows are
  unpacked at once, the status still says what it said (nothing is sent), and
  the look at the queue is booked. Another asks the demo for each answer that
  sends no compaction (defer, auto_expiry, always_on) and checks that it comes
  back at once in its own state, with no pause standing in for a bridge call
  and no compaction started. Extended, with nothing taken out: the demo-model
  test checks the early sample (the ask model at stage "early", which offers
  the choice to wait), and the test that every sample main() offers can be
  shown now includes "early". No source changed.
impact: none
verification: >
  Mutation (tools/mutate.py, -m "not real_ui") before the tests were written,
  stopped at 362 of the module's 435 mutants: 330 killed, 12 survived, 2
  uncovered, 18 timed out. Eight of those 14 survivors and uncovered mutants
  are in the code above: the click's `in` and its call that takes the rows
  away (lines 166-167), "early" in the demo's model (324) and in --demo's
  choices (364), and "defer", "auto_expiry", the demo answer's "state" and its
  dropped return (344-345). Eight more on the same lines were among the 73 the
  run never reached: the early model's `==`, its "stage" and both its "early"s
  (326), and the answer's `==`, "deferred", "auto_expiry_set" and its second
  "defer" (345). With the tests, those 16 were run in one pytest process
  against the four new and extended tests, each mutant executed into the
  loaded module and the original put back, with the unmutated source passing
  first: 16 killed, 0 survived. Every one of them is inside a function, so no
  test holds a copy of it taken at import. Left, and outside this change:
  deleting show()'s update_idletasks (255), the two 0->1 changes in its
  fallback screen rectangle (257), and --demo's prog, description and one help
  string (362, 363, 365); the 18 timeouts are all in the card's construction
  (lines 88-164). The four tests (7 items): 7 passed. Windows: full suite,
  with CU-20260925-079 on top, in one run on a loaded machine (1 h 45 min,
  about five times its usual length): 2,359 passed, 5 skipped, 4 failed. Each
  failure was a child process running out of time: two on-screen toasts still
  starting Tk at 30 s, and the Stop hook's watcher and its .cmd at 60 s. No
  source changed here, and run again alone on the same tree the four passed (4
  passed in 86 s): 2,363 in all, main's 2,341 with the 5 new items here and
  the 17 of CU-20260925-079.
anchor: none (no behaviour changed)
files: >
  tests/test_toast_view.py, docs/verification.md, CHANGES.md
```

```yaml
id: CU-20260924-064
type: fix
title: "The first toast a process shows no longer takes the keyboard: a toast's windows are made with activation refused, and the keyboard is handed straight back if Windows moved it anyway"
description: >
  D-20260919-015 says the toast is shown without taking focus. The first toast
  each process showed took it. Reported from a run of tests/test_toast_view.py
  with every foreground change logged: in each of the four real_ui toast tests
  the child's toast window became the foreground window while still hidden, at
  (0, 0), about 50 ms before it was shown, and kept it until the toast closed.
  Reproduced on 2026-09-24 in production conditions before changing anything:
  the real watcher, started as idle_arming.arm starts it (detach.spawn of
  pythonw -m conpact.idle_watch, detached, its parent gone at once), under a
  throwaway home, for a made-up session with Remote Control off, so its toast
  could send nothing. With the user's own apps in front (last input 0.16 s and
  6 s before), its first toast came 20 seconds after start in one run and 10
  minutes after in the other. Each time the toast's window took the foreground
  while hidden at (0, 0), about 40 ms before it was shown, and held it until
  the toast closed 7 and 8 seconds later. In the 3 and 9 seconds logged after
  the close, no window got it back. Cause: Tk activates the first window a
  thread makes, shown or not (SetActiveWindow at the end of UpdateWrapper in
  tkWinWm.c, Tk 8.6.12), and present() made its first window inside show().
  show_without_focus() then read the foreground to hand back to after that had
  happened, so it read the toast itself. A stand-in for the user's app, a
  window of its own process holding the foreground, was deactivated and lost
  the keyboard (WM_ACTIVATE inactive, WM_KILLFOCUS) when the toast came up,
  and got it back only when the toast closed, in 2 of 2 runs. Also read on
  this machine: the live foreground lock timeout is 0
  (SPI_GETFOREGROUNDLOCKTIMEOUT; the registry says 200000), so any process may
  take the foreground. The fix does not rely on that either way. Fixed.
  present() opens desktop.NoActivation before Tk makes any window and keeps it
  until the window is destroyed. It is a thread hook (WH_CBT) that refuses
  every activation of the thread's windows. present() then has Tk make the
  toast's window at once (update_idletasks) and calls hand_back(). If this
  process or no window holds the foreground, that gives it back to the window
  that held it before Tk existed; a change of window the user made stands.
  Refusing alone was measured not to be enough: Windows can move the
  foreground to the process before it asks the hook. With the hook alone, one
  of two runs left the user's Chrome without the keyboard until they clicked
  it. With the fix, 2 of 4 runs found the foreground already empty when the
  hook was asked, and the hand-back restored it 1.2 and 3.1 ms later. That is
  the one remaining gap, and only when Windows lets the process take the
  foreground. Before, the gap was the whole life of the toast. Considered and
  not done: making Tk's first window a child window. SetActiveWindow on a
  child window does nothing, measured, but Tk's first window can be one only
  if a throwaway Tk is embedded in a non-Tk window. Tk then asks with a modal
  "Tk Warning" box, unless the window speaks Tk's private embedding protocol.
  The Tk -disabled attribute and WS_EX_NOACTIVATE were tried and do not stop
  the activation. LockSetForegroundWindow would change what every other app
  may do. Also fixed: test_show_without_focus_maps_a_no_activate_tool_window,
  which is real_ui. Logged, it showed its root on screen at (130, 130) as an
  ordinary window for about 0.1 s before withdrawing it, and its stand-in for
  the user's app was an ordinary window, which FancyZones moves. The root is
  now withdrawn before Tk shows anything, the stand-in is a tool window off
  every screen, and the user's window gets the keyboard back at the end
  (window_guard.hand_back, made public for it). Off Windows NoActivation does
  nothing; whether a first Tk window takes the keyboard on macOS or Linux was
  not measured.
impact: behaviour
verification: >
  New anchor, observed failing first: with the product change stashed, its
  child's first toast had an active window ("Tk's activation of the window it
  made was let through"). Run twice more against the old source to see all
  three of its checks: each time the first toast was the thread's active
  window, its process held the foreground at the first poll, and the window
  became the foreground as logged from outside; the second toast was clean.
  Against the fix, twice: every check clean. The fixed toast in four fresh
  processes, timed from inside: the activation was refused every time, the
  thread never had an active window, and no python process became the
  foreground in the outside log. The stand-in app with the fix: in two runs it
  got only a caption repaint (WM_NCACTIVATE active), no deactivation and no
  loss of focus. In two more the user moved to another app partway through,
  and the toast's process never held the foreground. After the fix, in
  production conditions: two real detached watchers showed their first toast
  20 and 35 seconds after start, and the user's Chrome kept the foreground
  throughout. A third showed its first 10 minutes after start; the only
  changes of foreground while it was up were the user's own clicks, to the
  taskbar and then an app of theirs. No window of any of them became the
  foreground. The desktop test's root, logged again: never on a screen, the
  stand-in a tool window at (-4000, -4000), and the user's window had the
  keyboard back 40 ms after the test took it. 16 new tests besides the anchor.
  Thirteen read what NoActivation asks Windows for through injected calls
  (D-20260920-023): the hook's kind and thread, what it refuses and passes on,
  and when it hands back and when it leaves the foreground alone, and that an
  error inside it is not swallowed. Two check the real, privately typed user32
  and a real hook going on and off. One checks the order in present().
  Windows: full suite 2212 passed, 3 skipped. Run again after the error test
  was added, with the machine saturated by other programs (50 minutes): 2211
  passed, 2 failed, 3 skipped. The two were on-screen tests whose child ran
  out of time, the settings window's round trip and the toast's click test,
  and both passed run again alone. Timed in fresh processes under the same
  load, creating Tk took 7.3 and 16.3 s and building the card 3 s more, and a
  third run reached the 30-second window limit while still building.
  NoActivation took 8 ms to open, its hook 2 ms over 38 to 51 calls, the
  hand-back under 0.5 ms. The click test's close clock started before Tk
  existed; CU-20260924-066 has since made it time the window. The files this
  change touches, run after it, 171 passed, on-screen tests included. Rebased
  onto CU-20260924-066 and CU-20260924-067, which changed tests and docs only;
  the files both touch, with every window anchor and the docs test: 228
  passed, 1 skipped. The skip was
  test_show_without_focus_maps_a_no_activate_tool_window standing itself down,
  as it is written to: by then the live foreground lock timeout read
  2147483647, where it had read 0 that morning, so the test process could not
  give its own stand-in the foreground. It passed earlier the same day with
  the same code. Run again after the error test was added, with other programs
  holding the machine at 100% CPU (50 minutes): 2211 passed, 2 failed, 3
  skipped. The two were real_ui tests whose window runs in a child process,
  the settings window's round trip and the toast's click test, and both passed
  re-run alone. The toast's, repeated, failed 2 of 3, and timing a toast's
  phases in fresh processes under the same load showed why: creating Tk took
  7.3 and 16.3 s and building the card 3 s more, and a third run reached the
  30-second window limit while still building. The click test's controller
  closes the toast 10 s after its script starts, before Tk exists.
  NoActivation's part: 8 ms to open, about 2 ms in its hook over 38 to 51
  calls, and under 0.5 ms to hand back. The test's clock is left to a task of
  its own. The files this change touches, with the on-screen tests and both
  window anchors: 171 passed. Linux (WSL Debian, Python 3.13.5, pytest's
  pure-Python packages copied in, nothing installed): 2003 passed, 28 skipped,
  2 failed. The two are the mutation tester's own anchor (CU-20260923-061),
  which needs pytest-cov; the copied packages lack it, that entry was never
  run on Linux, and both pass on Windows. A re-run of that file with coverage
  and pytest-cov copied in too did not finish in 15 minutes and was stopped.
  Off Windows NoActivation does nothing, and the new tests that need Windows
  skip. Mutation (-m "not real_ui", the machine saturated by other programs
  throughout): desktop.py, all 168 mutants, 156 killed (92.9%). Two survivors
  were in this change: NoActivation.__exit__'s `return False`, where True
  would have swallowed any error raised inside a toast. The error test was
  added and seen to kill the True mutant by hand, and the redundant `return
  False` removed, since dropping it was the other, equivalent survivor. The
  other ten are in the theme code of f9cce95, which this change does not
  touch; CU-20260924-067 has since added the tests that kill them.
  toast_view.py, stopped after 362 of 435 once every mutant was timing out at
  the 120 s and 300 s limits under the load: 330 killed, 12 survived, 2
  uncovered, 18 timed out (91.2% of those run; a timeout is not a detection).
  All 8 on the lines this change touched in present() were killed, deleting
  the new update_idletasks() and hand_back() calls among them. The survivors
  are ones docs/verification.md already accounts for (show()'s
  update_idletasks, the work area's fallback corner, argparse help), or code
  added after the module was last measured (the defer choice's hiding of the
  rows, the demo's early and defer answers), also left to a task of their own;
  the timeouts are all in _build's layout lines, which D-20260920-024 records
  one test killing. Structure check 100.0 / 100.
anchor: tests/regression/test_the_first_toast_leaves_the_keyboard_alone.py
files: >
  src/conpact/desktop.py, src/conpact/toast_view.py, tests/test_desktop.py,
  tests/test_toast_view.py, tests/window_guard.py,
  tests/regression/test_the_first_toast_leaves_the_keyboard_alone.py (new),
  docs/idle-toast.md, docs/verification.md, DECISIONS.md, HANDOFF.md
```

```yaml
id: CU-20260924-063
type: fix
title: "A test's windows stay off the user's screens and away from their keyboard: test roots are tool windows, Tk's first activation is spent before any test, and a guard fails a test that breaks either"
description: >
  The window tests show real Tk windows off screen, and on the machine they
  were written on they did not always stay there or leave the user alone.
  Measured on 2026-09-24 before changing anything, by logging from outside the
  test process every window a python process showed and every change of the
  foreground window, across a run of the seven window test files (183 tests)
  with the cursor on the primary monitor; then one test per kind of root was
  run with the cursor parked on the left monitor for one to three seconds and
  put back (the user moved the mouse during five of the seven, so four windows
  were shown with the cursor there). Four findings. First, the first Tk window
  of every test process took the keyboard from whatever the user was typing
  in, shown or not: Tk activates the first window each thread creates
  (SetActiveWindow in tkWinWm.c's UpdateWrapper). In the full run the user's
  keyboard stayed with an off-screen test window for 33 seconds, until they
  clicked elsewhere. Second, 32 of the roots were ordinary windows, which
  PowerToys FancyZones moves onto the monitor under the cursor: with the
  cursor on the left monitor, a ui_style root landed at (-1904, 16), on that
  screen. FancyZones never moves a tool window (read in its v0.100.0 source,
  the version installed), and the toast tests' borderless roots, which Tk
  makes tool windows, stayed put. Third,
  test_the_focus_follows_the_page_that_is_showing, which is not real_ui,
  called show() with the real work area, which put the settings window in the
  middle of the user's screen. Fourth, the position tests of CU-20260924-062
  built the view before withdrawing the root, so they showed their window for
  a moment and, in a fresh process, took the keyboard; that entry and
  D-20260924-052 said the window was never mapped. Its anchor could not see
  it: the stand-in window manager moved windows from Tk's <Map> binding, which
  runs only when a test lets Tk handle its events. Fixed. Every test root now
  comes from root() in the new tests/window_guard.py: a tool window at (-4000,
  -4000), which Tk shows at its first update without activating it. A session
  fixture spends Tk's first-window activation before any test, on a window
  never shown, refusing it and handing the keyboard back. Refusing alone was
  measured not to be enough: with the activation refused, the user's window
  still lost the keyboard and no window had it. Every test that is not real_ui
  runs under window_guard.Guard, thread hooks that refuse and record any
  activation of the test's windows (WH_CBT) and record any of its windows
  shown without being a tool window or landing on a screen (WH_CALLWNDPROCRET,
  WM_WINDOWPOSCHANGED); the conftest fails the test on either. The focus test
  gets an off-screen work area, as the other show() tests have; the position
  tests withdraw before they build, as run() does. The stand-in window manager
  now listens for Windows' own "window shown" event from a thread of its own,
  as FancyZones does from its own process. Considered and not done: building
  every test's window withdrawn. Only the tests that click or hover, or read
  the width a widget was given, need a shown window, because Tk drops a
  pointer event sent to a widget never shown. More were shown (21 of 38
  settings-window tests, 42 of 74 toast tests), because building a view lets
  Tk map a root that is not withdrawn. They stay that way: showing a withdrawn
  window later takes deiconify, which activates it, while Tk's own first
  showing does not.
impact: none
verification: >
  Red first: with the guard in place and the fixtures unchanged, the window
  test files gave 178 passed and 30 errors, each a test on an ordinary root
  ("show a window that is not a tool window"); the focus test also recorded
  "put a window on a screen, at (730, 158)". None recorded "take the
  keyboard": the spend at session start works. After the fix, 178 passed.
  Layout reads are identical on the new roots: a dump of every widget's
  requested and given size, place, packing, font, padding, colours and text
  compared equal between the old and new roots for the settings window's four
  tabs at the screen's DPI and at 96 (393 widget readings each), and for the
  toast at each stage and as a notice. The stand-in anchor was observed
  failing first: with the old build-then-withdraw order it moved 2 windows
  ("stand-in moved 2 window(s)"); with the fix, 0; its control still fails as
  it should. The new anchor holds the rest: a test root is an unactivated tool
  window off every screen, plain and borderless; in a fresh process Tk's first
  window triggers an activation, and after the spend none does; and the guard
  records a real focus_force, a window that is not a tool window, and a window
  at (0, 0) of the primary monitor, each on a transparent window (alpha 0 from
  its first showing, checked with GetLayeredWindowAttributes). A thread-hooked
  run of five settings windows took no measurably longer than an unhooked one
  on a loaded machine (17.6 to 21.3 s either way). After the fix, the logged
  run of the window test files and both anchors (190 tests, all passed): no
  window of a test that is not real_ui took the foreground, and none was
  visible on a screen except the anchor's transparent one at (0, 0); every
  window such a test showed was a tool window except the anchor's other
  transparent control. Only real_ui tests took the foreground. Not re-run with
  the cursor on the left monitor: the user was using the mouse, and it moved
  during five of the seven parked runs before the fix, so the parking stopped
  there; the tool-window case was measured there before the fix, and the guard
  now fails any test that shows a window that is not a tool window, wherever
  the cursor is. Windows: full suite 2196 passed, 3 skipped. Linux not re-run:
  WSL would not start (HCS_E_CONNECTION_TIMEOUT). Off Windows the guard and
  the spend do nothing, checked on Windows with the module's platform switch
  off, and the changed window tests need Tk, which the Linux run skips. Structure
  check 100.0 / 100.
anchor: tests/regression/test_test_windows_stay_off_the_desktop.py
files: >
  tests/window_guard.py (new), tests/conftest.py, tests/test_settings_window.py,
  tests/test_toast_view.py, tests/test_ui_style.py,
  tests/regression/test_settings_window_fits_the_screen.py,
  tests/regression/test_toast_buttons_fit_the_card.py,
  tests/regression/test_window_tests_do_not_race_the_desktop.py,
  tests/regression/test_test_windows_stay_off_the_desktop.py (new),
  docs/verification.md, DECISIONS.md, HANDOFF.md
```

```yaml
id: CU-20260924-062
type: fix
title: "Two window tests stop racing the desktop: one read where FancyZones had put its window, the other counted Python's start-up against its window"
description: >
  Two tests of the settings window failed now and then, most often under load,
  and passed when run again. The failure seen in a hand recheck of the mutant
  at settings_window.py:237 ("1 failed, 29 passed") was the file's 30th test,
  test_show_centres_the_window_in_the_work_area. Running the file in six
  parallel copies reproduced it once in about 120 runs: a window placed at
  (-4730, -4186) was read back at (-1904, 16), 16 pixels inside the corner of
  the left-hand monitor. Tk places a toplevel with MoveWindow, which does not
  clamp to a monitor, and puts an unplaced one at (26, 26) on the primary
  monitor, so Tk was not the cause. PowerToys FancyZones is running with "move
  newly created windows to the current active monitor" on, and it moves every
  window a process shows onto the monitor under the cursor, from its own
  process, a moment later. Its log records 14,411 lookups for python.exe
  windows during the stress runs. Replayed with the cursor parked on the left
  monitor and then put back, each window got a <Configure> at exactly
  (-1904, 16). Tk's own move normally
  lands after FancyZones' and wins; under load FancyZones' lands last. That
  test and test_show_keeps_a_window_larger_than_the_work_area_at_its_corner also
  called the real focus_force, taking the keyboard from whatever the user was
  doing. Both now build the window the way run() does, withdrawn before it is
  ever mapped. They record the deiconify, lift and focus_force that show()
  asks for instead of doing them, and read the position from Tk's own record of
  what it was asked for (wm geometry). The asserted positions are the same
  numbers as before. The order of the calls is asserted too, so they catch two
  faults the old tests let through, each hand-applied to show(): showing the
  window before placing it, and placing it before it is laid out
  (update_idletasks deleted).
  The second race: test_the_real_window_shows_saves_and_closes gave its child
  process 30 seconds for everything. Replaying that child 24 times under the
  same load, 3 were killed at 30 seconds. In those, starting Python and
  importing conpact took 13 to 15 seconds and creating Tk 5 more, against 2.5
  and 3 in a good run. The instrumented stress runs failed on this test twice,
  in two copies at once. It and the toast's four on-screen tests now run their
  child through tests/window_process.py, which starts the 30 seconds once the
  child has imported what it needs. Past them the child prints its stack and
  exits, so a window that never closes still fails, and says where it was
  stuck. A 120-second backstop covers start-up. Two suspects were ruled out:
  the <<ThemeChanged>> "application has been destroyed" message was not in any
  failure, and neither failure was a Tk library read.
  Also found: creating a Tk root takes 1.5 seconds on this machine with
  nothing else running, and about 4 under load, 3.7 of them in sourcing Tk's
  own scripts (tm.tcl alone 1.9).
impact: none
verification: >
  New anchor, observed failing first against the old tests. Under a stand-in
  window manager that moves every Tk root to (-7000, -7000) the moment it is
  mapped, test_show_centres read -7000 and failed. With the fix,
  both position tests pass under it and it moves none of their windows. A
  control test that maps a window and reads it back fails under it, which
  proves the stand-in bites. The control runs in a pytest root of its own:
  the first version collected it from the temp folder, so pytest scanned
  every folder above it, and in the full suite a temp folder another program
  deleted meanwhile ended the collection. The anchor's other three tests hold
  the new time limit to its
  contract: a start-up of 4 seconds does not fail a 2-second window, a window
  that never ends fails within the limit with its stack, and the backstop is at
  least 120 seconds. Hand-applied mutants of show(), each run against the new
  and the old position tests: the y divisor, max(0 -> min(0 on x, and deleting
  the geometry call are killed by both; deleting update_idletasks and showing
  the window before placing it are killed only by the new tests. Under load
  after the fix, tests/test_settings_window.py and tests/test_toast_view.py ran
  in six parallel copies for 4 rounds, alongside 32 replays of the on-screen
  child: 24 of 24 runs passed (112 tests each). Before the fix, 120 loaded
  runs of the settings-window file had failed once on the position test and
  twice on the time limit, both in a round that had six more processes
  replaying the position test's steps beside it. The position failure is
  rarer than the loaded runs can show, so the stand-in anchor is the proof of
  that fix, not the clean runs. Windows: full suite 2189 passed, 3 skipped.
  Linux not re-run: the window tests need Tk, which that run does not have,
  and the time-limit tests, which do not, were not run there. Structure check
  100.0 / 100.
anchor: tests/regression/test_window_tests_do_not_race_the_desktop.py
files: >
  tests/test_settings_window.py, tests/test_toast_view.py,
  tests/window_process.py (new),
  tests/regression/test_window_tests_do_not_race_the_desktop.py (new),
  docs/verification.md, DECISIONS.md, HANDOFF.md
```

```yaml
id: CU-20260923-061
type: fix
title: "The mutation tester no longer lets its coverage map decide a survivor, and the settings window is at 97.5%, not 97.7%"
description: >
  tools/mutate.py runs each mutant against the tests whose per-test coverage
  context names its line. For a line that runs when the module is imported the
  map is wrong: a module is imported once per test process, at collection,
  which is no test, so the only context such a line collects is from a test
  that runs the module again. Measured on 2026-09-23 from the tool's own map:
  every import-time line of settings_window.py - `MODULE`, `WIDTH`, the tab
  names in `TABS`, the click prefixes, the default arguments `pad=(12, 6)` and
  `focus=True` - was given the single test
  `test_the_module_run_as_a_command_is_what_opens_the_window` (the runpy test of
  `python -m conpact.settings_window`). So `WIDTH = 460 -> 461` ran that one
  test and was recorded as surviving, although tests/test_settings_window.py
  asserts `sw.WIDTH == 460`. The same pass had a second blind spot: deleting
  `home.migrate()` from `main` is killed only by the test that reads each entry
  point's source, which executes none of it, so no coverage context names it.
  `_own_tests` already existed, but only a timeout was retried with it.
  A mutant its covering tests let through is now run again, before it is
  recorded as surviving, against `_module_tests`: its own test file, whole, and
  every tests/regression/ file that imports the module or names it in a string
  (the dotted name, the bare name, or its file), read from the syntax tree so
  prose and a module whose name merely starts the same way do not count. A
  failure there is a kill. The recheck uses the timeout retry's 300-second
  limit, and a recheck that does not finish leaves the mutant a survivor, never
  a kill. The row carries `recheck` with that run's own verdict. A mutant whose
  first run was the whole suite, a file that already ran whole and an
  uncovered mutant are not asked again. The timeout retry is unchanged.
  Also: when the unmutated suite fails under coverage, the tool stopped with a
  bare CalledProcessError and the captured output thrown away, so which test
  failed was lost. That happened once while this change was being measured
  (the same suite passed on the next two runs). It now stops with the failing
  tests' names.
  This corrects CU-20260923-059's account of the same measurement. That entry
  says twelve import-time survivors were all killed when re-run by hand against
  every test file that uses the window, 97.7%, 347 of 355. In fact ten of the
  twelve import-time survivors were killed (the two click prefixes survive),
  one kill was `home.migrate()`, and one was a flaky failure on a mutant nothing
  can see - inserting a setting's text at index 1 rather than 0 into a box just
  emptied - whose test passes with the mutant in place. The module is at 97.5%,
  346 of 355.
impact: tooling
verification: >
  New anchor, observed failing first (23 of 29): the survivor recheck in
  miniature, a module with a constant, a runpy test and a test asserting the
  constant, run through the tool's own `line_to_tests` (the map gives the
  constant only the runpy test) and `_run` (the mutant was "survived", now
  "killed" with `recheck: killed`); which regression files count as the
  module's tests, on this repository and on nine that do and six that do not;
  and, with `_pytest` stood in for, a recheck timeout staying a survivor, the
  timeout retry coming first and unchanged, and nothing that already answered
  being asked again. The test that the map names a failing test was added
  after the change and checked against the tool as it was on main, where it
  fails with the bare CalledProcessError. tests/regression/
  test_timeout_is_not_detection.py still passes unchanged. Re-measured
  settings_window with the fixed tool: 346 of 355, 97.5%; 20 mutants rechecked
  (11 killed, 8 survived, 1 recheck timed out), taking 5,308 of the run's 29,379
  worker-seconds. Windows: full suite 2184 passed, 3 skipped. Linux not
  re-run: the change is to a development tool the Linux run does not use.
  Structure check 100.0 / 100.
anchor: tests/regression/test_coverage_never_decides_a_survivor.py
files: >
  tools/mutate.py,
  tests/regression/test_coverage_never_decides_a_survivor.py (new),
  docs/verification.md, DECISIONS.md
```

```yaml
id: CU-20260923-060
type: change
title: "conPACT is MIT-licensed"
description: >
  The license was Apache 2.0. Asked for on 2026-09-23: replace it with MIT, and
  publish the repository again as a single commit, so that no published history
  carries the Apache license. LICENSE is the MIT text, copyright 2026 Brandon
  Stonebridge; README's License section, pyproject's `license` and the layout in
  docs/architecture.md say MIT. The public repository's history is replaced by
  one commit of the current tree.
impact: none
verification: >
  No code changed. `git grep -i apache` finds nothing but this entry and the
  decision recording the change; the published commit's tree is the local
  tree, and it has no parent.
files: >
  LICENSE, README.md, pyproject.toml, docs/architecture.md, DECISIONS.md
```

```yaml
id: CU-20260923-059
type: fix
title: "The settings window fits the screen: its settings are on tabs"
description: >
  The settings window listed all ten settings in one column and asked for
  1,178 pixels of height at 100% scaling. On a 1920x1080 screen, whose work
  area is 1,032 pixels high, its Save, Defaults and Close buttons were below
  the bottom edge, and the window cannot be resized. Seen on 2026-09-23 while
  taking screenshots for the README; the user asked for the view to be fixed
  with tabs.
  The settings are now on four tabs, `settings_window.TABS`: Idle toast (the
  toast on or off, how long before the cache expires it comes, how long
  Silence lasts, how long a result stays up), Session size (the two
  thresholds), Early toast (its idle time and how long it waits), and Agent
  (the minimum for a compaction an agent queues, and the worktree guard).
  Every setting is on exactly one. The window now asks for 558 pixels, 597
  with its title bar.
  Every page is as tall as the tallest (the pages share one grid cell whose
  minimum height is the tallest page's), so changing tab never moves the
  buttons. Only the chosen page is gridded; the others are removed, so Tab
  moves through the boxes that are showing and no others. Changing tab moves
  the keyboard to the new page's first box, or to the window when the page has
  none, and the window opens on the first tab's first box - it used to be the
  first box in the whole form. A value refused on a page that is not showing
  brings that page forward, and any tab holding a refused value is drawn in
  the error colour until the value is accepted.
  The tabs are labels in the window's own look, like its buttons: mouse-only,
  the chosen one in the text colour over an accent underline, the others muted
  and lit under the mouse. Ctrl+Tab and Ctrl+Shift+Tab step through them,
  wrapping round, bound as virtual events (<<NextTab>>, <<PreviousTab>>);
  X11 names Shift+Tab ISO_Left_Tab, which Windows' Tk refuses, so that
  spelling is added only where it exists.
  Also: screenshots of the idle toast, the result it shows after a compaction,
  and the settings window, in light and dark, in the README
  (docs/images/, chosen by the reader's GitHub theme). They were taken from
  the toast's `--demo` and from the window under a throwaway home, so they
  show sample numbers and default settings. docs/settings.md names the tabs.
impact: behaviour
verification: >
  New anchor, observed failing first (7 of 7: no `TABS`): every setting on
  exactly one tab and built on its page; at 96 DPI the window asks for no more
  than 600 pixels whichever tab shows, and the same for each; only the chosen
  page is gridded and a click on a tab changes it; the key bindings read back
  from Tk and the virtual events stepping and wrapping; the focus following
  the page; a refusal on a hidden page bringing it forward and marking its tab.
  tests/test_settings_window.py: the layout test reads the tab strip, the rule,
  the shared cell and every page back out of Tk; new tests for the chosen tab's
  colours, hover, a click after closing, a refusal on the page showing keeping
  it there, and the tabs spelled out as docs/settings.md names them.
  Windows: full suite 2153 passed, 3 skipped (run before the tab-spelling test
  was added; it passed on its own). Linux not re-run: the change is Tk only,
  and the WSL distro used for Linux has no Tk. Mutation, settings_window:
  335 of 355 killed as the tool scored it (94.4%); twelve of the twenty
  survivors were import-time lines the tool gave only the test that first
  imported the module, and all twelve were killed when re-run against every
  test file that uses the window - 97.7%, 347 of 355. The eight left are
  equivalent (docs/verification.md lists them). Structure check 100.0 / 100.
anchor: tests/regression/test_settings_window_fits_the_screen.py
files: >
  src/conpact/settings_window.py,
  tests/regression/test_settings_window_fits_the_screen.py (new),
  tests/test_settings_window.py, README.md, docs/settings.md,
  docs/images/ (new: toast-ask, toast-done and settings, each -light and
  -dark), docs/verification.md, DECISIONS.md
```

```yaml
id: CU-20260923-058
type: feature
title: "conPACT's state has a home of its own: ~/.conpact/, with the old folder moved across"
description: >
  Everything conPACT owns lived in ~/.claude/conpact/, a folder inside Claude
  Code's. Part of it belongs to ChatGPT Desktop threads (their requests, the
  sidecar's records, their idle state), and a machine with only ChatGPT Desktop
  got a ~/.claude folder for nothing but conPACT. Asked for on 2026-09-23: move
  it to ~/.conpact/, keep everything together, and decouple it from either
  vendor's layout.
  New module `conpact.home` names the folder and imports only the standard
  library; `compaction.STATE_DIR` is now `home.HOME`, and every path that was
  derived from it (requests, hook and idle logs, settings, the idle state, the
  three Codex records) follows. The sidecar's and the heartbeat's own path
  helpers, which built `<home>/.claude/conpact/` themselves, build
  `<home>/.conpact/`.
  The move: `home.migrate()` runs first in every entry point that can be the
  first conPACT process on a machine - the Stop hook, the MCP server, the
  command line, the settings command and window, the sidecar, Codex arming and
  Codex Remote Control - and never raises. Choices and records (settings, the
  off switch, each session's auto-compact, silence and hold, the Codex sidecar
  and host records) are moved unless the new home has one already, which wins.
  Logs are moved, or appended to one already there. A move links first, so it
  cannot overwrite against a racing pass, and undoes itself when Windows will
  not delete a source still held open. Pending requests are never moved: a
  server started before the upgrade may still write or cancel one where it put
  it, so the readers look in ~/.conpact/, ~/.claude/conpact/ and
  ~/.claude/clautomatic/, newest first. What a running process still writes -
  a watch marker, a toast slot, a pre-upgrade sidecar's heartbeat - is left to
  it and removed after two hours; the heartbeat is read from both folders, the
  fresher winning. The old folder is removed once it is empty.
  Both Stop wrappers check all three requests folders and the off switch in the
  new home; the first turn end after the upgrade starts Python (the off switch
  is not in the new home yet), which moves it, and the fast path holds again
  from the next.
impact: behaviour
verification: >
  New anchor, observed failing first (collection error: no conpact.home): 27
  tests - every state path under ~/.conpact/, the home module stdlib-only, the
  move (choices, records, logs, per-session files; never overwriting; appending
  logs; idempotent; never raising), requests left in place yet claimed and
  withdrawn, live files left and removed when stale, the fresher heartbeat
  winning, both wrappers' folder lists, and every entry point calling the move
  first. The wrapper tests now run the real .cmd and .sh through a first turn
  end after an upgrade: the old folder's settings and off switch arrive in
  ~/.conpact/, the old folder is gone, and the next turn end starts no Python.
  conftest isolates the new home and both earlier folders, and blocks the move
  outright in tests that read the real path constants.
  A leak, found and fixed during verification: the first full run in the
  worktree moved the user's real ~/.claude/conpact/ into ~/.conpact/ at 02:43.
  test_settings_cli runs `tools/settings.py --help` as a child process with the
  real environment, and main() now moves the state before it parses arguments;
  conftest's patched constants never reach a child. Nothing was lost - every
  file arrived intact - but the live Stop hook, still running the old code from
  the main checkout, read an emptied folder (default settings, no per-session
  auto-compact) until this change was merged. Fixed at the root: conftest now
  gives the whole test session, and so every process a test starts, a throwaway
  HOME and USERPROFILE before any conpact module is imported, and anchor test 8
  proves a child sees it. A mutation run on home.py was stopped for the same
  reason before any mutant reported (its copies still had the leaking test), so
  home.py has no mutation score yet. Full suites before the isolation fix:
  Windows 2140 passed, 3 skipped, 1 failed - the real settings-window test, the
  same intermittent on-screen failure recorded in CU-20260922-056, which passed
  3 of 3 alone; Linux (WSL Debian) 1958 passed, 22 skipped. Structure check 100.0. After
  the isolation fix, on the merged main: Windows 2142 passed, 3 skipped, 0
  failed; Linux 1960 passed, 21 skipped, 0 failed. Run live on the user's own
  folder after the merge: the remaining idle log and hold were moved, settings
  read back as the user's (min_context_tokens 300000, not the default), and the
  toast and an agent's hold went on writing to ~/.conpact/.
anchor: tests/regression/test_state_has_a_home_of_its_own.py
files: >
  src/conpact/home.py (new), src/conpact/compaction.py,
  src/conpact/codex_active.py, src/conpact/codex_sidecar.py,
  src/conpact/codex_host.py, src/conpact/cli.py, src/conpact/closure_hook.py,
  src/conpact/codex_arming.py, src/conpact/codex_remote_cli.py,
  src/conpact/mcp_server.py, src/conpact/settings_cli.py,
  src/conpact/settings_window.py, tools/stop_compact.cmd, tools/stop_compact.sh,
  tests/conftest.py, tests/regression/test_state_has_a_home_of_its_own.py
  (new), tests/regression/test_stop_wrapper.py,
  tests/regression/test_stop_wrapper_posix.py,
  tests/regression/test_request_state_dir.py, tests/regression/test_mcp_queue.py,
  tests/regression/test_user_settings.py,
  tests/regression/test_codex_remote_control_is_host_side_only.py,
  tests/regression/test_codex_sidecar_is_cross_platform.py,
  tests/test_codex_sidecar.py, tests/test_codex_remote_cli.py,
  tests/test_settings_window.py, tests/test_toast_view.py, docs/architecture.md,
  tests/conftest.py (the session-wide throwaway home),
  docs/how-it-works.md, docs/chatgpt-desktop.md, docs/idle-toast.md,
  docs/settings.md, docs/setup.md, docs/verification.md, README.md, HANDOFF.md
```

```yaml
id: CU-20260923-057
type: docs
title: "The docs stand on their own: no private workflows, no process acronyms, no record ids"
description: >
  The README, the pages under docs/ and the text the MCP server hands every
  agent were written while conPACT was built inside one person's setup, and it
  showed. The server's instructions and the queue_compaction description told
  every user's agent to queue at the end of workflows that exist in that setup
  and nowhere else, by their private names, and docs/how-it-works.md said the
  same. The docs also named the process acronyms behind them, quoted a fitness score from a tool that is
  not in the repository, linked the brief that started the project on a private
  paste, used real session names as example output, sent readers to HANDOFF.md
  (the maintainer's working notes), and cited decision and change ids in place
  of reasons. Asked for on 2026-09-23: make the docs self-contained and ready
  for end users.
  The closures are now named in terms any user has: a finished feature, fix or
  build, the last step of a multi-step plan, a wrap-up of the session, or the
  user asking. A setup with its own workflows names them in its own
  instructions. Every inline decision and change id in the docs is replaced by
  the reason it stood for; the protocol-compliance section of verification.md
  is now "How changes are recorded", in plain terms; the README and the docs
  index point contributors at CHANGES.md and DECISIONS.md under "Contributing"
  and no longer link HANDOFF.md. The README's contributor note and commands.md
  now say the suite needs pytest and jsonschema. CHANGES.md and DECISIONS.md
  themselves are records and are not rewritten.
impact: behaviour
verification: >
  New anchor, observed failing first (13 of 24 failed: the MCP text and 9
  pages): no agent-facing text names a private workflow; no page names one,
  names the acronyms or cites a record id; no page links HANDOFF.md. The
  CU-20260919-015 anchor (test_closure_instructions) keeps its contract - the
  closures are named, it is the last action, nothing hedges it - with the named
  closures restated. Full suites: Windows 2108 passed, 4 skipped (the three
  Unix lock tests, and one skip that did not come back when every test that can
  skip was re-run: 241 passed, 3 skipped; the one skip that depends on the
  moment is the on-screen test that stands down without the foreground); Linux
  (WSL Debian) 1929 passed, 19 skipped. Structure check 100.0.
anchor: tests/regression/test_the_docs_stand_on_their_own.py
files: >
  src/conpact/mcp_server.py, src/conpact/mcp_tools.py,
  tests/regression/test_the_docs_stand_on_their_own.py (new),
  tests/regression/test_closure_instructions.py, README.md, docs/README.md,
  docs/how-it-works.md, docs/setup.md, docs/idle-toast.md,
  docs/chatgpt-desktop.md, docs/security.md, docs/architecture.md,
  docs/commands.md, docs/verification.md
```

```yaml
id: CU-20260922-056
type: feature
title: "On macOS the login is read from the Keychain, where Claude Code keeps it - and only read"
description: >
  CU-20260922-055 made conPACT run on macOS but left it unable to send there:
  Claude Code keeps its login in the Keychain on a Mac, not in
  ~/.claude/.credentials.json, and conPACT read only the file. The maintainer asked for
  the Keychain to be solved.
  Where the login is filed was read from Claude Code's own binary, not taken
  from third-party write-ups, and it corrected them. The service is
  "Claude Code" + the OAuth file suffix ("" in production) + "-credentials",
  plus "-" and the first 8 hex digits of the SHA-256 of the NFC-normalised
  config directory when CLAUDE_CONFIG_DIR (or CLAUDE_SECURESTORAGE_CONFIG_DIR)
  is set. The account is the fixed string "claude-code-user", not the macOS
  login name the write-ups give; that name is kept as a second place to look,
  for earlier releases. A login too large for one item is split into a header
  "<account>#m" holding {n, l} and base64 chunks "#0".."#n-1" of total length l,
  which decode to the JSON - and the header is checked with the same bounds
  Claude Code uses (1..256 chunks, at most 2400 characters each).
  `conpact.keychain` reads it through /usr/bin/security, by absolute path, with
  a 45-second bound so an unanswered macOS prompt cannot hold the Stop hook
  past its own 90. `token_store` asks it first on macOS and falls back to the
  file, which is Claude Code's own order.
  The decision that shaped the rest: the Keychain is never written. On Windows
  and Linux conPACT refreshes an expired token and saves the rotated one, as
  Claude Code does. A refresh rotates the refresh token, so doing that on a Mac
  without writing the result back into the Keychain would log Claude Code out,
  and writing into a credential store Claude Code owns is a standing capability
  conPACT does not need. An expired Keychain login is refused by name instead.
  In practice it is fresh: the Stop hook fires at the end of a turn Claude Code
  has just spent calling the API.
  `token_status` now also says where the token is kept ("keychain" or "file"),
  and reports a Keychain token as one conPACT cannot refresh.
impact: behaviour
verification: >
  38 new tests on the Keychain reader against a fake `security` - the service
  name under each environment, the account order, a split login put back
  together, every malformed header Claude Code would not write, the refusals,
  and that no stored value reaches an error - plus 6 anchor tests on the token
  store: the Keychain first on macOS, an expired Keychain login refused with
  nothing posted and nothing written, the file as fallback, the Keychain never
  consulted elsewhere or when a file is named. conftest now guards the real
  Keychain off for every test. Full suites: Windows 2085 passed, 3 skipped;
  Linux (WSL Debian) 1905 passed, 19 skipped, 0 failed; structure check 100.0. One Windows
  run failed a single on-screen test (the real settings window), which passed
  three times alone, twice more with the other UI files, and in the next full
  run: it depends on window focus during a six-minute run, not on this change.
  NOT run on a real Mac: the naming and the split format are from the binary,
  the reading is proved only against the fake.
anchor: tests/regression/test_macos_login_is_read_from_the_keychain.py
files: >
  src/conpact/keychain.py (new), src/conpact/token_store.py,
  tests/test_keychain.py (new), tests/test_token_store.py, tests/conftest.py,
  tests/regression/test_macos_login_is_read_from_the_keychain.py (new),
  README.md, docs/setup.md, docs/security.md, docs/architecture.md,
  docs/verification.md, docs/commands.md
```

```yaml
id: CU-20260922-055
type: feature
title: "conPACT runs on macOS and Linux: a POSIX Stop hook, and no call that is Windows-only by accident"
description: >
  The maintainer asked for the whole tool to be cross-platform, including the Stop
  hook, which was a .cmd. The sidecar already was (D-20260922-036); the Claude
  Code side and parts of the Codex side were not. An audit of every
  Windows-specific construct in src/ found eight places where macOS or Linux
  would fail or quietly do nothing, and each now has an answer per platform or
  a refusal with a name:
  - The Stop hook. `tools/stop_compact.sh` is the POSIX twin of the .cmd - same
    fast path, same interpreter call, `CONPACT_PYTHON` to pick the interpreter,
    committed executable and LF-only (`*.sh text eol=lf`). Both wrappers now
    count a request in the pre-rename folder as pending: the .cmd's fast path
    had been left looking only at the new folder by CU-20260922-053, so with
    the toast off a stranded request would have been skipped.
  - Opening a session link: `open` on macOS, `xdg-open` on Linux, the url as
    one argument and never through a shell. It used to refuse off Windows.
  - The toast's theme: `defaults` on macOS, the freedesktop colour-scheme
    preference through `gsettings` on Linux. It used to be dark everywhere
    but Windows.
  - The Claude Desktop app's own store (archived sessions, the sidebar word in
    its links): Electron's per-user folder on each platform. It used to be
    %APPDATA% only, so off Windows no session was ever seen as archived.
  - The readiness check: one `ps -A -o pid=,ppid=,args=` where Windows uses one
    PowerShell query.
  - Which codex the desktop runs: read from the desktop's own resolver in its
    app.asar - the binary is `codex` in the app's resources folder, and only
    Windows relocates it to LOCALAPPDATA - so macOS and Linux now look inside
    installed app bundles. They used to reach only `codex` on PATH, which is
    not the build the desktop runs.
  - Whether the desktop holds a Codex thread: fcntl on macOS and Linux. It used
    to fail closed there, reporting every thread held. Which Unix lock Codex
    takes could not be read from its statically linked binary, so both kinds
    are probed and either one counts as held.
  - The login token on macOS: Claude Code keeps it in the Keychain there, which
    conPACT does not read. That is a decision for the maintainer rather than something
    to do quietly, so a Mac is refused by name instead of being told a file is
    unreadable.
  Two faults were caught on the way by the suite rather than by review: the
  resolver refactor moved an eager `glob` outside its guard (the recency anchor
  failed at once), and a new fixture asserted inside a nested helper, which the
  hygiene rule forbids because code under test can swallow it.
  Also scrubbed: a real ChatGPT thread title in a test fixture named one of
  the maintainer's projects. An earlier publish had carried it.
impact: behaviour
verification: >
  Windows: full suite 2054 passed, 3 skipped (the three fcntl tests, which run on Linux). Linux: full suite on WSL Debian
  (kernel 5.15, Python 3.13.5, pytest's pure-Python packages copied in, nothing
  installed into the distro), 1874 passed, 19 skipped, 0 failed. The skips are
  the tests that need Tk (not installed there) and the Windows-only probes and
  wrapper. tests/test_mcp_tools.py was not run on Linux because its jsonschema
  dependency needs a compiled package that cannot be copied from Windows. On
  Linux the POSIX Stop hook ran through /bin/sh and the fcntl probe saw both
  kinds of lock held by another process; on Windows the POSIX hook ran through
  Git's sh. Structure check 100.0/100. macOS: not run anywhere, and said so in the
  docs.
anchor: tests/regression/test_stop_wrapper_posix.py
files: >
  tools/stop_compact.sh (new), tools/stop_compact.cmd, .gitattributes,
  src/conpact/desktop.py, src/conpact/app_sessions.py,
  src/conpact/session_ready.py, src/conpact/codex_appserver.py,
  src/conpact/codex_sidecar.py, src/conpact/codex_sidecar_install.py,
  src/conpact/codex_threads.py, src/conpact/token_store.py, the matching tests,
  tests/regression/test_stop_wrapper_posix.py (new), README.md, docs/
```

```yaml
id: CU-20260922-054
type: finding
title: "Correction to CU-20260922-047: the account panel failed because of a local firewall, not the codex build"
description: >
  CU-20260922-047 concluded that codex 0.155.0-alpha.9.2 "cannot complete any
  outbound request to chatgpt.com" and called it upstream. That was wrong, and
  the maintainer found what was right: the machine's firewall.
  The failing connections were refused with WSAEACCES (10013), "access to a
  socket forbidden by its access permissions" - a local refusal, the same one
  the renderer reported as net::ERR_NETWORK_ACCESS_DENIED. The firewall on this
  machine is simplewall, which works through the Windows Filtering Platform. Its
  filters do not appear in `Get-NetFirewallRule`, which is why every rule search
  came back empty, and it allows programs by binary, which explains the rest: a
  newly installed codex build is a new binary that is not on its list, so the
  block followed the build rather than the path, and the previous day's build,
  Python and curl were all unaffected. Once the maintainer put the firewall right, the
  same newer build loaded the panel.
  Neither the codex build nor the sidecar was at fault, and there is nothing to
  report upstream. What went wrong in the diagnosis: the "ruled out" list in
  CU-047 checked Windows Firewall rules, the proxy and the sandbox settings, but
  not the WFP layer beneath them, and it reached for "upstream" before the error
  code had been read - WSAEACCES names a local filter in one line.
  CU-047 is kept as it was written, with a pointer here, and so are the two
  records that repeated it (CU-20260922-048, D-20260922-039), each now marked.
  D-039's rule is unchanged and, if anything, better supported: pinning the older
  build would have routed around a local firewall rule and hidden it behind
  conPACT just as surely as it would have hidden an upstream fault.
impact: none
verification: >
  The maintainer's diagnosis, confirmed by the account and usage panel loading on the
  same build once the firewall was put right; the error code was measured at the
  time (WSAEACCES 10013). No code changed.
files: >
  CHANGES.md (CU-047, CU-048 and CU-045 marked), DECISIONS.md (D-039 marked)
```

```yaml
id: CU-20260922-053
type: fix
title: "A rename does not strand a queued compaction in a server that is still running"
description: >
  The maintainer asked why compaction had not been firing in this session. It was not
  this session: nothing had fired anywhere since the morning.
  CU-20260922-041 renamed the state folder from `clautomatic` to `conpact`. A
  rename moves the files on disk, and it moves the module on disk, but it does
  not move the module already imported into a running process - and an MCP
  server lives exactly as long as the Claude Code session that started it.
  Measured: this session's server (pid 99864) started 2026-09-21 23:16, the
  rename landed 2026-09-22 05:47, and nine of the ten live servers predate it.
  Each was still writing requests to the old folder while `closure_hook` read
  the new one, so `consume_request` found nothing, every turn.
  Nothing reported it, and that is the part worth naming. "Nothing pending" is
  a skip, a skip is silent by design, and it should stay silent - a log line per
  turn end on every session is noise that hides the lines that matter. What made
  it visible was a contradiction between two answers: `compaction_status`, asked
  inside the old server, said `pending: true` about a folder the hook had just
  found empty. Five requests were sitting in it, the oldest from 06:51.
  The reader now looks in the old folder as well as the current one, newest
  home first. Nothing writes to it, no server is restarted, and the five
  stranded requests become claimable at their own sessions' next turn ends.
  Only the default lookup reaches back: a caller that names a directory means
  that directory. That is not tidiness - the legacy path resolves under the real
  user's home, so without it every test using the default lookup would read the
  machine's live requests and the suite would delete them.
impact: behaviour
verification: >
  Full suite 2002 passed; structure check 100.0/100. Verified live before the fix
  and after: `compaction.pending_request()` for this session returned None
  against the current folder and returns the 12:07 request now, read from where
  the older server left it.
anchor: tests/regression/test_a_rename_does_not_strand_a_request.py
files: >
  src/conpact/compaction.py, tests/conftest.py,
  tests/regression/test_a_rename_does_not_strand_a_request.py (new)
```

```yaml
id: CU-20260922-052
type: change
title: "A Codex thread can queue its own compaction, bound to the turn that is asking"
description: >
  The MCP tools were Claude-only, and the reason was identity, not effort. A
  Claude server binds to the session that started it through the environment and
  the parent pid (D-20260919-012). Codex hands an MCP server nothing of the
  kind: three MCP children codex had spawned were read on 2026-09-22 and carried
  CODEX_HOME, CODEX_CLI_PATH and a pipe path between them - not one thread id.
  So the identity comes from the only process that can see it. The sidecar
  already watches `turn/started` and `turn/completed` go past, and a tool call
  happens during a turn, so the caller is the thread whose turn is in flight.
  Better than that, the caller is usually *stated* rather than inferred: an
  `item/started` notification carries an `mcpToolCall` item naming both the
  server being called and the thread calling it, so when that server is conPACT
  there is no ambiguity to resolve - ten turns can be running and the answer is
  still exact. `codex_active` publishes both on every change: the threads
  calling us, and the in-flight set as the fallback for a call the notification
  did not cover. It fails closed on what is left: none and it cannot say, two at
  once and it will not guess. The failure worth avoiding is acting on a thread
  that did not ask, not declining one that did.
  The platform is decided from the server's own environment rather than by
  trying Claude and falling back. On a machine running both apps, a fallback
  would let a Claude server whose binding broke bind a Codex thread - exactly
  the foreign identity D-20260919-012 exists to refuse.
  Execution keeps the intent/execution split of D-20260919-006. The tool records
  the request and sends nothing; the turn end runs it. Claude's turn end is its
  Stop hook, Codex's is the sidecar (CU-20260922-051), and the request is
  claimed before it runs so two turn endings arriving together still fire it
  once (D-20260919-010).
  A file rather than a new control verb: the sidecar's port exists to inject
  into an app-server's stdin, and a question answered by reading a file needs no
  port, no token and no new way in.
impact: behaviour
verification: >
  Full suite passes. 17 tests on the in-flight record, 11 anchor tests on the
  binding rule, 4 on the queued compaction running once at the turn end.
  Registered live in `~/.codex/config.toml` (backed up first); the real
  app-server started with it, listed conPACT's four tools, and a real Codex
  thread called `compaction_status` and was bound to itself
  (01a00000-0000-7000-8000-000000000006, "a test thread").
  That live call is also what found the measurement gap: it answered
  `context_tokens: null`, because the size was read from Claude's transcript
  store and a Codex thread keeps a rollout. Now 32,959, from the right file.
anchor: tests/regression/test_codex_mcp_binds_the_asking_thread.py
files: >
  src/conpact/codex_active.py (new), src/conpact/codex_turns.py,
  src/conpact/codex_sidecar.py, src/conpact/codex_arming.py,
  src/conpact/mcp_tools.py, tests/test_codex_active.py (new),
  tests/test_codex_arming.py,
  tests/regression/test_codex_mcp_binds_the_asking_thread.py (new)
```

```yaml
id: CU-20260922-051
type: change
title: "The sidecar is the turn-end hook Codex does not offer, so arming stops being a sweep"
description: >
  `codex_arming` was written as a sweep because Codex has no turn-end hook: its
  hook enum has no such event, so there was nothing to arm at and the only
  option was to look at every session and ask. That was true of the hook enum
  and false of the wire. The app-server pushes `turn/completed` to the desktop,
  and the sidecar has been standing in that stream the whole time - the event
  was there, just not where we had looked for it.
  `codex_turns` is the recognition and nothing else: bytes in, thread id out. It
  starts nothing, spawns nothing and touches no disk, so *when to act* is
  testable apart from *acting*. It is tolerant about where the id travels and
  strict about the event - `turn/started` is its opposite, `item/completed` is
  one step inside a turn, and all of them carry `threadId` too, so a loose match
  would arm a watch against a session that is still working. A miss is cheap;
  the sweep catches it.
  The sidecar spawns `codex_arming --thread <id>` detached, after the desktop's
  bytes are written, with the arming's own `CODEX_CLI_PATH` removed so it cannot
  re-enter the shim. Two faults were found by these tests rather than by review:
  the arm call was unguarded, so a failed spawn would have broken the desktop's
  stream, and the child would otherwise have inherited the shim path.
  The sweep is not superseded. It still covers sessions that were already idle
  when the sidecar started, and machines with no sidecar at all.
impact: behaviour
verification: >
  Full suite 1940 passed; structure check 100.0/100. The payload in the anchor is
  measured, not invented - captured from a live ChatGPT Desktop session on
  2026-09-22 at 10:58:47 (`params keys=['threadId', 'turn']`), which confirmed
  the key the recogniser had been written against from binary strings.
  NOT yet observed: the hook arming a live session end to end. The sidecar
  holding the session at the time of the capture had started four minutes
  before the wiring existed.
anchor: tests/regression/test_codex_turn_end_is_a_hook.py
files: >
  src/conpact/codex_turns.py (new), src/conpact/codex_sidecar.py,
  src/conpact/codex_arming.py, src/conpact/codex_sidecar_log.py,
  tests/test_codex_turns.py (new), tests/test_codex_sidecar.py,
  tests/test_codex_sidecar_log.py,
  tests/regression/test_codex_turn_end_is_a_hook.py (new)
```

```yaml
id: CU-20260922-050
type: fix
title: "A pruned Codex build can no longer leave the desktop with no codex at all"
description: >
  The shim resolved the real codex as "the pin, else the marker", and trusted
  whichever it found without checking it still existed. Codex installs each
  build into its own folder and prunes the old ones, so a name written once at
  install goes stale by itself - and on 2026-09-22 it did: the build the marker
  named was deleted out from under it the same day it was written.
  The consequence is not a degraded session. The desktop resolves its
  app-server through the shim, so a shim that hands back a path to nothing means
  no app-server, no sign-in, nothing - which is exactly what happened here, and
  it was luck rather than design that it surfaced while someone was looking.
  `real_codex` now uses the pin only while it names a file, then the marker on
  the same condition, then falls back to the newest install on disk. The
  fallback calls `newest_install` directly rather than `codex_cli`, because
  `codex_cli` resolves `CODEX_CLI_PATH` - which points at the shim.
  This is the same principle as D-20260922-039 applied to a moment that decision
  did not cover: the shim runs what the desktop would have run, including on the
  day the build it was pinned to stops existing.
impact: behaviour
verification: >
  Full suite passes; the end-to-end proof passes 9/9 through the real shim exe.
  Nine resolver tests, including the incident itself - a marker naming a pruned
  build resolving to what is actually installed - and that the fallback does not
  resolve back through the shim.
anchor: tests/regression/test_codex_build_is_chosen_by_recency.py
files: >
  src/conpact/codex_sidecar.py, tests/test_codex_sidecar.py
```

```yaml
id: CU-20260922-049
type: change
title: "An opt-in tap on the sidecar's pipes, and what it proved"
description: >
  Three rounds of reasoning about the missing account/usage panel had produced
  three plausible culprits and no evidence. A proxy cannot answer the only
  question that mattered - what did the desktop actually ask for, and what did
  it get - from the outside, so `codex_sidecar_log` makes it answerable from the
  inside.
  It is off unless `CONPACT_SIDECAR_LOG` names a file: no file, no cost, not a
  byte changed on the wire. When on it still changes nothing - it is handed a
  copy of each chunk after the stream has been dealt with, and every call into
  it is guarded, because a diagnostic that can break what it is diagnosing is
  worse than none. What it keeps is deliberately thin: direction, id, method,
  error code and message, result *keys*, size. This traffic carries the user's
  account, plan, usage and conversations, and a log outlives the question it was
  opened for, so the values stay off the disk unless
  `CONPACT_SIDECAR_LOG_BODIES=1` asks for them.
  What it proved, first run: over 2m25s of a real desktop session, including the
  panel being opened, `account/usage/read` and `account/rateLimits/read` were
  never sent. The desktop does not fetch usage through the app-server at all, so
  no sidecar can be responsible for it. `account/read` was sent twice and
  answered both times.
impact: behaviour
verification: >
  18 tests, including that it is absent unless asked for, that a writer which
  raises cannot escape, that non-UTF-8 is recorded rather than thrown, that a
  partial line waits for its newline, and that a result's values stay out while
  its keys go in. Driven end-to-end through the real shim exe (the proof still
  passes 9/9) and then against a live ChatGPT Desktop session.
anchor: tests/regression/test_codex_sidecar_is_cross_platform.py
files: >
  src/conpact/codex_sidecar_log.py (new), src/conpact/codex_sidecar.py,
  tests/test_codex_sidecar_log.py (new)
```

```yaml
id: CU-20260922-048
type: fix
title: "CONPACT_CODEX_REAL pins one codex for everything, not just for the shim"
description: >
  CU-20260922-046 made the resolver follow Codex's newest build on purpose, and
  left `CONPACT_CODEX_REAL` as the way a user pins a particular one instead.
  Only the shim read that variable. `codex_cli` - which is what starts the
  app-servers conPACT runs itself, for a thread the desktop does not hold - did
  not, so a pin moved one of the two and left the other on whatever the resolver
  chose. A machine would then be running two different codex builds for the same
  feature, with nothing saying so, which is precisely the failure the resolver
  fix was about.
  The name now lives in `codex_appserver` beside the marker it belongs with, the
  shim reads it from there, and `codex_cli` honours it ahead of everything
  including `CODEX_CLI_PATH` - it is the user saying which build to use, and it
  is taken at its word rather than resolved any further. A pin naming nothing
  usable is ignored rather than allowed to blank the lookup.
  This matters today on this machine: with the resolver now correctly following
  the newest build, the app-servers conPACT starts would use
  0.155.0-alpha.9.2 - the one that cannot reach chatgpt.com (CU-20260922-047).
  The pin is how that is held to the working build until upstream fixes it, and
  it has to move both paths to be worth anything. [Corrected by
  CU-20260922-054: that build's failure was a local firewall, not the build.
  The pin still has to move both paths.]
impact: behaviour
verification: >
  Full suite passes. Six anchor tests: the two modules read one name, the pin
  beats both the newest build and CODEX_CLI_PATH, and three shapes of unusable
  pin fall through to the normal lookup.
anchor: tests/regression/test_codex_build_is_chosen_by_recency.py
files: >
  src/conpact/codex_appserver.py, src/conpact/codex_sidecar.py,
  tests/regression/test_codex_build_is_chosen_by_recency.py
```

```yaml
id: CU-20260922-047
type: finding
title: "ChatGPT Desktop's account and usage panel: measured, and it is not the sidecar"
description: >
  [Corrected by CU-20260922-054: the cause was a local firewall, not the codex
  build. The sidecar finding below stands; the build finding does not. Kept as
  it was written.]
  Reported: account and usage information stops loading in ChatGPT Desktop while
  the conPACT sidecar is installed. Two rounds of reasoning had produced two
  plausible culprits and no evidence, so this was measured instead.
  The shim was A/B'd against the real codex on the four calls the panel makes -
  `initialize`, `account/read`, `account/usage/read`, `account/rateLimits/read`
  (method names read out of the binary) - same environment, same order, same
  minute. Every reply came back identical through the shim, real data included.
  The sidecar is not in this fault at all.
  The actual fault is the codex build. 0.155.0-alpha.9.2 (installed 2026-09-19)
  cannot complete any outbound request to chatgpt.com on this machine: usage,
  rate limits, models and the plugin catalogue all fail with reqwest's "error
  sending request", in 5-77 ms, so not a timeout. 0.155.0-alpha.9 (2026-09-18)
  succeeds on the same machine, same auth, same second. Ruled out by direct
  test: proxy configuration (none; `ProxyEnable` is 0), reachability (the
  endpoint answers 401 from this host), `windows.sandbox`, `sandbox_mode` and
  the plugin set - the newer build fails under every variant, the older passes
  under none of them being needed.
  This is upstream, not ours, and nothing here works around it. It is recorded
  because it is the reason the panel is empty, because the conclusion was
  reached by measurement after two failed guesses, and because CU-20260922-046
  changes which of those two builds conPACT launches.
impact: none
verification: >
  A/B harnesses driven against both real binaries; method names extracted from
  the shipped executables rather than assumed. Full traces captured with
  RUST_LOG.
files: >
  none - diagnosis only
```

```yaml
id: CU-20260922-046
type: fix
title: "The real codex is chosen by recency, not by how its folder name happens to sort"
description: >
  Codex installs each build into a folder named by a content hash, and the
  resolver sorted those names and took the last one. A hash carries no order, so
  this picked whichever one sorted last. Measured on this machine on 2026-09-22:
  two builds were present, and the chosen one was 2026-09-18's, not the
  2026-09-19 build Codex had provisioned that morning. Two things follow, and
  both were real. The sidecar pins the real codex in a marker at install, so it
  would have gone on launching a superseded build indefinitely. And the
  superseded folder held a bare `codex.exe` where the current one ships three
  helper binaries beside it - the command runner, the code-mode host and the
  Windows sandbox setup - which codex resolves relative to its own location.
  `newest_install` replaces the sort: newest modification time wins, ties break
  on the name so the answer is stable, and a build that vanishes mid-scan (Codex
  prunes old ones) is skipped rather than allowed to lose the lookup. The first
  version of that guard wrapped only the `glob` call, which returns a lazy
  iterator - the error surfaced in the `for` loop and escaped. Its own test
  caught that, not review.
  The shim now runs what the desktop would have run without it, which is the
  only defensible answer: deliberately pinning an older build to dodge an
  upstream fault would be a workaround hidden inside a resolver.
impact: behaviour
verification: >
  Driven against the real installs on this machine: the resolver now returns the
  2026-09-19 build (with its helper binaries) where it previously returned the
  2026-09-18 one. Seven anchor tests, including the exact hash pair that bit
  ("cdef5aaf..." newer-sorting than "247581e4..." but a day older).
anchor: tests/regression/test_codex_build_is_chosen_by_recency.py
files: >
  src/conpact/codex_appserver.py,
  tests/regression/test_codex_build_is_chosen_by_recency.py (new)
```

```yaml
id: CU-20260922-045
type: fix
title: "The real codex no longer inherits CODEX_CLI_PATH pointing at the shim, and every byte of a reply is written"
description: >
  `CODEX_CLI_PATH` is how ChatGPT Desktop finds codex, and installing points it
  at the shim. The shim then started the real codex without touching its
  environment, so the child inherited that variable still naming the shim: a
  process that went looking for codex would have found the interposer and
  re-entered it. Codex spawns helpers of its own, so this was not hypothetical.
  `child_environment` hands the child the real path - what it would have seen had
  the shim never been installed.
  Separately, both pump directions used a bare `write`. `os.write` and an
  unbuffered file object may take fewer bytes than offered and report how many;
  discarding that count truncates the line, and a truncated JSON-RPC reply is
  not a slow reply but a broken one. `write_all` loops until the buffer is gone.
  Its first version treated a zero-byte write as success, which would have
  spun silently; it now reports failure.
  Neither fault was the account/usage failure they were found while chasing
  (CU-20260922-054 records what that actually was, correcting CU-20260922-047). They are fixed on their own
  merits, and the record says so rather than claiming a cure.
impact: behaviour
verification: >
  The end-to-end proof against a real app-server through the real shim passes
  9/9. Five new tests drive short writes, zero-byte writes and write failures in
  both directions.
anchor: tests/regression/test_codex_sidecar_is_cross_platform.py
files: >
  src/conpact/codex_sidecar.py, tests/test_codex_sidecar.py
```

```yaml
id: CU-20260922-044
type: change
title: "\"Big enough to be worth compacting\" is a fraction of the window wherever the app reports one"
description: >
  The idle notifier's minimum was an absolute token count. That is only
  meaningful against a window, and the two apps' windows are nothing like each
  other: ChatGPT Desktop's is 258,400 tokens, so the 300,000 an ordinary Claude
  session reaches silenced ChatGPT Desktop completely - including a session
  sitting at 94% full. The setting always meant "cheap to pick up again", and
  cheapness is relative to the window.
  `min_context_fill` (default 50%) is used wherever the app reports a window.
  Claude Code reports none - not in the transcript, not in the session record -
  so `min_context_tokens` remains the rule there. That is the answer for an app
  that does not say, not a fallback that will quietly stop being used.
  `parse` now also accepts the percent sign `describe` prints, so a value the
  window shows back can be typed in again.
impact: behaviour
verification: >
  Twelve anchor tests, including the 94%-full session the absolute minimum
  refused, both sides of each boundary, and a missing window not being read as a
  window of zero. The settings suite (115 tests) and the settings-window suite
  (33) pass with the new key and its new first position in the form.
anchor: tests/regression/test_context_threshold_travels_between_apps.py
files: >
  src/conpact/settings.py, src/conpact/idle_arming.py,
  src/conpact/codex_arming.py, tests/test_settings.py,
  tests/test_settings_window.py,
  tests/regression/test_context_threshold_travels_between_apps.py (new)
```

```yaml
id: CU-20260922-043
type: change
title: "The idle toast now watches ChatGPT Desktop sessions too, and the compaction engine finally has a caller"
description: >
  `codex_compact` had no caller anywhere in the package. Compaction of a live
  Codex session was verified twice against the real desktop (CU-20260922-038,
  CU-20260922-040) and could not be reached from the toast, the MCP tools or any
  command - it was an engine with nothing attached to it. Every module in the
  idle path held zero references to Codex. This connects the two.
  The hard part is that there is nothing to hook. Claude Code arms a watch at a
  turn end because it has a Stop hook; Codex's hook enum has no turn-end event
  at all (D-20260921-031). So `codex_arming` is a *sweep*: it looks at every
  session and asks the same questions `idle_arming` asks of one, and it is
  called from the Stop hook - the one moment conPACT is reliably running on a
  machine with both apps - and is also an entry point of its own
  (`python -m conpact.codex_arming`) for a machine that has only ChatGPT
  Desktop and therefore no hook whatsoever. A sweep is idempotent on purpose:
  re-arming a session that is already being watched would retire its watcher and
  restart the timer, so a session that never changed would never reach its
  toast.
  Only four things actually differ once a watch is armed, so only four are
  written twice: whether the session has been used since (read from the rollout,
  because a Codex session has no runtime record with a status), whether it can
  be reached (always - Remote Control is Claude's relay and has no part here),
  whether it is still idle at the moment of acting, and how it is compacted.
  Those are `watching.Platform`, which `idle_watch` now asks instead of calling
  `session_registry` directly. The stages, the mute, the hold, the toast, and the
  generation checks that retire a superseded watcher are shared rather than
  written twice.
  The cache lifetime had to be modelled rather than read, and the model is
  measured. Claude Code records the lifetime it bought
  (`ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`) and `cache_window`
  reads it; Codex records `cached_input_tokens` and never how long for. So 2,232
  consecutive API calls across 108 rollouts on this machine were grouped by the
  gap since the previous call and asked whether the later one hit the cache:
  100% up to 45 minutes, 75% at 45-60, and 69% past two hours. `codex_window.TTL`
  is one hour on that evidence, the numbers are in the module's docstring, and
  the toast says "should expire in about" rather than "expires in" so it never
  implies the figure came from the app.
  Two things were got wrong on the way and are worth recording. Codex writes a
  record's kind in two different places - `token_usage_record` carries `type` at
  the top level, `token_count` is an `event_msg` whose payload carries it - and
  reading only the payload found neither, so every real session reported "no
  window". And the first version of the adapter imported the watcher for its
  types while the watcher imported the adapter, which the module-structure check's `cycles` test
  caught immediately; `watching` now holds the two shared types so the
  dependency runs one way.
  The toast calls a Codex session a session, not a thread: it is ChatGPT
  Desktop's own session, and the user should not be taught a second word for it.
impact: behaviour, structure
verification: >
  Full suite passes; structure check 100.0/100 (the cycle it found is fixed, not
  argued with). The sweep was run against this machine's real sessions and every
  refusal was a real reason - spin-offs refused, compacted sessions below the
  minimum, large ones whose cache had genuinely expired hours ago. Arming,
  idempotence and re-arming after use were each driven directly.
  NOT yet observed live: a Codex toast on screen. That needs a large ChatGPT
  session used within the hour, and every session on this machine is older than
  its cache.
anchor: tests/regression/test_codex_idle_toast.py
files: >
  src/conpact/codex_window.py (new), src/conpact/codex_arming.py (new),
  src/conpact/codex_watching.py (new), src/conpact/watching.py (new),
  src/conpact/idle_watch.py, src/conpact/closure_hook.py,
  src/conpact/toast_text.py, tests/test_codex_window.py (new),
  tests/test_codex_arming.py (new), tests/test_codex_watching.py (new),
  tests/regression/test_codex_idle_toast.py (new), tests/test_idle_watch.py
```

---

```yaml
id: CU-20260922-042
type: change
title: "The MCP tools lose their redundant prefix: mcp__conpact__queue_compaction, not mcp__conpact__conpact_queue_compaction"
description: >
  Claude Code exposes an MCP tool as `mcp__<server>__<toolname>`, so a tool whose
  own name repeats the server's says it twice. The server is `conpact`; the tools
  are now `queue_compaction`, `cancel_compaction`, `compaction_status` and
  `hold_idle_toast`, which resolve as `mcp__conpact__queue_compaction` and its
  three siblings.
  The stutter predates the rename - it was `mcp__clautomatic__clautomatic_queue_compaction`
  - and was carried through CU-20260922-041 without being looked at. The maintainer
  spotted it. The evidence was in this session's own deferred-tool list the whole
  time.
  CU-20260922-041 is left saying `conpact_queue_compaction`, because that is what
  the tools were called when it was written and published; a change log that is
  edited to match the present is not a record. The decision entries are updated,
  because those are read before changing code and have to name what exists.
impact: behaviour
verification: >
  The server was started over stdio and asked for `tools/list`: it answers with
  the four unprefixed names and `serverInfo` `{"name": "conpact", "title":
  "conPACT"}`. Full suite passes.
anchor: tests/regression/test_mcp_queue.py
files: >
  src/conpact/mcp_tools.py, src/conpact/mcp_server.py, DECISIONS.md, README.md,
  docs/README.md, HANDOFF.md, tests/test_mcp_tools.py, tests/test_mcp_server.py,
  tests/regression/test_mcp_queue.py,
  tests/regression/test_closure_instructions.py,
  tests/regression/test_worktree_sessions_are_not_compacted.py
```

---

```yaml
id: CU-20260922-041
type: change
title: "Renamed to conPACT, and the repository made ready to hand to someone else"
description: >
  The tool is called **conPACT** now - CONtext comPACT - stylised that way in
  prose, `conpact` everywhere an identifier is needed. The rename is total
  rather than cosmetic: the package is `src/conpact/`, the MCP tools are
  `conpact_queue_compaction` and its three siblings, the environment variables
  are `CONPACT_CODEX_REAL` and `CONPACT_SIDECAR_DIR`, the macOS login agent is
  `com.conpact.codexcli`, the Linux drop-in is `10-conpact-codex.conf`, the id
  tag the sidecar injects is `conpact-<pid>-`, the state directory is
  `~/.claude/conpact/`, and the toast's brand line reads `conPACT`.
  One thing was nearly got wrong and is worth recording. The state directory was
  treated as transient - queued requests, idle state, the sidecar record, all of
  which regenerate - so the first plan was to let the new path simply start
  empty. It also holds `settings.json`, which is the user's own configuration and
  regenerates as defaults. The directory was copied across rather than renamed,
  and the old one left untouched, so nothing had to be trusted to be disposable.
  The Windows launcher was rebuilt and reinstalled in the same step, because it
  names the module it execs: an installed shim still pointing at
  `clautomatic.codex_sidecar` would have failed the moment ChatGPT Desktop next
  started codex, which is a broken app rather than a broken feature.
  Production readiness alongside it: `pyproject.toml` added so the package
  installs like any other, with five console entry points, no runtime
  dependencies at all (everything is stdlib, so there is no supply chain to
  audit), and `requires-python = ">=3.11"` - the version it is actually tested
  on, rather than the lower bound the syntax would allow. Build and test
  leftovers removed (`.coverage`, `.pytest_cache/`, `__pycache__/`, a stray
  `bash.exe.stackdump`) and the ignore rules cover the generated sidecar shim on
  every platform. No TODO, FIXME or debug print remains in the package.
impact: behaviour, structure
verification: >
  The full suite passes after the rename. The rebuilt shim was checked against
  the real codex through the installed path (`codex_sidecar.exe --version` ->
  `codex-cli 0.155.0-alpha.9`). `settings.json` was read back from the new state
  directory with its three values intact. Structure check re-measured.
anchor: tests/regression/test_codex_sidecar_is_cross_platform.py
files: >
  src/clautomatic/** -> src/conpact/** (git mv), src/sidecar/codex_launcher.c,
  pyproject.toml (new), README.md, DECISIONS.md, HANDOFF.md, docs/README.md,
  tools/**, tests/**, .gitignore
```

---

```yaml
id: CU-20260922-040
type: verification
title: "The rewritten sidecar compacted a live thread ChatGPT was holding: 177,573 -> 13,083 tokens, observed"
description: >
  CU-20260922-039 replaced the native interposer with one Python module and a
  launcher stub, so the live proof behind CU-20260922-038 no longer covered the
  shipped code. Re-done against the real desktop, on a different thread.
  ChatGPT Desktop was started and spawned the new chain exactly as designed:
  ChatGPT.exe 88672 -> codex_sidecar.exe 46252 (the native launcher, which holds
  no logic) -> python.exe 77548 (clautomatic.codex_sidecar) -> codex.exe 41512
  (the real app-server). The sidecar wrote a record in the new shape -
  `127.0.0.1:61263` with a capability token - and `codex_compact.compact` on the
  thread "a long-running review thread" returned compacted=True in 75.8s.
  `platforms.blocked` read `busy` before the call: the desktop held that thread's
  writer lock throughout, which is the whole point.
  The rollout is the proof, not the return value. `thread/compact/start` returns
  when the task is accepted, not when it finishes, so the first read of the
  rollout showed only `task_started` - the compaction was still running. It
  completed three and a half minutes later with a clean sequence and nothing
  else: task_started 03:56:23.757Z -> token_usage_record -> `compacted` at
  04:00:02.486Z replacing the history with 6 items -> token_count reading
  context 13,083 against a 258,400 window -> task_complete 04:00:03.246Z. No
  turn_aborted, no error. Clautomatic's own listing now reads the thread at
  13,083 (5%) against the 177,573 (69%) it read before, and the thread beside it
  that the desktop is also holding ("a second review thread", 100,238)
  is untouched - so the injection reached one thread and only the one asked for.
impact: none
verification: >
  Observed live, as described. Process chain read from Win32_Process; the record
  read from ~/.claude/clautomatic/codex-sidecar.json; the event sequence read
  from the thread's own rollout (159,152,534 bytes, tail only); the before and
  after context read through platforms.codex_session_of.
files: >
  (no code change - this records the live verification of CU-20260922-039)
```

---

```yaml
id: CU-20260922-039
type: change
title: "The sidecar is one Python module on all three platforms; installing it is one click and needs no compiler"
description: >
  Two requests, one answer. "Make the sidecar cross-platform" and "can it just
  be a Python script" turn out to be the same change, because the only reason
  the sidecar was C was that ChatGPT Desktop on Windows can spawn a real
  executable and nothing else - Node refuses a .cmd without a shell
  (CVE-2024-27980) and has never run a .py. That constraint applies to the file
  the desktop launches, not to the logic behind it. So the 530-line C
  interposer is gone, replaced by `clautomatic.codex_sidecar` (one module, every
  platform) plus `src/sidecar/codex_launcher.c`, a ~90-line stub whose whole job
  is to exec that module with the arguments it was handed. On macOS and Linux
  there is no native code at all: `install` generates a small shell script that
  execs the current interpreter, so a Mac with no Xcode installs in one click.
  The control channel changed with it. A named pipe and a Unix socket are two
  implementations; a loopback TCP port guarded by a capability token is one, and
  it is the boundary this project already uses for its own app-server
  (D-20260922-034). The sidecar binds 127.0.0.1 on a port the system picks,
  writes the token into its record, and closes any connection whose first line
  is not that token before a byte of it is forwarded (D-20260922-036).
  Four defects were found and fixed on the way, three of which had shipped:
  `codex_inject` imported `ctypes.wintypes` at module scope, so importing it -
  and therefore Codex compaction at all - was impossible off Windows, and no
  test caught it because every test runs on Windows; the sidecar's record was
  written with only its last folder created, so on a machine with ChatGPT
  Desktop and no Claude the record was silently never written; `install` wrote
  what the Windows launcher needs only when the shim was missing, so
  reinstalling after Python moved left a shim that could not start; and the
  macOS login agent was hand-written XML, which an `&` in a path would have made
  unreadable (it is `plistlib` now, and the per-key merge means clearing one
  variable no longer discards another).
  Installing and uninstalling are each one click: `codex_sidecar_window` offers
  exactly the action that applies, does the build, the marker and the
  environment behind it, and says what happened. `tools/install-sidecar.cmd` and
  `tools/install-sidecar.sh` open it.
impact: behaviour, structure
verification: >
  1715 tests pass. The end-to-end proof runs the real built exe the way the
  desktop would - shim -> launcher.txt -> Python -> fake app-server - and checks
  nine things, all PASS: the record is written; the desktop's requests are
  answered through the shim; an injected resume+compact comes back tagged; the
  desktop's later traffic still flows; the desktop never sees a reply to an id
  it did not send; it still sees the app-server's notifications; and an
  unauthenticated client's request never reaches the app-server. Passthrough was
  verified against the real codex (`codex_sidecar.exe --version` ->
  `codex-cli 0.155.0-alpha.9`, identical to the real binary). Either app alone
  was measured rather than argued: with no `~/.claude` at all, `installed()`
  reports `['codex']` and lists 5 threads; with no `~/.codex`, `['claude']` and
  10 sessions; with neither, `[]` and no error. Structure check 100.0/100.
anchor: tests/regression/test_codex_sidecar_is_cross_platform.py
files: >
  src/clautomatic/codex_sidecar.py (new), src/clautomatic/codex_env.py (new),
  src/clautomatic/codex_sidecar_window.py (new),
  src/sidecar/codex_launcher.c (new, replaces codex_sidecar.c),
  src/clautomatic/codex_inject.py, src/clautomatic/codex_sidecar_install.py,
  src/sidecar/build.cmd, tools/codex_sidecar.py,
  tools/install-sidecar.cmd (new), tools/install-sidecar.sh (new),
  tests/test_codex_sidecar.py (new), tests/test_codex_env.py (new),
  tests/test_codex_sidecar_window.py (new),
  tests/test_codex_sidecar_install.py, tests/test_codex_inject.py,
  tests/conftest.py,
  tests/regression/test_codex_sidecar_is_cross_platform.py (new)
```

---

```yaml
id: CU-20260922-038
type: verification
title: "The sidecar compacted a live thread ChatGPT Desktop was holding: 91,485 -> 11,956 tokens, observed"
description: >
  The step CU-20260922-037 left open is done, against the real desktop. After a
  one-time ChatGPT restart the desktop spawned the shim as its app-server
  (ChatGPT.exe 53016 -> codex_sidecar.exe 23796 -> codex.exe 78792), and
  `codex_compact.compact` on the thread "a long-running build thread" -
  busy=True, the desktop holding its writer lock - routed through the injector
  and returned compacted=True. The rollout is the proof, not the return value: a
  clean `task_started -> compacted -> task_complete` (turn 01a0c6e3), the
  `compacted` event replacing 27 history items with a summary, and the following
  `token_count` reading context 11,956 against the pre-compaction 91,485. No
  `turn_aborted`, no error.
  The desktop UI showed a brief "Reconnecting" and a "stream disconnected before
  completion" while the compaction replaced the thread's history under its open
  websocket; the app-server logged `task_complete`, so it was the client
  catching up to a history swap, not lost work. The sidecar and all ChatGPT
  processes were intact afterwards. This is the case D-20260921-031 had refused
  and this work set out to reach: compaction of the session actually being used.
impact: none
affected_modules: []
related_tests:
  - "tests/test_codex_inject.py"
commit_ref: "feature/codex-remote-control"
author: "Claude Opus 4.8 (agent)"
timestamp: "2026-09-22T02:16:00Z"
```

---

```yaml
id: CU-20260922-037
type: feature
title: "A sidecar shim reaches the live thread - the one ChatGPT Desktop is holding - by standing in its app-server's stdin"
description: >
  Compaction is for the session you are working in. Targeting only threads no
  app holds was not that, and the earlier refusal of a busy thread made the
  feature useless for its actual purpose: the busy thread IS the live thread. A
  Codex rollout may only be written by the app-server holding its per-thread
  lock, and for a live thread that is the desktop's own app-server - a stdio
  child with no socket. The one supported way into that process is to be the
  executable the desktop launches, and its resolver takes CODEX_CLI_PATH ahead
  of the bundled binary (measured from the app's own `Sq()`).
  `codex_sidecar.c` is that executable: a small native shim (clang, no runtime
  deps) that execs the real codex with the arguments it was handed and proxies
  both pipes faithfully. It adds one named pipe on which Clautomatic submits a
  JSON-RPC request; what it injects carries a per-process id tag, and the tagged
  reply is lifted out of the stream before the desktop sees it, so the desktop
  never receives a response to an id it did not send. Everything else is copied
  byte for byte, the child is handed the desktop's own stderr, and anything that
  is not the desktop's stdio app-server (a `--listen` server of ours, `proxy`,
  `daemon`) is run untouched.
  `codex_inject` is the client: it reads the shim's record, opens the pipe,
  sends `thread/compact/start` for the live thread (no initialize, no resume -
  the desktop already did both and the thread is loaded, which is why it is
  locked), and lifts back its own reply. `codex_compact.compact` now routes a
  `busy` thread through it, and falls back to the old refusal when no shim is
  installed - an archived or spin-off thread is still never touched.
  `codex_sidecar_install` puts the shim in the desktop's path and takes it out:
  it names the real codex in a marker beside the shim, sets CODEX_CLI_PATH in the
  user's own environment (HKCU only, one key), and the desktop is restarted by
  the user to pick it up. `codex_appserver.codex_cli` resolves through that
  marker, so Clautomatic's own tooling always reaches the real codex and never
  the shim, even with the global env var set. Uninstall clears all three and
  leaves a CODEX_CLI_PATH the user set themselves alone.
  This is, honestly, an interposer: it inserts Clautomatic into another app's
  process path and injects commands that app did not originate. The maintainer asked for
  it explicitly, twice, for his own machine and account, after that shape was
  spelled out. It is reversible, fails open at every step (no shim, a stale
  record, a pipe that will not open, a reply that never comes - each is "fall
  back", never a crash), and reads only its own tagged replies so it cannot
  disturb the desktop's traffic.
  Not yet verified live: the shim exe was not compiled in-session (the compile
  and the tests that touch the CODEX_CLI_PATH persistence path are refused by the
  harness's own auto-mode classifier, which is correct to flag a persistence
  surface). The C, the injector, the installer and the routing are written and
  unit-tested where the classifier allows; building and the end-to-end run are a
  step the maintainer takes with `src/sidecar/build.cmd` and `tools/codex_sidecar.py
  install`. Until then this claim is design-complete, not observed.
impact: high
affected_modules:
  - "src/sidecar/codex_sidecar.c"
  - "src/sidecar/build.cmd"
  - "src/clautomatic/codex_inject.py"
  - "src/clautomatic/codex_sidecar_install.py"
  - "src/clautomatic/codex_compact.py"
  - "src/clautomatic/codex_appserver.py"
  - "tools/codex_sidecar.py"
  - "tests/conftest.py"
related_tests:
  - "tests/test_codex_inject.py"
  - "tests/test_codex_sidecar_install.py"
  - "tests/test_codex_compact.py"
commit_ref: "feature/codex-remote-control"
author: "Claude Opus 4.8 (agent)"
timestamp: "2026-09-22T02:00:00Z"
```

---

```yaml
id: CU-20260922-036
type: feature
title: "Codex remote control runs on an app-server of our own, not on a daemon that will not start here"
description: >
  The first cut of this feature drove Codex's shared local daemon. It cannot
  work on this machine and the reason is structural, not a misconfiguration: the
  daemon runs only from a *packaged* CLI (one whose folder carries
  `codex-package.json`), the copy ChatGPT Desktop installs is not one, and
  `codex app-server daemon bootstrap` refuses for the same reason, so it cannot
  even install its own prerequisite. Its control socket is AF_UNIX besides,
  which Python on Windows cannot open at all.
  A plain `codex app-server --listen ws://127.0.0.1:<port>` has neither problem.
  It starts from the CLI that is already here, serves `/readyz` and a WebSocket
  on `/rpc`, and outlives the process that started it, so a command now and a
  toast click an hour later reach the same server. Clautomatic runs one of those
  and offers *that* for remote control, which is the honest shape of the feature
  anyway: on Codex the thing that is offered is an app-server, not a session.
  `codex_ws` is the client for it - RFC 6455 in the stdlib, text frames, client
  masking, continuation frames and a pong for every ping - and refuses anything
  else on the wire rather than guessing. `codex_host` owns the process: it mints
  a token, gives the app-server only its SHA-256 (`--ws-auth capability-token
  --ws-token-sha256`), binds loopback, records port and pid under
  `~/.claude/clautomatic/`, waits for `/readyz`, and signals only a pid it wrote
  down itself. Measured: without the token every upgrade is refused with 401, on
  loopback as well as off it, so the listener is not an open door for anything
  else running as this user.
  With the daemon gone, so is the CLI: `remoteControl/{enable,disable,
  pairing/start,pairing/status,client/list,client/revoke,status/read}` are all
  app-server methods, so every action is now one call on our own server and
  `codex_remote` runs no subprocess at all beyond starting it.
  One report was wrong and is corrected: whether remote control is *on* was read
  from the enrolment row in Codex's state store, which belongs to the desktop's
  app-server rather than ours. `show` therefore said "ready - this machine can be
  driven remotely" while our own server was answering `status: disabled`. It now
  asks the server it is talking about, and a server that is up but will not
  answer counts as not offering rather than falling back to the row.
  Verified against the real machine end to end: started detached on a
  token-protected loopback port, `show` read it back, `remoteControl/status/read`
  and `remoteControl/client/list` answered over the WebSocket - the latter
  returning a real paired device - and `stop` shut it down with no leftover
  process. `enable` is deliberately not exercised here: it enrols a server on the
  user's ChatGPT account, which is theirs to switch on.
impact: high
affected_modules:
  - "src/clautomatic/codex_ws.py"
  - "src/clautomatic/codex_host.py"
  - "src/clautomatic/codex_remote.py"
  - "src/clautomatic/codex_remote_cli.py"
  - "src/clautomatic/codex_appserver.py"
  - "tests/conftest.py"
related_tests:
  - "tests/regression/test_codex_remote_control_is_host_side_only.py"
  - "tests/test_codex_ws.py"
  - "tests/test_codex_host.py"
  - "tests/test_codex_remote.py"
  - "tests/test_codex_remote_cli.py"
commit_ref: "feature/codex-remote-control"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-22T00:00:00Z"
```

---

```yaml
id: CU-20260921-035
type: feature
title: "Codex's own Remote Control is read, acted on only when asked, and its two closed doors are now named rather than retried"
description: >
  Parity with Claude's Remote Control, against the half of Codex's relay that is
  actually open. The desktop's `codex.exe` carries the whole feature: a CLI
  (`remote-control start|stop|pair`, `app-server daemon
  start|stop|version|enable-remote-control|disable-remote-control|bootstrap`,
  `app-server proxy`), the app-server methods `remoteControl/{enable,disable,
  status/read,pairing/start,pairing/status,client/list,client/revoke}`, and the
  backend's `wham/remote/control/server/{enroll,refresh,pair,pair/status}`. All
  of it is the **server** half - this machine offering itself for control. The
  client half, which is what would reach a thread the running app holds, is a
  device-keyed enrolment behind a step-up authorisation (D-20260921-032), and
  none of it is implemented here.
  `codex_appserver` is the transport both Codex features now share: the JSON-RPC
  client, the executable lookup, and the two argv that select a transport -
  `app-server` for a server of our own, `app-server proxy` for the shared local
  daemon's control socket, which Python on Windows cannot open directly.
  `connect` completes the handshake and shuts the process down before the error
  leaves, rather than leaking one per refused attempt.
  `codex_remote` is the feature: the enrolment read `mode=ro` from Codex's own
  state store, the daemon probe, one status shape saying what this machine still
  needs, and the actions behind it. `codex_remote_cli` and
  `tools/codex_remote.py` are the surface (`show` reads; every other command is
  the action just typed), and `tools/codex_sessions.py --remote` prints the same
  block beside the session listing.
  Two things are measured rather than assumed, and both are refusals with a name
  rather than something to retry. (1) The desktop app never shares this daemon on
  Windows: its own launcher takes the control socket only when
  `process.platform !== "win32"` (and only with
  `CODEX_APP_SERVER_USE_LOCAL_DAEMON=1`, no `CODEX_CLI_PATH`, a null
  `codex_cli_command`, and a daemon whose version it accepts), so a daemon we
  start is ours alone and D-20260921-031's refusal of a held thread stands, now
  for a named reason instead of an observation. (2) Only the `remote-control`
  subcommands accept `--json`; the `app-server daemon` ones reject it outright,
  which the first real run found after the code had assumed otherwise. A third
  was found the same way: the daemon runs only from a *packaged* CLI, one whose
  folder carries `codex-package.json`. The copy ChatGPT Desktop installs does
  not, so every action on this machine is currently blocked behind
  `codex app-server daemon bootstrap` - reported as `no_package`, read from the
  manifest beside the executable rather than by running `start` and watching it
  fail.
  Three more came from asking a real app-server, which is the only reason they
  are right: the handshake has to declare `capabilities: {experimentalApi:
  true}` or `remoteControl/status/read` answers "requires experimentalApi
  capability"; `client/list` and `client/revoke` are scoped to an
  `environmentId` and are otherwise refused with "missing field"; and the list
  takes a `limit` the server holds between 1 and 100. The environment is asked
  of the server being talked to - it reports its own - and falls back to the
  enrolment row for a daemon that has not settled one, which is why
  `environment_id` is now read from the state store while `account_id` and
  `server_id` still are not. All three calls share one connection, so listing
  the clients starts one app-server rather than two.
  Both spawn defaults are `None` and resolved at call time, so the conftest
  guards that stand for "no test starts an app-server or runs the real CLI"
  actually bite; a default bound at import sailed straight past them.
impact: high
affected_modules:
  - "src/clautomatic/codex_appserver.py"
  - "src/clautomatic/codex_remote.py"
  - "src/clautomatic/codex_remote_cli.py"
  - "src/clautomatic/codex_compact.py"
  - "tools/codex_remote.py"
  - "tools/codex_sessions.py"
  - "tests/conftest.py"
related_tests:
  - "tests/regression/test_codex_remote_control_is_host_side_only.py"
  - "tests/test_codex_remote.py"
  - "tests/test_codex_remote_cli.py"
  - "tests/test_codex_appserver.py"
commit_ref: "feature/codex-remote-control"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-21T23:00:00Z"
```

---

```yaml
id: CU-20260921-034
type: fix
title: "The Codex wire protocol was asserted against its own constants, so renaming any of it passed - and two constants were dead"
description: >
  A mutation run over the five new modules scored platforms 62.7% and
  codex_compact 73.6%, and the survivors named one cause: every test compared a
  method name against the module's own constant
  (`process.sent[2]["method"] == codex_compact.COMPACT`), which passes whatever
  that constant is renamed to. `initialize`, `thread/resume`,
  `thread/compact/start` and the `app-server` subcommand are a contract with
  someone else's binary, and none of them was protected. This repo already
  recorded that defect once (b7db9b1); this is the same mistake made again in
  new code, and only mutation testing found it.
  Those strings, the platform names, the four blocking reasons, the turn states
  and the rollout markers are now asserted as literals beside the readable
  constant-based assertions. Checked by hand-applying the mutants: renaming
  COMPACT, deleting the stdin flush and flipping the reader thread off daemon
  each now fail a test - the flush one by hitting the real 60-second request
  timeout, which is the production symptom of a request that never arrives.
  The run also found dead code that review had not: `codex_threads.USER` is
  never referenced, and `codex_threads.REFUSAL` is shadowed at every call site
  by `spin_off.REFUSAL`, because `platforms.REASONS` ended up carrying that
  wording. Both removed.
impact: tooling
affected_modules:
  - "src/clautomatic/codex_threads.py"
related_tests:
  - "tests/test_codex_compact.py"
  - "tests/test_platforms.py"
  - "tests/test_codex_threads.py"
  - "tests/test_codex_meter.py"
commit_ref: "feature/codex-platform"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-21T08:15:00Z"
```

---

```yaml
id: CU-20260921-031
type: feature
title: "ChatGPT Desktop (Codex) is a second platform: its threads are read, measured and guarded like Claude Code's, and a thread no app holds can be compacted"
description: >
  Clautomatic could see Claude Code and nothing else. ChatGPT Desktop keeps the
  same four things under a different roof, and all four now have a module:
  `codex_home` locates its state and opens every database `mode=ro`, so a
  mistake here cannot become a write into a running app's store;
  `codex_threads` reads the thread rows and classifies them; `codex_meter`
  measures a thread from its JSONL rollout; `codex_compact` compacts one.
  `platforms` gives both apps one shape, so anything that only wants to look
  asks once instead of branching. Nothing binds or sends through it: D-005 and
  D-012 stay on each platform's own modules.
  The guards map across cleanly. `thread_source` separates a real user thread
  from the ones Codex spawns for itself - subagents and the guardian review it
  runs after a turn - which are the counterpart of a `.claude/worktrees/`
  checkout (D-028) and are 72 of this machine's 105 threads. `archived` is a
  column. Both fail open on a value we do not recognise.
  What does not map is the sending. Codex has no Stop hook (no turn-end event in
  its hook enum, and its one `notify` slot already holds
  `codex-computer-use.exe`), no `/compact` command, and no bridge. Compaction is
  the JSON-RPC method `thread/compact/start`, and the desktop app serves it from
  an app-server that is a stdio child of ChatGPT.exe with no socket - so a
  thread the app holds cannot be reached from outside at all. Its own UI guards
  the same call with `getStreamRole(threadId).role === "owner"`.
  So `codex_compact` uses that ownership rule rather than fighting it: a thread
  no app holds is compacted by starting our own app-server, resuming it and
  calling the method there, and Codex's per-thread writer lock is what makes
  that safe. Every other thread is refused with a named reason and left exactly
  as it was; a refused thread never reaches a subprocess.
  Turn ends come from the rollout instead of a hook: Codex writes `task_started`
  and `task_complete` into the same file it writes usage into.
impact: behaviour
affected_modules:
  - "src/clautomatic/codex_home.py"
  - "src/clautomatic/codex_threads.py"
  - "src/clautomatic/codex_meter.py"
  - "src/clautomatic/codex_compact.py"
  - "src/clautomatic/platforms.py"
  - "tools/codex_sessions.py"
  - "tests/conftest.py"
related_tests:
  - "tests/regression/test_codex_guards_are_measured_not_assumed.py"
  - "tests/test_codex_home.py"
  - "tests/test_codex_threads.py"
  - "tests/test_codex_meter.py"
  - "tests/test_codex_compact.py"
  - "tests/test_platforms.py"
commit_ref: "feature/codex-platform"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-21T06:30:00Z"
```

**Verification evidence (read against the live ~/.codex, 105 threads):**

- Classification: 55 `guardian_review`, 28 `user`, 17 `subagent`, 5 with the
  column empty (predating it) - 72 refused as spin-offs, 1 archived.
- Measurement on the live thread: 177,573 tokens of a 258,400 window (69%),
  read from a 158 MB rollout in 0.02 s; every thread measured in under 0.13 s.
- The lock guard named the three threads a running Codex was holding, and
  `tools/codex_sessions.py` showed that thread as `busy` beside nine Claude
  sessions in one listing.

---

```yaml
id: CU-20260921-032
type: fix
title: "A thread Codex holds open was reported as free to write to: its lock is a byte range, which opening the file cannot see"
description: >
  The first `codex_threads.is_loaded` tested the writer lock by opening the lock
  file, on the reasoning that a held file refuses to open. Measured against the
  live app, all four locks Codex was holding opened without error in both "r+b"
  and "ab", and the guard reported every live thread as safe to write to - the
  exact opposite of its purpose, and the one error in this module that could
  corrupt a user's rollout rather than merely skip a compaction.
  Codex takes a byte-range lock (LockFileEx), which leaves the file freely
  openable. `msvcrt.locking(..., LK_NBLCK, 1)` sees it; nothing else does. The
  guard now takes the lock to test it and gives it straight back, and closing
  the handle releases it even if the explicit unlock fails, so the window cannot
  outlive the call.
  It also fails closed in every direction: an id that is not a plain name, a
  platform with no `msvcrt`, and any unexpected error all read as "held". A
  wrong "held" costs one skipped compaction; a wrong "free" costs the rollout.
  The regression test holds a real lock from a second handle and was checked by
  restoring the `open()` version and watching it fail.
impact: behaviour
affected_modules:
  - "src/clautomatic/codex_threads.py"
related_tests:
  - "tests/regression/test_codex_guards_are_measured_not_assumed.py"
commit_ref: "feature/codex-platform"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-21T06:30:00Z"
```

---

```yaml
id: CU-20260921-030
type: fix
title: "The mutation tester's timeout retry had never once run: 92 of 93 timeouts stopped dead at the first limit, and ui_style read 42.7% instead of 97.4%"
description: >
  CU-20260920-027 stopped counting a timeout as a kill and added a retry: a
  timed-out mutant is re-run against its own module's tests at a 300-second
  limit, because a mutant on a module-level constant is covered by the whole
  suite, which is what pushes it past the limit in the first place. The retry
  was right about the cause and never reached it.
  `_own_tests` picked the module's own test file out of the tests coverage said
  covered the line. But a line executed only at import has no per-test coverage
  context at all, so `line_to_tests` maps it to the whole directory - the single
  entry `["tests"]`, which names no test file. `_own_tests` returned nothing,
  `if own:` was false, and the outcome stayed "timeout". Every mutant the retry
  was written for was precisely the kind it could not act on.
  Measured, not assumed: of 93 timeouts in the run over the four modules changed
  by CU-20260920-028, 92 finished in 121 seconds - the first limit, with no
  second run after it - and one took 428, the only one whose line had real
  coverage contexts. The mutants are exactly what the docstring predicted:
  `toast_text.py:19 BRAND`, `:20 MAX_NAME`, `:21 SETTINGS_LINK`, the `_ACTIONS`
  entries, and `ui_style`'s palettes.
  The fix asks for the module's own test file by name when no context named it,
  which is the case the retry exists for. The scores this corrects are
  understatements, not regressions - the affected mutants had no verdict at all.
impact: tooling
affected_modules:
  - "tools/mutate.py"
related_tests:
  - "tests/regression/test_timeout_is_not_detection.py"
commit_ref: "phase/idle-defer-to-expiry"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-21T02:05:00Z"
```

---

```yaml
id: CU-20260921-029
type: feature
title: "A session working in a .claude/worktrees/ checkout is refused a compaction, and the refusal is one setting away from off"
description: >
  The desktop app makes a worktree checkout under `.claude/worktrees/` for a
  session started from a suggestion card, a task chip, or an agent run isolated
  in a worktree. The maintainer merges those and archives them, so they are never
  resumed and the summary a compaction writes there is never read: queuing one
  spends a turn and a compaction on nothing.
  b7db9b1 told agents so in `mcp_server.INSTRUCTIONS`. This is the same rule in
  code, for when the instructions are not followed:
  `clautomatic_queue_compaction` reads the bound session record's `cwd` and
  answers `queued: false` without writing a request when it is inside such a
  checkout. It is a refusal, not a failure - `isError` stays false and the text
  says there is nothing to retry - because a tool that worked and said no is not
  a tool that broke.
  It fails open. A record with no `cwd`, an unreadable one, and a path that only
  looks similar all queue as before; the two names must be adjacent, in that
  order, with a checkout name after them, so `.claude/worktrees` itself (the
  folder that holds them) is not matched. A desktop scratch workspace under
  `AppData/Roaming/Claude/scratch-workspaces/` is deliberately out of scope:
  The maintainer talks in those, so their summaries do get read.
  The new setting `guard_spin_off_sessions` (default on) turns the refusal off,
  so it never becomes unappealable. Adding it needed the settings window's single
  on/off toggle to become one per on/off setting - `Form.on` is now a dict keyed
  by setting, and `SettingsView.toggle_buttons` likewise, with each button's
  click carrying its own key. The settings command needed no change; it already
  read `settings.SETTINGS` generically.
impact: behaviour
affected_modules:
  - "src/clautomatic/spin_off.py"
  - "src/clautomatic/mcp_tools.py"
  - "src/clautomatic/mcp_server.py"
  - "src/clautomatic/settings.py"
  - "src/clautomatic/settings_window.py"
related_tests:
  - "tests/regression/test_worktree_sessions_are_not_compacted.py"
  - "tests/test_spin_off.py"
  - "tests/test_mcp_tools.py"
  - "tests/test_settings.py"
  - "tests/test_settings_window.py"
commit_ref: "phase/idle-defer-to-expiry"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-21T02:00:00Z"
```

---

```yaml
id: CU-20260920-028
type: feature
title: "The early idle toast can hand its compaction to the stage before the cache expires, once or from now on - and the button row no longer runs off the card"
description: >
  Seeing the early toast while a build or a test suite is still running, the
  answer is usually "not yet, but do it before the cache goes cold". There was no
  way to say that: the choices were compact now, auto-compact from now on, or
  dismiss and be asked again later. The early toast now offers two more.
  "Near expiry" defers this idle's compaction to the stage before the prompt
  cache expires, which then acts without asking again; "Always near expiry"
  writes the per-session switch so every later idle does the same. Both are
  offered only on the early stage, which is the only one with a later stage to
  hand the work to (idle_arming.stages always appends the expiry stage and only
  adds an early one strictly before it).
  A deferral is deliberately not written to disk: it lives in the watcher
  process, so using the session ends the watcher and the deferral with it, and
  the next Stop arms a fresh watch. The standing switch does persist, which is
  what distinguishes the two. Neither sends anything when clicked, and the later
  stage re-checks for activity before it sends - the existing wait_for /
  bind_idle(strict) path, not a second mechanism. The notice shown after a
  one-off deferral no longer offers "Turn off auto-compact", because that
  deferral set no switch to turn off.
  Measured while fitting the fourth choice in: the button row was already wider
  than the card. "Not now" was being shown 37px wide of the 74px it asked for on
  the expiry toast and 19px short with no stage - half the dismiss button was
  clipped off the card on the toast a user actually saw, and nothing measured it.
  The two long labels are now short enough to fit ("Always compact",
  "Always near expiry"), and the early toast, which has four choices, puts its
  two standing ones on a second line as links rather than trying to fit a fourth
  button. `python -m clautomatic.toast_view --demo early` shows it.
impact: behaviour
affected_modules:
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/toast_text.py"
  - "src/clautomatic/toast_view.py"
  - "src/clautomatic/ui_style.py"
related_tests:
  - "tests/regression/test_toast_buttons_fit_the_card.py"
  - "tests/test_idle_watch.py"
  - "tests/test_toast_text.py"
  - "tests/test_toast_view.py"
commit_ref: "phase/idle-defer-to-expiry"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T23:55:00Z"
```

---

```yaml
id: CU-20260920-027
type: fix
title: "A timeout was never a detection: the mutation tester said so, 8 survivors were hiding behind it, and one of them silently disabled the Settings link"
description: >
  `tools/mutate.py` counted a mutant whose test run hit the 120-second limit as
  killed. It is not: a timeout says the run did not finish, not that a test
  failed - and it lands exactly where it hides most, because a mutant on a
  module-level constant is covered by the whole suite, which is what pushes it
  past the limit. A parallel session re-ran one such mutant and found a survivor;
  all 39 behind the two UI passes and the settings window were then re-run, one
  at a time, against their own module's tests. Eight were real survivors, so the
  published 98.0% and 97.6% had really been 97.0% and 95.2%. The tool now re-asks
  a timed-out mutant of its own module's tests at a 300-second limit, counts only
  `killed` towards a score, and lists an unsettled timeout with the survivors.
  Two of the eight were assertions of this repo's own that computed their
  expectation from the constant under test, so a mutant moved both sides and
  passed; both are now literal. Two more were the `__main__` guards of modules
  the code spawns as `python -m` - `settings_window`, which a toast's Settings
  link starts, and `toast_view`, the documented demo - written off as "run only
  in subprocesses". `idle_watch`, which every armed session spawns, had the same
  gap recorded as "uncovered by design"; it is tested too, and that module is now
  at 100% line and branch coverage. Tests that drive a Tk main loop carry a
  five-second watchdog, so a mutant that deletes the `show()` call which would
  have ended the loop fails in seconds instead of hanging. No source outside
  `tools/` changed.
impact: internal
affected_modules:
  - "tools/mutate.py"
related_tests:
  - "tests/regression/test_timeout_is_not_detection.py"
  - "tests/test_toast_view.py"
  - "tests/test_settings_window.py"
  - "tests/test_idle_watch.py"
commit_ref: "feature/timeout-detection-audit"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T21:20:00Z"
```

**Verification evidence:**

- All **39** timeouts re-run against their own module's tests, restoring from a
  `cp` backup each time: **31 really detected, 8 survivors** - `toast_view` 91
  `pad=(6, 0)->(6, 1)`, 131 `pad=(12, 6)` twice, 337 the `__main__` guard;
  `settings_window` 25 `parents[1]`, 26 `WIDTH = 460`, 137 `pad=(12, 6)` twice.
- Seven of the eight are now killed, each **hand-verified one mutant at a time**
  (7 of 7 killed, and the eighth survived as predicted). The eighth is provably
  equivalent, not a gap: `px()` clamps with `max(1, round(...))`, so `px(0)` and
  `px(1)` are the same pixel and `pad=(6, 0)` and `pad=(6, 1)` build the same
  widget. The assertion there is now a literal `1` with that reason written next
  to it, rather than `px(0)`, which restated the mutation.
- Two mutants that previously only *hung* their module's tests now fail in about
  a second, checked by hand: `toast_view:269` and `settings_window:229`, both
  `view.show(...)` deleted. One timeout is left and is recorded as unresolved:
  inverting `settings_window`'s `__main__` guard makes importing the module open
  the window and sit in its main loop, so the suite hangs at collection - nothing
  passes, but no measurement finishes either.
- Both modules' previously "uncovered" mutant was `sys.exit(main())`; each is now
  killed (hand-checked), so both modules end with no uncovered mutants.
- Scores, all timeout-free: `desktop` **100.0%** (73/73), `toast_view` **97.7%**
  (378/387), together **98.0%** (451/460); `settings_window` **97.6%** (243/249,
  one unresolved timeout). The headline figures are where they were - the
  difference is that they are now finished measurements rather than partly an
  assumption.
- 1,090 passed, 1 skipped. Branch coverage **99%** (2,411 statements, 9 missed,
  down from 12; 680 branches, 6 partial). `idle_watch` reached **100%**, and the
  nine left are four `__main__` guards nothing spawns in-process, `detach`'s
  `return False` for a handle Windows declines, and the two defensive
  `except tk.TclError` blocks. `-m "not real_ui"` gives 1,085 passed and the
  identical 99%, the same nine lines. Structure check **100.0/100**.
- The tool's own change is anchored by
  `tests/regression/test_timeout_is_not_detection.py`: the scoring function,
  the narrowing of a timed-out mutant to its module's tests, and the limit
  enforced against a test that really does hang.

---

```yaml
id: CU-20260920-026
type: test
title: "The settings window's layout and its run() are measured too: 78.3% to 97.6%, and the last claim that Tk geometry is unassertable is gone"
description: >
  CU-025 disproved this repo's written claim that Tk geometry mutants are ones
  "no assertion can see", but left the module that claim was actually about
  unmeasured. This measures it. The baseline was 78.3% (195/249) with 54
  undetected, and they fell into the same two groups the toast's had: 36 in
  `_build` and `_row` - the paddings, font sizes, the accent stripe's width, the
  entry's width, its inner padding and its focus ring, and the `style == "ghost"`
  that decides which side each button packs to - and 9 in `run()`, which was
  proved only by the on-screen test, and that runs in a subprocess where no
  coverage is collected. Three more were `lift()`, `focus_force()` and the
  cursor going into the first box, each deletable with every test still passing,
  and two were the near corners of the work-area fallback, which this window uses
  all four of (the toast discards two). The layout is now read back out of Tk the
  way D-024 sets out, and `run()` is called in-process behind a new
  `real_settings_run` marker with `show()` stubbed, so no window is mapped and
  nothing takes the keyboard from whatever the user is doing. No source changed.
impact: none
affected_modules: []
related_tests:
  - "tests/test_settings_window.py"
  - "tests/tk_reading.py"
  - "tests/conftest.py"
commit_ref: "feature/settings-window-mutation"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T14:05:00Z"
```

**Verification evidence:**

- Measured: **78.3% (195/249) -> 97.6% (243/249)**, the re-run seeded with the
  195 rows already settled so only the 54 undetected ran again.
- 44 mutants hand-applied one at a time before the run, each restored from a
  `cp` backup. Two of those checks were wrong and were fixed, not explained away:
  the first centring test computed its expectation from `winfo_screenwidth()`,
  so a mutated corner moved both sides of the assertion equally and survived - it
  now pins the screen size to gaps divisible by neither 2 nor 3, and both corners
  die; and a test written for `entry.delete(0, "end")` killed nothing, because
  existing tests already covered that line, so it was removed rather than kept.
- Line coverage of the module went **93% -> 98%** (13 statements missed -> 3),
  and repo-wide missed lines 22 -> 12. 1,082 passed. Structure check 100.0/100.
- The six survivors left were each confirmed by hand, not assumed. Four are
  equivalent for two reasons worth recording. Three of them - the status text,
  the toggle's "On" and every error line's text - are literals `_build` passes
  that `refresh()`, called from the constructor, overwrites before anything is
  on screen; they can never reach a user. The fourth is `insert(0, ...)` into a
  box `delete(0, "end")` has just emptied, where index 1 clamps back to 0. The
  fifth is deleting `root.update_idletasks()` from `show()`, the same equivalence
  `toast_view` showed: Tk computes a window's requested size synchronously as
  widgets are packed. The sixth is `sys.exit(main())` under `__main__` -
  **corrected by CU-20260920-027**: that is the entry point a toast's Settings
  link spawns, it is neither equivalent nor unreachable, and it is killed now.

---

```yaml
id: CU-20260920-025
type: test
title: "The toast's layout is read back out of Tk instead of being called unprovable, and the two UI modules go from below the standard to 100% and 97.7%"
description: >
  CU-024 made `toast_view` and `desktop` reachable by a mutation run; this is the
  run, and what reading its survivors found. The measured jump was 60.3 to 97.3
  for `desktop` and 53.5 to 76.0 for `toast_view` - both past the 60% mutation standard
  - but 94 mutants still survived, and they were not the equivalents this repo
  had assumed. Five were behaviour: `tick()` failing to book its own next tick
  (the countdown, the progress bar and the polling all stop for good and the
  card sits showing a time that never moves), `_fill(1.0)` and `bar.coords(...)`
  deleted (the bar never moves while a compaction runs), `span or 1` losing the
  guard that keeps a spanless model from dividing by zero, the worker thread
  losing `daemon=True` (a stuck bridge call would hold the process open), and
  `act_into`'s `"error"` state, the only thing between an exception on a worker
  thread and a toast that waits for a result which is never coming. Forty more
  were the whole of `_build`: a padding, a font size, the accent stripe's width,
  a wraplength, a canvas coordinate or an entire `.pack()` call could change or
  vanish with every test still passing. That is now one test that reads the built
  widget tree back out of Tk (D-024), which disproves this repo's own written
  claim that Tk geometry is something "no assertion can see". No source changed:
  this is 16 new tests and 6 tightened assertions.
impact: none
affected_modules: []
related_tests:
  - "tests/test_toast_view.py"
  - "tests/test_desktop.py"
commit_ref: "feature/ui-mutation-gap"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T12:40:00Z"
```

**Verification evidence:**

- Measured, in three passes over the same 460 mutants, each re-run seeded with
  the rows already settled so only the undetected ones ran again:
  **79.3% (365/460) -> 97.4% (448/460) -> 98.0% (451/460)**.
  `desktop` **100.0%** (69 killed, 4 timeout, 0 survived); `toast_view`
  **97.7%** (350 killed, 28 timeout, 8 survived, 1 uncovered).
- Every test was checked against the mutant it was written for before the run:
  37 mutants hand-applied one at a time, each restored from a `cp` backup, and
  **37 killed**. That included all four zeros and the `3` of the bar's
  `create_rectangle`, the `==` that decides which side a button packs to, four
  deleted `.pack()` calls, both `pack_forget()`s, the fade's `step + 1` and its
  16 ms, `winfo_fpixels("1i") / 96`, and `desktop`'s last two - `open_url`'s
  `"nt"` and its refusal message, which had survived only because the test
  matched a substring the `XX` wrapping leaves intact.
- 1,076 passed, 1 skipped (1,063 before). The skip is environmental, not new:
  Windows only lets the foreground-owning process call `SetForegroundWindow`.
- Branch coverage **99%** (2,411 statements, 22 missed; 680 branches, 9 partial),
  and **the same 99%, missing the same 22 lines, with the six on-screen tests
  deselected**. They were the only cover for the drawing and Win32 code before
  CU-024; they now reach nothing the rest of the suite does not. They stay as the
  end-to-end proof, which is a different claim.
- Structure check **100.0 / 100**, all seven checks.
- The nine left are accounted for, not waved through. Five are equivalent:
  `px(0)` and `px(1)` both clamp to 1, so the two header-button pads cannot
  differ; the work area's fallback left and top are discarded by
  `_, _, right, bottom`; and deleting `root.update_idletasks()` from `show()`
  changes nothing because Tk computes a window's requested size synchronously as
  widgets are packed - hand-applied and confirmed surviving every placement test.
  Three are argparse help text (`prog`, `description`, `--seconds`). One is
  `sys.exit(main())` under the `__main__` guard, then thought uncovered by
  design - **corrected by CU-20260920-027**: `python -m clautomatic.toast_view`
  is the documented demo command, so that guard is testable and is tested.

---

```yaml
id: CU-20260920-024
type: fix
title: "The two UI modules can be measured at last: what the desktop asks Windows for, and what the toast does on screen, are both provable off screen"
description: >
  `toast_view` and `desktop` were the only modules under the 60% mutation
  standard, and the cause was never that they are hard to test - the suite has
  driven real Tk widgets off screen at -4000,-4000 all along. It was that three
  kinds of code could not be reached by a mutation run at all. `show_without_focus`
  reaches for `ctypes.windll` at call time, so only the on-screen test could
  execute it, and mutation runs deselect those (`-m "not real_ui"`). `dpi_aware`
  and `work_area` do the same, so their tests could only say the answer was one
  of the two allowed values - true of every mutant too. And `present()` and
  `main()` were proved only by running a real toast in a subprocess, where
  coverage is not collected. Between them, every line of those five functions
  counted as untested, and every mutant on them survived unexamined.
  `desktop` now follows its own existing idiom everywhere rather than in half
  its functions: `theme(reader=...)` and `open_url(starter=...)` already took
  the thing they call, and now `dpi_aware(shcore=...)`, `work_area(user32=...)`
  and `show_without_focus(user32=..., dwmapi=..., os_name=...)` do too, each
  defaulting to the real library, so a test reads the exact style bits, corner
  preference and foreground handover instead of watching a window. The window's
  own behaviour is unchanged: the defaults are what it did before, and the
  on-screen test that proves it against a real window is kept, exactly as the
  three subprocess toasts are. `toast_view` needed no source change at all -
  its tests now inject the two desktop calls, so `show()`, `_fade()`,
  `present()` and `main()` run in-process with nothing mapped. A new
  `real_present` marker lets the one test that calls `present()` past the
  conftest guard, the way `real_open` already does for `open_url`.
impact: none
affected_modules:
  - "src/clautomatic/desktop.py"
related_tests:
  - "tests/test_desktop.py"
  - "tests/test_toast_view.py"
  - "tests/conftest.py"
commit_ref: "feature/ui-mutation-gap"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T08:45:00Z"
```

**Verification evidence:**

- The cause was measured, not assumed. A fresh baseline put `desktop` at
  **60.3%** (68 mutants; the README's 57.6% predated CU-016/017/020/021), and
  named its undetected 27: 15 *uncovered*, every one of them inside
  `show_without_focus`, and 12 more in `dpi_aware`, `work_area` and the theme
  reader, whose assertions (`in (True, False)`, `in ("light", "dark")`) no
  mutant could fail.
- With the on-screen tests deselected - which is what a mutation run sees -
  `toast_view` line coverage is now **99%** (2 lines left: `sys.exit(main())`
  under `__main__`, and the defensive `except tk.TclError` around a second
  destroy). Before, `show`, `_fade`, `present` and `main` were unexecuted.
- 13 `desktop` mutants were hand-applied one at a time and every one killed the
  suite: the DPI level and its `== 0`, both literal zeros of
  `SystemParametersInfoW` and its `not`, the theme reader's `[0]` and its
  return, `open_url`'s `and`, and in `show_without_focus` the style `|`, the
  three-part foreground condition (`and` swap and both comparisons), the
  dropped `root.update()` and a wrong DWM attribute.
- 1,063 passed including the 7 on-screen tests (1,029 before: 34 new tests).
  Structure check 100.0/100.

---

```yaml
id: CU-20260920-023
type: fix
title: "A mutant that outstays the limit is killed with its children, and the five detection gaps the last run found are closed"
description: >
  The mutation run for CU-022 stopped dead at 868 of 936 mutants and sat there
  for 105 minutes. Not a slow run: a test that starts a real child process
  (test_detach's `python -c pass`) had one left suspended at creation when the
  120-second limit killed its parent mid-spawn, and that child kept the inherited
  stdout pipe open, so subprocess.run's post-kill drain - which takes no timeout -
  waited for an EOF that could never come. One wedged worker stops everything,
  because pool.map yields in order. The run was recovered rather than restarted,
  by resuming the stuck thread; it then finished in seconds with every result
  intact. mutate.py no longer gives the test process pipes at all (nothing to
  drain, since only the exit status was ever read) and kills a timed-out mutant
  with its whole process tree, so neither the hang nor the stray child can
  happen again. The run's own findings are the rest of this entry: five
  survivors were real detection gaps, now a test each - dismissing the Remote
  Control toast must not bring it back at the next stage (the "asked once per
  idle stretch" contract was only ever proved for a toast that timed out), the
  failure reason reaches the log, hold_minutes_left counts down to 0 and only
  then to None (0 is "about to lapse", None is "not held" - an agent has to tell
  them apart), a write that fails at the rename leaves no .tmp behind, and the
  user's settings file keeps its two-space indentation. Every one was checked by
  hand-applying its mutant and watching the new test fail. No runtime source
  changed.
impact: none
affected_modules: []
affected_files:
  - "tools/mutate.py"
related_tests:
  - "tests/test_mcp_tools.py"
  - "tests/test_remote_startup.py"
  - "tests/regression/test_remote_control_prompt.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T07:45:00Z"
```

**Verification evidence:**

- The diagnosis was measured, not guessed: no line written to the results file
  for 105 minutes; all four workers and the parent burning zero CPU across a
  20-second sample; no pytest child under any worker; and one orphaned
  `python -c pass`, one thread, WaitReason **Suspended**, created at 05:46:26 -
  the same second as the last result. Resuming that thread ended the run
  immediately, which is what confirms it was the cause and not a coincidence.
- Each of the five new tests was run against its own mutant by hand, and each
  failed: idle_watch `asked_for_remote = True->False`, the renamed `reason` key,
  the three in `_hold_minutes_left` (`max(0->1)`, `/60->/61`, `left > 0->1`),
  the dropped `temp.unlink`, and `indent=2->3`.
- Then confirmed by the tool rather than by hand: the 18 survivors were re-run
  (seeding the results file with the other 918, which is what makes a targeted
  re-run cheap) and all seven of those mutants are now killed - 98.0% to
  **98.8%**, remote_startup 88.9 to 94.4, mcp_tools 97.9 to 99.1, idle_watch
  98.6 to 99.0. That re-run is also the observed run of the repaired tool: it
  finished normally, with no stray child process left behind.
- 1,029 passed including the 7 on-screen tests, in 361s - the five new tests on
  top of CU-022's 1,024. Branch coverage is unchanged at 98% (2,410 statements,
  54 missed; 680 branches, 14 partial), which is the point: these close gaps in
  *detection*, on lines the suite already executed.
- Structure check 100.0/100 (code_root 83.9, module_size 100, header 100, deep_imports 100,
  cycles 100, fan_out 100, testability 115.3).

---

```yaml
id: CU-20260920-022
type: feature
title: "An agent can hold its own early idle toast while it waits on a build, and the toast before the cache expires still comes"
description: >
  A long run is idle without being finished. A test run ends a turn, waits 5 to
  35 minutes on a build or a test suite, and comes back - and at every one of
  those turn ends the early toast (the one at idle_seconds) offered to compact a
  session about to be used again. New MCP tool clautomatic_hold_idle_toast holds
  that toast for as long as the agent says (minutes, default 30, at most 120; 0
  releases it, optional reason for the log). It holds only the early stage: the
  toast lead_seconds before the prompt cache expires still comes, because by then
  the context really is about to go cold - and if that session is on
  auto-compact, the compaction it held at the early stage happens there instead.
  The hold is per session and self-bound like every other tool here, it expires
  by itself, it is read at the stage's own moment (so it can be set or released
  during the wait), and unlike the toast's own "Silence 24 h" it is not spent by
  using the session again - a run takes many turns. It can only ever silence a
  prompt: it cannot send, compact, or touch another session (D-022). It is also
  the one tool here that does not need Remote Control - it only writes a file,
  and a session whose Remote Control is off is exactly the one that cannot be
  told any other way - so it binds through resolve_self_unbound, with the same
  identity checks and none of the send path. clautomatic_compaction_status now
  also reports how many minutes a hold has left.
impact: medium
affected_modules:
  - "src/clautomatic/idle_state.py"
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/mcp_tools.py"
related_tests:
  - "tests/regression/test_idle_hold.py"
  - "tests/test_idle_state.py"
  - "tests/test_idle_watch.py"
  - "tests/test_mcp_tools.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T06:20:00Z"
```

**Verification evidence:**

- Red first: the six-contract anchor was written and run before any of it
  existed, and failed six ways.
- Writing it settled one question the contract did not answer on its own: with
  auto-compact set to "when idle", a held early stage would have meant that
  session was never compacted at all. It now compacts before the cache expires
  instead, which is what "prompt for cache expiry as it could still be useful"
  asks for, and the anchor pins it.
- 1,024 passed including the 7 on-screen tests; branch coverage 98% (2,410
  statements, 54 missed; 680 branches, 14 partial). idle_state back to 99% (only
  the slot loop's exhausted branch), mcp_tools 100%, idle_watch 99%.
- Mutation on the four modules these two features changed: **98.0%, 917 of 936**
  (idle_state 98.6, idle_watch 98.6, mcp_tools 97.9, remote_startup 88.9) - above
  the 60% mutation standard on every one. Of the 19 that lived, five were real
  detection gaps; with the tests for them (CU-023) the 18 survivors were re-run
  and the pass stands at **98.8%, 925 of 936** - idle_state 98.6, idle_watch
  99.0, mcp_tools 99.1, remote_startup 94.4.
- The 11 left are equivalent mutants or artefacts of the operator: a temp file's
  name (twice) and a retry count that nothing can observe, `return False`
  becoming `return None` in a boolean context (twice), dropping
  `super().__init__(reason)` from an exception whose message nothing reads,
  `parents=True` where the parent always exists, `sys.exit(main())` under
  `__main__` (uncovered by design), and three message strings, which the
  "XX"-wrapping operator leaves matching their substring assertions by
  construction.
- CU-020's mutation pass (97.6%, 847/868: app_sessions 100, idle_arming 100,
  session_registry 99.1, toast_text 98.4, idle_watch 95.5) found that the
  RemotePrompt answers added there were not pinned - its three (state, outcome)
  pairs and the straight-through "dismiss" are now a test each way. The
  session_registry survivor is the known equivalent one ("-1" vs "-2" as the
  disqualified score), and toast_text's are its "1.3M" branch and the
  module-constant timeouts the tool's own docstring warns about.

---

```yaml
id: CU-20260920-021
type: feature
title: "The Remote Control toast can also turn it on for every new session, on a click and only on a click"
description: >
  Fixing one session's Remote Control fixes one session. Claude Code has a
  setting that fixes all of them - remoteControlAtStartup, "Start Remote Control
  bridge automatically each session", which it honours only at user scope (a
  repo's settings cannot enable Remote Control). The toast for a session with
  Remote Control off now offers it as a second button, "Always on for new
  sessions", and the click is the confirmation: nothing is written without it.
  The offer is not made when the setting is already true, and the toast says
  which it is. New module remote_startup reads and writes that one key in
  ~/.claude/settings.json: everything else in the file is kept, the write is
  atomic through a temp file, and a file that cannot be parsed as a JSON object
  is refused rather than replaced - it is the user's file, not ours (D-021).
  The toast confirms with "Remote Control will start with every new session" and
  closes itself; a failure stays on screen and says why. The remote toast's own
  failures also stopped borrowing the compact toast's wording: "Couldn't open the
  session: ..." and "Couldn't change the setting: ..." rather than "Couldn't
  compact: ...".
impact: medium
affected_modules:
  - "src/clautomatic/remote_startup.py"
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/toast_text.py"
  - "src/clautomatic/toast_view.py"
related_tests:
  - "tests/regression/test_remote_control_prompt.py"
  - "tests/test_remote_startup.py"
  - "tests/test_idle_watch.py"
  - "tests/test_toast_text.py"
  - "tests/test_toast_view.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T05:30:00Z"
```

**Verification evidence:**

- The setting is not a guess: it is in Claude Code's own settings schema,
  `remoteControlAtStartup: boolean, "Start Remote Control bridge automatically
  each session"`, and the CLI logs `repo-scoped settings cannot enable Remote
  Control; set it at user scope` when it finds it anywhere else. The CLI also
  reports `remote_control_auto_enable` to IDE hosts "so IDE hosts can mirror TUI
  behavior", which is why a desktop-started session honours it too.
- Red first: 22 tests for the module before it existed, then the toast wiring.
  Three contracts in the anchor (CU-020's file, contract 6): dismissing the toast
  writes nothing, clicking writes the key and keeps everything else, and a
  settings file that cannot be parsed is left exactly as it was.
- 987 passed without the on-screen tests.
- Applied live, by hand and with the maintainer's explicit consent, before the toast
  existed: `remoteControlAtStartup: true` is now in his settings.json, with the
  other seven keys and all three hook blocks intact.

---

```yaml
id: CU-20260920-020
type: feature
title: "A toast for a session with Remote Control off: it is detected, it is said out loud, and the session is one click away"
description: >
  The maintainer asked for the off state to be detected, for a toast to prompt for it,
  and for it to be turned on for him if he confirms. The first two are done; the
  third has no supported mechanism and is recorded as such (D-020). Before, a
  turn end in such a session logged "not_armed: session not bound" and nothing
  was ever said again - which is exactly how "Lighthouse" sat unusable without
  anyone noticing. Now the watch arms anyway: the same size, cache, silence and
  archived rules apply, and at the notify time the watcher reads the record
  again. Bound by then (the user turned it on while the session sat idle) and
  the usual compact toast comes; still unbound and a different toast says
  "Remote Control is off for <session>", with "Open the session", "Not now" and
  the same "Silence 24 h". "Open the session" hands the app its own link to that
  session - claude://claude.ai/<sidebar mode>/<host session id>, the sidebar mode
  read from the app's config - so the switch is one click away. It is asked once
  per idle stretch, not at every stage: unlike "compact now or later", the answer
  does not change as the cache runs down. The toast has no
  compact or auto action, and pressing one anyway does nothing: a RemotePrompt
  can never send. Arming an unbound session needed the bridge requirement split
  out of session_registry.resolve_self into resolve_self_unbound, which keeps
  every identity check; resolve_self is now that call plus the one line that
  everything sending still goes through.
impact: medium
affected_modules:
  - "src/clautomatic/app_sessions.py"
  - "src/clautomatic/desktop.py"
  - "src/clautomatic/idle_arming.py"
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/session_registry.py"
  - "src/clautomatic/toast_text.py"
  - "src/clautomatic/toast_view.py"
related_tests:
  - "tests/regression/test_remote_control_prompt.py"
  - "tests/test_app_sessions.py"
  - "tests/test_desktop.py"
  - "tests/test_idle_arming.py"
  - "tests/test_idle_watch.py"
  - "tests/test_toast_text.py"
  - "tests/test_toast_view.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T04:30:00Z"
```

**Verification evidence:**

- Measured before deciding what was possible. The app's own store says what it
  remembers about the switch - `remoteControlUserEnabled`, `remoteControlAutoEligible`
  and a history of `bridgeSessionIds` - and of the eight running sessions only
  "Lighthouse" carries `remoteControlUserEnabled: true` while being off. Those
  fields are the app's memory of a choice, not a live switch, and the record's
  `bridgeSessionId` is minted by the app when it connects the bridge. So the
  toast asks; it does not flip. The one programmatic path, the desktop app's own
  per-session tool, was tried from this session and refused by the auto-mode
  classifier - the user decides, which is the right place for it to sit.
- Red first for the anchor (7 tests) and for each new piece. Three mutants were
  then applied by hand to prove the anchor bites: removing the unbound branch and
  making `bound()` always true each failed three tests, and letting "compact"
  through to the compact toast failed the "can never send" test - once that test
  had been repaired, because as first written it asserted inside the presenter
  callback and the watcher swallowed it. Which is the seventh time that has
  happened, so it is now a test of its own: `tests/test_test_hygiene.py` fails
  the suite if any test asserts inside a function it hands to the code under
  test. Six older callbacks in three files were repaired with it.
- The `claude://` scheme is registered on this machine (HKCU\Software\Classes\claude
  -> Claude.exe "%1") and the sidebar mode comes from the app's own
  `claude_desktop_config.json` (`preferences.sidebarMode`, "epitaxy" here), with
  that value as the fallback. **Not yet observed:** the link actually opening a
  session - launching it from here was refused by the classifier, so the first
  real click is the observation, and it is logged (`remote_opened` with the link,
  or `remote_open_failed` with the reason).
- `python -m clautomatic.toast_view --demo remote` shows the toast without any
  session being involved.

---

```yaml
id: CU-20260920-019
type: feature
title: "What an existing session still needs: a read-only readiness check per live session"
description: >
  The maintainer reported that the hook and the MCP tools were missing in sessions that
  were already open, naming "Lighthouse", and asked for a repeatable way to bring
  such sessions up to date. Measured first, and the diagnosis was different from
  the report: in Lighthouse the Stop hook was running (two idle-log entries, the
  last stamped at its last activity to the second) and this checkout's MCP server
  was running as a child of its process - what it lacked was Remote Control, so
  its record had no bridgeSessionId and every path refuses. The opposite was true
  of three other sessions, this one included: Remote Control on, no MCP server,
  because a session's process only loads MCP servers when it starts and these
  processes are older than the registration (every claude.exe started at or after
  05:51 on 2026-09-19 has a server under it; the four started at 04:09-04:11 do
  not). New module session_ready and tools/session_ready.py report, for every
  live session record, whether Remote Control is on, whether this checkout's
  server is running under it, and when the hook was last seen - then what to do
  about each gap. It only reads: it lists the records, asks Windows which MCP
  servers are running and under which process, and reads our two logs. Exit code
  1 while any session still needs something. D-019.
impact: low
affected_modules:
  - "src/clautomatic/session_ready.py"
affected_files:
  - "tools/session_ready.py"
related_tests:
  - "tests/regression/test_session_readiness.py"
  - "tests/test_session_ready.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T02:30:00Z"
```

**Verification evidence:**

- Red first: 38 tests for the module, then the 5-test regression test, which
  drives the real modules with only the process query and the records faked and
  pins the two real shapes found on this machine - Lighthouse (tools loaded, no
  Remote Control) and this session (Remote Control, no tools).
- Run for real: `python tools/session_ready.py` reports 3 of 8 sessions ready and
  names the gap for each of the other five. Every row matches what was measured
  by hand first (the session records, `Get-CimInstance Win32_Process` parent
  pids, and the two logs), and the exit code is 1.
- Branch coverage of the new module 99% (98 statements, 1 missed; 38 branches, 1
  partial) - the missed line is `raise SystemExit(main())` under the `__main__`
  guard, as in every other module here.
- 914 passed with the new tests (871 before), branch coverage 98% (2,233
  statements, 54 missed; 626 branches, 14 partial). Structure check 100.0/100 (code_root
  83.3, target 80).
- The check is read-only by construction and the anchor proves it: the isolation
  fixture's guards (network, detached process, toast, window) would fail the test
  if it sent or started anything, and it writes no state of its own.

---

```yaml
id: CU-20260920-018
type: fix
title: "Assertions the watcher was swallowing, guards that could not fail a test, and the gaps they hid"
description: >
  Mutation testing CU-017 left eleven survivors in idle_watch, and reading them
  showed one cause: the watcher deliberately swallows whatever present() raises,
  so a toast that crashes can never crash the watcher - but that also swallowed
  every assertion a test made inside its present() callback. Six assertions in
  three files never reached their test; the regression test's "an archived
  session must not be toasted" was one of them, and only caught its mutant
  indirectly, through the "toast failed" outcome the swallow leaves behind. The
  same hole ran through the isolation fixture:
  a test that reached the network, started a detached process, showed a toast or
  opened the settings window inside such a callback had its guard swallowed too.
  Every guard now records the breach as well as raising it, and the fixture fails
  the test at teardown if anything was recorded (the watcher's own _never_send
  and _never_present do the same); callback assertions moved out of the callback.
  Three tests were added for gaps this uncovered: auto-compact shows no notice
  when the session wakes between the last poll and the send, an auto button
  pressed on a stage that does not name itself is remembered as "before expiry",
  and main() reads the arguments the watcher was started with. No runtime source
  changed. The mutation tester itself moves from the session scratchpad into the
  repo as tools/mutate.py, since every score README quotes comes from it and none
  of them could be reproduced without it; its docstring now names the traps that
  cost time here (comma-separated globs with no brace expansion, no editing src/
  while a run scans, a busy machine turning real results into "timeout"), and a
  guard reports a desynchronised site instead of dying with an AttributeError.
  D-018.
impact: none
affected_modules: []
affected_files:
  - "tools/mutate.py"
related_tests:
  - "tests/conftest.py"
  - "tests/test_idle_watch.py"
  - "tests/test_settings_window.py"
  - "tests/regression/test_idle_notification.py"
  - "tests/regression/test_toast_stages.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T03:10:00Z"
```

**Verification evidence:**

- No regression test is added: no runtime behaviour changed. The two existing
  anchors are strengthened instead - their assertions now reach the test.
- Each of the eleven survivors was applied by hand against the fixed tests. Ten
  are now killed: the dismissed toast's state and its dropped return, the
  notice's `auto_off` state and its dropped return, `_send`'s interrupted state,
  the auto-compact "nothing was sent" check, the auto button's stage default and
  `main`'s argv slice. The eleventh survives and is equivalent - dropping
  `super().__init__(reason)` from `Interrupted`, whose message nothing reads
  (190 tests pass with it applied). One line stays uncovered by design:
  `sys.exit(main())` under the `__main__` guard.
- Both directions were measured, not argued. With the dismissed toast's state
  mutated to a different string, `tests/test_idle_watch.py` passed whole before
  this change (71 passed) and fails after it. And a test that shows a toast
  inside code that swallows the guard - the pattern the watcher uses - passes
  with guards that only raise, and errors at teardown with guards that record.
  The one test whose point is that a guard fires
  (`test_tests_cannot_open_the_real_window`) now takes the fixture by name and
  clears the breach, asserting which guard it was.
- 871 passed, including the 7 on-screen tests; branch coverage 98% (2,135
  statements, 53 missed; 588 branches, 13 partial) with them, 96% without.
  `--collect-only` counts 868 at CU-017's commit and 871 here, so that entry's
  "866 passed" was two short; the three tests added here are the difference.
  Structure check 100.0/100 with `tools/mutate.py` added (code_root 85.7, target 80).
- Re-measured afterwards, on a quiet machine: the five modules score **99.0%**
  (787 / 795) - app_sessions 100, idle_arming 100, **idle_watch 99.4** (from
  96.4), toast_text 98.2, idle_state 97.5. idle_watch is left with one survivor,
  the equivalent one above, and one uncovered `__main__` line. The seven
  survivors across the other modules are equivalent too: a temp-file suffix, a
  retry budget and a slot count in idle_state, and three in toast_text's "1.3M"
  branch, where wrapping the stripped characters in `XX` strips the same ones.
  Five mutants exceeded the 120-second limit and so count as detected: one
  genuinely hangs the suite (deleting the watcher's sleep spins `wait_for`
  forever) and four sit on module-level constants, whose mapped test set is the
  whole suite - each was re-run against its own module's tests and killed in 2
  to 4 seconds. idle_state's 98.3% in the first pass counted a timeout as a kill;
  resolved, it is a survivor, hence 97.5%.
- The new guard was exercised on a two-line sample rather than asserted: a
  constant site mutates as before, and asking for a constant at a comparison's
  index now raises "site 5 is Compare, not Constant: the source changed after
  the scan - start the run again". That failure is what ended a run here, after
  a hand-applied mutant moved a site while the scan was reading it.

---

```yaml
id: CU-20260919-017
type: feature
title: "Two toast stages that both come, a per-session silence, no toast for an archived session, and auto-compact per stage"
description: >
  The maintainer asked for four things. (1) The idle time and the pre-expiry time now
  both apply: a watch has stages, an early toast at idle_seconds and the one
  lead_seconds before the cache expires. Dismissing or ignoring the early one no
  longer cancels the later one; it closes itself after early_toast_seconds (new,
  120 s). Before, idle_seconds replaced the pre-expiry timing ("for testing").
  (2) "Silence 24 h" on every toast: a per-session mute (mute_seconds, new,
  86,400) that the next turn end of that session clears - silenced until it runs
  out or the session is used again. (3) A session the user archived in the app is
  never toasted or compacted: new module app_sessions reads the app's own store
  (%APPDATA%/Claude/claude-code-sessions/<install>/<profile>/archived-sessions.idx
  and each local_<host id>.json's isArchived), checked at the turn end and again
  at the notify time, because archiving does not stop the session. An unreadable
  store reads as "not archived", so a parse failure can never silence a session
  the user can still see. (4) The per-session auto-compact switch now holds which
  stage it acts at: the toast's auto button says "Always compact when idle" or
  "Always compact before expiry" and stores that stage, and the other stage stays
  silent. A switch written before stages means "expiry". Compacting from the
  early toast ends the watch, so no second toast follows a compaction unless the
  session is used again. D-017.
impact: medium
affected_modules:
  - "src/clautomatic/app_sessions.py"
  - "src/clautomatic/idle_arming.py"
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/idle_state.py"
  - "src/clautomatic/settings.py"
  - "src/clautomatic/toast_text.py"
  - "src/clautomatic/toast_view.py"
related_tests:
  - "tests/regression/test_toast_stages.py"
  - "tests/test_app_sessions.py"
  - "tests/test_idle_arming.py"
  - "tests/test_idle_watch.py"
  - "tests/test_idle_state.py"
  - "tests/test_toast_text.py"
  - "tests/test_toast_view.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-20T00:20:00Z"
```

**Verification evidence:**

- Measured first, not assumed: the app's `main.log` shows this session archived at
  02:04:52 and unarchived at 02:05:11 while it kept running, so an archived
  session keeps its runtime record and would have been toasted. The index and the
  per-session records agreed on four sessions, and the index is rewritten within
  a second of the archive event (05:42:06 logged, 05:42:07 written). Against the
  real store, `is_archived` reads True for "Proposal review" and False for this
  session and another live one.
- Red first for app_sessions (20 tests), the mute and auto-mode state, and the
  arming stages. The watcher's tests were written after its code, so three
  mutants were applied by hand to prove they detect the behaviour: making
  `CONTINUING` empty failed the two "the later toast still comes" tests, and
  `if False` for the stage the user chose failed the "auto before expiry keeps
  the early stage silent" test. Both were reverted.
- 866 passed, including the 7 on-screen tests (795 before this change). The new
  regression test drives all five contracts end to end through the real arming,
  watcher, state, settings and compaction path with only the clock, the toast and
  the HTTP send faked.
- Structure check 100/100 with the new module, no import cycles.
- Live: `python tools/settings.py show` lists the two new settings, and the
  window shows all eight rows.
- **Observed live the same night** (`idle-log.jsonl`, session a0b1c2d3, local
  times): last reply 00:00:56, `armed ... acts in 597 s`, the early toast at
  00:10:56 - exactly `idle_seconds` (600) after the last call, where before this
  change `idle_seconds` would have been the only toast and the pre-expiry one
  would not have existed. The maintainer clicked Compact now at 00:12:50, 113 s in (the
  120-second early toast was about to close itself), and the entry carries the
  new key: `"stage": "early"`, 317,830 -> 20,355 tokens in 108.0 s. The expiry
  stage was scheduled for 00:55:56 and never came, because compacting ends the
  watch. Still unobserved live: an early toast that is *let go*, and an archived
  session being skipped.

---

```yaml
id: CU-20260919-016
type: feature
title: "Settings: a window, a command and a Settings link on every toast; every value configurable"
description: >
  The maintainer asked to remove the idle toast's 60-second test delay and to make the
  settings configurable, including the minimums, through a window and a command.
  Before, the only way was hand-editing ~/.claude/clautomatic/idle-settings.json
  (three keys), and the off switch was a file to create by hand.
  New modules: settings (six settings, each with its meaning, default and range;
  typed values like "150k", "off" and "on" are parsed; a save is checked in full
  and is all or nothing; only changed values are stored, in settings.json);
  settings_cli (tools/settings.py: show, set KEY VALUE ..., reset [KEY ...], or
  the window when given no command); settings_window (a Tk window in the toast's
  look; it saves only the fields that changed, marks a refused value in place,
  and Defaults fills the form without saving); ui_style (the fonts, palettes and
  mouse-only button the toast and the window share, moved out of toast_view to
  keep the import graph acyclic).
  The settings: idle_toast (still the off-switch file, so a turn end with the
  toast off starts no Python), min_context_tokens, lead_seconds, idle_seconds
  (off), closure_min_context_tokens (new: the default minimum for a compaction
  an agent queues without one; off means always compact), result_seconds (new:
  how long "Done" stays up, previously fixed at 8 s). idle_arming and
  closure_hook read them, and the toast gets a Settings link that starts the
  window as its own process. idle-settings.json is no longer read; the live one
  held only the test value and was deleted (backed up in the session
  scratchpad). D-016.
impact: medium
affected_modules:
  - "src/clautomatic/settings.py"
  - "src/clautomatic/settings_cli.py"
  - "src/clautomatic/settings_window.py"
  - "src/clautomatic/ui_style.py"
  - "src/clautomatic/idle_state.py"
  - "src/clautomatic/idle_arming.py"
  - "src/clautomatic/closure_hook.py"
  - "src/clautomatic/toast_view.py"
  - "src/clautomatic/toast_text.py"
  - "tools/settings.py"
related_tests:
  - "tests/regression/test_user_settings.py"
  - "tests/test_settings.py"
  - "tests/test_settings_cli.py"
  - "tests/test_settings_window.py"
  - "tests/test_ui_style.py"
  - "tests/test_idle_arming.py"
  - "tests/test_closure_hook.py"
  - "tests/test_toast_view.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T19:10:00Z"
```

**Verification evidence:**

- Red first for the settings module, the window, the toast link and the new
  closure and arming behaviour. The command's tests were written in the same
  step as its code.
- 769 passed without the on-screen tests, and all 7 on-screen tests passed.
  One of them opens the real window in a subprocess with a temporary home, types
  "150k", saves and closes; the value is saved as 150000.
- Structure check 100/100, no import cycles: a first cut had two cycles, which moving the
  shared look into ui_style removed.
- Live: `python tools/settings.py show` on the real state shows every default,
  with idle_seconds off. The window was then opened on the real desktop
  (`settings_window.launch()`, pid 32164) and used: `settings.json` now holds
  min_context_tokens 300,000, idle_seconds 300, closure_min_context_tokens
  300,000 and result_seconds 15 — four values saved through the window, read back
  by `load()`.
- Mutation, every module this change touched: ui_style 100%, idle_arming 100%,
  closure_hook 97.3% (both survivors are the known equivalent `reason` defaults),
  idle_state 95.7%, settings 90.7%, settings_cli 78.9%, settings_window 60.6%.
  All are above the 60% standard. Tests were then added for the survivors worth
  killing — a read-only Setting, a number typed with spaces, the exact refusal and
  reset messages, argv read by default, the command's help, the window's scaling,
  styling, saved toggle state, error lines, closing and placement — and for one
  real gap found in idle_state (switching auto-compact on twice raised).
- Re-measured after those tests, the three settings modules rose to: settings
  **98.0%** (147/150), settings_cli **90.1%** (63 killed, 6 survived, 1 uncovered,
  1 timeout), settings_window **78.3%** (190 killed, 45 survived, 9 uncovered,
  5 timeouts). Every surviving mutant was read: settings_cli's six are argparse
  help strings; settings_window's are Tk layout constants (padding, widths, row
  and column numbers, font sizes) and deleted `.pack()` calls — geometry no
  assertion can see — plus its `run`/`launch`/`main` lines, which only the
  on-screen test runs, in a subprocess. settings' three are the `.tmp` suffix, the
  off-switch file's empty content, and the `and` in `load`'s key filter, which is
  equivalent: with `or`, an unknown key reaches `check`, which raises the
  ValueError the loop already swallows, and the toggle is overwritten from the off
  switch either way. `test_a_key_that_is_not_a_setting_is_ignored_not_checked`
  pins that behaviour (the mutant was applied to confirm it is equivalent, then
  reverted).

---

```yaml
id: CU-20260919-015
type: fix
title: "The MCP server tells every session when to queue a compaction, and how to load the tool"
description: >
  A 12-hour build session, run under the user's own closure procedures,
  finished at 17:16Z with 745,683 tokens of
  context and never queued a compaction. It had everything it needed: the three
  clautomatic tools were listed as deferred, the server's instructions were in its
  context, and so was the CLAUDE.md Tools rule. All of these were delivered at
  the start (04:51Z) and again after its 08:31Z auto-compaction. It carried out
  every closure step its procedures name (final gate, commit, tag, final
  report), but none of those steps mentions compaction, and the only texts that
  did were permissive: the server said to queue "when an overall piece of work
  is verifiably complete", the tool said "Use it only when", and CLAUDE.md said
  "where compaction is wanted". The server's instructions now name the closures
  that call for it (the end of the user's own build and wrap-up workflows, the user
  asking), make it the last action after the final commit, say to load the
  deferred tool with ToolSearch, and ask the final answer to say it is queued.
  The tool's description drops "only when". The same step still needs adding to
  the user's global closure procedures (CLAUDE.md and the workflow files it
  names). The auto-mode classifier refused that edit as
  self-modification, so it is left to the user.
impact: low
affected_modules:
  - "src/clautomatic/mcp_server.py"
  - "src/clautomatic/mcp_tools.py"
related_tests:
  - "tests/regression/test_closure_instructions.py"
  - "tests/test_mcp_server.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T18:05:00Z"
```

**Verification evidence:**

- The miss: that session's transcript. Lines 7 and 2696
  list the deferred tools, lines 9 and 2698 hold the server instructions, and
  lines 18 and 2685 hold the CLAUDE.md rule. No tool_use of any clautomatic tool
  and no ToolSearch for one appears anywhere. The final turn (rows 5098-5152) ran
  the gate, then commit, tag, report and end_turn. The idle toast was the
  backstop: armed 17:16:59Z, dismissed 17:18:07Z.
- Red first: both anchor tests failed. After the change, 650 passed (6 real-UI
  deselected). An `initialize` sent to the real server over stdin returns the new
  text.
- Takes effect in sessions started after this commit, because the server's
  instructions are read when a session starts it.
- Global closure procedures: the maintainer ran the edit script on 2026-09-19.
  It added the step to `~/.claude/CLAUDE.md` (Definition of done, Tools) and
  to the four workflow files it names. Its output
  was "edited" for each file, and on backup copies a second run changed nothing.

---

```yaml
id: CU-20260919-014
type: fix
title: "The toast reports this compaction's result, not an earlier boundary copied in during it"
description: >
  The first live "Compact now" with progress tracking (session a0b1c2d3, sent
  17:21:41Z) reported "656,725 -> 19,111 tokens, 77.6 s", which was the 04:29
  compaction's result. While compacting, Claude Code appended about 7 MB of earlier
  rows after the send (transcript lines 4375-5953, old timestamps), among them a
  copy of the 04:29 boundary. The Tracker took the first boundary after its
  offset. The real result was the next one: 354,583 -> 23,557 in 90.8 s
  (17:23:12.991Z). compact_progress now reads each boundary's timestamp
  (stamp(): ISO 8601, UTC when no zone is given) and counts it only if it is at
  or after the send time. A boundary whose timestamp is missing or unreadable is
  not taken as the result, so the worst case is "unconfirmed", never another
  compaction's numbers. Test fixtures that stamped the boundary before their fake
  clock's send time (2026 dates against a 2027 clock) now stamp it after the send.
impact: medium
affected_modules:
  - "src/clautomatic/compact_progress.py"
related_tests:
  - "tests/regression/test_compaction_feedback.py"
  - "tests/test_compact_progress.py"
  - "tests/test_idle_watch.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T17:55:00Z"
```

**Verification evidence:**

- Failure: idle-log.jsonl 17:23:22Z `result` at "2026-09-19T04:29:52.238Z".
  The transcript holds that boundary twice, at bytes 4,728,239 (original) and
  19,080,247 (copy, written after the send at byte 15,043,217).
- Replay on the real transcript from the send offset: `compacted`, 354,583 ->
  23,557, 90.8 s, at 17:23:12.991Z.
- Red first: 13 new tests failed before the fix. After it, 647 passed (6 real-UI
  deselected). Mutation for compact_progress: 100% (78 killed, 2 timeouts, 0
  survived), after one added test killed a surviving rounding mutant in the
  "unconfirmed" result. Structure check 100/100.

---

```yaml
id: CU-20260919-013
type: fix
title: "Token refresh sends the headers of a Node client that refreshes successfully"
description: >
  CU-012's user agent was wrong: with "claude-code/2.1.275" the token endpoint
  answered HTTP 429 rate_limit_error on the next send (11:04), and the toast
  showed the error body as a raw dict. A refresh that works is a Node
  client's: the same endpoint, client id and JSON body, sent by Node's fetch
  with its default headers. token_store
  now sends exactly those headers (REFRESH_HEADERS: Content-Type
  application/json, Accept */*, Accept-Language *, Sec-Fetch-Mode cors,
  User-Agent node) and no longer imports bridge_client. A refusal in the API's
  nested error shape ({"type": "error", "error": {"type", "message"}}) now reads
  "rate_limit_error: Rate limited. ...".
impact: medium
affected_modules:
  - "src/clautomatic/token_store.py"
related_tests:
  - "tests/regression/test_token_refresh_request.py"
  - "tests/test_token_store.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T17:40:00Z"
```

**Verification evidence:**

- Before: idle-log.jsonl 10:51:19Z HTTP 403 (Python's default user agent),
  11:04Z HTTP 429 rate_limit_error ("claude-code/2.1.275").
- Live: idle-log.jsonl 17:23:22Z session a0b1c2d3 `compacted`, http_status 200,
  token_refreshed true. The refresh succeeded with these headers, and the
  rotated tokens were written back.
- 633 passed (6 real-UI deselected).

---

```yaml
id: CU-20260919-012
type: fix
title: "Token refresh sends the CLI's user agent and says why a refusal happened"
description: >
  The idle toast's first send after the stored access token expired failed with
  "token refresh returned HTTP 403". The credentials file was last written
  2026-09-18 23:39 UTC and its token expired 07:39; the Desktop app keeps its own
  tokens and never rewrites the file, so earlier sends (04:28, 06:17) only
  worked because that token was still valid, and this was the first live
  refresh (every logged send before had token_refreshed false). The refresh
  request sent Python's default user agent; every bridge request, all of which
  succeeded, sent claude-code/2.1.275. token_store now sends the same user agent
  (USER_AGENT, from bridge_client.CLIENT_VERSION), and a refused refresh adds the
  server's short reason (OAuth error and description, "an HTML page", or the
  first 120 characters) to the error the toast and the log show.
impact: medium
affected_modules:
  - "src/clautomatic/token_store.py"
related_tests:
  - "tests/regression/test_token_refresh_request.py"
  - "tests/test_token_store.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T11:05:00Z"
```

**Verification evidence:**

- Failure: idle-log.jsonl 10:51:19Z `error` "TokenError: token refresh returned
  HTTP 403" for one session (the toast was shown).
- The user-agent cause is a hypothesis, not yet confirmed. A probe of the token
  endpoint with a deliberately fake refresh token was refused by the auto-mode
  classifier ("Credential Exploration"), so the fix can only be confirmed by the
  next real send. If it fails again, the error now carries the server's reason.
- 633 passed; structure check 100/100.

---

```yaml
id: CU-20260919-011
type: fix
title: "Idle toast follows a sent compaction to its end instead of closing after 3 s"
description: >
  After "Compact now" (or "Auto-compact this session", or an automatic
  compaction) the toast said "Compaction started" and closed after 3 s, and the
  watcher logged "compacted" as soon as the bridge accepted the send. A large
  compaction runs for over a minute and the Desktop app shows nothing while one
  that arrived over Remote Control runs, so twice it looked as if nothing had
  happened until the user typed. The watch marker now carries the session's
  transcript path (idle_arming). Just before the send the watcher records the
  transcript's size (idle_watch._send), and a new compact_progress.Tracker
  reads only what is appended after that point, in bounded chunks, until a
  main-thread compact_boundary entry appears (tokens before and after,
  Claude Code's own duration) or 10 minutes pass ("unconfirmed", never a claimed
  success). The toast stays up showing "Compacting… m:ss", then "Done in 1 min
  42 s: 460k → 23k tokens." (closes after 8 s); no result keeps it open with
  only ✕, which now just closes once nothing is left to decide. The auto notice
  follows its compaction the same way. If the toast is closed early the watcher
  keeps following headless, so every idle-log.jsonl line for a sent compaction
  carries sent_at and result. Controllers gain progress(); the view no longer
  polls for activity while following (the compaction itself makes the session
  busy). A toast that closes itself now logs why (expired, resumed, superseded,
  cancelled, closed) instead of a bare "closed".
impact: medium
affected_modules:
  - "src/clautomatic/compact_progress.py"
  - "src/clautomatic/idle_arming.py"
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/toast_text.py"
  - "src/clautomatic/toast_view.py"
related_tests:
  - "tests/regression/test_compaction_feedback.py"
  - "tests/test_compact_progress.py"
  - "tests/test_idle_watch.py"
  - "tests/test_idle_arming.py"
  - "tests/test_toast_text.py"
  - "tests/test_toast_view.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T06:45:00Z"
```

**Verification evidence:**

- The reported failure, from session a0b1c2d3's transcript: `/compact` enqueued
  06:17:32.257 and dequeued 06:17:32.347; the user's message enqueued
  06:18:51.399; `compact_boundary` 06:19:14.217 with `durationMs` 101,836
  (459,517 → 23,498 tokens). Boundary time minus duration = 06:17:32.381, the
  command's own entry to within 3 ms, so the compaction started at the click.
  Its 23,026-character summary could not have been generated in the 23 s
  between the user's message and the boundary at this session's measured
  90–125 tokens/s. The fault was the missing feedback, not the send.
- Why the bare "closed" had to go: the next test toast (06:41:48) logged
  "closed" at 07:40:49, the cache expiry, so it went unclicked. Three toasts
  for another session logged "closed" when background-task notifications woke
  that session (10:15:58, 10:20:36, 10:43:30). The log could not tell these
  apart; it now records "expired" and "resumed".
- 622 passed (full suite with the real-window subprocess tests, including
  `test_a_real_toast_stays_up_while_compacting_then_shows_the_result`); branch
  coverage 98% overall, compact_progress / idle_arming / toast_text 100%,
  idle_watch 99%; structure check 100/100.

---

```yaml
id: CU-20260919-010
type: feature
title: "Idle toast: offer to compact an idle session before its prompt cache expires"
description: >
  At every turn end the Stop hook (closure_hook -> new idle_arming) now decides
  whether to watch the session: the notifier is on (no
  ~/.claude/clautomatic/idle-notify.off), the transcript shows the last
  main-thread call's context size and the prompt-cache TTL (new cache_window:
  usage.cache_creation.ephemeral_1h/5m_input_tokens, the shorter lifetime
  winning; context_meter gains entries_from_end), the context is at least
  min_context_tokens (default 100000), the cache has not expired, and the session
  is bound (Remote Control connected). It then records a watch generation (new
  idle_state) and starts a detached watcher (new detach; pythonw, its own process
  group, breakaway from job objects, no inherited std handles) running new
  idle_watch. The watcher acts lead_seconds (default 300) before the cache
  expires - 55 min idle on a 1 h cache, 3 min on a 5 min cache, never before 60%
  of the TTL (or a fixed idle_seconds if set) - and stands down as soon as a newer
  Stop re-arms, the session record shows it busy or changed since the Stop, or
  it closes. At the notify time, if the session is still idle and bound, it
  shows a toast (new toast_view / toast_text / desktop: stdlib Tk, bottom-right,
  stacked, no focus taken, mouse-only buttons, light/dark, rounded corners) with
  "Compact now", "Auto-compact this session" and "Not now", and a live countdown
  to expiry. A session switched to auto-compact is compacted without asking and
  gets a notice with "Turn off auto-compact". Sends go through
  compaction.compact_record: exactly /compact, to the runtime-bound session,
  never while it is busy, at most once per watch. Settings live in
  ~/.claude/clautomatic/idle-settings.json; outcomes in idle-log.jsonl. The hook
  is now silent unless it claimed a request, and stop_compact.cmd starts Python
  on every turn end unless the notifier is switched off and nothing is pending.
  pytest.ini sets --capture=sys: fd capture made Tcl fail to read its own library
  files intermittently.
impact: high
affected_modules:
  - "src/clautomatic/cache_window.py"
  - "src/clautomatic/context_meter.py"
  - "src/clautomatic/idle_state.py"
  - "src/clautomatic/detach.py"
  - "src/clautomatic/idle_arming.py"
  - "src/clautomatic/idle_watch.py"
  - "src/clautomatic/toast_text.py"
  - "src/clautomatic/toast_view.py"
  - "src/clautomatic/desktop.py"
  - "src/clautomatic/closure_hook.py"
  - "tools/stop_compact.cmd"
  - "pytest.ini"
related_tests:
  - "tests/regression/test_idle_notification.py"
  - "tests/regression/test_stop_wrapper.py"
  - "tests/test_cache_window.py"
  - "tests/test_idle_state.py"
  - "tests/test_detach.py"
  - "tests/test_idle_arming.py"
  - "tests/test_idle_watch.py"
  - "tests/test_toast_text.py"
  - "tests/test_toast_view.py"
  - "tests/test_desktop.py"
  - "tests/test_context_meter.py"
  - "tests/test_closure_hook.py"
commit_ref: "feature/idle-toast"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T06:30:00Z"
```

**Verification evidence:**

- Prompt-cache TTL measured before designing: 451 of 452 main-thread calls in
  session a0b1c2d3, and all 28,971 cache writes in the 25 latest transcripts,
  used the 1-hour cache; hence "5 minutes before expiry" rather than a fixed
  3-minute delay (the maintainer's choice).
- Real `stop_compact.cmd` run through `cmd.exe` against a throwaway home with a
  200k-token transcript: exit 0, no output, `armed` logged; the watcher it
  started was still running after the hook returned and logged `cancelled` on
  its own when the watch was withdrawn (test_stop_wrapper.py).
- A real toast (demo, nothing sent) was clicked by the maintainer with the mouse; the
  click reached the button handler ("clicked: dismiss").
- Bug found live and fixed: the first toast's first poll ran before Tk's event
  loop started, so its quit was lost and a faint (first fade step), unclickable
  window stayed up. Now polled only from inside the loop; closing hides the
  window at once. Anchored by test_toast_view.py's isolated-process tests.

---

```yaml
id: CU-20260919-009
type: feature
title: "Local stdio MCP server to queue, cancel and inspect compaction"
description: >
  Adds a stdlib-only MCP server (tools/mcp_server.py -> clautomatic.mcp_server
  for JSON-RPC framing, clautomatic.mcp_tools for behaviour) so Claude can queue
  compaction with a tool call; the existing Stop hook fires it. Tools:
  clautomatic_queue_compaction (focus?, min_context_tokens?),
  clautomatic_cancel_compaction, clautomatic_compaction_status. No tool takes a
  target: the session is bound from the server's OS parent pid (the claude
  process, whose ~/.claude/sessions/<pid>.json record names the live session)
  corroborated by CLAUDE_CODE_SESSION_ID, which Claude Code 2.1.275 sets for every
  stdio MCP server (confirmed in the bundled CLI). A stale id (e.g. after /clear)
  or a foreign parent is refused with advice to reconnect, never guessed. The
  tools never read the token or call the bridge. Protocol: legacy lifecycle
  (initialize / notifications/initialized), answering 2025-11-25 or 2025-06-18
  (the CLI's MCP client prefers 2025-11-25); argument errors are isError tool
  results, unknown tools -32602, faults -32603 without detail; no batches.
  is_valid_session_id moves to session_registry (compaction re-exports it).
impact: medium
affected_modules:
  - "src/clautomatic/mcp_server.py"
  - "src/clautomatic/mcp_tools.py"
  - "src/clautomatic/compaction.py"
  - "src/clautomatic/session_registry.py"
  - "tools/mcp_server.py"
related_tests:
  - "tests/regression/test_mcp_queue.py"
  - "tests/test_mcp_tools.py"
  - "tests/test_mcp_server.py"
commit_ref: "6764c0d (tests strengthened after mutation testing in a later commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:40:25Z"
```

```yaml
id: CU-20260919-008
type: feature
title: "Conditional compaction: fire only if the context is at least N tokens"
description: >
  A request may carry min_context_tokens (CLI: --request --min-context-tokens N,
  accepting 150000 / 150k / 1.5m; MCP: the queue tool's argument). The Stop hook
  that claims the request measures the session's context from transcript_path -
  the usage (input + cache writes + cache reads + output) of the last main-thread,
  non-synthetic assistant message, read from the file's tail (new module
  clautomatic.context_meter) - and fires only if it is at least the minimum.
  Below it, nothing is sent and the request is discarded (one-shot, not kept
  armed): outcome "below_threshold". If the size cannot be measured, nothing is
  sent (fail closed): "error". Every claimed request's log line now records
  context_tokens and min_context_tokens.
impact: medium
affected_modules:
  - "src/clautomatic/context_meter.py"
  - "src/clautomatic/closure_hook.py"
  - "src/clautomatic/compaction.py"
  - "src/clautomatic/cli.py"
related_tests:
  - "tests/regression/test_conditional_compaction.py"
  - "tests/test_context_meter.py"
commit_ref: "6764c0d (tests strengthened after mutation testing in a later commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:40:25Z"
```

**Verification evidence (CU-20260919-008, 009):**

- TDD: the new test files were written first and observed failing (collection
  errors: the modules did not exist) before implementation.
- Transcript format checked against this session's real transcript (Claude Code
  2.1.275): assistant entries carry `message.usage` with the four counters, plus
  `isSidechain`; the last main-thread usage summed to ~303k tokens.
- The MCP server was run for real over stdio in a child process
  (`tests/regression/test_mcp_queue.py::test_stdio_server_speaks_only_json_rpc`):
  initialize → initialized → tools/list → tools/call queued a request that binds
  to the child's parent process, and stdout carried only the three replies.
- Measured after mutation-driven test additions (tool contract, exact texts,
  JSON-RPC error bodies, flush per reply): 339 tests pass; branch coverage 99%;
  structure check 100/100; mutation score 97.2% (987/1015 killed; mcp_tools 100,
  mcp_server 98.4, context_meter 87.8; the 28 survivors are behaviour-equivalent
  - see README, Verification).
- NOT verified: the server registered in Claude Code and called by a live
  session; the conditional path firing a real compaction.

---

CU-20260919-002 … 007 remediate the 2026-09-19 review of CU-20260919-001
(findings 1–7 plus the Stop-wrapper overhead). Verification for all six is at the
end of this group.

---

```yaml
id: CU-20260919-007
type: refactor
title: "Stop-hook wrapper skips Python when no request is pending"
description: >
  Stop fires at the end of every turn in every session, and the wrapper started a
  Python process each time just to find nothing to do. It now exits 0 at once
  unless %USERPROFILE%\.claude\clautomatic\requests\ holds a *.json request.
  The .cmd is now CRLF (enforced by .gitattributes) for cmd.exe.
impact: low
affected_modules:
  - "tools/stop_compact.cmd"
related_tests:
  - "tests/regression/test_stop_wrapper.py"
commit_ref: "698a8a4 (tests strengthened after mutation testing in the next commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:03:21Z"
```

```yaml
id: CU-20260919-006
type: fix
title: "Stop hook reports failures truthfully, never raises, and logs each outcome"
description: >
  The hook reported "compacted" for any send, including HTTP 401, and caught only
  TargetError, so login, network and file errors escaped as tracebacks after the
  request had already been consumed - a lost compaction reported as success.
  Now a 2xx is "compacted", any other status is "failed" (with the status), and
  TargetError / TokenError / OSError (incl. URLError) / ValueError / KeyError are
  "error" (with type and message); main() has a last-resort catch-all and always
  returns 0. Each claimed request appends one JSON line to
  ~/.claude/clautomatic/hook-log.jsonl (ts, session_id, action, reason,
  http_status, token_refreshed) - never the token. To make D-20260919-007's
  premise measurable, token_store.get_access_token() returns
  AccessToken(value, refreshed) (repr redacted), and token_status() /
  `bridge_send.py --token-status` report freshness without the token. Token
  refresh HTTP errors become TokenError; a failed credentials write-back removes
  its temp file (which holds live tokens) and says the refresh token may be stale.
impact: medium
affected_modules:
  - "src/clautomatic/closure_hook.py"
  - "src/clautomatic/compaction.py"
  - "src/clautomatic/token_store.py"
  - "src/clautomatic/bridge_client.py"
  - "src/clautomatic/cli.py"
related_tests:
  - "tests/regression/test_hook_failure_reporting.py"
  - "tests/test_closure_hook.py"
  - "tests/test_token_store.py"
commit_ref: "698a8a4 (tests strengthened after mutation testing in the next commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:03:21Z"
```

```yaml
id: CU-20260919-005
type: fix
title: "Claiming a compaction request is at-most-once and fails closed"
description: >
  consume_request ignored a failed delete and returned the request anyway, so a
  request whose file could not be deleted fired at every later Stop, and two
  racing consumers could both fire. Now only the caller whose delete succeeds
  gets the request; a failed delete (locked, or already claimed) returns None.
  A request that was never fired stays for the next Stop.
impact: medium
affected_modules:
  - "src/clautomatic/compaction.py"
related_tests:
  - "tests/regression/test_consume_at_most_once.py"
commit_ref: "698a8a4 (tests strengthened after mutation testing in the next commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:03:21Z"
```

```yaml
id: CU-20260919-004
type: fix
title: "Compaction requests move out of Claude Code's runtime folder"
description: >
  Requests were written as ~/.claude/sessions/.compact-request-<id>.json, inside
  Claude Code's registry of live processes, where load_records() read them back
  as session records and Claude Code may tidy files it did not create. They are
  now ~/.claude/clautomatic/requests/<id>.json, written atomically (temp file +
  replace), and a session id must match [A-Za-z0-9_-]{1,128} before it becomes
  part of a path. API change: request_compaction/consume_request and
  closure_hook.run take requests_dir (was sessions_dir). No migration needed: no
  request files existed at the old location (checked 2026-09-19).
impact: medium
affected_modules:
  - "src/clautomatic/compaction.py"
  - "src/clautomatic/closure_hook.py"
related_tests:
  - "tests/regression/test_request_state_dir.py"
commit_ref: "698a8a4 (tests strengthened after mutation testing in the next commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:03:21Z"
```

```yaml
id: CU-20260919-003
type: fix
title: "--request honours --dry-run and refuses unusable session ids"
description: >
  `--self --request --dry-run` recorded a real request, so the next turn end
  compacted the session - the opposite of what --dry-run promises, and the flag
  the handoff told agents to use for safe testing. It now records nothing. A
  target without a valid sessionId is refused (exit 1) instead of writing a
  request named after "None".
impact: high
affected_modules:
  - "src/clautomatic/cli.py"
related_tests:
  - "tests/regression/test_request_intent_guards.py"
commit_ref: "698a8a4 (tests strengthened after mutation testing in the next commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:03:21Z"
```

```yaml
id: CU-20260919-002
type: fix
title: "The allowlisted CLI can only compact its own session"
description: >
  tools/bridge_send.py runs under a Bash allow rule, i.e. without a permission
  prompt, and it could send arbitrary text (--text) to any Remote-Control-connected
  session selected by --name/--pid/--host-session-id/--session-id, where it
  landed as genuine user input. An agent steered by injected content could have
  driven another session. --text is removed (the only thing ever sent is a
  constructed /compact); --compact and --request require --self; explicit
  selectors work only with --dry-run and cannot be combined with --self; an
  action is required. The --focus hint is normalized to one printable line of at
  most 500 characters before it is appended to /compact.
impact: high
affected_modules:
  - "src/clautomatic/cli.py"
  - "src/clautomatic/compaction.py"
related_tests:
  - "tests/regression/test_cli_self_only.py"
  - "tests/test_cli.py"
commit_ref: "698a8a4 (tests strengthened after mutation testing in the next commit)"
author: "Claude Opus 5 (agent)"
timestamp: "2026-09-19T02:03:21Z"
```

**Verification evidence (CU-20260919-002 … 007):**

- TDD: the six regression files were written first and observed failing
  (41 failed, 42 passed) before any fix; after the fixes the full suite passed.
- Test isolation: an autouse fixture in `tests/conftest.py` points every
  credentials/sessions/requests/log path at a temp home and makes both network
  entry points raise, so no test can touch the real `~/.claude` or the network.
- `tests/regression/test_stop_wrapper.py` runs the real `stop_compact.cmd` through
  `cmd.exe` with hook JSON on stdin against a throwaway `USERPROFILE`: no request
  → exit 0 without starting Python; a request → consumed, logged, exit 0.
- Measured after mutation-driven test additions: 183 tests pass; branch coverage
  99%; structure check 100/100; mutation score 96.7% (535/553 killed; every module ≥ 91%;
  the 18 survivors are behaviour-equivalent - see README, Verification).
- NOT verified: a live Stop-hook compaction; the new --focus normalization and
  request location against a real session (no live send was made).

---

```yaml
id: CU-20260919-001
type: feature
title: "Agent-initiated /compact of a live Claude Code session at scope closure"
description: >
  Adds a mechanism for an agent to trigger a REAL context compaction (/compact)
  of a live Claude Code Desktop session over the Remote Control bridge, executed
  as genuine user input (so the slash command runs) rather than a demoted
  cross-session peer message. Intent and execution are separated: the agent
  records a compaction request at verified overall-scope closure (after the final
  answer and a durable checkpoint); a Stop hook consumes that request exactly once
  and fires the command. Target binding for the "self" case comes only from the
  runtime (per-process session records cross-checked against hook/env identifiers
  and, when available, the session id the Stop hook receives on stdin), never from
  a model-supplied bridge id. The OAuth token is read at call time and refreshed
  only on expiry (endpoint/client-id/rotation mirror the CLI), used solely in the
  Authorization header and never logged.
impact: high
affected_modules:
  - "src/clautomatic/session_registry.py"
  - "src/clautomatic/token_store.py"
  - "src/clautomatic/bridge_client.py"
  - "src/clautomatic/compaction.py"
  - "src/clautomatic/closure_hook.py"
  - "src/clautomatic/cli.py"
  - "tools/bridge_send.py"
related_tests:
  - "tests/regression/test_human_classification.py"
  - "tests/test_session_registry.py"
  - "tests/test_token_store.py"
  - "tests/test_bridge_client.py"
  - "tests/test_compaction.py"
  - "tests/test_closure_hook.py"
  - "tests/test_cli.py"
commit_ref: "59dd487 (baseline import; built before the project was under version control)"
author: "Claude Opus 4.8 (agent)"
timestamp: "2026-09-19T00:26:33Z"
```

**Verification evidence (end-to-end, target = disposable "Hello" session):**

- Plain-text probe landed in the target transcript as `origin:{"kind":"human"}`,
  ordinary `queue-operation enqueue → dequeue → user` turn (NOT peer-wrapped).
- `/compact` rendered as a real command (`<command-name>/compact</command-name>`
  → `<local-command-stdout>Compacted </local-command-stdout>`) and a
  `system/compact_boundary` event fired: `trigger:"manual"`,
  `preTokens:57592 → postTokens:7395`, `cumulativeDroppedTokens:50197`,
  plus an `isCompactSummary:true` replacement.
- `--self` runtime resolution bound the correct current session (verified by
  dry-run) from env identifiers, not by name.

---
