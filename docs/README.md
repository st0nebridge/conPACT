# conPACT documentation

New here? Start with the [project README](../README.md), which covers what
conPACT does and how to set it up in five steps.

## Using conPACT

| Page | Read it for |
|---|---|
| [Setup](setup.md) | The Stop hook, the MCP server, the mod, Remote Control, and sessions that were already open |
| [The Claude Code mod](claude-code-mod.md) | Compacting a session from inside Claude Code, without Remote Control |
| [Idle toast](idle-toast.md) | When the toast comes, what each button does, auto-compaction, holds |
| [Settings](settings.md) | Every setting, with its default and range |
| [Commands](commands.md) | Every command-line tool and its options |
| [ChatGPT Desktop](chatgpt-desktop.md) | Codex threads, the sidecar, Codex MCP tools and Codex Remote Control |

## Understanding conPACT

| Page | Read it for |
|---|---|
| [How it works](how-it-works.md) | The goal, the Remote Control route, and why a request fires only after the final answer |
| [Security model](security.md) | What conPACT can and cannot do, and the reason for each rule |
| [Architecture](architecture.md) | Every module, the entry points, the state files, the layout |
| [Verification](verification.md) | Tests, coverage, mutation scores, and what has been observed live |

## Contributing

Two records at the top of the repository, not here, are for anyone changing
conPACT:

- [CHANGES.md](../CHANGES.md): every change, newest first, with how it was
  verified.
- [DECISIONS.md](../DECISIONS.md): every settled design choice and why. Read the
  entries for an area before proposing to change it.

These pages do not depend on them: each states its reasons where it uses them.
