# ChatGPT Desktop (Codex)

ChatGPT Desktop's coding agent, Codex, is conPACT's second platform. Out of the
box conPACT only **reads** it. Compacting the thread you are working in takes
one opt-in step: installing the sidecar.

| | Without the sidecar | With the sidecar |
|---|---|---|
| List and measure threads | ✓ | ✓ |
| Idle toast | ✓ (armed by a sweep) | ✓ (armed at each turn end) |
| Compact a thread no app has open | ✓ | ✓ |
| Compact the thread the app has open | refused, with the reason | ✓ |
| `queue_compaction` from a Codex thread | — | ✓ |

## Setting it up

1. **Install the sidecar**, one click:

   ```bash
   python tools/codex_sidecar.py window
   ```

   or double-click `tools/install-sidecar.cmd` (Windows) or run
   `tools/install-sidecar.sh` (macOS, Linux).

2. **Restart ChatGPT Desktop.**

3. **Optionally, register the MCP server** so a Codex thread can queue its own
   compaction. Add to `~/.codex/config.toml`:

   ```toml
   [mcp_servers.conpact]
   command = 'C:\path\to\python.exe'
   args = ["-m", "conpact.mcp_server"]
   startup_timeout_sec = 120

   [mcp_servers.conpact.env]
   PYTHONPATH = 'C:\path\to\conpact\src'
   CODEX_HOME = 'C:\Users\<you>\.codex'
   ```

   and restart ChatGPT Desktop again. See
   [MCP tools in a Codex thread](#mcp-tools-in-a-codex-thread).

To check what conPACT sees:

```bash
python tools/codex_sessions.py --platform codex
```

## What conPACT reads

Codex's threads are listed, measured and guarded by the same rules as Claude
sessions:

- **Measured:** the context size *and* the model's window, which Claude Code
  does not publish. That is why a Codex thread's "big enough" is a fraction of
  its window (`min_context_fill`, default 50%) rather than a token count.
- **Guarded:** the threads Codex spawns for itself (subagents, and the guardian
  review it runs after a turn) are throwaways in the sense of a
  `.claude/worktrees/` checkout and are refused, as are archived threads.
- **Read-only:** Codex's state is opened `mode=ro`, so nothing on the read path
  can write to it.
- **Held or free:** whether the app has a thread open is read from Codex's own
  lock on it. On Windows that is a byte-range lock, measured. On macOS and Linux
  which of the two Unix lock kinds Codex takes has not been measured, so both
  are tested, and a thread counts as held if either is taken.

`tools/codex_sessions.py` shows both apps in one listing.

## How a Codex thread is compacted

Compaction on the app-server is the JSON-RPC method `thread/compact/start`.
Current Codex clients also expose `/compact`, but queued MCP work cannot safely
pretend to be interactive slash-command input; conPACT calls the owning
app-server method instead.

There are two routes, and which one a thread needs is the whole story:

- **A thread no app has open** is compacted by an app-server of conPACT's own:
  connect, resume the thread, call the method. Codex's own per-thread
  byte-range writer lock keeps that safe.
- **A thread ChatGPT Desktop has open** (the live thread, the one actually worth
  compacting) may only be written by the app-server that holds its lock. That
  is the desktop's own, a stdio child with no socket, so conPACT cannot connect
  to it. It is reached through the **sidecar**.

When no sidecar is installed, a thread the desktop holds is refused with that
reason, so nothing changes on a machine that has not opted in.

For a loaded thread, conPACT calls compaction directly. Only Codex's explicit
`thread not found` refusal permits a metadata-only resume (`excludeTurns: true`)
followed by one submission. Another refusal or an uncertain transport result
ends the attempt; conPACT never resubmits it through another app-server.

The RPC response acknowledges the start. Success requires a new compaction
record in the exact target rollout and completion of that same turn. An abort,
missing completion or observation timeout is reported separately. Connection,
resume, submission and observation share one deadline. This does not interrupt
a Desktop compaction whose completion remains unconfirmed.

## The sidecar

### What it is

ChatGPT Desktop finds its app-server through the `CODEX_CLI_PATH` environment
variable, ahead of the binary it bundles. The sidecar runs at that path. It:

1. execs the real codex, and proxies its stdin and stdout faithfully;
2. offers one control connection, on which conPACT injects `thread/compact/start`
   into the very process that holds the thread's lock;
3. tags each injected request and lifts its reply out of the stream, so the
   desktop never sees a response to an id it did not send.

Lifted replies are delivered by a separate sender with a bounded queue and
socket timeout. A client that stops reading cannot hold the shared Desktop
output stream. Each app-server has its own control address record under
`~/.conpact/codex-sidecars/<app-server-pid>.json`. Detached turn-end workers carry
that exact owner; the global `codex-sidecar.json` is a diagnostic pointer and
is used for execution only when its recorded owner matches. Failure to publish
the control record leaves the Desktop proxy running without injection.

It is an interposer, and installed deliberately. It is user-scope and
reversible, and it fails open at every step: when a part of it fails, the
desktop's app-server still runs, and conPACT simply cannot reach it.

### Python proxy, three platforms

The same Python proxy (`conpact.codex_sidecar`) and control sender run on
Windows, macOS and Linux. Only how the desktop starts it differs:

- **macOS and Linux:** the shim is a generated shell script that execs your
  interpreter. Nothing is compiled.
- **Windows:** the desktop spawns a real executable and nothing else. Node has
  never run a `.py`, and refuses a `.cmd` without a shell. So a ~90-line
  launcher ([`codex_launcher.c`](../src/sidecar/codex_launcher.c)) execs the
  module and carries no logic of its own.

The control channel is a loopback TCP port guarded by a capability token. The
sidecar binds `127.0.0.1` on a port the system picks, and closes any connection
whose first line is not the token before a byte of it reaches the app-server.

### What installing changes

Wheel and source-archive installations include the Windows launcher sources.
They build the shim under `~/.conpact/sidecar/`, in a separate directory for each
Python installation. A checkout keeps its existing `src/sidecar/` location.
On Windows, LLVM's `clang` or the MSVC compiler must be available on `PATH`.

The window offers Install or Uninstall, whichever applies, and does the rest:

- makes the shim (compiling the launcher on Windows, generating the script
  elsewhere);
- names the real codex in a marker file, `real-codex.txt`, beside the shim;
- points `CODEX_CLI_PATH` at the shim in your own user environment, stored the
  way each platform makes a GUI app see it
  ([`codex_env.py`](../src/conpact/codex_env.py)): `HKCU\Environment` on
  Windows, `launchctl` plus a login agent on macOS, `~/.config/environment.d`
  on Linux. One key, user scope, reversible.

`python tools/codex_sidecar.py install`, `uninstall` and `status` do the same
from a terminal. conPACT's own tooling resolves *through* the marker, so it
always reaches the real codex, never the shim.

### Which codex build it runs

`status` shows the recorded marker, the newest installed build, and the build
selected for the next launch (`codex_selected`, `codex_selection`). The recorded
marker can be older without affecting automatic selection.

Where the desktop keeps that codex depends on the platform, and was read from
the desktop's own code: the binary is `codex.exe` on Windows and `codex`
elsewhere, in the app's resources folder, and only Windows then moves it out.

| Platform | Where conPACT looks |
|---|---|
| Windows | `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`, plus installed OpenAI app resources under `%ProgramFiles%\WindowsApps` |
| macOS | `Contents/Resources/codex` inside any app in `/Applications` or `~/Applications` |
| Linux | `resources/codex` inside any app in `/opt`, `/usr/lib` or `~/.local/share` |

The app's own name is not assumed; any app that ships a codex counts. Only the
Windows layout has been seen on a real machine. Where none is found, `codex` on
your `PATH` is used, and `CONPACT_CODEX_REAL` overrides all of it.

On Windows each build goes into a folder named by a content hash, and those names
carry no order. So on every platform conPACT picks the **most recently
installed** build, by modification time, and the shim runs what the desktop
would have run without it. It never pins an older build to route around a fault
upstream: a shim that quietly ran a different codex than the desktop asked for
would make every upstream fault look like conPACT's, and hide the ones that
are.

- The sidecar detects the newest installed build on every launch. The marker
  written at installation is used only when no installed build can be found.
  This prevents an old marker from launching a superseded build whose tool
  host Codex may remove while the app-server is running.
- On Windows, the shim override can bypass Desktop's normal copy of the new
  bundled Codex into its cache. Detection therefore checks the installed app
  resources too, using a newer bundle directly when needed. A matching cached
  copy takes precedence; an unreadable app directory leaves cache lookup working.
- To hold a specific build deliberately, set `CONPACT_CODEX_REAL` to its path.
  That one variable pins the shim *and* the app-servers conPACT starts itself,
  and it is taken ahead of everything else.

If a running app-server's build has already lost its helpers, fully quit and
restart ChatGPT Desktop. Build selection applies when the process starts;
an existing app-server cannot switch executables while keeping its threads open.

### When native inference stalls on WebSockets

Codex's outbound model connection is separate from the sidecar's local control
channel. If native logs repeatedly report `idle timeout waiting for websocket`
and then `falling back to HTTP`, an explicit HTTP-only provider can avoid those
WebSocket attempts. This also applies to native automatic context compaction.

Merge the [HTTP configuration fragment](codex-http.toml) into your user-level
Codex `config.toml`: `model_provider` belongs before any table header, and
`[model_providers.openai-http]` is a separate table. The provider retains native
OpenAI authentication and its default endpoint. Existing model, reasoning and
sign-in settings remain in effect. Current builds reject attempts to override
the reserved built-in `openai` provider, so use the distinct ID shown.

Native resume also keeps a history's saved provider when Desktop sends a null
provider. With this explicit configuration, the sidecar selects `openai-http`
on Desktop resume/fork requests for histories recorded under `openai`, using
read-only metadata snapshotted at launch. A supplied rollout path must match.
Explicit providers, provider/profile overrides, custom-provider histories and
unknown targets keep their original behavior. The input pump performs no I/O;
the sidecar does not start, stop or resume a thread itself.

Already running turns can retain their original provider. Finish or stop those
turns yourself and restart Desktop to load the configuration and resume policy.
Revert by removing the added provider table and restoring the previous root
`model_provider` setting (or removing that setting if it was absent). This is
an optional local workaround; installing conPACT does not enable it.

The opt-in regression probe drives the selected native executable against a
local fake backend, using synthetic file credentials and temporary state:
`python tests/regression/test_codex_http_probe.py <native-codex-executable>`.
It first saves history under the built-in provider, then exercises the production
resume selector. It requires a completed normal response, a recorded manual
compaction and zero WebSocket upgrades after resume. Adding
`--websocket-control` enables the failing transport baseline.
The probe does not spend account tokens or load Desktop's chats.

### Diagnosing the pipes

Set `CONPACT_SIDECAR_LOG` to a file path to have the sidecar record what the
desktop asked for and what came back: direction, id, method, error, and the keys
of each message. Values are never written unless you also set
`CONPACT_SIDECAR_LOG_BODIES=1`, because this traffic carries your account, your
usage and your conversations. With the variable unset, the tap does not exist:
no file, no cost, no change to a byte on the wire.

### Removing it

Open the window again and click Uninstall, or run
`python tools/codex_sidecar.py uninstall`, then restart ChatGPT Desktop.

## The turn-end hook

Current Codex CLI releases have a Stop hook with the exact session id. The
`conpact-codex` launcher uses it because the CLI is connected to conPACT's own
reachable app-server. ChatGPT Desktop still uses the sidecar event below: its
separate stdio app-server is reached through the sidecar, not through the CLI
launcher's listener.

The CLI Stop hook validates the listener's ancestry and detaches a worker with
that same owner. The hook returns before the worker waits for the turn to end,
so compaction cannot hold the Stop hook whose completion it needs. Listener
connections recheck the expected owner before sending a request.

The sidecar makes that unnecessary. The app-server pushes `turn/completed` to
the desktop, and the sidecar sees every byte of that stream. So when a thread
finishes a turn, the sidecar starts the arming for that one thread, detached and
after the desktop's bytes are written, so the desktop never waits on it.
Measured live: 605 ms from `turn/completed` to an armed watch.

The sweep is kept as the fallback. It covers threads that were already idle when
the sidecar started, and machines with no sidecar. It runs from Claude's Stop
hook, or on its own: `PYTHONPATH=src python -m conpact.codex_arming`.

## MCP tools in a Codex thread

With the MCP server registered in `config.toml`, a Codex thread gets the same
four tools as a Claude session: `queue_compaction`, `cancel_compaction`,
`compaction_status` and `hold_idle_toast`.

The registration is shared with Codex CLI. In the CLI, conPACT identifies the
calling rollout from the MCP server's direct parent and the just-recorded tool
call, even while ChatGPT Desktop has other turns running. When started through
`conpact-codex`, the direct parent is conPACT's recorded app-server, so all four
tools work and the Stop hook executes queued compaction on that same owner. A
plain `codex` launch still supports `compaction_status` and
`cancel_compaction`; `queue_compaction` and `hold_idle_toast` refuse rather than
leave work with no safe executor.

### How it knows which thread is asking

Codex hands an MCP server no session identity at all, so the server cannot bind
itself the way a Claude one does. The MCP server first reads its direct parent's
command line and process id: conPACT's recorded listener is the integrated CLI,
another `codex ... app-server` is ChatGPT Desktop, while `codex` or `codex exec`
is a plain CLI. Desktop then uses the sidecar's
`~/.conpact/codex-active.json`:

1. **Exactly, when it can.** When a thread calls a tool, the app-server announces
   an `mcpToolCall` item naming both the server and the thread. If the server is
   conPACT, that thread is the caller, however many other turns are running.
   The record must name this MCP server's parent process and the current tool
   method. A call from another app-server or to another method cannot bind it.
2. **From the rollout when the sidecar missed a boundary.** Some resumed desktop
   tasks write `task_started` to their rollout without forwarding the matching
   notification through the sidecar stream. If the sidecar names no caller,
   exactly one recent, non-archived user rollout must record an outstanding,
   awaited invocation of the current conPACT method. Mentions in comments or
   strings do not count. Old markers and spin-offs do not count, and concurrent
   calls to that method refuse.
   The open call is read within the newest 200 records; a long turn's start
   may be further back and is not required. A newer turn boundary, final answer
   or returned tool result clears an older call. Binding polls the current call
   without first scanning the turn's older history.
   A thread whose rollout file is not there is passed over, since it records
   no turn; a recent rollout that is there but cannot be read refuses, since
   it might be a second caller.
3. **Otherwise it refuses.** A running turn alone never identifies a caller.
   The failure worth avoiding is acting on a thread that did not ask.

The CLI never consults the Desktop sidecar record. It waits at most half a
second for its outer MCP call to reach its rollout, then requires exactly one
calling rollout. This keeps a CLI call
from binding to whichever Desktop task happens to be active.

The platform is decided from the server's own environment, never by trying
Claude and falling back, so on a machine running both apps a Claude server can
never reach a Codex thread.

### When the compaction runs

An agent queues compaction when the user explicitly asks, or after verified,
saved implementation work. Routine questions, read-only investigations,
status reports and intermediate answers do not queue it, even when their
context is large. A finished answer alone is not a compaction trigger.

As on Claude Code, the tool records the request and sends nothing. When that
thread's turn completes, the worker checks that the request preceded that event
and the rollout is observably idle. A delayed worker leaves a newer request
pending; a running or unknown turn state also leaves it pending. An atomic
claim preserves a replacement queued during the check. State is checked again
before the request is sent. A claimed request fires at most once.
Competing workers take a process-shared lease before consuming a generation;
busy or unavailable ownership leaves the request untouched.

Closure requests use their own `min_context_tokens`, or
`closure_min_context_tokens` when configured. The idle toast's separate minimum
does not impose a minimum on an agent-queued closure request.

Restart Desktop to load updated sidecar code. MCP-only code updates require
a fresh MCP client, since older processes keep their imported modules and a
native configuration reload can reuse unchanged connections. A changed
`CONPACT_MCP_REVISION` value in conPACT's server environment gives Codex a new
client configuration identity. Back up the configuration, preserve its other
settings, reload MCP configuration and verify an actual tool call before
declaring the update active. IDE and CLI clients also need to load fresh code.

A caller-identification refusal applies to the failed call, rather than
disabling compaction for that chat. Report it and investigate the integration;
do not guess a target or blindly resubmit the same request. Once the integration
is repaired, a later completed piece of work can check `compaction_status`
again and queue only with a fresh, unambiguous binding. In code mode, direct
awaited calls and literal tool calls in awaited `Promise.all` or
`Promise.allSettled` arrays identify the calling method. Deferred callbacks,
quoted examples and unknown wrappers provide no identity. Desktop allows up to
0.5 seconds of polling for a call record to appear, without sending any action
while waiting; known caller ambiguity or a foreign owner refuses immediately.

On refusal, each helper retains its latest diagnostic in
`~/.conpact/codex-caller/<pid>.json`: the owning process, method, polling count,
record ages and last call-lifecycle kind/time. Each file is capped at 8 KiB and
replaced atomically. No tool arguments, call source or rollout paths are saved;
a diagnostic write failure leaves the refusal unchanged.

Observed live on 2026-09-22: a thread queued its own compaction, the sidecar
logged `codex_compacted` at 11:04:42Z under the old acceptance-based logging,
and the thread's rollout recorded the compaction 9 seconds later. Current
logging waits for recorded completion. See
[verification.md](verification.md#chatgpt-desktop).

## Codex Remote Control

This is Codex's counterpart of the Remote Control switch in a Claude session's
toolbar, and the shape differs in a way that decides the design.

On Claude, a session offers *itself* over the bridge. On Codex, the thing offered
is an **app-server**, which enrols with the backend as a *server* and is then
driven by paired clients. So conPACT **runs an app-server of its own** and
offers that:

```
codex app-server --listen ws://127.0.0.1:<port> --ws-auth capability-token --ws-token-sha256 <digest>
```

It is started detached, recorded in `~/.conpact/codex-host.json`, reached
over a standard-library WebSocket client on `/rpc`, and stopped by the pid
conPACT wrote down. Every action is one call on it
(`remoteControl/{status/read,enable,disable,pairing/start,pairing/status,client/list,client/revoke}`),
so no CLI subprocess is involved beyond starting the server.

```bash
python tools/codex_remote.py            # read the state; changes nothing
python tools/codex_remote.py start      # then enable, pair, clients, revoke, stop ...
```

See [commands.md](commands.md#codex-remote-control-codex_remotepy) for every
command.

conPACT never enrols as a remote-control *client*. That half is a device-keyed
credential minted behind a step-up authorisation: a permanent capability on your
ChatGPT account, which conPACT has no business holding. It is also the only
remote route to a thread the running app holds, which is why a live thread is
reached through the sidecar instead.

### Why not Codex's own shared daemon?

It exists for exactly this, but it cannot run here, structurally:

- it starts only from a **packaged** CLI (one whose folder carries
  `codex-package.json`), and the copy ChatGPT Desktop installs is not one;
- `codex app-server daemon bootstrap` refuses for the same reason, so it cannot
  install its own prerequisite;
- its control socket is AF_UNIX, which Python on Windows cannot open.

### Four things measured, not assumed

Each is a refusal with a name rather than something to retry.

- **The listener is not an open door.** Without `--ws-auth`, any local process
  could drive your Codex account. With it, every upgrade lacking the token is
  refused **401, on loopback as well as off it**, and the app-server is given
  only the token's SHA-256, so the secret never reaches its process or its argv.
  It binds `127.0.0.1` and nothing else.
- **The desktop never shares an app-server with us on Windows.** Its launcher
  takes the shared socket only when `process.platform !== "win32"`, and also
  requires `CODEX_APP_SERVER_USE_LOCAL_DAEMON=1`, an empty `CODEX_CLI_PATH`, a
  null `codex_cli_command` and a daemon whose version its own probe accepts. So
  a server conPACT starts is its alone.
- **The app-server's API was asked, not assumed.** The handshake must declare
  `capabilities: {experimentalApi: true}`, or `remoteControl/status/read`
  answers *"requires experimentalApi capability"*. `client/list` and
  `client/revoke` are scoped to an `environmentId` and refused without one. The
  list's `limit` must be between 1 and 100.
- **Whether remote control is *on* is asked of our own server.** The enrolment
  row in Codex's state store describes the *desktop's* app-server, which had
  `show` reporting "ready" while conPACT's own server answered
  `status: disabled`. A server that is up but will not answer counts as not
  offering.
