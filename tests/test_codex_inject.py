"""
@module tests.test_codex_inject
@description Reaching the desktop's live app-server through the sidecar's
             control channel: the record it reads, the request it frames, the
             tagged reply it lifts out, and the promise that no sidecar means
             "fall back", never a crash.
@input      conpact.codex_inject, against a fake transport
@output     assertions on the request shape, reply matching, every fall-back
            path, and the compaction routing in codex_compact
@dependencies conpact.codex_inject, conpact.codex_compact; stdlib: json
"""
import json

import pytest

from conpact import codex_compact, codex_inject, codex_threads, compaction, platforms
from types import SimpleNamespace


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(compaction, "STATE_DIR", tmp_path / "conpact")
    return tmp_path


@pytest.fixture
def record(state, monkeypatch):
    monkeypatch.setenv(codex_inject.OWNER_ENV, "4243")
    def write(address="127.0.0.1:51234", token="s3cret", pid=4242,
              tag="conpact-4242-"):
        path = codex_inject.record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"address": address, "token": token,
                                    "pid": pid, "tag": tag, "parent_pid": 4243}), encoding="utf-8")
    return write


class FakeChannel:
    """A sidecar channel that answers a scripted reply to whatever id it is sent."""

    def __init__(self, *, reply=None, error=None, silent=False, drop=False):
        self.reply, self.error, self.silent, self.drop = reply, error, silent, drop
        self.sent, self.closed = [], False
        self._lines = []

    def send(self, data):
        if self.drop:
            raise OSError("pipe broke")
        message = json.loads(data.decode("utf-8"))
        self.sent.append(message)
        if self.silent:
            return
        body = {"id": message["id"]}
        if self.error is not None:
            body["error"] = self.error
        else:
            body["result"] = self.reply if self.reply is not None else {"ok": True}
        self._lines.append(json.dumps(body))

    def read_line(self, deadline):
        return self._lines.pop(0) if self._lines else None

    def close(self):
        self.closed = True


class TestTheRecord:
    def test_no_record_reads_as_nothing(self, state):
        assert codex_inject.read_record() is None

    def test_a_record_is_read_back_with_the_address_split_out(self, record):
        record()
        assert codex_inject.read_record() == {
            "address": "127.0.0.1:51234", "host": "127.0.0.1", "port": 51234,
            "token": "s3cret", "pid": 4242, "tag": "conpact-4242-"}

    @pytest.mark.parametrize("body", [
        "not json", "[]", '{"pid": 1}',
        '{"address": "", "token": "t", "tag": "t"}',
        '{"address": "127.0.0.1:1", "token": "t", "tag": ""}',
        '{"address": "127.0.0.1:1", "token": "", "tag": "t"}',
        '{"address": "127.0.0.1", "token": "t", "tag": "t"}',
        '{"address": "127.0.0.1:nope", "token": "t", "tag": "t"}',
        '{"address": ":51234", "token": "t", "tag": "t"}'])
    def test_a_record_that_makes_no_sense_reads_as_nothing(self, state, body):
        path = codex_inject.record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        assert codex_inject.read_record() is None


class TestTheRequest:
    def test_it_names_the_method_and_the_thread_tagged_so_its_reply_is_found(self):
        request_id, body = codex_inject._request("thread/compact/start", "t-1", "conpact-99-")
        message = json.loads(body.decode("utf-8"))
        assert message["method"] == "thread/compact/start"
        assert message["params"] == {"threadId": "t-1"}
        assert request_id.startswith("conpact-99-")
        assert message["id"] == request_id
        assert body.endswith(b"\n")

    def test_the_methods_are_the_ones_codex_serves(self):
        assert codex_inject.RESUME == "thread/resume"
        assert codex_inject.COMPACT == "thread/compact/start"

    def test_two_requests_do_not_share_an_id(self):
        assert codex_inject._request("m", "t", "x-")[0] != codex_inject._request("m", "t", "x-")[0]


class TestRoutingThroughTheSidecar:
    def test_with_no_sidecar_it_returns_none_to_fall_back(self, state):
        assert codex_inject.compact_thread("t-1") is None

    def test_it_compacts_a_loaded_thread_without_resuming_it(self, record):
        record()
        channel = FakeChannel(reply={"compacted": True})
        got = codex_inject.compact_thread("t-1", opener=lambda record: channel)
        assert got == {"compacted": False, "accepted": True, "via": "sidecar",
                       "detail": {"compacted": True}}
        assert [m["method"] for m in channel.sent] == ["thread/compact/start"]
        assert all(m["params"] == {"threadId": "t-1"} for m in channel.sent)
        assert channel.closed is True

    def test_a_compaction_refusal_is_reported_without_a_resume_retry(self, record):
        record()
        channel = FakeChannel(error={"message": "no such thread"})
        got = codex_inject.compact_thread("t-1", opener=lambda record: channel)
        assert (got["compacted"], got["detail"]) == (False, {"message": "no such thread"})
        assert [m["method"] for m in channel.sent] == ["thread/compact/start"]

    def test_a_channel_that_will_not_open_falls_back_rather_than_raising(self, record):
        record()

        def broken(record):
            raise OSError("nothing is listening")

        assert codex_inject.compact_thread("t-1", opener=broken) is None

    def test_a_reply_that_never_comes_is_reported_within_the_deadline(self, record):
        record()
        channel = FakeChannel(silent=True)
        got = codex_inject.compact_thread("t-1", opener=lambda record: channel, deadline=0.05)
        assert got["compacted"] is False
        assert "did not answer" in got["detail"]
        assert "thread/compact/start" in got["detail"]

    def test_a_channel_that_breaks_mid_call_is_reported_not_raised(self, record):
        record()
        got = codex_inject.compact_thread("t-1", opener=lambda record: FakeChannel(drop=True))
        assert got["compacted"] is False
        assert "OSError" in got["detail"]

    def test_replies_to_other_ids_are_skipped_until_ours_arrives(self, record):
        record()

        class Noisy(FakeChannel):
            def send(self, data):
                mine = json.loads(data.decode())["id"]
                self._lines.append(json.dumps({"id": "someone-else", "result": {"no": True}}))
                self._lines.append(json.dumps({"id": mine, "result": {"yes": True}}))
                self.sent.append(json.loads(data.decode()))

        got = codex_inject.compact_thread("t-1", opener=lambda record: Noisy())
        assert got["detail"] == {"yes": True}

    def test_the_channel_is_always_closed(self, record):
        record()
        channel = FakeChannel(drop=True)
        codex_inject.compact_thread("t-1", opener=lambda record: channel)
        assert channel.closed is True

    @pytest.mark.parametrize("last_reply,accepted", [({"result": {}}, True),
        ({"error": {"message": "cannot resume"}}, False)])
    def test_only_explicit_not_loaded_allows_metadata_resume(self, record, last_reply, accepted):
        record()
        replies = iter([{"error": {"code": -32600, "message": "thread not found: t-1"}},
                        last_reply, {"result": {}}])
        class Scripted(FakeChannel):
            def send(self, data):
                msg = json.loads(data)
                self.sent.append(msg)
                self._lines.append(json.dumps({"id": msg["id"], **next(replies)}))
        channel = Scripted()
        got = codex_inject.compact_thread("t-1", opener=lambda r: channel)
        assert bool(got.get("accepted")) == accepted and channel.closed
        assert channel.sent[1]["params"] == {"threadId": "t-1", "excludeTurns": True}
        assert [m["method"] for m in channel.sent] == (
            [codex_inject.COMPACT, codex_inject.RESUME, codex_inject.COMPACT] if accepted else
            [codex_inject.COMPACT, codex_inject.RESUME])

    def test_expired_deadline_does_not_submit_a_request(self, record):
        record()
        channel = FakeChannel()
        got = codex_inject.compact_thread("t-1", opener=lambda r: channel, deadline=0)
        assert channel.sent == [] and channel.closed and not got.get("accepted")


class TestSocketTransport:
    class Socket:
        def __init__(self, blocks=(), *, fail_send=False, fail_close=False):
            self.blocks = iter(blocks)
            self.sent, self.timeouts, self.closed = [], [], False
            self.fail_send, self.fail_close = fail_send, fail_close
        def sendall(self, data):
            if self.fail_send:
                raise OSError("authentication send failed")
            self.sent.append(data)
        def recv(self, size):
            value = next(self.blocks)
            if isinstance(value, BaseException):
                raise value
            return value
        def settimeout(self, seconds):
            self.timeouts.append(seconds)
        def close(self):
            self.closed = True
            if self.fail_close:
                raise OSError("already closed")

    def test_authentication_fragmented_lines_and_buffered_following_line(self, monkeypatch):
        sock = self.Socket([TimeoutError(), b'first', b'\nsecond\n'])
        opened = []
        monkeypatch.setattr(codex_inject.socket, "create_connection",
                            lambda address, wait: opened.append((address, wait)) or sock)
        channel = codex_inject._Channel("127.0.0.1", 123, "test-token")
        channel.send(b'request\n')
        lines = [channel.read_line(codex_inject.time.monotonic() + 1) for _ in range(2)]
        channel.close()
        assert lines == ["first", "second"] and sock.closed
        assert sock.sent == [b'test-token\n', b'request\n']
        assert opened == [(("127.0.0.1", 123), 3.0)]
        assert all(0 < wait <= 0.2 for wait in sock.timeouts)

    def test_authentication_failure_closes_the_channel_even_if_close_raises(self, monkeypatch):
        sock = self.Socket(fail_send=True, fail_close=True)
        monkeypatch.setattr(codex_inject.socket, "create_connection", lambda *a: sock)
        with pytest.raises(OSError, match="authentication send failed"):
            codex_inject._Channel("127.0.0.1", 123, "test-token")
        assert sock.closed

    def test_eof_and_expired_wait_cannot_hang_the_reader(self, monkeypatch):
        sock = self.Socket([b''])
        monkeypatch.setattr(codex_inject.socket, "create_connection", lambda *a: sock)
        channel = codex_inject._Channel("127.0.0.1", 123, "test-token")
        with pytest.raises(OSError, match="closed the connection"):
            channel.read_line(codex_inject.time.monotonic() + 1)
        assert channel.read_line(codex_inject.time.monotonic() - 1) is None
        channel.close()

    def test_invalid_and_non_object_messages_are_ignored_before_our_reply(self):
        lines = iter(["invalid", "[]", '{"id":"ours","result":{}}'])
        channel = SimpleNamespace(read_line=lambda stop: next(lines))
        got = codex_inject._await_reply(channel, "ours", codex_inject.time.monotonic() + 1)
        assert got == {"id": "ours", "result": {}}


class TestAllCompactionGoesThroughTheSidecar:
    """Every thread that may be compacted - busy or free - goes through the
    sidecar, because it is the desktop's own app-server and the only process
    that may write any rollout. The own-app-server path is only the fallback for
    a machine with no sidecar installed."""

    def _thread(self, monkeypatch, blocked):
        monkeypatch.setattr(codex_threads, "thread", lambda tid, env=None: {"id": tid})
        monkeypatch.setattr(platforms, "codex_session_of",
                            lambda record, env=None, measure=True: {})
        monkeypatch.setattr(platforms, "blocked", lambda s: blocked)
        monkeypatch.setattr(codex_compact.codex_meter, "turn_state", lambda *a, **k: "idle")
        class Completed:
            def __init__(self, path):
                pass

            def wait(self, stop):
                return {"state": "completed", "turn_id": "c-1", "detail": None}
        monkeypatch.setattr(codex_compact.codex_completion, "Rollout", Completed)

    @pytest.mark.parametrize("blocked", [platforms.BUSY, None])
    def test_busy_and_free_threads_both_go_through_the_sidecar(self, monkeypatch, blocked):
        seen = []
        self._thread(monkeypatch, blocked)
        monkeypatch.setattr(codex_inject, "compact_thread",
                            lambda tid, env=None, **kw: seen.append(tid) or
                            {"compacted": True, "via": "sidecar", "detail": {"ok": True}})
        got = codex_compact.compact("t-9")
        assert got["compacted"] is True
        assert seen == ["t-9"]

    def test_a_sidecar_refusal_is_reported_as_a_failure_with_its_detail(self, monkeypatch):
        self._thread(monkeypatch, platforms.BUSY)
        monkeypatch.setattr(codex_inject, "compact_thread",
                            lambda tid, env=None, **kw: {"compacted": False, "via": "sidecar",
                                                   "detail": "the app-server refused"})
        got = codex_compact.compact("t-9")
        assert (got["compacted"], got["reason"]) == (False, codex_compact.FAILED)
        assert got["detail"] == "the app-server refused"

    def test_a_busy_thread_with_no_sidecar_is_refused(self, monkeypatch):
        """The own-app-server fallback can reach only a free thread."""
        self._thread(monkeypatch, platforms.BUSY)
        monkeypatch.setattr(codex_inject, "compact_thread", lambda tid, env=None, **kw: None)
        got = codex_compact.compact("t-9")
        assert (got["compacted"], got["reason"]) == (False, platforms.BUSY)

    def test_a_free_thread_with_no_sidecar_falls_back_to_our_own_app_server(self, monkeypatch):
        self._thread(monkeypatch, None)
        monkeypatch.setattr(codex_inject, "compact_thread", lambda tid, env=None, **kw: None)
        reached = []
        monkeypatch.setattr(codex_compact, "codex_cli", lambda env: reached.append("own") or None)
        got = codex_compact.compact("t-9")
        assert reached == ["own"]                          # the fallback path ran
        assert got["reason"] == codex_compact.NO_CLI       # (stopped at a missing cli)

    @pytest.mark.parametrize("blocking", ["archived", "spin_off"])
    def test_a_thread_that_must_not_be_touched_never_reaches_the_sidecar(self, monkeypatch, blocking):
        reason = getattr(platforms, blocking.upper())
        self._thread(monkeypatch, reason)
        monkeypatch.setattr(codex_inject, "compact_thread",
                            lambda tid, env=None: pytest.fail("a guarded thread must not be injected"))
        got = codex_compact.compact("t-9")
        assert (got["compacted"], got["reason"]) == (False, reason)


class TestNothingOpensTheRealPipeUnasked:
    def test_without_an_injected_opener_the_real_one_is_looked_up_at_call_time(
            self, record, _isolate_user_state):
        """A default bound at import would sail past the guard that stands for
        'no test opens the sidecar channel' (D-20260920-018)."""
        record()
        with pytest.raises(AssertionError):
            codex_inject.compact_thread("t-1")
        assert "open the sidecar channel" in _isolate_user_state
        _isolate_user_state.clear()
