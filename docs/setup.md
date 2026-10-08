# Setup

conPACT has four pieces on Claude Code.

| Piece | Required? | What it gives you |
|---|---|---|
| [Stop hook](#1-the-stop-hook) | Yes | Arms the idle toast, and sends a queued `/compact` at the end of a turn where the mod is not loaded. |
| [MCP server](#2-the-mcp-server) | Optional | Lets the agent queue a compaction with a tool call. |
| [Remote Control](#3-remote-control) | Per session, without the mod | The route the `/compact` travels wherever the mod is not loaded: for the idle toast and for a queued compaction. |
| [The mod](#4-the-mod) | Recommended | Carries out a queued compaction inside the session, with no Remote Control. Needs the MCP server. |

For ChatGPT Desktop, see [chatgpt-desktop.md](chatgpt-desktop.md#setting-it-up).

## 0. Get the code

```bash
git clone https://github.com/st0nebridge/conPACT.git conpact
```

Python 3.11 or later, and nothing else: conPACT has no third-party
dependencies. The tools run straight from the checkout; they put `src/` on the
path themselves. If you use uv and want the commands available from every new
terminal, install the checkout as an editable tool:

```bash
uv tool install --editable .
uv tool update-shell
```

Alternatively, `pip install -e .` installs the same entry points. They include
`conpact`, `conpact-settings`, `conpact-mcp`, `conpact-codex`,
`conpact-codex-remote` and `conpact-sidecar`.

The toast and the settings window are Tk, which ships with Python on Windows and
with the python.org installer on macOS. Some Linux distributions package it
separately (`python3-tk` on Debian and Ubuntu); without it everything works
except the windows themselves.

On macOS and Linux, read `python` as `python3` in the commands in these pages.

### What each platform supports

| | Windows | Linux | macOS |
|---|---|---|---|
| Queue a compaction | ✓ | ✓ | ✓ |
| Send it to a Claude Code session | ✓ | ✓ | ✓, with the login read from the Keychain (see below) |
| Idle toast | ✓ | ✓ (with Tk) | ✓ |
| Session readiness check | ✓ | ✓ | ✓ |
| ChatGPT Desktop sidecar | ✓ | ✓ | ✓ |
| Codex CLI launcher and Stop hook | ✓ | ✓ | ✓ |
| Claude Code mod (compacting without Remote Control) | ✓, used live | its tests | its tests |
| Tested | whole suite, and live | whole suite, on WSL | whole suite on an Intel Mac |

**macOS and the Claude Code login token.** This section does not apply to
ChatGPT Desktop or Codex CLI: conPACT never reads their credentials. Sending
`/compact` to **Claude Code** over Remote Control needs Claude Code's login token.
On Windows and Linux Claude Code keeps it in
`~/.claude/.credentials.json`. On macOS it keeps it in the Keychain, and conPACT
reads it from there, through `/usr/bin/security`, the same entry Claude Code
itself uses. Two things follow:

- **macOS may ask once** whether to let `security` read the "Claude Code-credentials"
  item. Choose **Always Allow**, or it will ask each time a compaction is sent. A
  prompt left unanswered for 45 seconds is treated as a refusal.
- **conPACT only reads the Keychain, never writes it.** On Windows and Linux it
  refreshes an expired token and saves the new one, as Claude Code does. On a Mac
  it does not: a refresh replaces the refresh token, and one conPACT did not save
  back would log Claude Code out. An expired token is refused instead, and
  Claude Code refreshes it on its own next request, which in practice is the
  turn that just ended.

## 1. The Stop hook

Add it to `~/.claude/settings.json` under `hooks`. The command is the one
wrapper for your platform:

| Platform | `command` |
|---|---|
| Windows | `C:/path/to/conpact/tools/stop_compact.cmd` |
| macOS, Linux | `/path/to/conpact/tools/stop_compact.sh` |

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/conpact/tools/stop_compact.sh",
            "timeout": 90
          }
        ]
      }
    ]
  }
}
```

The two wrappers do the same thing: run `python -m conpact.closure_hook` with the
checkout's `src/` on the path, and hand it the hook's input. The `.sh` runs
`python3`; set `CONPACT_PYTHON` to use a different interpreter. It is committed
executable; if your checkout lost the bit, `chmod +x tools/stop_compact.sh`.

The hook writes nothing to stdout, never raises and always exits 0, so it cannot
disturb a session. With the idle toast switched off and no request pending, it
does not even start Python.

Claude Code reads the hook from settings at every turn end, so it starts working
in sessions that were already open, without a restart.

## 2. The MCP server

Register it for every project, with the **full path to the Python executable**
(`python.exe` on Windows, `python3` elsewhere):

```bash
claude mcp add --scope user conpact -- "/path/to/python3" "/path/to/conpact/tools/mcp_server.py"
```

The server binds to the session of the process that started it, so it must be
started by Claude Code directly. A `python` shim such as pyenv-win's
`python.bat` would put `cmd.exe` in between, and the binding would be refused.

Claude Code shows the tools as `mcp__conpact__<name>`:

| Tool | Does |
|---|---|
| `queue_compaction` | Queue `/compact` for this session at the end of the turn. Optional `focus`, optional `min_context_tokens`. Queuing again replaces the request. In a `.claude/worktrees/...` checkout it answers `queued: false` and queues nothing (`guard_spin_off_sessions`). |
| `cancel_compaction` | Withdraw the queued request. |
| `hold_idle_toast` | Hold *this* session's early idle toast while a run waits on a build or a test suite: `minutes` (default 30, at most 120), `0` releases it, optional `reason`. The toast before the cache expires still comes. It can never send or compact. |
| `compaction_status` | Show what is queued, the current context size and any hold. Read-only. |

None of them takes a target, reads the login token or talks to the bridge. The
server also hands the agent instructions on when to use them: queue at the end
of a finished piece of work, never in a throwaway worktree session.

After `/clear` or a resume, reconnect the server from `/mcp`. Until then it
refuses rather than guess which session it belongs to.

## 3. Remote Control

Remote Control is a per-session switch in the session's toolbar. It is what puts
a `bridgeSessionId` in the session's record, and every path that sends
`/compact` needs it: the toast, and the queue tool and the hook wherever the mod
is not loaded, all refuse without it. A session with the mod loaded compacts
itself without it.

You do not have to hunt for it. When a session without it has been idle long
enough to be worth compacting, the idle toast asks, and offers **Always on for
new sessions**, which sets Claude Code's own `remoteControlAtStartup`.

## 4. The mod

The mod is a Claude Code plugin in `src/mod`. Where it loads, it answers the MCP
server's queue, cancel and status tools itself and compacts the session from
inside Claude Code when the turn ends. Install it from this repository's
marketplace:

```bash
claude plugin marketplace add st0nebridge/conPACT
claude plugin install conpact@conpact
```

It needs Claude Code 2.1.284 or later, and before 2.1.287 the early-access
switch `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` in the `env` block of
`~/.claude/settings.json`. Sessions load it when they start. Everything else
about it, including loading it from your checkout and what it can reach:
[claude-code-mod.md](claude-code-mod.md).

## Codex CLI

The installed Stop command points to this copy of conPACT, so it also works
from a checkout without an editable install. After moving or updating that
copy, run `--install` again to refresh conPACT's handler; other hooks are kept.

Codex CLI has a Stop hook, but a normal interactive `codex` process does not
expose the app-server connection that owns its active task. conPACT uses the
CLI's remote-app-server mode so that same owning process is safely reachable at
turn end.

With the editable install from step 0:

```bash
conpact-codex --install
conpact-codex
```

Or directly from the checkout:

```bash
python tools/codex_cli.py --install
python tools/codex_cli.py
```

The installer merges one synchronous `Stop` handler into
`~/.codex/hooks.json`, preserves every existing hook, and writes the original
file once as `hooks.json.conpact-backup`. On the next CLI start, use `/hooks` to
review and trust the conPACT handler. Codex requires that trust for user hooks;
conPACT does not bypass it.

`conpact-codex` starts or reuses conPACT's capability-token-protected app-server
on `127.0.0.1`, and execs the real Codex TUI with `--remote`. The secret is
named through `--remote-auth-token-env` and never appears in the process
arguments. `queue_compaction`, `cancel_compaction`, `compaction_status`,
`hold_idle_toast`, and the idle watcher then work for that CLI task. A plain
`codex` launch remains untouched and continues to refuse queue and hold rather
than strand work it cannot execute.

Check or remove only this integration:

```bash
conpact-codex --status
conpact-codex --uninstall
```

## Sessions that were already open

The three pieces reach a running session in different ways, so a session that
was open before you installed anything can end up half-working. To see which
half:

```bash
python tools/session_ready.py
```

```
conPACT readiness: 3 of 8 sessions ready

  session                            pid  remote mcp  hook last seen
  API refactor                     20148  yes    NO   2026-09-19T07:27:36Z
  Docs site                        28248  NO     yes  2026-09-20T00:16:44Z
  ...
```

| Piece | How it reaches a session | If it is missing |
|---|---|---|
| **Stop hook** | Read at every turn end, so it works in sessions that were already open. | Nothing to do. A hook that has never been *seen* has simply had nothing to say: a quiet turn end writes no log line. |
| **MCP server** | Started as a child of the session's own process, only when that process starts. A session older than the registration has no tools, and no amount of waiting will give it any. | Reopen the session. Restarting the app does it for every session at once. |
| **Remote Control** | A per-session switch. | Wait for the idle toast to ask, or turn it on in the session's toolbar. |

The check only reads: the session records, which MCP servers the operating
system says are running and under which process, and the two logs. It sends
nothing and changes nothing: it never turns Remote Control on, restarts a
session or writes to one, because each of those is yours to decide. It exits 1
while any session still needs something, so it can gate a setup script.

## Uninstalling

Remove the Stop hook entry from `~/.claude/settings.json`, then
`claude mcp remove --scope user conpact` and `claude plugin uninstall
conpact@conpact` (or take `src/mod` out of `CLAUDE_CODE_PLUGIN_DIRS`). conPACT's own state is the folder
`~/.conpact/`, safe to delete once no session is using it. If you are removing
an earlier version, its folder was `~/.claude/conpact/`.
