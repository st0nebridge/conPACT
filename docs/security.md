# Security model

conPACT sends commands into live coding sessions, so what it *cannot* do matters
as much as what it does. The short version:

- It only ever acts on the session that asked.
- It only ever sends `/compact` (on Codex, `thread/compact/start`).
- A request fires at most once.
- Your login token is never printed, logged or copied.
- Anything that listens is loopback-only and token-guarded.

The rest of this page is the detail, with the reason for each rule.

## Claude Code

### The command-line tool is self-only and `/compact`-only

`tools/bridge_send.py` is meant to run under a Bash allow rule, that is,
without a permission prompt. Anything it could do would then be done without
asking you, so it can do nothing more than compact the session it runs in.

- There is no free-text sending.
- Explicit selectors (`--name`, `--pid`, `--host-session-id`, `--session-id`)
  work only with `--dry-run`.
- The `--focus` hint is reduced to one printable line of at most 500
  characters, and the command text is built by conPACT, never taken from an
  argument, so a leading slash cannot be mangled.

### The MCP tools are self-only and never execute

They take no target. They bind through their parent process's session record,
corroborated by the `CLAUDE_CODE_SESSION_ID` Claude Code gives every stdio MCP
server, and refuse a stale or foreign identity. They only write, read or delete
the request file; they hold no token and never talk to the bridge. Sending
stays with the Stop hook.

### Target binding comes from the runtime only

The `--self` and Stop-hook target is resolved from the per-process records in
`~/.claude/sessions/<pid>.json`, cross-checked against
`CLAUDE_CODE_HOST_SESSION_ID`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID` and the
Stop hook's own session id:

- **at least two corroborating identifiers** are required when available;
- any conflict disqualifies a record;
- a bridge id supplied by the model or a caller is never trusted;
- session ids become file names or glob patterns only if they are plain ids
  (`[A-Za-z0-9_-]`).

### Execution is at most once, and only at a turn end

The Stop hook may fire a request only if its own delete of the request file
succeeds, so two hooks racing cannot both fire it. A refused or failed send is
logged, never retried, because a retry path could compact a session again and
again.

### The mod compacts only its own session, at most once per request

Where the conPACT mod is loaded it answers the queue, cancel and status tools
in the server's place. It is held to the same rules, plus some of its own:

- **Self only.** It acts on the session it runs in, named by Claude Code
  itself, and refuses a session id that is not plain. Like the server's tools,
  it takes no target, and a call that names one is refused.
- **Only after the turn, at most once.** A request is claimed when the turn
  ends with an answer and then run once. A compaction that ran, was vetoed, or
  was below the minimum ends the request. Only a run that made no compaction
  goes back in the queue, for at most three tries: one Claude Code refused to
  *start* because a new turn was already under way, or a `/compact` that
  compacted nothing. Neither compacts anything, so this cannot compact a
  session twice.
- **Nothing beyond what it lists.** It starts no process, makes no network
  request, runs no command but `/compact` (and that only in a session with no
  terminal behind it, such as the Desktop app's Code tab, where Claude Code
  refuses the direct call), never submits a prompt and never reads the login.
  It writes two kinds of file, both small and both conPACT's: the session's
  heartbeat and its answers to the idle toast, under `~/.conpact/mod/`. Its one
  write call refuses any other path, and any path with `..` in it, before it
  reaches Claude Code. Every call is spelled out in
  `src/mod/hooks/register.js`, and `claude plugin validate src/mod` lists them
  all: the session's id, folder, size and compaction, `/compact`, the mod's own
  store, conPACT's files read and those two written, two environment
  variables, the clock, lines on screen, and the band above the prompt,
  whose two buttons only withdraw a request that has not begun (Cancel) or
  hide a result (Dismiss).
- **The idle toast's request is one compaction, once.** The toast leaves a
  request with an id and a time it lapses, 10 seconds out. The mod takes each id
  once (its store remembers it, since a mod cannot delete the file), never one
  that has lapsed, and only the session's own. It runs the same compaction
  `/compact` runs, with no instructions of conPACT's. A request it did not take
  in time is reported as failed and is not sent over Remote Control instead, so
  a slow mod cannot lead to two compactions.

### The idle toast sends only what you click

- The watcher re-binds the session from the runtime right before sending,
  requires it to be idle since its turn end, sends only a constructed
  `/compact`, and sends at most once per watch.
- The auto-compact switch is per session and set only by your click on the
  toast. The command-line tool and the MCP tools can neither read nor set it.
- The toast is a Tk window inside the watcher process, with no URL handler,
  registry entry or other listener that something else could trigger.
- Its one outward call, opening a session in the app, hands the platform's own
  opener (the shell, `open` or `xdg-open`) a link conPACT built from a checked
  id, as a single argument and never through a shell.
- conPACT never turns Remote Control on for a session, never restarts one and
  never writes to another session. The one Claude Code setting it can write,
  `remoteControlAtStartup`, is written only when you click **Always on for new
  sessions**, and every other key is kept.

### The token never leaks

The OAuth token is read at call time, used only in the `Authorization` header,
refreshed only within the expiry margin, and never printed or logged
(`AccessToken`'s repr is redacted). It is never written anywhere but its own
credentials file, and a failed write-back removes the temp file that held it.
The hook log records whether a refresh happened, never the token.

On macOS the login is read from the Keychain, and only read:

- through `/usr/bin/security` by absolute path, so nothing earlier on `PATH` can
  stand in for it, and only the one item Claude Code files its login under;
- never refreshed there, because a refresh rotates the refresh token and conPACT
  does not write to a credential store Claude Code owns;
- with every refusal built from fixed text and exit codes, so no value the
  Keychain returns can reach an error, a log or the terminal.

### Throwaway sessions are refused

A session working in a `.claude/worktrees/...` checkout is merged and archived
rather than resumed, so compacting it spends a turn on a summary nobody reads.
`queue_compaction` refuses there unless you switch `guard_spin_off_sessions`
off.

## ChatGPT Desktop

### Read-only unless you opt in

Codex's state is opened `mode=ro`. Listing, measuring and the idle toast change
nothing in Codex. The subagents and review threads Codex spawns for itself are
refused, as are archived threads.

### The sidecar is an opt-in interposer, and treated as one

It is installed only by your click or command, is user-scope and reversible, and
fails open at every step: when a part of it fails, the desktop's app-server
still runs, and conPACT simply cannot reach it.

- The desktop's own stream is passed through byte for byte.
- A reply to an id the desktop did not send is never shown to it; conPACT only
  reads replies carrying its own tag.
- Only the desktop's stdio app-server is proxied, nothing else.
- Its control port binds `127.0.0.1` only, and a connection whose first line is
  not the capability token (compared with `hmac.compare_digest`) is closed
  before a byte of it reaches the app-server. A loopback port is reachable by
  any local process, which is exactly why the token is required.
- The optional traffic log records method names and message keys, never values,
  unless you separately ask for bodies.

### conPACT's own app-server is not an open door

It binds `127.0.0.1`, refuses every connection without the token with 401 (on
loopback as well as off it), and is given only the token's SHA-256, so the
secret never reaches its process or its command line.

### Never a remote-control client

Driving a thread the desktop holds from outside would mean enrolling conPACT as
a permanent, device-keyed remote-control client on your ChatGPT account, behind
a step-up authorisation. conPACT does not do that. Every remote-control action
it does take is the host-side one you typed.

### Codex MCP tools fail closed

Codex gives an MCP server no session identity. ChatGPT Desktop's caller is taken
from the sidecar's record of which thread is calling: exactly, from the `mcpToolCall`
item naming the thread, or as the only thread mid-turn. With none, or several,
the tool refuses rather than guess. A resumed desktop task can omit that turn
boundary from the sidecar stream while still writing it to Codex's own rollout;
when the sidecar names no caller, the just-recorded code-mode conPACT invocation
identifies its running rollout. Without that marker, exactly one recent,
non-archived user rollout with `task_started` is required. Stale markers,
spin-offs, sidecar ambiguity, or two conPACT callers all refuse, and so does a
recent rollout that is there but cannot be read, because it might be a second
caller. A thread whose rollout file is missing records no turn and is passed
over. A Claude server never falls back to a Codex thread.

A Codex CLI MCP server is distinguished from Desktop by its direct parent. A
plain `codex`/`codex exec` binds only from its own recent rollout and never
borrows the Desktop sidecar's active thread; queue and idle-hold refuse because
that process exposes no safe execution channel. `conpact-codex` is different by
construction: its MCP server is a child of the exact app-server pid recorded in
`~/.conpact/codex-host.json`, so queue and hold are permitted and the Stop hook
can address only the session id Codex itself supplied. The app-server listens on
127.0.0.1, requires a random capability token, receives only the token's digest
at startup, and the launcher passes the token to the CLI by environment-variable
name rather than putting the secret in argv.
