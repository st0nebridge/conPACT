"""
Regression test for CU-20260919-004 (review finding 2).

Compaction requests used to be written into Claude Code's own runtime folder
(~/.claude/sessions/), beside the per-process session records. They were read
back as if they were sessions, and Claude Code may tidy files there that it did
not create. Requests now live in a folder conPACT owns - since CU-20260923-058
its own home, ~/.conpact/, outside Claude Code's folder altogether - and a
session id only ever becomes a file name if it is a plain id.
"""
import pytest

from conpact import compaction, home, session_registry


@pytest.mark.real_paths
def test_requests_live_in_a_folder_conpact_owns():
    assert compaction.REQUESTS_DIR == home.HOME / "requests"
    assert session_registry.CLAUDE_DIR not in compaction.REQUESTS_DIR.parents
    assert compaction.REQUESTS_DIR != session_registry.SESSIONS_DIR
    assert session_registry.SESSIONS_DIR not in compaction.REQUESTS_DIR.parents


def test_request_files_are_not_read_as_session_records(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    requests = tmp_path / "requests"
    compaction.request_compaction("sess-a", requests_dir=requests)
    assert session_registry.load_records(sessions) == []
    assert compaction.consume_request("sess-a", requests_dir=requests) is not None


@pytest.mark.parametrize("bad", [None, "", "../x", "a/b", "a\\b", "C:x", "None?", "x" * 200])
def test_invalid_session_ids_never_become_paths(tmp_path, bad):
    with pytest.raises(ValueError):
        compaction.request_compaction(bad, requests_dir=tmp_path)
    assert compaction.consume_request(bad, requests_dir=tmp_path) is None
    assert list(tmp_path.iterdir()) == []
