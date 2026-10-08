"""Tests for conpact.context_meter: context size from a session transcript."""
import json

import pytest

from conpact import context_meter as cm

# Shape observed in a real Claude Code 2.1.275 transcript on 2026-09-19.
_USAGE = {"input_tokens": 2, "cache_creation_input_tokens": 476,
          "cache_read_input_tokens": 299715, "output_tokens": 3055}


def _assistant(usage, sidechain=False, model="claude-opus-5"):
    return {"type": "assistant", "isSidechain": sidechain, "sessionId": "s",
            "message": {"model": model, "role": "assistant", "usage": usage}}


def _usage(total):
    return {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": total, "output_tokens": 0}


def _write(path, entries, tail=""):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries) + tail, encoding="utf-8")
    return path


def test_usage_tokens_sums_input_cache_and_output():
    assert cm.usage_tokens(_assistant(_USAGE)) == 2 + 476 + 299715 + 3055


@pytest.mark.parametrize("entry", [
    {"type": "user", "message": {"usage": _USAGE}},
    _assistant(_USAGE, sidechain=True),
    _assistant(_USAGE, model="<synthetic>"),
    _assistant(_usage(0)),
    {"type": "assistant", "message": {"model": "m"}},
    {"type": "assistant", "message": "not a dict"},
    {"type": "assistant", "message": {"model": "m", "usage": "nope"}},
    "not a dict",
])
def test_usage_tokens_ignores_entries_that_do_not_describe_the_main_context(entry):
    assert cm.usage_tokens(entry) is None


def test_usage_tokens_ignores_non_integer_fields():
    entry = _assistant({"input_tokens": "5", "output_tokens": True, "cache_read_input_tokens": 10})
    assert cm.usage_tokens(entry) == 10


def test_current_context_uses_the_last_main_thread_usage(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant(_usage(100)),
        _assistant(_usage(250)),
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        _assistant(_usage(999), sidechain=True),
        _assistant(_usage(0), model="<synthetic>"),
        {"type": "attachment"},
    ])
    assert cm.current_context_tokens(path) == 250


def test_current_context_reads_further_back_when_the_tail_has_no_usage(tmp_path):
    filler = [{"type": "user", "message": {"content": "x" * 50}} for _ in range(40)]
    path = _write(tmp_path / "t.jsonl", [_assistant(_usage(4321))] + filler)
    assert cm.current_context_tokens(path, tail_bytes=64) == 4321


def test_current_context_skips_a_partially_written_last_line(tmp_path):
    path = _write(tmp_path / "t.jsonl", [_assistant(_usage(700))], tail='{"type": "assistant", "mess')
    assert cm.current_context_tokens(path) == 700


def test_current_context_ignores_a_line_cut_by_the_tail_window(tmp_path):
    # The window starts mid-way through the only usage line, so that line must be
    # ignored rather than misread, and the full read must find it.
    path = _write(tmp_path / "t.jsonl", [_assistant(_usage(555)), {"type": "user"}])
    size = path.stat().st_size
    assert cm.current_context_tokens(path, tail_bytes=size - 5) == 555


@pytest.mark.parametrize("content", ["", "\n\n", "not json\n", json.dumps({"type": "user"}) + "\n"])
def test_current_context_is_none_without_usage(tmp_path, content):
    path = tmp_path / "t.jsonl"
    path.write_text(content, encoding="utf-8")
    assert cm.current_context_tokens(path) is None


def test_current_context_is_none_for_a_missing_or_unreadable_path(tmp_path):
    assert cm.current_context_tokens(tmp_path / "absent.jsonl") is None
    assert cm.current_context_tokens(tmp_path) is None
    assert cm.current_context_tokens(None) is None
    assert cm.current_context_tokens("") is None


def test_find_transcript_by_session_id(tmp_path):
    project = tmp_path / "C--src-X"
    project.mkdir()
    path = _write(project / "sess-1.jsonl", [])
    assert cm.find_transcript("sess-1", projects_dir=tmp_path) == path
    assert cm.find_transcript("sess-2", projects_dir=tmp_path) is None


@pytest.mark.parametrize("bad", [None, "", "*", "../x", "a?b", "[ab]"])
def test_find_transcript_rejects_ids_that_are_not_plain(tmp_path, bad):
    (tmp_path / "p").mkdir()
    _write(tmp_path / "p" / "x.jsonl", [])
    assert cm.find_transcript(bad, projects_dir=tmp_path) is None


def test_find_transcript_defaults_to_the_projects_dir():
    (cm.PROJECTS_DIR / "proj").mkdir(parents=True)
    path = _write(cm.PROJECTS_DIR / "proj" / "sess-9.jsonl", [])
    assert cm.find_transcript("sess-9") == path


def test_find_transcript_missing_projects_dir(tmp_path):
    assert cm.find_transcript("sess-1", projects_dir=tmp_path / "absent") is None


def test_find_transcript_survives_an_unreadable_projects_dir(tmp_path, monkeypatch):
    import pathlib

    def refuse(self, pattern):
        raise PermissionError("denied")

    monkeypatch.setattr(pathlib.Path, "glob", refuse)
    assert cm.find_transcript("sess-1", projects_dir=tmp_path) is None


@pytest.mark.real_paths
def test_projects_dir_is_claude_codes():
    import os
    import pathlib
    assert cm.PROJECTS_DIR == pathlib.Path(os.path.expanduser("~")) / ".claude" / "projects"


def test_entries_from_end_yields_newest_first(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"n": 1}, {"n": 2}, {"n": 3}])
    assert [e["n"] for e in cm.entries_from_end(path)] == [3, 2, 1]


def test_entries_from_end_reads_back_in_growing_windows_without_repeats(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"n": i, "pad": "x" * 30} for i in range(50)])
    assert [e["n"] for e in cm.entries_from_end(path, tail_bytes=64)] == list(range(49, -1, -1))


def test_entries_from_end_handles_a_line_longer_than_the_window(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"n": 0, "pad": "y" * 500}, {"n": 1}])
    assert [e["n"] for e in cm.entries_from_end(path, tail_bytes=16)] == [1, 0]


def test_entries_from_end_yields_only_whole_json_objects(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"n": 1}], tail='[1, 2]\n\nnot json\n{"n": 2')
    assert list(cm.entries_from_end(path)) == [{"n": 1}]


def test_entries_from_end_is_empty_for_a_missing_or_unreadable_path(tmp_path):
    assert list(cm.entries_from_end(tmp_path / "absent.jsonl")) == []
    assert list(cm.entries_from_end(tmp_path)) == []
    assert list(cm.entries_from_end(None)) == []
    assert list(cm.entries_from_end("")) == []
