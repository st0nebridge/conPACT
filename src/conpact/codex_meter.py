"""
@module conpact.codex_meter
@description What a Codex thread's rollout says about it right now: how large the
             context is, how large the model's window is, and whether a turn is
             still running. Codex writes one JSONL rollout per thread and records
             usage twice over - a `token_usage_record` after each API call and an
             `event_msg`/`token_count` for the UI - and each of those carries both
             a per-call total and a running total for the whole thread. Only the
             per-call total is the context; the cumulative one read 419,896,175
             against a real context of 177,573 on this machine, and the state
             store's `tokens_used` column is that same cumulative number. Turn
             boundaries are in the same file, as `task_started` / `task_complete`,
             which is what stands in for the Stop hook Codex does not have.
@input      a rollout path (the state store's rollout_path)
@output     the context size in tokens, the model's context window, and whether
            the thread is between turns - each None when the file does not say
@dependencies conpact.context_meter; stdlib: itertools
"""
from __future__ import annotations

import itertools

from . import context_meter

IDLE = "idle"
RUNNING = "running"
STARTED = "task_started"
COMPLETE = "task_complete"
WINDOW = "model_context_window"

# How far back to look before giving up. A rollout reaches 158 MB here, and the
# reader behind this one grows its window fourfold each time it is exhausted, so
# an unbounded scan of a thread whose tail carries no usage would read the whole
# file. Every real thread answers within the first few dozen records.
MAX_RECORDS = 2000


def _payload(record) -> dict | None:
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else None


def _total(usage) -> int | None:
    """The per-call total of one usage block, or None when it is not a count."""
    if not isinstance(usage, dict):
        return None
    value = usage.get("total_tokens")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def usage_tokens(record) -> int | None:
    """The context size implied by one rollout record, from either of the two
    shapes Codex writes it in. The cumulative siblings on the same records -
    `thread_token_usage`, `turn_token_usage`, `total_token_usage` - are
    deliberately never read."""
    payload = _payload(record)
    if payload is None:
        return None
    if record.get("type") == "token_usage_record":
        return _total(payload.get("usage"))
    if record.get("type") == "event_msg" and payload.get("type") == "token_count":
        info = payload.get("info")
        if isinstance(info, dict):
            return _total(info.get("last_token_usage"))
    return None


def _records_from_end(rollout_path, max_records: int):
    return itertools.islice(context_meter.entries_from_end(rollout_path), max_records)


def current_context_tokens(rollout_path, max_records: int = MAX_RECORDS) -> int | None:
    """The context the model saw on this thread's most recent API call."""
    for record in _records_from_end(rollout_path, max_records):
        tokens = usage_tokens(record)
        if tokens is not None:
            return tokens
    return None


def context_window(rollout_path, max_records: int = MAX_RECORDS) -> int | None:
    """How many tokens this thread's model can hold. Codex states it on the
    token_count events and again on every turn marker, so a thread that has just
    started its first turn can still be asked."""
    for record in _records_from_end(rollout_path, max_records):
        payload = _payload(record)
        if payload is None:
            continue
        for holder in (payload, payload.get("info")):
            if isinstance(holder, dict):
                value = holder.get(WINDOW)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    return value
    return None


def turn_state(rollout_path, max_records: int = MAX_RECORDS) -> str | None:
    """Whether the thread is between turns (IDLE) or working (RUNNING), from the
    newest turn marker in its rollout - or None when there is no marker to read.
    This is the fallback signal for a client where conPACT has no exact
    turn-end event. Integrated CLI tasks now use Codex's Stop hook, while the
    Desktop sidecar uses `turn/completed`."""
    for record in _records_from_end(rollout_path, max_records):
        payload = _payload(record)
        if payload is None or record.get("type") != "event_msg":
            continue
        if payload.get("type") in (COMPLETE, "turn_aborted"):
            return IDLE
        if payload.get("type") == STARTED:
            return RUNNING
    return None
