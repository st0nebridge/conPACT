"""
@module conpact.codex_window
@description When will an idle Codex thread's prompt cache expire? This is the
             ChatGPT Desktop counterpart of `cache_window`, and the difference
             between them is the whole reason it is a separate module: Claude
             Code *states* the cache lifetime it bought, recording
             `ephemeral_5m_input_tokens` or `ephemeral_1h_input_tokens` with each
             call, so `cache_window` reads the TTL. Codex records how much was
             cached (`cached_input_tokens`, `cache_write_input_tokens`) and never
             how long for, so the lifetime here is modelled rather than read, and
             is labelled that way wherever it is shown.

             The model is measured, not assumed. Across 108 rollouts on this
             machine, 2,232 consecutive API calls were grouped by the gap since
             the previous call and asked whether the later one hit the cache:

               gap          pairs   hit cache   mean cached share
               0-45 min      2209        100%         75-97%
               45-60 min        4         75%            24%
               60-120 min       6         83%            33%
               120+ min        13         69%            14%

             So the cache holds reliably for at least 45 minutes and is
             unreliable past an hour - the same order as Claude's 1-hour TTL,
             which is what `TTL` is set to. The tail buckets are small (4, 6 and
             13 pairs), so this is a working model and not a measurement of
             OpenAI's policy; `TTL` is one constant, in one place, for when
             better evidence turns up.

             The window itself is the same shape as Claude's - the last API call,
             a lifetime, and the context that call saw - so everything downstream
             (the stages, the watcher, the toast) is shared rather than written
             twice.
             The context size is not measured here. `codex_meter` already owns
             that question and answers it from either record shape; this module
             asks it, so there is one place that can be wrong about how large a
             thread is rather than two.
@input      a Codex thread's rollout path
@output     a cache_window.CacheWindow, or None when the rollout does not show a
            call with a context size and a time
@dependencies conpact.cache_window, conpact.codex_meter, conpact.context_meter;
              stdlib: datetime
"""
from __future__ import annotations

import datetime

from . import codex_meter, context_meter
from .cache_window import CacheWindow

# Modelled from the measurement in this module's docstring, not read from the
# rollout: Codex records what it cached, never for how long.
TTL = 3600
TTL_IS_MEASURED_NOT_DECLARED = True

# A rollout reaches hundreds of megabytes and one `compacted` record alone can
# be 380 KB, so records are walked from the end rather than a byte window sliced
# off it (context_meter.entries_from_end grows its window until a line fits).
MAX_RECORDS = codex_meter.MAX_RECORDS

USAGE = "token_usage_record"
COUNT = "token_count"


def parse_timestamp(text) -> float | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _kind(record) -> str | None:
    """Codex writes the kind in two places: a `token_usage_record` carries
    `type` at the top level, while a `token_count` is an `event_msg` whose
    payload carries it. Reading only one of them finds neither reliably, which
    is how this first went wrong."""
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    for value in (record.get("type"), payload.get("type")):
        if value in (USAGE, COUNT):
            return value
    return None


def last_call(rollout_path, max_records: int = MAX_RECORDS) -> float | None:
    """When the thread last called the model, or None.

    Either record kind stands for a call: the usage record is written per API
    call, and the `token_count` the UI reads follows it. Whichever is nearest the
    end is the most recent evidence that the thread was talking to the model,
    which is what the cache lifetime runs from.
    """
    for record in context_meter.entries_from_end(rollout_path):
        max_records -= 1
        if max_records < 0:
            return None
        if _kind(record) is None:
            continue
        when = parse_timestamp(record.get("timestamp"))
        if when is not None:
            return when
    return None


def read_window(rollout_path, max_records: int = MAX_RECORDS) -> CacheWindow | None:
    """The thread's cache window, or None when its rollout does not show one."""
    when = last_call(rollout_path, max_records)
    if when is None:
        return None
    tokens = codex_meter.current_context_tokens(rollout_path, max_records)
    if not tokens:
        return None
    return CacheWindow(when, TTL, tokens)
