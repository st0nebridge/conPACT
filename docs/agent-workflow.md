# Telling your agent when to compact

The MCP server already tells the agent when to use its tools: queue a
compaction once a piece of work is finished and saved, or when you ask, and not
otherwise. That is enough to start. This page is for making it reliable in your
own workflow and for making each compaction count.

## Why the timing matters

A compaction first reads the whole context once, to summarise it. If the session
has been idle past its prompt cache, that read is uncached and priced as a cache
write. If the session is still warm, it costs a fraction of that. So the best
moment to compact is the end of a piece of work, while the session is still
warm, rather than when you come back to it later.

Measured over the maintainer's own use (187,978 Claude Code API calls, 12 active
days with conPACT against 80 before it):

| | Typed `/compact`, before | Queued by the agent |
|---|---|---|
| Compactions on a warm cache | 30 of 121 | 134 of 134 |
| Estimated cost of the compaction itself, list price | $5.67 | $0.20 |
| Median context when compacted | 608k | 307k at the end of work |

Compacting at the end of the work did not cause rework. The agent re-reads the
files it needs, and the next prompt was a correction 5.5% of the time in the
one to three turns after a compaction, against 6.1% in ordinary turns.

## When to queue, and when not

Queue at a closure:

- A feature, fix or build is finished, its tests pass, and it is committed.
- A multi-step plan has been carried out to the end.
- The end of a phase, if you work in phases.
- A wrap-up of the session.
- You ask for it.

Do not queue:

- After a question, a read-only investigation, a status report or an answer
  part-way through a task, however large the context. The next prompt usually
  needs that context.
- Before the work is verified. If it needs another pass, the detail that pass
  needs may not survive the summary.
- In a throwaway session working in a `.claude/worktrees/...` checkout. It is
  merged and discarded rather than resumed, so the summary would never be read.
  By default the tool refuses there anyway.

## Make it a step in your instructions

The server's instructions describe the tool. An agent follows a named step in
the workflow it is running more reliably than a general suggestion: in the
maintainer's use, agents often skipped the compaction while it was only
suggested, and did it reliably once it was the named last step of each closure.

Paste this into your `CLAUDE.md` (Claude Code) or `AGENTS.md` (Codex), and adapt
the closures to the ones you use:

```markdown
## Compaction (conPACT)

When a piece of work is finished (a feature, fix or build verified and
committed, a completed plan, or a wrap-up), call `queue_compaction` as the
last action of the turn, after the final commit, and say in your final answer
that it is queued. It is often a deferred tool: load it first.

- Pass a `focus` naming what the next stretch of work needs: the next step,
  the open decisions, and anything learned that is not written down elsewhere.
- Do not queue after questions, read-only investigation, status reports or
  intermediate answers, however large the context.
- Do not queue in a throwaway `.claude/worktrees/...` session; say in one
  clause that you skipped it.
- Before waiting idle on a long build or test run, call `hold_idle_toast`.
- Never send `/compact` yourself mid-turn: a busy session receives it as plain
  text and it never runs. If the conPACT tools are not loaded, say so.
```

## Attach it to the closures you already have

If you already have a wrap-up command, a release checklist or phase gates, add
the queue as their last step, after the commit. A custom slash command such as
`.claude/commands/close-out.md` might read:

```markdown
Close out this session:

1. Run the tests and show the result.
2. Commit the verified changes.
3. List what is left open.
4. Last: call queue_compaction, with a focus on what is left open.
```

Put it last, after the commit, so it is reached only once the work is verified
and saved.

## Writing a good focus

`focus` steers what Claude Code's `/compact` keeps in its summary. It is one
line, at most 500 characters. The finished work is already in the commits; the
summary is for what comes next. Name:

- the next step, and the steps of the plan that remain;
- the decisions still open, and any made in this session that are not written
  down elsewhere;
- constraints or traps found along the way: a flaky test, a command that must
  not be run, an API that behaves unexpectedly;
- the files or areas in play.

A useful focus:

```text
keep: migration steps 4-6 still to do, the decision to keep the v1 API until clients move, test_sync.py is flaky on Windows
```

One that adds nothing:

```text
keep everything important
```

## Choosing a minimum size

`min_context_tokens` skips the compaction when the context is smaller. A small
context is cheap to carry, and compacting it costs a turn and some detail for
little saving. Something around 100,000 to 150,000 tokens suits closures the
agent queues on its own; leave it out when you ask for a compaction yourself.
When a request is skipped this way, the mod's row above the prompt says so:
**not compacted**, with the context size and the minimum.

`compaction_status` shows the current context size, which helps the agent
decide.

## Long runs: hold the idle toast

A session waiting on a long build, a test suite or a review is idle but not
finished. Before it waits, the agent can call `hold_idle_toast` (30 minutes by
default, at most 120; `0` releases it) so the early idle toast does not offer to
compact a session that is about to be used again. The toast shortly before the
cache expires still comes.

## Checking it works

- With the mod, the row above the prompt shows **queued**, with the
  minimum and the focus, and **cancel**, as soon as the agent queues. After the
  turn it shows what the compaction came to.
- `compaction_status` shows what is queued and the current context size.
- Without the mod, the compaction travels over Remote Control, which must be on
  for that session. See [Setup](setup.md).
