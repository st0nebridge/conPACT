# The idle toast

A turn end leaves a session's context in the prompt cache for one TTL. Come back
after it expires and the next message re-reads the whole context uncached.
Compacting while the cache is still warm avoids that, but only you know whether
you are coming back, so conPACT asks.

The same toast covers ChatGPT Desktop threads; the differences are listed
[at the end](#chatgpt-desktop-threads).

## At a glance

- A session big enough to be worth compacting gets watched after every turn end.
- **Five minutes before its cache expires** (55 minutes idle on a 1-hour cache),
  a toast appears in the bottom-right corner, without taking focus.
- You choose: **Compact now**, compact it automatically from now on, silence it,
  or ignore it.
- Using the session again cancels the toast. Nothing is ever sent to a busy
  session.

## When a session is watched

At every turn end the Stop hook reads the session's transcript: the context
size of the last main-thread call, and the cache lifetime it was written under
(`usage.cache_creation`: 1 hour or 5 minutes; if both appear, the shorter wins).

It starts a small detached watcher for the session when all of these hold:

- the session is big enough: at least `min_context_fill` of the window (default
  **50%**) where the app reports one, else at least `min_context_tokens`
  (default **100,000**). Claude Code reports no window, so for it the token
  count is the rule;
- the cache is still valid;
- the session is not silenced, and you have not archived it in the app.

The hook returns at once, and a newer turn end retires the previous watcher. A
session with Remote Control off is still watched; the toast then asks for
Remote Control instead of offering to compact
([below](#when-remote-control-is-off)).

## The two stages

The watcher waits for each of the watch's stages:

| Stage | When | Notes |
|---|---|---|
| **Early** (optional) | `idle_seconds` after the last reply | Only if you set `idle_seconds`. Closes itself after `early_toast_seconds` (default **120**). |
| **Expiry** | `lead_seconds` (default **300**) before the cache expires | 55 minutes idle on a 1-hour cache, 3 minutes on a 5-minute cache, never before 60% of the lifetime. Shows a live countdown. |

Letting the early toast go is not an answer for the whole idle stretch: the
expiry toast still comes.

The watcher stands down as soon as you use the session again (its record shows
it busy, or changed since the turn end), the session is compacted some other
way (your own `/compact`, a compaction the agent queued, or Claude Code's
automatic one: the transcript gains a compaction after that turn end), a newer
turn end re-arms it, the session closes, or you archive it. So a session the
agent compacted at the end of its work is never offered, or given, a second
compaction while it sits idle.

## The buttons

The toast shows the session, its size, how long it has been idle and how long
the cache has left.

| Button | What it does |
|---|---|
| **Compact now** | Sends `/compact` to that session. That ends the watch: no later toast follows a compaction unless you use the session again. |
| **Near expiry** (early toast only) | Leaves this idle stretch's compaction to the expiry stage, which then runs it without asking again. The answer when tests are still running and you want the context kept warm until they are not. Held in the watcher and written nowhere, so using the session voids it. |
| **Always compact** / **Always near expiry** / **Always when idle** | Compacts *that session* without asking from then on, at the stage the choice belonged to, with the other stage silent. On the early toast the two standing choices are the second line of links; the buttons act now. |
| **Not now** / ✕ | Closes the toast. The later toast still comes. |
| **Silence 24 h** | Stops every toast for that session until it runs out (`mute_seconds`) or you use the session again, whichever comes first. |

After an automatic compaction you get a short notice each time, with **Turn off
auto-compact**. A one-off **Near expiry** does not show it, because it set no
switch.

The buttons respond to the mouse only, so a stray Enter or Space while you type
elsewhere can never press one. Nor does the toast take the keyboard from what
you are typing in, the first one a watcher shows included. On Windows, Tk
activates the first window a process makes, so the toast's windows are made
with activation refused. If Windows moves the keyboard anyway, the toast hands
it straight back, within a few milliseconds. The toast follows the desktop's
light or dark theme: Windows' app theme, macOS's appearance, and on Linux the
colour-scheme preference GNOME and desktops that follow it publish.

## After a send

The ✕ button hides the toast immediately, including while its request is
waiting for a result. The watcher keeps recording the result in the background;
closing the toast does not cancel or repeat the compaction.

The toast stays up and shows **Compacting… m:ss** until the session's
transcript records the compaction's end. It then shows the result, for example
*Done in 1 min 42 s: 460k → 23k tokens.*

Where the session runs conPACT's [mod](claude-code-mod.md#the-idle-toast),
the toast asks the mod to compact the session instead of sending `/compact`
over Remote Control, so the session needs no Remote Control. If the mod does not
take the request within 10 seconds, or Claude Code refuses it, the toast says
the compaction failed.

A large compaction takes a minute or more, and the Desktop app shows nothing
while one sent over Remote Control runs. If no result appears within 10 minutes
the toast says so and stays open. Closing it early is fine: the watcher keeps
following, and `idle-log.jsonl` gets the send time and the result.

The watcher checks the session is idle right before sending, because a busy
session would receive `/compact` as plain text.

## Holding the early toast during a long run

An agent working in a session can hold **the early toast only**, while it waits
on a build or a test suite, with the `hold_idle_toast` tool (`minutes`, default
30, at most 120; `0` releases it). A hold is not spent by using the session,
because a run takes many turns. The expiry toast still comes, and a held
auto-compaction happens there instead: a hold can delay a compaction, never
cost you the cache.

## When Remote Control is off

Nothing can be sent to a session without Remote Control, so there is nothing to
offer. The toast says so instead:

- **Open the session** brings it up in the app, where the switch is in its
  toolbar. **Silence** and **Not now** work as usual.
- **Always on for new sessions** sets Claude Code's own
  `remoteControlAtStartup` ("Start Remote Control bridge automatically each
  session"), so you never have to answer again. The click is the confirmation:
  nothing is written unless you press it, the offer is not made when the setting
  is already on, and every other key in `~/.claude/settings.json` is kept.
  Claude Code honours that setting only at user scope.

conPACT never turns Remote Control on for a session itself: whether a session
can be driven remotely is your decision, so the toast only shows you where the
switch is. The watcher reads the record at the notify time, so a switch you
flipped while the session sat idle gets you the normal toast instead. It asks
once per idle stretch, not at both stages.

## Previewing the toast

Nothing is sent. `--demo` takes `ask`, `early` (the one with **Near expiry** and
the two standing choices), `notice`, `failed` or `remote`:

```bash
PYTHONPATH=src python -m conpact.toast_view --demo early
```

## ChatGPT Desktop threads

A Codex thread gets the same stages, buttons, mute and hold. Four things differ:

- **Its cache lifetime is modelled, not read.** Codex records how much was
  cached and never for how long, so conPACT uses a measured one-hour model and
  the toast says "should expire in about".
- **The size rule is a fraction of the window.** ChatGPT Desktop reports its
  window (258,400 tokens when measured), so `min_context_fill` applies. A token
  count chosen for Claude Code means something different in a window of another
  size; a fraction means the same in both.
- **There is no Remote Control to ask for.** A thread is compacted through the
  sidecar or an app-server of conPACT's own, so the toast never asks.
- **Arming comes from the sidecar,** which sees each `turn/completed` on the
  wire. Without a sidecar, threads are swept from Claude's Stop hook instead.
  See [chatgpt-desktop.md](chatgpt-desktop.md#the-turn-end-hook).

## Files

Everything is under `~/.conpact/`. See
[architecture.md](architecture.md#state-files) for the full list;
`idle-log.jsonl` is the one to read when you want to know what the watcher did.
