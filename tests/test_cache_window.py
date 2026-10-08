"""Tests for conpact.cache_window: when an idle session's prompt cache expires."""
import datetime
import json

import pytest

from conpact import cache_window as cw

H1 = {"ephemeral_1h_input_tokens": 148, "ephemeral_5m_input_tokens": 0}
M5 = {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 90}
NONE = {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}
TS1, TS2 = "2026-09-19T04:28:17.226Z", "2026-09-19T04:28:34.334Z"


def _epoch(ts):
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _assistant(ts, tokens, cache_creation=None, sidechain=False):
    usage = {"input_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": tokens, "output_tokens": 0}
    if cache_creation is not None:
        usage["cache_creation"] = cache_creation
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": ts,
            "message": {"model": "claude-opus-5", "usage": usage}}


def _write(tmp_path, entries):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def test_ttl_constants():
    assert (cw.TTL_1H, cw.TTL_5M) == (3600, 300)


def test_parse_timestamp():
    assert cw.parse_timestamp(TS2) == _epoch(TS2)
    assert cw.parse_timestamp("2026-09-19T04:28:34+00:00") == _epoch("2026-09-19T04:28:34Z")
    assert cw.parse_timestamp("2026-09-19T04:28:34") == _epoch("2026-09-19T04:28:34Z")  # naive = UTC
    for bad in ("", "yesterday", None, 17, ["x"]):
        assert cw.parse_timestamp(bad) is None


@pytest.mark.parametrize("cache_creation, ttl", [
    (H1, 3600), (M5, 300), ({"ephemeral_1h_input_tokens": 1}, 3600), ({"ephemeral_5m_input_tokens": 1}, 300),
    ({"ephemeral_1h_input_tokens": 5, "ephemeral_5m_input_tokens": 5}, 300),  # the shorter lifetime wins
    (NONE, None), ({}, None), ("x", None),
    ({"ephemeral_1h_input_tokens": True, "ephemeral_5m_input_tokens": 0}, None),
    ({"ephemeral_1h_input_tokens": 4.0}, None),
])
def test_entry_ttl(cache_creation, ttl):
    assert cw.entry_ttl(_assistant(TS1, 10, cache_creation)) == ttl


def test_entry_ttl_only_reads_main_thread_assistant_calls():
    assert cw.entry_ttl(_assistant(TS1, 10)) is None  # no cache_creation at all
    assert cw.entry_ttl(_assistant(TS1, 10, H1, sidechain=True)) is None
    assert cw.entry_ttl({"type": "user", "message": {"usage": {"cache_creation": H1}}}) is None
    assert cw.entry_ttl(None) is None


def test_read_window_uses_the_last_main_call_and_its_ttl(tmp_path):
    path = _write(tmp_path, [_assistant(TS1, 100, M5), _assistant(TS2, 200, H1)])
    window = cw.read_window(path)
    assert window == cw.CacheWindow(last_call=_epoch(TS2), ttl=3600, context_tokens=200)
    assert window.expires_at == _epoch(TS2) + 3600


def test_read_window_takes_ttl_evidence_from_an_earlier_call(tmp_path):
    # The latest call only read the cache, so its lifetime is shown by an earlier write.
    path = _write(tmp_path, [_assistant(TS1, 100, H1), {"type": "user"}, _assistant(TS2, 200, NONE)])
    assert cw.read_window(path) == cw.CacheWindow(_epoch(TS2), 3600, 200)


def test_read_window_ignores_subagent_calls(tmp_path):
    path = _write(tmp_path, [_assistant(TS1, 100, H1), _assistant(TS2, 999, M5, sidechain=True)])
    assert cw.read_window(path) == cw.CacheWindow(_epoch(TS1), 3600, 100)


@pytest.mark.parametrize("entries", [
    [],
    [_assistant(TS1, 100, NONE)],          # no lifetime evidence anywhere
    [_assistant("not a time", 100, H1)],   # the last call's time is unknown
    [{"type": "user"}],
])
def test_read_window_is_none_without_complete_evidence(tmp_path, entries):
    assert cw.read_window(_write(tmp_path, entries)) is None


def test_read_window_is_none_for_a_missing_transcript(tmp_path):
    assert cw.read_window(tmp_path / "absent.jsonl") is None
    assert cw.read_window(None) is None
