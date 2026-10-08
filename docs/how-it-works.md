# How it works

conPACT does one thing on Claude Code: it gets a **real `/compact`** into a
live session at the right moment. This page covers what that means, the route
the command takes, and why a request only ever fires after the final answer.
ChatGPT Desktop works differently; see [chatgpt-desktop.md](chatgpt-desktop.md).

## The goal

Give the agent the ability to trigger *real context compaction of its own live
session* when saved implementation work is finished, or the user explicitly asks.
Routine questions, read-only investigations, status reports and intermediate
answers do not schedule compaction, even when the context is large. Finishing
an answer does not establish that the work is ready to be compacted.
That rules out four things:

- **not** a token threshold,
- **not** a reminder to the user to type `/compact`,
- **not** `/clear`,
- **not** a fake "I compacted" claim.

The visible chat history must be preserved; only the live context window is
summarised in the background.

The optional minimum context size does not change that. It is a one-shot
condition on a request ("only if it is worth it"), checked once when the turn
ends, never a trigger that waits for the context to grow. A request whose
session is below the minimum is discarded, not kept armed.

The idle toast is a separate feature. It leaves the agent's requests unchanged,
and it compacts only when you click, or when you have switched that one session
to auto-compact. See [idle-toast.md](idle-toast.md).

## The route from inside: the mod

Claude Code's mods run inside Claude Code, and one of the things a mod can do
is compact the session it runs in, between turns, through the same operation
`/compact` uses. conPACT's mod (in `src/mod`) does exactly that: it answers the
MCP server's queue, cancel and status tools itself, keeps the request in its own
store, and compacts the session once the turn that asked has ended. In the
Desktop app's Code tab, and any other session with no terminal behind it,
Claude Code does not let a mod call that operation, so the mod runs `/compact`
there instead, which reaches the same compaction. Nothing crosses a network and
Remote Control is not involved, so a session compacts itself whether Remote
Control is on or not.

Where the mod is loaded, it is the route every queued compaction takes, and the
idle toast's too: the toast leaves its request in a small file the mod looks for
every two seconds, and the mod compacts the session at once. Where it is not (an
older Claude Code, a session in WSL, mods switched off), the route below takes
over, unchanged. See [claude-code-mod.md](claude-code-mod.md).

## The route in: Remote Control

The command reaches a session through the same transport the web and mobile
Remote Control clients use:

```
POST https://api.anthropic.com/v1/code/sessions/{bridgeSessionId}/events
```

with an event envelope whose `payload.message.content` is the command text.
That is why every Claude Code path in conPACT that sends `/compact` needs Remote
Control turned on for the session: it is what gives the session a
`bridgeSessionId` to post to.

### The one non-obvious requirement

What makes this work is the `anthropic-client-platform` header. The receiving
session treats an event as **genuine human input**, so slash commands execute,
only when that header is a *human* value: one of `ios`, `android`,
`web_claude_ai`, `desktop_app`.

With `cli`, the event is demoted to a cross-session **peer** message ("Another
Claude session sent a message …") and slash commands are silently ignored.
conPACT sends `web_claude_ai`.

## Intent and execution

The two halves are deliberately separated, so the command lands *after* the
final answer and can only fire once.

### 1. Intent: the agent records a request

When implementation work is finished and verified (a feature, a fix or a
build is done, an implementation plan is complete, or the user explicitly
wraps up the session) and its results are saved, for example committed, the
agent records a request for its own session. An explicit request to compact
can also queue one. With a tool call:

```
queue_compaction { "focus": "keep the API design", "min_context_tokens": 150000 }
```

or from the shell, in the conPACT folder:

```bash
python tools/bridge_send.py --self --request
# optional: --focus "keep the API design and the open questions"   (one line, max 500 chars)
# optional: --min-context-tokens 150k                                (150000, 150k or 1.5m)
```

Nothing is sent at this point. The request is a small file under
`~/.conpact/requests/`, keyed by the session id.

### 2. Execution: the Stop hook fires it

On the next `Stop` (the end of the turn), the Stop hook claims the request.

- **At most once.** The hook may fire only if its own delete of the request file
  succeeds, which holds even under locks or races.
- **Minimum size.** If the request has a minimum, or you set a default one
  (`closure_min_context_tokens`), the hook measures the context from the
  session's transcript: the token usage of the last main-thread API call, that
  is input + cache writes + cache reads + output. It sends nothing if the
  context is smaller, or if it cannot be measured.
- **Otherwise it posts `/compact`**, and compaction runs exactly as if you had
  typed it.

A refused or failed send is logged in `~/.conpact/hook-log.jsonl` and
never retried.

### Why not just send `/compact` straight away?

Because a busy session does not run it. `--self --compact` from inside a turn
arrives while the session is working and is injected into the running turn as
plain text (observed 2026-09-19). The request-then-Stop-hook flow exists so the
command arrives as the turn ends, when the session will treat it as a command.

## Where requests live

Requests are written only to `~/.conpact/requests/`, one file per session,
named by its id. ChatGPT Desktop threads use the same folder, named by thread
id. `~/.conpact/` is conPACT's own folder, shared by both apps and inside
neither's.

Earlier versions wrote requests to `~/.claude/conpact/requests/`, and before
that to `~/.claude/clautomatic/requests/`. conPACT still reads both. An MCP
server keeps the code it started with for as long as its session runs, so a
server started before an upgrade may still write there. See
[architecture.md](architecture.md#moving-from-an-earlier-version) for what an
upgrade moves.
