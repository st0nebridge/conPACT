"""
@module conpact.spin_off
@description Whether a session is a throwaway spin-off: one whose working
             directory is a checkout the desktop app made under
             `.claude/worktrees/` for a suggestion card, a task chip or an agent
             run isolated in a worktree. Those are merged and archived rather
             than resumed, so a compaction summary written there is never read.
             The server's instructions already ask an agent not to queue one
             (mcp_server.INSTRUCTIONS); this is the same rule in code, for when
             the instructions are not followed. It is one setting away from off.
@input      a session record's cwd (any separator, any case, or nothing at all)
@output     True/False, and the words the refusing tool says
@dependencies conpact.settings; stdlib: none
"""
from __future__ import annotations

from . import settings

SETTING = settings.GUARD_SPIN_OFF
MARKER = (".claude", "worktrees")

REFUSAL = (
    "Nothing was queued: this session is working in a .claude/worktrees/... checkout, which is a "
    "throwaway spin-off. Those are merged and archived rather than resumed, so the summary a "
    "compaction writes here is never read and the compaction spends a turn on nothing. This is not "
    "an error and there is nothing to retry: finish your answer, and say in one clause that you "
    "skipped the compaction because this is a spin-off session. (The user can turn this off in the "
    "conPACT settings.)"
)


def _parts(cwd) -> list:
    """A path's names, lowercased, whichever separator it was written with."""
    if not isinstance(cwd, str):
        return []
    return [part.casefold() for part in cwd.replace("\\", "/").split("/") if part]


def is_spin_off(cwd) -> bool:
    """True when `cwd` is inside a checkout under `.claude/worktrees/`.

    The two names must be adjacent and in that order, and something must follow
    them: `.claude/worktrees` itself is the folder that holds the checkouts, not
    one of them. A desktop scratch workspace is deliberately not matched - the
    user talks in those, so their summaries do get read.
    """
    parts = _parts(cwd)
    return any(tuple(parts[i:i + 2]) == MARKER for i in range(len(parts) - 2))


def refuses(cwd, enabled=None) -> bool:
    """Whether a compaction queued from `cwd` should be refused."""
    if enabled is None:
        enabled = settings.load()[SETTING]
    return bool(enabled) and is_spin_off(cwd)
