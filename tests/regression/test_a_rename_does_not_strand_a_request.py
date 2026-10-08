"""Regression: a request written by an older server is still claimed.

CU-20260922-041 renamed this project's state folder from `clautomatic` to
`conpact`. A rename moves files on disk; it does not move the module already
imported into a running process, and an MCP server lives as long as the session
that started it. Measured on the day: nine of ten live servers were still
writing to the old folder while the Stop hook read the new one, so five queued
compactions sat stranded and nothing said so - "nothing pending" is a skip, and
a skip is silent.

The reader looks in both places. Nothing writes to the old one.
"""
import json

import pytest

from conpact import compaction

SESSION = "0a0a0a0a-0000-4000-8000-000000000007"


def _write(where, session_id, focus):
    where.mkdir(parents=True, exist_ok=True)
    (where / f"{session_id}.json").write_text(
        json.dumps({"session_id": session_id, "focus": focus}), encoding="utf-8")


class TestAnOlderServersRequestIsStillHonoured:
    def test_it_is_found_where_the_older_server_left_it(self):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "stranded")
        assert compaction.pending_request(SESSION)["focus"] == "stranded"

    def test_it_is_claimed_and_then_gone(self):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "stranded")
        assert compaction.consume_request(SESSION)["focus"] == "stranded"
        assert compaction.pending_request(SESSION) is None

    def test_it_still_fires_at_most_once(self):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "stranded")
        assert compaction.consume_request(SESSION) is not None
        assert compaction.consume_request(SESSION) is None

    def test_the_current_folder_wins_when_both_hold_one(self):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "old")
        _write(compaction.REQUESTS_DIR, SESSION, "current")
        assert compaction.pending_request(SESSION)["focus"] == "current"

    def test_cancelling_clears_it_wherever_it_is(self):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "stranded")
        assert compaction.cancel_request(SESSION) is True
        assert compaction.pending_request(SESSION) is None

    def test_nothing_anywhere_is_still_nothing(self):
        assert compaction.pending_request(SESSION) is None
        assert compaction.consume_request(SESSION) is None
        assert compaction.cancel_request(SESSION) is False


class TestANamedFolderMeansThatFolder:
    """Only the default lookup reaches back; a caller that names a directory
    gets that directory, which is what keeps every other test isolated."""

    def test_an_explicit_folder_does_not_consult_the_old_one(self, tmp_path):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "stranded")
        assert compaction.pending_request(SESSION, requests_dir=tmp_path) is None
        assert compaction.consume_request(SESSION, requests_dir=tmp_path) is None

    def test_and_the_old_one_is_left_untouched_by_it(self, tmp_path):
        _write(compaction.LEGACY_REQUESTS_DIR, SESSION, "stranded")
        compaction.cancel_request(SESSION, requests_dir=tmp_path)
        assert compaction.pending_request(SESSION)["focus"] == "stranded"
