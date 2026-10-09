# Architecture

All logic lives under `src/`: the Python package in `src/conpact/` and the
Claude Code mod in `src/mod/`. One purpose per module, no import cycles, no
third-party dependencies. The entry points in `tools/` are deliberately thin.

The "Depends on" column lists conPACT modules only, read from each module's
imports.

## Modules

### Compacting a Claude Code session

| Module | Responsibility | Depends on |
|---|---|---|
| [`home.py`](../src/conpact/home.py) | Where conPACT keeps its own state, `~/.conpact/`, inside neither app's folders; the one-time move from the folder it used before | — |
| [`session_registry.py`](../src/conpact/session_registry.py) | Resolve a target session record; bind the current ("self") session from the runtime only; define a plain session id | — |
| [`token_store.py`](../src/conpact/token_store.py) | Read the OAuth token (the Keychain first on macOS, else the credentials file); refresh a file's token on expiry (mirrors the CLI); report freshness; never log it | keychain |
| [`keychain.py`](../src/conpact/keychain.py) | Read Claude Code's login from the macOS Keychain, the entry named as Claude Code names it, split logins put back together; never write | — |
| [`bridge_client.py`](../src/conpact/bridge_client.py) | The single source of truth for the bridge wire format and what counts as accepted (2xx) | — |
| [`context_meter.py`](../src/conpact/context_meter.py) | Measure a session's live context size from its transcript | session_registry |
| [`compaction.py`](../src/conpact/compaction.py) | Construct `/compact` text, with the provenance clause every send carries; record, read, cancel and claim requests; orchestrate a send | bridge_client, session_registry, token_store |
| [`closure_hook.py`](../src/conpact/closure_hook.py) | The Stop hook: claim a request at most once, check the minimum size, fire, report and log; then hand the turn end to the idle notifier and sweep Codex threads | bridge_client, codex_arming, compaction, context_meter, idle_arming, session_registry, settings, token_store |
| [`spin_off.py`](../src/conpact/spin_off.py) | Is the calling session a throwaway `.claude/worktrees/...` checkout, and is the refusal switched on? | settings |
| [`cli.py`](../src/conpact/cli.py) | The command-line surface: self-only, `/compact`-only | bridge_client, compaction, session_registry, token_store |
| [`mcp_tools.py`](../src/conpact/mcp_tools.py) | The MCP tools: queue, cancel, hold, inspect, for the calling session on either platform | codex_caller, codex_meter, codex_threads, compaction, context_meter, idle_state, session_registry, spin_off |
| [`codex_caller.py`](../src/conpact/codex_caller.py) | Which Codex surface started the MCP server (ChatGPT Desktop, the CLI, or conPACT's own app-server) and which Codex thread is calling it: exactly one, or a refusal | codex_active, codex_host, codex_meter, codex_threads, compaction, context_meter |
| [`mcp_server.py`](../src/conpact/mcp_server.py) | Stdio JSON-RPC 2.0 framing and the MCP lifecycle for those tools | mcp_tools |

### The Claude Code mod

A Claude Code plugin in `src/mod/` (manifest `.claude-plugin/plugin.json`, hooks
module named in `hooks/hooks.json`), listed by the repository's own marketplace,
`.claude-plugin/marketplace.json`. JavaScript, run by Claude Code itself. Claude
Code reads `register.js` to list what a mod calls, so every mod API call is
spelled out there and the other modules are handed `host`, a small object of
those calls, rather than the API itself.

| Module | Responsibility | Depends on |
|---|---|---|
| [`register.js`](../src/mod/hooks/register.js) | The mod: which events it handles, the `host` it lends the other modules (its one file write guarded to `~/.conpact/mod/`, and its compaction run as `/compact` in a session with no terminal behind it), the turn-end trigger, the watch on other compactions, the idle toast's two timers, and the band above the prompt | band, handoff, requests, rules, run, tools |
| [`tools.js`](../src/mod/hooks/tools.js) | Answer queue, cancel and status in the MCP server's place, with the server's names, arguments and words; the band's Cancel | files, requests, rules |
| [`band.js`](../src/mod/hooks/band.js) | The band above the prompt, one row drawn from the surface's own elements: the request while it waits and runs, then before -> after with a meter, the saving and the time; cancel and dismiss | rules |
| [`run.js`](../src/mod/hooks/run.js) | Run a session's request after its turn: claim, check the minimum, compact, record, show | files, requests, rules, tools |
| [`handoff.js`](../src/mod/hooks/handoff.js) | The idle toast's way in: the heartbeat, and the toast's request taken once, run at once and answered | files, requests, run, tools |
| [`requests.js`](../src/mod/hooks/requests.js) | Each session's request and last result in the mod's store, and the last idle toast request it took: queue, claim, release, finish, dismiss, take, prune | rules |
| [`files.js`](../src/mod/hooks/files.js) | conPACT's files under `~/.conpact/`: the settings, this session's toast hold, and the idle toast's ask read; the beat and answers written | rules |
| [`rules.js`](../src/mod/hooks/rules.js) | The rules shared with the Python side, as plain functions: focus, minimum, session id, worktree, settings, hold, the turn-end verdict | — |

Its tests are in `src/mod/tests/` and run with `claude plugin test`, through
Claude Code's own test host; the Python suite runs them too.

### The idle notifier

| Module | Responsibility | Depends on |
|---|---|---|
| [`cache_window.py`](../src/conpact/cache_window.py) | When an idle Claude session's prompt cache expires: last main-thread call, its context size, the cache TTL | context_meter |
| [`idle_state.py`](../src/conpact/idle_state.py) | The notifier's files: off switch, watch markers (generations), per-session auto switch and mute, log, toast slots | compaction, session_registry |
| [`idle_arming.py`](../src/conpact/idle_arming.py) | At a turn end: whether to watch the session and at which stages; start the watcher | app_sessions, cache_window, detach, idle_state, session_registry, settings |
| [`watching.py`](../src/conpact/watching.py) | The shape of a platform adapter (four questions) and the "no longer idle" exception, shared by the watcher and each adapter | — |
| [`idle_watch.py`](../src/conpact/idle_watch.py) | The detached watcher: walk the stages, stand down on activity or an archive, then ask (toast) or auto-compact - through the session's mod where it beats, else over the bridge | app_sessions, bridge_client, closure_hook, codex_watching, compact_progress, compaction, desktop, idle_state, mod_handoff, remote_startup, session_registry, settings, toast_view, watching |
| [`mod_handoff.py`](../src/conpact/mod_handoff.py) | The watcher's side of the mod's hand-off: is the mod's beat fresh, leave a request, wait for its answer, follow it, clear old files | compaction, session_registry |
| [`compact_progress.py`](../src/conpact/compact_progress.py) | When a sent `/compact` has finished: the first compact boundary in the transcript stamped after the send | — |
| [`app_sessions.py`](../src/conpact/app_sessions.py) | The desktop app's own record of a session, read-only: is it archived, and what link opens it? Found in Electron's per-user folder on each platform | — |
| [`session_ready.py`](../src/conpact/session_ready.py) | Read-only: what each live session still needs (Remote Control, the MCP server, the hook); processes read with PowerShell on Windows, `ps` elsewhere | closure_hook, idle_state, session_registry |
| [`doctor.py`](../src/conpact/doctor.py) | Read-only installed Codex health: Python, Codex login, MCP config, sidecar, bundled build, state access; reports Claude's optional Keychain login separately | codex_home, codex_sidecar_install, codex_threads, token_store |
| [`remote_startup.py`](../src/conpact/remote_startup.py) | One key of Claude Code's own settings, `remoteControlAtStartup`, written only on the toast's click | session_registry |
| [`detach.py`](../src/conpact/detach.py) | Start a process that outlives the hook and holds none of its handles; is a pid alive | — |
| [`provenance.py`](../src/conpact/provenance.py) | The post-compaction provenance check (a `SessionStart` hook, matcher `compact`): trace each constraint of the summary just written to the user's words, an instruction file, the system prompt, a file the agent wrote itself, another session - or nothing; print it unsourced first, log it, sum the log up | home, provenance_items, provenance_match, provenance_transcript |
| [`provenance_transcript.py`](../src/conpact/provenance_transcript.py) | Read a transcript for that check, sorting whose words are whose: the user's (typed, queued, answers, denials), look-alikes (other sessions, subagents, task chips, `/compact`), the agent's writes to rule files, the summaries, the system prompt | — |
| [`provenance_items.py`](../src/conpact/provenance_items.py) | Pick the constraints out of a summary: constraint lists in their many shapes, and sentences worded as rules | — |
| [`provenance_match.py`](../src/conpact/provenance_match.py) | Whether a constraint plausibly came from a text: content-word containment with a threshold, and whether the matching text seems to say the opposite | — |

### Windows, toast and settings

| Module | Responsibility | Depends on |
|---|---|---|
| [`toast_text.py`](../src/conpact/toast_text.py) | Every word and number format the toast shows | — |
| [`toast_view.py`](../src/conpact/toast_view.py) | The toast window (stdlib Tk): layout, clicks off the UI thread, countdown, Settings link; `--demo` | desktop, detach, idle_state, settings, settings_window, toast_text, ui_style |
| [`ui_style.py`](../src/conpact/ui_style.py) | The look both windows share: fonts, light and dark palettes, the mouse-only button | — |
| [`desktop.py`](../src/conpact/desktop.py) | The desktop's theme and handing it a link, on Windows, macOS and Linux; DPI, work area and focus-free showing on Windows, with a safe default elsewhere | — |
| [`settings.py`](../src/conpact/settings.py) | The user's settings: meaning, default, range; read, check, save (all or nothing), reset | compaction, idle_state |
| [`settings_cli.py`](../src/conpact/settings_cli.py) | The settings command: show, set, reset, or open the window | settings, settings_window |
| [`settings_window.py`](../src/conpact/settings_window.py) | The settings window (stdlib Tk) and the form behind it | desktop, detach, settings, toast_text, ui_style |

### ChatGPT Desktop: reading

| Module | Responsibility | Depends on |
|---|---|---|
| [`codex_home.py`](../src/conpact/codex_home.py) | Where ChatGPT Desktop keeps its state, opened `mode=ro` | — |
| [`codex_threads.py`](../src/conpact/codex_threads.py) | Which Codex threads exist, which are spin-offs, and which a running app holds (its lock probed with msvcrt on Windows, fcntl elsewhere) | codex_home |
| [`codex_meter.py`](../src/conpact/codex_meter.py) | A Codex thread's context size, window and turn state, from its rollout | context_meter |
| [`codex_window.py`](../src/conpact/codex_window.py) | When an idle Codex thread's cache should expire: a measured model, since Codex does not state its lifetime | cache_window, codex_meter, context_meter |
| [`platforms.py`](../src/conpact/platforms.py) | One shape for a session on either app, and why it cannot be compacted. Looks only | codex_home, codex_meter, codex_threads, context_meter, session_registry, spin_off |

### ChatGPT Desktop: compacting and the sidecar

| Module | Responsibility | Depends on |
|---|---|---|
| [`codex_ws.py`](../src/conpact/codex_ws.py) | The stdlib WebSocket client: text frames, client masking, reassembly, pongs, refusals | — |
| [`codex_appserver.py`](../src/conpact/codex_appserver.py) | One JSON-RPC conversation with a Codex app-server over stdio or WebSocket; which codex build the desktop runs, on each platform | codex_ws |
| [`codex_compact.py`](../src/conpact/codex_compact.py) | Compact one Codex thread: conPACT's reachable host for integrated CLI, the sidecar for Desktop, a fresh app-server for a free thread, or a named refusal | codex_appserver, codex_host, codex_inject, codex_threads, platforms |
| [`codex_inject.py`](../src/conpact/codex_inject.py) | Reach the live thread's app-server through the sidecar's control port and inject one tagged `thread/compact/start` | compaction |
| [`codex_sidecar.py`](../src/conpact/codex_sidecar.py) | The sidecar: proxy the desktop's app-server stdio, lift our tagged replies out, serve the token-guarded control port, act on turn ends | codex_active, codex_appserver, codex_sidecar_log, codex_turns, detach |
| [`codex_turns.py`](../src/conpact/codex_turns.py) | Recognise turn starts, turn ends and conPACT tool calls in the app-server's stream. Recognition only | — |
| [`codex_active.py`](../src/conpact/codex_active.py) | Which Codex threads are mid-turn or calling conPACT, published by the sidecar for the MCP tools | compaction |
| [`codex_sidecar_log.py`](../src/conpact/codex_sidecar_log.py) | The opt-in tap on the sidecar's pipes: methods and keys, never values unless asked | — |
| [`codex_arming.py`](../src/conpact/codex_arming.py) | Arm Codex threads for the idle toast (one thread at its turn end, or a sweep of all), and run a queued compaction | codex_compact, codex_meter, codex_threads, codex_window, compaction, detach, idle_arming, idle_state, platforms, settings |
| [`codex_watching.py`](../src/conpact/codex_watching.py) | The watcher's Codex adapter: resumed, reachable, idle, and how to compact | codex_compact, codex_meter, codex_threads, codex_window, platforms, watching |
| [`codex_env.py`](../src/conpact/codex_env.py) | One persistent user environment variable, stored the way each platform makes a GUI app see it | — |
| [`codex_sidecar_install.py`](../src/conpact/codex_sidecar_install.py) | Put the shim in the desktop's path and take it out: the shim, the marker, the one env key | codex_appserver, codex_env, codex_inject, detach |
| [`codex_sidecar_window.py`](../src/conpact/codex_sidecar_window.py) | The one-click window offering Install or Uninstall | codex_sidecar_install, desktop, detach, ui_style |

### ChatGPT Desktop: Remote Control

| Module | Responsibility | Depends on |
|---|---|---|
| [`codex_host.py`](../src/conpact/codex_host.py) | conPACT's own app-server: mint a token, bind loopback, start it detached, record it, wait for `/readyz`, stop it | codex_appserver, compaction, detach |
| [`codex_remote.py`](../src/conpact/codex_remote.py) | Codex Remote Control: what this machine offers (read-only), and the host-side actions | codex_appserver, codex_home, codex_host |
| [`codex_remote_cli.py`](../src/conpact/codex_remote_cli.py) | The remote-control command: `show` reads, every other command is the action typed | codex_remote |
| [`codex_cli.py`](../src/conpact/codex_cli.py) | Merge/remove the Codex Stop hook and launch the TUI as a client of conPACT's app-server | codex_appserver, codex_home, codex_host |
| [`codex_cli_hook.py`](../src/conpact/codex_cli_hook.py) | Run a queued compaction or arm a watch at Stop, only below conPACT's recorded app-server | codex_arming, codex_host, compaction |

## Entry points

Everything outside `src/` is a thin shim.

| File | What it is |
|---|---|
| [`tools/stop_compact.cmd`](../tools/stop_compact.cmd), [`tools/stop_compact.sh`](../tools/stop_compact.sh) | The Stop-hook wrapper, for Windows and for macOS and Linux; the two must agree. Puts `src/` on `PYTHONPATH` and runs `python -m conpact.closure_hook`. Exits without starting Python only when no request is pending in either requests folder *and* the idle toast is off. |
| [`tools/mcp_server.py`](../tools/mcp_server.py) | Shim to `conpact.mcp_server`. Register it with the full path to `python.exe`. |
| [`tools/bridge_send.py`](../tools/bridge_send.py) | Shim to `conpact.cli`, kept at this path for its Bash allow rule. |
| [`tools/settings.py`](../tools/settings.py) | Shim to `conpact.settings_cli`. |
| [`tools/session_ready.py`](../tools/session_ready.py) | Shim to `conpact.session_ready`. |
| [`tools/codex_sessions.py`](../tools/codex_sessions.py) | Read-only listing of every session on both apps. |
| [`tools/codex_sidecar.py`](../tools/codex_sidecar.py) | `install`, `status`, `uninstall`, `window` for the sidecar. `install` makes the shim itself, so there is no separate build step. |
| [`tools/install-sidecar.cmd`](../tools/install-sidecar.cmd), [`tools/install-sidecar.sh`](../tools/install-sidecar.sh) | One click: open the sidecar window. |
| [`tools/codex_remote.py`](../tools/codex_remote.py) | Shim to `conpact.codex_remote_cli`. |
| [`tools/codex_cli.py`](../tools/codex_cli.py) | Shim to the integrated Codex CLI launcher and hook installer. |
| [`tools/doctor.py`](../tools/doctor.py) | Shim to the read-only installed Codex health report. |
| [`tools/compact_provenance.py`](../tools/compact_provenance.py) | Shim to `conpact.provenance`: the post-compaction provenance check, as a hook or by hand (`--transcript`, `--report`). |
| [`tools/mutate.py`](../tools/mutate.py) | The mutation tester. Not imported by anything. |
| [`tools/mutate_mod.py`](../tools/mutate_mod.py) | The mutation tester for the mod, with `claude plugin test` as its oracle. Not imported by anything. |
| [`src/sidecar/codex_launcher.c`](../src/sidecar/codex_launcher.c) | The Windows launcher the desktop spawns; execs the Python sidecar and carries no logic. |

## State files

All under `~/.conpact/`, conPACT's own folder for both apps. Nothing conPACT
writes lives inside Claude Code's `~/.claude/` or ChatGPT Desktop's `~/.codex/`.

| Path | Holds |
|---|---|
| `requests/<sessionId>.json` | A pending compaction request: focus, optional `min_context_tokens`. |
| `hook-log.jsonl` | One line per claimed request: time, session id, outcome (`compacted`, `below_threshold`, `failed`, `error`), reason, HTTP status, whether the token was refreshed, the measured context size and the minimum. Never the token. |
| `settings.json` | Your settings, only the ones you changed. |
| `idle-notify.off` | Present when the idle toast is off. |
| `idle/watch/<sessionId>.json` | The current watch and its stages. |
| `idle/auto/<sessionId>` | Auto-compact is on for that session; holds the stage, `early` or `expiry`. |
| `idle/mute/<sessionId>.json` | Silenced until, and the call it was silenced after. |
| `idle/hold/<sessionId>.json` | The early toast is held until, set by the agent's `hold_idle_toast`. |
| `idle/toasts/slot-N` | Screen slots, so toasts do not overlap. |
| `idle-log.jsonl` | What the watcher did: armed, not_armed, superseded, resumed, cancelled, closed, archived, expired, timeout, dismissed, muted, compacted, compacted_auto_on, auto_compacted, failed, error, and the Codex equivalents. Each with its stage. |
| `codex-sidecar.json` | The running sidecar's address, pid, injection tag and token. |
| `codex-active.json` | Which Codex threads are mid-turn, and which are calling conPACT. |
| `codex-host.json` | conPACT's own app-server for Codex Remote Control. |

Beside the sidecar shim: `real-codex.txt` names the real codex, and on Windows
`launcher.txt` names the interpreter the launcher runs.

The mod keeps its own state in Claude Code's store for the plugin, not here:
`request:<sessionId>` (queued or running), `result:<sessionId>` (the last
outcome) and `handoff:<sessionId>` (the last idle toast request it took), each
cleared after a week. It reads `settings.json`, `idle/hold/<sessionId>.json`
and `mod/ask/<sessionId>.json` from this folder, and writes only under `mod/`:

| Path | Holds |
|---|---|
| `mod/beat/<sessionId>.json` | The mod's heartbeat for that session, every 30 s: the time, and `ended` once the session has ended. |
| `mod/ask/<sessionId>.json` | The idle toast's request to the mod: its id and the time it lapses. Written and removed by the watcher. |
| `mod/answer/<sessionId>.json` | The mod's answer to it: `claimed`, then `compacted`, `skipped` or `error`. |

The watcher clears any of these a week old.

### Moving from an earlier version

Until 2026-09-23 this folder was `~/.claude/conpact/`. The first conPACT process
to start after an upgrade (a turn end, an MCP server, the settings window, the
sidecar) moves its contents to `~/.conpact/`: your settings, the toast's off
switch, each session's auto-compact, silence and hold, the logs and the Codex
records. Nothing already in `~/.conpact/` is overwritten, and a log is added to
rather than replaced. The old folder is removed once it is empty.

Two things are deliberately not moved:

- **Pending requests** stay where they were written and are claimed from there.
  An MCP server keeps the code it started with for as long as its session runs,
  so one started before the upgrade still writes to (and cancels in) the old
  folder. The same holds for `~/.claude/clautomatic/requests/`, from before the
  project was renamed from *Clautomatic*.
- **What a running process still writes**: a watch's marker, a toast's slot,
  and the heartbeat of a sidecar started before the upgrade. They are left to
  that process and removed once they are more than two hours old; the heartbeat
  is read from both folders meanwhile, the fresher winning.

## Project layout

```
conpact/
├── README.md          # start here
├── docs/              # the documentation (docs/README.md is the index)
├── CHANGES.md         # every change, newest first, with how it was verified
├── DECISIONS.md       # every settled design choice, and why
├── LICENSE            # MIT
├── pyproject.toml     # packaging; no runtime dependencies
├── pytest.ini
├── .claude-plugin/    # marketplace.json: installs the mod as conpact@conpact
├── src/
│   ├── conpact/       # the package: all the Python logic
│   ├── mod/           # the Claude Code mod (a plugin) and its tests
│   └── sidecar/       # the Windows launcher source and build script
├── tools/             # thin entry points
└── tests/
    ├── conftest.py    # isolates every test from the real ~/.claude and the network
    ├── test_*.py      # one per module
    └── regression/    # one test per change that altered behaviour, named in CHANGES.md
```

`pytest.ini` makes pytest capture output at the sys level. With fd capture, Tcl
intermittently failed to read its own library files.
