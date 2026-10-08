# Commands

Every tool in `tools/` runs from the conPACT folder with plain `python`
(`python3` on macOS and Linux); each puts `src/` on the path itself. After
`uv tool install --editable .` (or `pip install -e .`) the main ones are also
on your `PATH`:

| Installed command | Same as |
|---|---|
| `conpact` | `python tools/bridge_send.py` |
| `conpact-settings` | `python tools/settings.py` |
| `conpact-mcp` | `python tools/mcp_server.py` |
| `conpact-codex-remote` | `python tools/codex_remote.py` |
| `conpact-codex` | `python tools/codex_cli.py` |
| `conpact-sidecar` | `python tools/codex_sidecar.py window` |

## Codex CLI: `codex_cli.py`

```bash
conpact-codex --install       # merge the Stop hook into ~/.codex/hooks.json
conpact-codex                 # start an integrated interactive CLI
conpact-codex resume <id>     # resume through the same reachable app-server
conpact-codex --status        # hook and local app-server status
conpact-codex --uninstall     # remove only conPACT's hook
```

The first CLI start asks you to review hooks. Trust the conPACT command once.
The launcher never replaces `codex`; plain Codex CLI continues to behave as it
did before. The integrated launcher is required for automatic turn-end
compaction because it makes the lock-owning app-server reachable.

## Installed Codex health: `doctor.py`

```bash
python tools/doctor.py
```

Read-only. Checks the Codex login, MCP registration, ChatGPT Desktop sidecar,
Codex CLI hook/app-server, bundled Codex build and Codex state. On macOS it reports Claude Code's optional
Keychain login separately; that credential is not used by Codex or ChatGPT
Desktop.

## Compacting a Claude Code session: `bridge_send.py`

```bash
# Record a request for THIS session; the Stop hook fires it at turn end
python tools/bridge_send.py --self --request

# ...only if the context is at least 150k tokens by then, with a focus for the summary
python tools/bridge_send.py --self --request --min-context-tokens 150k --focus "keep the open questions"

# Compact THIS session right now (see the warning below)
python tools/bridge_send.py --self --compact

# Show what would happen: resolve and print the target, send and record nothing
python tools/bridge_send.py --self --compact --dry-run
python tools/bridge_send.py --self --request --dry-run

# Inspect ANOTHER session (explicit selectors are --dry-run only)
python tools/bridge_send.py --name "Hello" --compact --dry-run

# Is the stored login token fresh, and where is it kept? (never prints the token)
python tools/bridge_send.py --token-status
```

| Option | Meaning |
|---|---|
| `--request` | Record a request; the Stop hook sends `/compact` at turn end. |
| `--compact` | Send `/compact` now. |
| `--token-status` | Report whether the stored login token is fresh. |
| `--focus TEXT` | Focus hint for the summary: one line, at most 500 characters. |
| `--min-context-tokens N` | With `--request`: fire only if the context is at least N at turn end (`150000`, `150k`, `1.5m`). |
| `--dry-run` | Resolve the target and show what would happen; send and record nothing. |
| `--self` | The session this command runs in, resolved from the runtime. |
| `--name`, `--pid`, `--host-session-id`, `--session-id` | Another session. Only with `--dry-run`. |

> ⚠️ `--self --compact` run from inside a turn does **not** compact: the
> `/compact` arrives while the session is busy and is injected into the running
> turn as plain text (observed 2026-09-19). Use `--request`, which the Stop hook
> sends as the turn ends.

## Settings: `settings.py`

```bash
python tools/settings.py                    # the window
python tools/settings.py show               # every setting, its value and what it accepts
python tools/settings.py set KEY VALUE [KEY VALUE ...]   # all or none
python tools/settings.py reset [KEY ...]    # the named ones, or all
```

See [settings.md](settings.md).

## What each session still needs: `session_ready.py`

```bash
python tools/session_ready.py
```

Read-only. Lists each live Claude Code session with whether it has Remote
Control, the MCP server and a Stop hook that has spoken for it. Exits 1 while any
session still needs something. See [setup.md](setup.md#sessions-that-were-already-open).

## Both apps in one listing: `codex_sessions.py`

```bash
python tools/codex_sessions.py                 # both apps, with how full each context is
python tools/codex_sessions.py --platform codex
python tools/codex_sessions.py --all           # include spin-offs and archived sessions
python tools/codex_sessions.py --remote        # also Codex's remote-control state
```

| Option | Meaning |
|---|---|
| `--platform {claude,codex}` | Only one app (default: both). |
| `--all` | Include spin-offs and archived sessions. |
| `--limit N` | How many Codex threads to read (default 20). |
| `--quiet` | Names only, no measuring. |
| `--remote` | Also show Codex's remote-control state for this machine. |

Changes nothing, starts nothing, sends nothing.

## The ChatGPT Desktop sidecar: `codex_sidecar.py`

```bash
python tools/codex_sidecar.py window      # one click: Install or Uninstall, whichever applies
python tools/codex_sidecar.py status
python tools/codex_sidecar.py install
python tools/codex_sidecar.py uninstall
```

`tools/install-sidecar.cmd` (Windows) and `tools/install-sidecar.sh` (macOS,
Linux) open the same window. Restart ChatGPT Desktop after installing or
uninstalling. See [chatgpt-desktop.md](chatgpt-desktop.md#the-sidecar).

## Codex Remote Control: `codex_remote.py`

With no command it only reads. Every other command is the action you typed.

| Command | Does |
|---|---|
| `show` | What remote control is doing here (read-only; the default). |
| `start` / `stop` | Start or stop conPACT's own app-server (loopback, token-protected). |
| `enable` / `disable` | Offer that app-server for remote control, or stop offering it. |
| `pair` | Print a short-lived pairing code for one client. |
| `claimed` | Has the pairing code been taken up yet? |
| `remote` | What the app-server says about its own remote control. |
| `clients` | List the clients paired to this machine. |
| `revoke` | Unpair one client by its id. |

See [chatgpt-desktop.md](chatgpt-desktop.md#codex-remote-control).

## Arming Codex threads without Claude Code

On a machine with a Stop hook, Codex threads are armed for the idle toast by the
sidecar at each turn end, and swept from Claude's Stop hook as a fallback. A
machine with only ChatGPT Desktop and no sidecar has no Stop hook to sweep from,
so run the sweep yourself (or on a schedule):

```bash
PYTHONPATH=src python -m conpact.codex_arming
```

## Previewing the toast

```bash
PYTHONPATH=src python -m conpact.toast_view --demo early   # ask, early, notice, failed, remote
```

Sends nothing.

## For developers

```bash
pip install pytest jsonschema              # what the suite needs; conPACT itself needs nothing
python -m pytest -q                        # the suite
python tools/mutate.py <project_root> <out_prefix> [workers] [module_glob]   # mutation testing
```

`tools/mutate.py` is the mutation tester behind every score in
[verification.md](verification.md#mutation). It is not imported by anything; its
own docstring is the manual.
