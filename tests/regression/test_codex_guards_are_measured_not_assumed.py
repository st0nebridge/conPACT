"""
@module tests.regression.test_codex_guards_are_measured_not_assumed
@description Two facts about ChatGPT Desktop that a reasonable implementation
             gets wrong, both found by measuring this machine rather than by
             reading the shapes. (1) Codex takes a *byte-range* lock on a
             thread's writer-lock file, so the file stays freely openable and an
             `open()` test reports every live thread as free - the first version
             of `is_loaded` did exactly that, and reported three threads a
             running Codex was holding as safe to write to. (2) Both of Codex's
             token records carry a per-call total beside a cumulative one; the
             cumulative field read 419,896,175 against a real context of 177,573
             on the same record, and the state store's `tokens_used` column is
             that same cumulative number.
@input      conpact.codex_threads, conpact.codex_meter
@output     assertions that the lock guard sees a real lock and that no
            cumulative counter can be returned as a context size
@dependencies conpact.codex_meter, conpact.codex_threads; stdlib: json
"""
import json

import pytest

from conpact import codex_meter, codex_threads

# The record as Codex really writes it, cumulative fields and all.
REAL_USAGE_RECORD = {
    "type": "token_usage_record",
    "payload": {
        "thread_id": "01a00000-0000-7000-9000-000000000002",
        "usage": {"input_tokens": 177337, "cached_input_tokens": 177024,
                  "output_tokens": 236, "total_tokens": 177573},
        "turn_token_usage": {"total_tokens": 2799281},
        "thread_token_usage": {"input_tokens": 419896175, "total_tokens": 419896175},
    },
}
CONTEXT = 177573
CUMULATIVE = (419896175, 2799281)


def test_a_byte_range_lock_is_invisible_to_opening_the_file(tmp_path):
    """The measurement that makes the next test necessary: all four locks Codex
    held on this machine opened without error in both "r+b" and "ab"."""
    msvcrt = pytest.importorskip("msvcrt")
    path = tmp_path / "held.lock"
    path.write_bytes(b"")
    holder = path.open("r+b")
    msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
    try:
        path.open("r+b").close()          # the bug in one line: this succeeds
        path.open("ab").close()
    finally:
        msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
        holder.close()


def test_the_lock_guard_sees_a_lock_that_opening_the_file_cannot(tmp_path):
    """What `is_loaded` must answer, against a real lock rather than a stand-in.
    A wrong "free" here means writing into a rollout a running app is writing to."""
    msvcrt = pytest.importorskip("msvcrt")
    env = {"CODEX_HOME": str(tmp_path)}
    (tmp_path / "thread-writer-locks").mkdir()
    path = tmp_path / "thread-writer-locks" / "live.lock"
    path.write_bytes(b"")
    assert codex_threads.is_loaded("live", env) is False     # nobody holds it yet

    holder = path.open("r+b")
    msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
    try:
        assert codex_threads.is_loaded("live", env) is True
    finally:
        msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
        holder.close()
    assert codex_threads.is_loaded("live", env) is False      # and released again


def test_the_guard_fails_closed_when_it_cannot_probe_at_all(tmp_path):
    """Every unknown reads as held. One skipped compaction costs a turn; one
    wrong "free" costs the user's rollout."""
    env = {"CODEX_HOME": str(tmp_path)}
    assert codex_threads.is_loaded("../escape", env) is True
    assert codex_threads.is_loaded(None, env) is True


def test_a_cumulative_token_counter_is_never_returned_as_the_context(tmp_path):
    """Both numbers sit on the same record; picking the wrong one is out by three
    orders of magnitude and would make every session look full."""
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps(REAL_USAGE_RECORD) + "\n", encoding="utf-8")
    measured = codex_meter.current_context_tokens(path)
    assert measured == CONTEXT
    assert measured not in CUMULATIVE


def test_the_state_stores_own_token_column_is_not_offered_as_a_context_either(tmp_path):
    """`threads.tokens_used` is the same cumulative spend - 414,134,090 on this
    machine's live thread - so the normalised record names it `tokens_spent` and
    nothing reads it as a context size."""
    record = codex_threads._record({"id": "t1", "tokens_used": 414134090})
    assert record["tokens_spent"] == 414134090
    assert "context" not in " ".join(record)
