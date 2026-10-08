"""
@module tests.test_codex_completion
@description Recorded compaction completion, turn identity, bounded observation
             and failure handling against isolated real rollout files.
@input      temporary JSONL rollouts and a simulated monotonic clock
@output     assertions on completed, failed and unobserved operations
@dependencies conpact.codex_completion; stdlib: json, os
"""
import json
import os

import pytest

from conpact import codex_completion as cc


def row(kind, turn="c-1", **extra):
    return {"type": "event_msg", "payload": {"type": kind, "turn_id": turn, **extra}}


def append(path, *rows):
    with path.open("a", encoding="utf-8") as stream:
        for entry in rows:
            stream.write(json.dumps(entry) + "\n")


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "target.jsonl"
    append(path, row("task_started", "old"), {"type": "compacted", "payload": {}},
           row("task_complete", "old"))
    return path, cc.Rollout(path)


def test_old_completion_is_not_evidence_for_a_new_request(target):
    path, tracker = target
    assert tracker.poll() is None
    assert tracker.wait(1, clock=lambda: 2)["state"] == "unobserved"


def test_compaction_and_its_matching_completion_are_both_required(target):
    path, tracker = target
    append(path, row("task_started"), {"type": "compacted", "payload": {}})
    assert tracker.poll() is None
    append(path, row("task_complete", "another"))
    assert tracker.poll() is None
    append(path, row("task_complete"))
    assert tracker.poll() == {"state": "completed", "turn_id": "c-1", "detail": None}


def test_partial_json_is_read_when_the_record_finishes(target):
    path, tracker = target
    data = json.dumps(row("task_started")).encode()
    with path.open("ab") as out:
        out.write(data[:12])
    assert tracker.poll() is None
    with path.open("ab") as out:
        out.write(data[12:] + b"\n")
    append(path, row("context_compacted"), row("task_complete"))
    assert tracker.poll()["state"] == "completed"


@pytest.mark.parametrize("end,detail", [
    ("turn_aborted", "interrupted"),
    ("task_complete", "without recording"),
])
def test_an_aborted_or_uncompacted_turn_is_not_success(target, end, detail):
    path, tracker = target
    append(path, row("task_started"), row(end))
    got = tracker.poll()
    assert got["state"] == "failed" and detail in got["detail"]


def test_recorded_error_is_preserved_when_a_turn_finishes_without_compaction(target):
    path, tracker = target
    append(path, row("task_started"), row("error", message="stream timed out"), row("task_complete"))
    assert tracker.poll()["detail"] == "stream timed out"


def test_another_turns_compaction_cannot_complete_the_original(target):
    path, tracker = target
    append(path, row("task_started"), row("task_started", "new"),
           {"type": "compacted", "payload": {}}, row("task_complete", "new"), row("task_complete"))
    assert tracker.poll()["state"] == "failed"


def test_invalid_or_unrelated_records_are_ignored(target):
    path, tracker = target
    append(path, [], {}, {"payload": []}, {"type": "response_item", "payload": {}},
           row("task_started", None), {"type": "compacted", "payload": {}},
           row("context_compacted"), row("task_complete", "other"))
    with path.open("ab") as stream:
        stream.write(b'invalid\n\xff\n')
    assert tracker.poll() is None


@pytest.mark.parametrize("change", ["truncate", "replace", "remove"])
def test_changed_or_missing_rollout_is_unobserved(target, tmp_path, change):
    path, tracker = target
    if change == "truncate":
        path.write_bytes(b"")
    elif change == "replace":
        replacement = tmp_path / "new.jsonl"
        replacement.write_bytes(b"")
        os.replace(replacement, path)
    else:
        path.unlink()
    got = tracker.wait(10, clock=lambda: 0)
    assert got["state"] == "unobserved" and "could not be observed" in got["detail"]


def test_oversized_partial_record_has_a_bounded_buffer(target, monkeypatch):
    path, tracker = target
    monkeypatch.setattr(cc, "MAX_LINE", 8)
    with path.open("ab") as out:
        out.write(b"partial-record-too-long")
    assert tracker.wait(10, clock=lambda: 0)["state"] == "unobserved"


def test_large_compaction_history_is_observed_with_a_bounded_buffer(target, monkeypatch):
    """A Codex project wrote a 15.5 MB compacted row on 2026-10-07."""
    path, tracker = target
    monkeypatch.setattr(cc, "MAX_LINE", 512)
    monkeypatch.setattr(cc, "CHUNK", 128)
    append(path, row("task_started"), {
        "timestamp": "2026-10-07T23:01:07.765Z", "ordinal": 50165, "type": "compacted",
        "payload": {"replacement_history": [{"text": "x" * 4096}]},
    })
    for _ in range(50):
        assert tracker.poll() is None  # A record is not a completed turn.
        assert len(tracker.held) <= cc.MAX_LINE + cc.CHUNK
    assert tracker.compacted is True
    append(path, row("task_complete"))
    assert tracker.poll() == {"state": "completed", "turn_id": "c-1", "detail": None}


def test_partial_large_compaction_is_not_evidence_until_its_record_ends(target, monkeypatch):
    path, tracker = target
    monkeypatch.setattr(cc, "MAX_LINE", 256)
    append(path, row("task_started"))
    with path.open("ab") as out:
        out.write(b'{"type":"compacted","payload":{"text":"' + b'x' * 1024)
    assert tracker.poll() is None
    assert tracker.compacted is False
    with path.open("ab") as out:
        out.write(b'"}}\n')
    append(path, row("task_complete"))
    assert tracker.poll()["state"] == "completed"


def test_large_history_from_another_turn_cannot_confirm_our_compaction(target, monkeypatch):
    path, tracker = target
    monkeypatch.setattr(cc, "MAX_LINE", 256)
    monkeypatch.setattr(cc, "CHUNK", 128)
    append(path, row("task_started"), row("task_started", "other"), {
        "type": "compacted", "payload": {"text": "x" * 2048},
    }, row("task_complete", "other"), row("task_complete"))
    for _ in range(30):
        result = tracker.poll()
        if result is not None:
            break
    assert result["state"] == "failed"
    assert result["turn_id"] == "c-1" and not tracker.compacted


@pytest.mark.parametrize("header", [
    b'{"type":"response_item","payload":{"type":"compacted","text":"',
    b'{"type":"compacted","payload":["',
])
def test_large_unrelated_record_cannot_become_a_compaction(target, monkeypatch, header):
    path, tracker = target
    monkeypatch.setattr(cc, "MAX_LINE", 64)
    with path.open("ab") as out:
        out.write(header + b'x' * 1024)
    assert tracker.wait(10, clock=lambda: 0)["state"] == "unobserved"


def test_wait_uses_one_deadline_and_checks_new_records(target):
    path, tracker = target
    now, pauses = [0], []

    def sleep(seconds):
        pauses.append(seconds)
        now[0] += seconds
        append(path, row("task_started"), row("context_compacted"), row("task_complete"))

    got = tracker.wait(1, clock=lambda: now[0], sleep=sleep)
    assert got["state"] == "completed" and pauses == [cc.POLL]


def test_empty_rollout_times_out_without_retry_or_cancel(target):
    path, tracker = target
    now, pauses = [0], []

    def sleep(seconds):
        pauses.append(seconds)
        now[0] += seconds

    got = tracker.wait(0.1, clock=lambda: now[0], sleep=sleep)
    assert got["state"] == "unobserved" and "may still be running" in got["detail"]
    assert pauses == [0.1]


def test_missing_target_is_refused_before_observation(tmp_path):
    with pytest.raises(ValueError):
        cc.Rollout(None)
    with pytest.raises(OSError):
        cc.Rollout(tmp_path / "missing")
