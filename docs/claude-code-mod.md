# The Claude Code mod

conPACT ships a Claude Code **mod**: a plugin whose code runs inside Claude
Code itself. With it, a compaction the agent queues is carried out by the
session itself at the end of the turn, through the same operation `/compact`
uses. Nothing is sent over Remote Control, so **Remote Control is not needed**
for it.

In a terminal session the mod calls that operation directly. A session with no
terminal behind it, such as the Desktop app's Code tab or one the Agent SDK
runs, does not let a mod call it, so there the mod runs `/compact` itself, as
you would type it, with the request's focus after it. Both reach the same
compaction.

Where the mod is loaded it is the path every agent-queued compaction takes.
Where it is not, nothing changes: the MCP server and the Stop hook do the work
over Remote Control, as described in [How it works](how-it-works.md).

## What it does

The agent keeps the tools it has. The mod answers three of the MCP server's
tools itself, under the same names and with the same arguments:

| Tool | Answered by the mod |
|---|---|
| `queue_compaction` | Keeps a request for this session: its `focus` and `min_context_tokens`. Queuing again replaces it. In a `.claude/worktrees/...` checkout it answers `queued: false`, as the server does. |
| `cancel_compaction` | Withdraws a request that has not started yet. |
| `compaction_status` | What is queued, the context size, any hold on the early toast, and how the last compaction of this session went. |
| `hold_idle_toast` | *Not taken over.* The MCP server answers it, as before. |

Each answer carries `"transport": "mod"` in its data, so you (and the agent) can
tell which side answered.

When the turn ends with an answer, the mod waits for the turn to finish and
then:

1. checks the minimum context size, if there is one: the request's own, or
   else your `closure_min_context_tokens` setting. Below it, nothing is
   compacted and the request is spent, as with the Stop hook;
2. compacts the session, with the request's `focus` telling the summary what to
   keep;
3. shows the outcome outside the conversation: in the band above the prompt
   (below), and as a notification if it failed. It writes nothing into the
   conversation itself.

If Claude Code reloads the mod while a compaction it started is running (a
plugin folder changing under a session that hot-reloads, say), the run goes
with the old load but the compaction carries on. When it finishes, the mod
that is loaded now records it as the request's outcome, so the session is not
compacted a second time.

### The band above the prompt

The mod also draws one row in the band above the prompt, in the terminal and
in the Desktop app's Code tab alike, that follows the request as it changes:

| While | The row reads |
|---|---|
| A request waits | `conPACT queued · 412.9k now · ≥ 150k · keep: the plan`, and which try is next if an earlier one could not start, with **cancel** |
| It runs | `conPACT compacting 412.9k`, and the focus; the idle toast's compaction shows here too |
| It has compacted | `conPACT 285.4k → 18.6k`, a meter of what was kept, `−93.5%` and `1m 25s`, with a **×** to dismiss it |
| It failed, or did not compact | `failed` in red, or `not compacted`, and why |

In the Desktop app the mark at the start is drawn: a pulsing dot while the
request waits, a turning ring while it runs, a green check with the meter
beside it, or a red cross. The terminal draws the same in Unicode
(`◇ ◆ ✓ ✗` and a thin `━━╸────` meter):

<p>
  <img src="images/band-states.svg" width="640" alt="The row in its four states, in a terminal: queued with a minimum of 150k and a focus, compacting, compacted from 285.4k to 18.6k, and failed with Claude Code's reason">
</p>

And in the Desktop app:

<p>
  <img src="images/band-desktop.png" width="640" alt="The row above the prompt in the Claude Desktop app, three times: queued at 231k with a minimum of 150k and a focus, with cancel; compacted from 248.3k to 14.9k, minus 94.0 percent in 48s, with a green check, a meter and a dismiss mark; and not compacted, because the context was under the request's minimum">
</p>

**cancel** withdraws a request that has not begun, as `cancel_compaction` does;
one that has begun is left to finish. A run that has not finished after ten
minutes was lost, and shows as queued again, `the last run did not finish`,
until the next turn end tries it; it can be cancelled then. A result stays for 15 minutes, or until
you dismiss it or a new request takes its place. A survey takes the band while
it is open, and whatever another plugin draws there stays, below conPACT's row.
The row is drawn again whenever the request changes, and once more two seconds
later; a drawing begun as a compaction ends reads the request again once the
mod has recorded the end, so the row does not stay on `compacting`.

## The idle toast

The idle toast is a separate window, started by the Stop hook, so it cannot
compact a session from inside. Where the mod is loaded it asks the mod to:

- while the session runs, the mod writes a small heartbeat,
  `~/.conpact/mod/beat/<session>.json`, every 30 seconds (and once more, marked
  ended, when the session ends);
- when you press **Compact now**, or auto-compact is due, the toast checks that
  heartbeat. If it is fresh, the toast leaves a request in
  `~/.conpact/mod/ask/<session>.json` instead of sending `/compact` over Remote
  Control;
- the mod looks for a request every 2 seconds, compacts the session at once (it
  is idle), and answers in `~/.conpact/mod/answer/<session>.json`. The toast
  follows the compaction as before and shows the result.

So with the mod, the idle toast needs no Remote Control either, and the "turn on
Remote Control" toast does not appear for that session. A session without a
fresh heartbeat (no mod, an older Claude Code, a session the mod was not loaded
in) is compacted over Remote Control, exactly as before.

A request the mod has not taken within 10 seconds lapses: the toast says the
compaction failed, and the mod will not take that request later. A request is
taken only once.

## Turning it on

The mod needs **Claude Code 2.1.284 or later** and runs in the terminal and in
the Code tab of the Desktop app. It also needs the MCP server registered (see
[Setup](setup.md#2-the-mcp-server)): the mod answers that server's tools, it does
not add tools of its own.

### Install it from this repository

```bash
claude plugin marketplace add st0nebridge/conPACT
claude plugin install conpact@conpact
```

A local checkout works as the marketplace too: `claude plugin marketplace add
/path/to/conpact`.

### Or load it from your checkout

To run the mod straight from a checkout, so that pulling a new version updates
it, name the folder in `~/.claude/settings.json`. This also reaches the Desktop
app, which takes no command-line flags:

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/conpact/src/mod"
  }
}
```

On Windows, separate several folders with `;`, elsewhere with `:`.

### Before Claude Code 2.1.287

Mods are on by default from Claude Code 2.1.287. Before that they were in early
access, and loaded only with this in the same `env` block:

```json
"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"
```

Later versions ignore it, so it is safe to leave in place.

### Check that it loaded

New sessions load it; one that was already open does not. In a terminal
session, `/plugin` shows `1 mod active · conpact` (or the count of all your
mods). Or ask the agent for `compaction_status`: the answer's data says
`"transport": "mod"` when the mod answered.

To find out whether mods can load on your machine at all, run
`claude plugin test` in a folder that holds no mod. "no hooks module to load"
means they can. "hooks modules are turned off" means a setting, your
organisation, or Anthropic has them off, and the MCP server and Stop hook carry
on as before.

## What it can reach

A mod runs with your permissions, so this one is deliberately small. It calls
only these parts of Claude Code's mod API, which `claude plugin validate
src/mod` lists:

| Call | For |
|---|---|
| `$.session.compact` | The compaction itself, between turns, in a terminal session |
| `$.command.run` | `/compact` and no other command, in a session with no terminal behind it (the Desktop app's Code tab, the Agent SDK), where Claude Code refuses `$.session.compact` |
| `$.session.id`, `$.session.cwd`, `$.session.usage` | Which session this is, whether it is a throwaway worktree, and its context size |
| `$.store` | The session's request and its last result, in the mod's own store |
| `$.fs.read` | conPACT's own files: `~/.conpact/settings.json`, this session's hold on the early toast, and the idle toast's request for it |
| `$.fs.write` | Only this session's heartbeat and its answers to the idle toast, under `~/.conpact/mod/`; any other path is refused before it reaches Claude Code |
| `$.env.get` | `USERPROFILE` and `HOME`, to find `~/.conpact/` |
| `$.clock`, `$.ui.toast` | Starting the run after the turn, the heartbeat and the look for the toast's request, and saying when a compaction failed |
| `$.ui.resolve`, `$.ui.invalidate` | Drawing the band above the prompt with the surface's own elements, and drawing it again when the request changes (at once, and once more two seconds later) |

It starts no process, makes no network request, writes no file but those two,
runs no command but `/compact`, never submits a prompt, and never reads Claude
Code's login.

## Where it does not run

| Where | What happens |
|---|---|
| A Desktop app session in WSL | Plugins do not load there. The MCP server and the Stop hook answer. |
| A machine where mods are switched off | The MCP server and the Stop hook answer. |

In each of these the idle toast finds no heartbeat, and compacts over Remote
Control as before.

A `/compact` the mod runs that compacts nothing (Claude Code says, for
instance, that there are not enough messages yet) is treated like a start that
was refused: the request is tried again at the next turn end, at most three
times, and then reported as failed in Claude Code's own words.

## Turning it off

`claude plugin uninstall conpact@conpact`, or remove the folder from
`CLAUDE_CODE_PLUGIN_DIRS`. New sessions then go back to the MCP server and the
Stop hook. A request the mod was holding is not carried over; it is dropped
after a week.
