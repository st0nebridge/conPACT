"""
@module conpact.cache_window
@description When will an idle session's prompt cache expire? Claude Code records,
             with each assistant message, how many input tokens that API call
             wrote to the prompt cache and under which lifetime
             (usage.cache_creation.ephemeral_5m_input_tokens /
             ephemeral_1h_input_tokens). A call that reads the cache refreshes
             it, so an idle session's cache expires one lifetime (TTL) after its
             last main-thread call. This module finds that call (its time and the
             context size it saw) and the most recent evidence of the TTL.
@input      a transcript path (the Stop hook receives it as transcript_path)
@output     a CacheWindow(last_call, ttl, context_tokens), or None when the
            transcript does not show all three
@dependencies conpact.context_meter; stdlib: datetime, typing
"""
from __future__ import annotations

import datetime
from typing import NamedTuple

from . import context_meter

TTL_1H = 3600
TTL_5M = 300
# Checked shortest first: if any part of the context was cached for 5 minutes,
# that part expires first and the next call after it pays for a cache miss.
_TTL_FIELDS = (("ephemeral_5m_input_tokens", TTL_5M), ("ephemeral_1h_input_tokens", TTL_1H))


class CacheWindow(NamedTuple):
    last_call: float      # epoch seconds of the last main-thread API call
    ttl: int              # prompt-cache lifetime in seconds
    context_tokens: int   # the context that call saw

    @property
    def expires_at(self) -> float:
        return self.last_call + self.ttl


def parse_timestamp(value) -> float | None:
    """Epoch seconds from a transcript timestamp ("...Z" or with an offset; naive = UTC)."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.timestamp()


def entry_ttl(entry) -> int | None:
    """The cache lifetime a main-thread assistant call wrote under, if it wrote any."""
    if context_meter.usage_tokens(entry) is None:
        return None
    breakdown = entry["message"]["usage"].get("cache_creation")
    if not isinstance(breakdown, dict):
        return None
    for field, ttl in _TTL_FIELDS:
        count = breakdown.get(field)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            return ttl
    return None


def read_window(transcript_path) -> CacheWindow | None:
    """The last main-thread call and the cache lifetime in force for it."""
    last_call = tokens = None
    for entry in context_meter.entries_from_end(transcript_path):
        size = context_meter.usage_tokens(entry)
        if size is None:
            continue
        if tokens is None:
            tokens, last_call = size, parse_timestamp(entry.get("timestamp"))
            if last_call is None:
                return None
        ttl = entry_ttl(entry)
        if ttl is not None:
            return CacheWindow(last_call, ttl, tokens)
    return None
