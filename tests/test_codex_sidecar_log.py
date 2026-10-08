"""Tests for conpact.codex_sidecar_log: the optional tap on the sidecar's pipes.

Two properties matter more than what it writes. It must be absent unless asked
for, and it must never be able to break the stream it is watching - a
diagnostic that can break the thing it diagnoses is worse than none.
"""
import json

import pytest

from conpact import codex_sidecar_log as slog


def _tap(bodies=False):
    written = []
    import threading
    return slog.Tap(written.append, threading.Lock(), bodies), written


class TestItIsOffUnlessAskedFor:
    def test_no_variable_means_no_tap_at_all(self):
        assert slog.open_tap({}) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_path_means_no_tap(self, value):
        assert slog.open_tap({slog.LOG_ENV: value}) is None

    def test_a_path_that_cannot_be_opened_is_not_an_error(self, tmp_path):
        wall = tmp_path / "file"
        wall.write_text("", encoding="utf-8")
        assert slog.open_tap({slog.LOG_ENV: str(wall / "under" / "a.log")}) is None

    def test_a_usable_path_gives_two_taps_and_a_closer(self, tmp_path):
        opened = slog.open_tap({slog.LOG_ENV: str(tmp_path / "deep" / "s.log")})
        assert opened is not None
        to_codex, to_desktop, close = opened
        assert to_codex is not to_desktop, "each direction holds its own partial line"
        close()
        assert (tmp_path / "deep" / "s.log").is_file()


class TestItNeverBreaksTheStream:
    def test_a_writer_that_raises_is_swallowed(self):
        import threading

        def explode(_text):
            raise OSError("the disk is gone")

        tap = slog.Tap(explode, threading.Lock())
        tap.note(slog.TO_CODEX, b'{"id":"1","method":"initialize"}\n')   # must not raise

    def test_bytes_that_are_not_utf8_are_recorded_not_raised(self):
        tap, written = _tap()
        tap.note(slog.TO_DESKTOP, b"\xff\xfe\x00nonsense\n")
        assert len(written) == 1 and "non-json" in written[0]

    def test_a_partial_line_waits_for_its_newline(self):
        tap, written = _tap()
        tap.note(slog.TO_CODEX, b'{"id":"1","meth')
        assert written == []
        tap.note(slog.TO_CODEX, b'od":"initialize"}\n')
        assert len(written) == 1 and "method=initialize" in written[0]

    def test_blank_lines_are_not_recorded(self):
        tap, written = _tap()
        tap.note(slog.TO_CODEX, b"\n\n   \n")
        assert written == []


class TestWhatItKeeps:
    def test_a_request_records_its_id_and_method(self):
        assert "method=account/usage/read" in slog.summarise(
            b'{"id":"7","method":"account/usage/read","params":{}}')

    def test_an_error_records_the_code_and_the_message(self):
        line = slog.summarise(json.dumps(
            {"id": "7", "error": {"code": -32603, "message": "failed to fetch usage"}}).encode())
        assert "ERROR" in line and "-32603" in line and "failed to fetch usage" in line

    def test_a_result_records_its_keys_and_not_its_values(self):
        line = slog.summarise(json.dumps(
            {"id": "7", "result": {"email": "someone@example.com", "planType": "pro"}}).encode())
        assert "email" in line and "planType" in line
        assert "someone@example.com" not in line, "the account's data stays off the disk"
        assert "pro" not in line.replace("planType", "")

    def test_bodies_are_only_written_when_they_are_asked_for(self):
        raw = json.dumps({"id": "7", "result": {"email": "someone@example.com"}}).encode()
        assert "someone@example.com" not in slog.summarise(raw, bodies=False)
        assert "someone@example.com" in slog.summarise(raw, bodies=True)

    def test_a_very_long_body_is_cut_and_says_so(self):
        raw = json.dumps({"id": "7", "result": {"blob": "x" * 20_000}}).encode()
        out = slog.summarise(raw, bodies=True)
        assert len(out) < 20_000 and "+" in out and "B)" in out

    @pytest.mark.parametrize("raw, expect", [
        (b"not json at all", "non-json"),
        (b"[1, 2, 3]", "json list"),
        (b'"a string"', "json str"),
    ])
    def test_anything_that_is_not_a_json_object_is_recorded_by_shape_only(self, raw, expect):
        assert expect in slog.summarise(raw)

    def test_a_notification_has_no_id_and_that_is_fine(self):
        line = slog.summarise(b'{"method":"thread/tokenUsage/updated","params":{"n":1}}')
        assert "method=thread/tokenUsage/updated" in line and "id=" not in line


class TestNotificationEnvelopes:
    """A notification is how the app-server says a turn ended, so the tap has to
    record enough to act on one - its keys and which thread it was - and still
    nothing that would be regrettable on disk."""

    def test_it_records_the_params_keys_of_a_notification(self):
        line = slog.summarise(
            b'{"method":"turn/completed","params":{"threadId":"abc-123","usage":{"total":9}}}')
        assert "method=turn/completed" in line
        assert "usage" in line and "threadId" in line

    def test_it_lifts_the_thread_id_out_because_that_is_what_makes_it_actionable(self):
        line = slog.summarise(b'{"method":"turn/completed","params":{"threadId":"abc-123"}}')
        assert "threadId=abc-123" in line

    def test_it_still_does_not_record_the_values_around_it(self):
        line = slog.summarise(
            b'{"method":"item/completed","params":{"threadId":"t1","text":"my secret plan"}}')
        assert "threadId=t1" in line
        assert "my secret plan" not in line

    def test_params_that_are_not_an_object_are_not_read_for_keys(self):
        assert "params keys" not in slog.summarise(b'{"method":"x","params":[1,2,3]}')
