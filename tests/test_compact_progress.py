"""Tests for conpact.compact_progress: telling when a sent /compact has finished."""
import json

import pytest

from conpact import compact_progress as cp

AT = "2026-09-19T06:19:14.217Z"
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "isSidechain": False, "timestamp": AT,
            "content": "Conversation compacted",
            "compactMetadata": {"trigger": "manual", "preTokens": 459_517, "postTokens": 23_498, "durationMs": 101_836}}
FOUND = {"pre_tokens": 459_517, "post_tokens": 23_498, "duration_ms": 101_836, "trigger": "manual", "at": AT}
COMPACTED = {"state": "compacted", "pre_tokens": 459_517, "post_tokens": 23_498, "seconds": 101.8,
             "trigger": "manual", "at": AT}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def _line(entry) -> bytes:
    return (json.dumps(entry) + "\n").encode("utf-8")


def _append(path, data: bytes):
    with open(path, "ab") as handle:
        handle.write(data)


@pytest.fixture
def transcript(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(_line({"type": "user", "message": {"content": "hi"}}))
    return path


def _tracker(path, clock, **kw):
    return cp.Tracker(str(path), cp.size(str(path)), clock(), clock, **kw)


def test_constants():
    assert (cp.TRACK_SECONDS, cp.MAX_READ) == (600, 4 * 1024 * 1024)


def test_size(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"abc\n")
    assert cp.size(str(path)) == 4
    assert cp.size(str(tmp_path / "absent.jsonl")) is None
    assert cp.size(None) is None


@pytest.mark.parametrize("entry, found", [
    (BOUNDARY, FOUND),
    ({**BOUNDARY, "compactMetadata": None}, {"pre_tokens": None, "post_tokens": None, "duration_ms": None,
                                             "trigger": None, "at": AT}),
    ({**BOUNDARY, "timestamp": None, "compactMetadata": {"trigger": 7, "preTokens": True, "postTokens": "23k",
                                                         "durationMs": -1}},
     {"pre_tokens": None, "post_tokens": None, "duration_ms": None, "trigger": None, "at": None}),
    ({**BOUNDARY, "compactMetadata": {"preTokens": 0, "postTokens": 1, "durationMs": 0}},
     {"pre_tokens": 0, "post_tokens": 1, "duration_ms": 0, "trigger": None, "at": AT}),
    ({**BOUNDARY, "isSidechain": True}, None),
    ({**BOUNDARY, "subtype": "informational"}, None),
    ({**BOUNDARY, "type": "user"}, None),
    ("compact_boundary", None),
    (None, None),
])
def test_boundary(entry, found):
    assert cp.boundary(entry) == found


def test_compacting_until_the_boundary_is_written(transcript):
    clock = Clock()
    tracker = _tracker(transcript, clock)
    clock.t += 42.5
    assert tracker.check() == {"state": "compacting", "elapsed": 42.5}
    _append(transcript, _line({"type": "queue-operation", "operation": "enqueue", "content": "/compact"}))
    assert tracker.check()["state"] == "compacting"
    _append(transcript, _line(BOUNDARY))
    assert tracker.check() == COMPACTED


def test_a_boundary_from_before_the_send_does_not_count(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(_line(BOUNDARY))
    tracker = _tracker(path, Clock())
    assert tracker.check()["state"] == "compacting"


@pytest.mark.parametrize("at, seconds", [
    ("2026-09-19T17:23:12.991Z", 1789838592.991),
    ("2026-09-19T17:23:12.991+00:00", 1789838592.991),
    ("2026-09-19T18:23:12.991+01:00", 1789838592.991),
    ("2026-09-19T17:23:12", 1789838592.0),  # no zone: UTC, as Claude Code writes them
    ("yesterday", None),
    ("", None),
    (None, None),
    (1789838592, None),
])
def test_stamp(at, seconds):
    assert cp.stamp(at) == (pytest.approx(seconds) if seconds else None)


# Seen live 2026-09-19 (session a0b1c2d3): while compacting, Claude Code appended
# about 7 MB of earlier rows after the send, among them a copy of the 04:29
# boundary (656,725 -> 19,111 tokens), before the new one (354,583 -> 23,557).
SENT = 1789838501.394  # 2026-09-19T17:21:41.394Z
NEW = {**BOUNDARY, "timestamp": "2026-09-19T17:23:12.991Z",
       "compactMetadata": {"trigger": "manual", "preTokens": 354_583, "postTokens": 23_557, "durationMs": 90_790}}


def test_an_earlier_boundary_appended_again_does_not_count(transcript):
    clock = Clock(SENT)
    tracker = _tracker(transcript, clock)
    _append(transcript, _line({"type": "user", "timestamp": "2026-09-19T04:28:34.590Z"}) + _line(BOUNDARY))
    assert tracker.check()["state"] == "compacting"
    _append(transcript, _line(NEW))
    assert tracker.check() == {"state": "compacted", "pre_tokens": 354_583, "post_tokens": 23_557,
                               "seconds": 90.8, "trigger": "manual", "at": "2026-09-19T17:23:12.991Z"}


@pytest.mark.parametrize("at, counts", [
    ("2026-09-19T17:21:41.394Z", True),   # the send's own second: the earliest a boundary can be
    ("2026-09-19T17:21:41.393Z", False),
    (None, False),                        # a boundary that cannot show it is new is not taken as the result
    ("garbled", False),
])
def test_a_boundary_counts_only_if_stamped_at_or_after_the_send(transcript, at, counts):
    tracker = _tracker(transcript, Clock(SENT))
    _append(transcript, _line({**NEW, "timestamp": at}))
    assert (tracker.check()["state"] == "compacted") is counts


def test_a_line_written_in_two_parts_is_read_whole(transcript):
    tracker = _tracker(transcript, Clock())
    data = _line(BOUNDARY)
    _append(transcript, data[:40])
    assert tracker.check()["state"] == "compacting"
    _append(transcript, data[40:])
    assert tracker.check() == COMPACTED


def test_unreadable_lines_are_skipped(transcript):
    tracker = _tracker(transcript, Clock())
    _append(transcript, b"not json\n\n[1, 2]\n" + _line(BOUNDARY))
    assert tracker.check() == COMPACTED


def test_it_reads_a_bounded_amount_per_check(transcript, monkeypatch):
    monkeypatch.setattr(cp, "MAX_READ", 64)
    tracker = _tracker(transcript, Clock())
    _append(transcript, _line({"type": "user", "pad": "x" * 100}) + _line(BOUNDARY))
    states = [tracker.check()["state"] for _ in range(8)]
    assert states[0] == "compacting" and states[-1] == "compacted"


def test_without_a_duration_the_seconds_come_from_the_clock(transcript):
    clock = Clock()
    tracker = _tracker(transcript, clock)
    clock.t += 30.04
    _append(transcript, _line({**BOUNDARY, "compactMetadata": {}}))
    assert tracker.check() == {"state": "compacted", "pre_tokens": None, "post_tokens": None, "seconds": 30.0,
                               "trigger": None, "at": AT}


def test_unconfirmed_after_the_time_limit_and_the_result_is_final(transcript):
    clock = Clock()
    tracker = _tracker(transcript, clock, limit=60)
    clock.t += 59.9
    assert tracker.check()["state"] == "compacting"
    clock.t += 0.1
    assert tracker.check() == {"state": "unconfirmed", "seconds": 60.0}
    _append(transcript, _line(BOUNDARY))
    assert tracker.check() == {"state": "unconfirmed", "seconds": 60.0}


def test_unconfirmed_seconds_are_rounded_to_a_tenth(transcript):
    clock = Clock()
    tracker = _tracker(transcript, clock, limit=60)
    clock.t += 60.04
    assert tracker.check() == {"state": "unconfirmed", "seconds": 60.0}


def test_a_missing_transcript_is_compacting_until_the_limit(tmp_path):
    clock = Clock()
    tracker = cp.Tracker(str(tmp_path / "gone.jsonl"), 0, clock(), clock)
    assert tracker.check()["state"] == "compacting"
    clock.t += cp.TRACK_SECONDS
    assert tracker.check()["state"] == "unconfirmed"


def test_the_found_result_is_kept(transcript):
    tracker = _tracker(transcript, Clock())
    _append(transcript, _line(BOUNDARY))
    assert tracker.check() == COMPACTED
    _append(transcript, _line({**BOUNDARY, "compactMetadata": {"preTokens": 1}}))
    assert tracker.check() == COMPACTED


def test_wait_polls_until_there_is_a_result(transcript):
    clock = Clock()
    tracker = _tracker(transcript, clock, limit=20)

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.t >= 1010:
            _append(transcript, _line(BOUNDARY))
    assert tracker.wait(sleep, 5) == COMPACTED
    assert clock.slept == [5, 5]
    assert tracker.wait(sleep, 5) == COMPACTED and clock.slept == [5, 5]


def test_wait_ends_at_the_limit(transcript):
    clock = Clock()
    tracker = _tracker(transcript, clock, limit=12)
    assert tracker.wait(clock.sleep, 5) == {"state": "unconfirmed", "seconds": 15.0}
    assert clock.slept == [5, 5, 5]


# --- compacted_since: a compaction nobody here sent -------------------------

def test_compacted_since_finds_a_boundary_appended_after_the_offset(transcript):
    offset = cp.size(str(transcript))
    assert cp.compacted_since(str(transcript), offset, SENT) is None
    _append(transcript, _line(NEW))
    assert cp.compacted_since(str(transcript), offset, SENT) == {
        "pre_tokens": 354_583, "post_tokens": 23_557, "duration_ms": 90_790, "trigger": "manual",
        "at": "2026-09-19T17:23:12.991Z"}


def test_compacted_since_ignores_what_was_there_before_the_offset(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(_line(NEW))
    assert cp.compacted_since(str(path), cp.size(str(path)), SENT) is None
    assert cp.compacted_since(str(path), 0, SENT) is not None


@pytest.mark.parametrize("at, counts", [
    ("2026-09-19T17:21:41.394Z", True),   # stamped at the moment itself
    ("2026-09-19T17:21:41.393Z", False),  # an earlier boundary Claude Code copied forward
    (None, False),
])
def test_compacted_since_counts_a_boundary_only_from_the_moment_on(transcript, at, counts):
    offset = cp.size(str(transcript))
    _append(transcript, _line({**NEW, "timestamp": at}))
    assert (cp.compacted_since(str(transcript), offset, SENT) is not None) is counts


def test_compacted_since_reads_past_rows_copied_forward_in_one_call(transcript, monkeypatch):
    """The 2026-10-08 compaction appended ~540 earlier rows before its boundary:
    one look reads all of it, however many bounded chunks that takes."""
    monkeypatch.setattr(cp, "MAX_READ", 64)
    offset = cp.size(str(transcript))
    copies = b"".join(_line({"type": "user", "timestamp": "2026-09-19T04:28:34.590Z", "pad": "x" * 50})
                      for _ in range(20))
    _append(transcript, copies + _line(BOUNDARY) + _line(NEW) + copies)
    assert cp.compacted_since(str(transcript), offset, SENT)["post_tokens"] == 23_557


def test_compacted_since_waits_for_a_line_still_being_written(transcript):
    offset = cp.size(str(transcript))
    data = _line(NEW)
    _append(transcript, data[:40])
    assert cp.compacted_since(str(transcript), offset, SENT) is None
    _append(transcript, data[40:])
    assert cp.compacted_since(str(transcript), offset, SENT) is not None


def test_compacted_since_with_nothing_to_read(tmp_path, transcript, monkeypatch):
    offset = cp.size(str(transcript))
    opened = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(OSError()))
    assert cp.compacted_since(str(transcript), offset, SENT) is None   # unchanged: a stat, no read
    assert opened == []
    assert cp.compacted_since(str(tmp_path / "gone.jsonl"), 0, SENT) is None
    assert cp.compacted_since(None, 0, SENT) is None
    assert cp.compacted_since(str(transcript), offset + 10, SENT) is None   # shorter than it was


def test_compacted_since_an_unreadable_transcript_shows_nothing(transcript, monkeypatch):
    """One failed read ends the look: it must not spin on a file it cannot open
    (the watcher asks again at its next poll anyway)."""
    _append(transcript, _line(NEW))
    tries = []

    def refuse(*args, **kwargs):
        tries.append(args)
        if len(tries) > 3:
            raise AssertionError("kept retrying a transcript it cannot read")
        raise OSError("locked")
    monkeypatch.setattr("builtins.open", refuse)
    assert cp.compacted_since(str(transcript), 0, SENT) is None
    assert len(tries) == 1
