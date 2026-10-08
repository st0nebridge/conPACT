"""
@module tests.regression.test_codex_compaction_finishes_before_success
@description A start acknowledgement cannot certify completed compaction or
             disrupt Desktop traffic. Regression test for CU-20261003-087.
@input      isolated rollouts and scripted control/RPC transports
@output     completion, routing, deadline and stream isolation assertions
@dependencies conpact.codex_compact, conpact.codex_inject,
              conpact.codex_meter, conpact.codex_sidecar;
              stdlib: json, threading
"""
import json
import threading
import io
from types import SimpleNamespace
import pytest

from conpact import (codex_compact, codex_inject, codex_meter,
                     codex_sidecar, codex_threads, codex_cli_hook, detach, platforms)


def event(kind, turn="compact-1"):
    return json.dumps({"type": "event_msg", "payload": {"type": kind,
                      "turn_id": turn}}) + "\n"


def setup_thread(monkeypatch, tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(event("task_complete", "previous"), encoding="utf-8")
    monkeypatch.setattr(codex_threads, "thread", lambda *a, **k:
                        {"id": "t-1", "rollout_path": str(rollout)})
    monkeypatch.setattr(platforms, "codex_session_of", lambda *a, **k: {})
    monkeypatch.setattr(platforms, "blocked", lambda *a, **k: None)
    return rollout


class Channel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent, self.lines = [], []

    def send(self, data):
        message = json.loads(data)
        self.sent.append(message)
        self.lines.append(json.dumps({"id": message["id"], **next(self.replies)}))

    def read_line(self, stop):
        return self.lines.pop(0) if self.lines else None

    def close(self):
        pass


def test_loaded_thread_is_compacted_without_resuming_it(monkeypatch):
    monkeypatch.setattr(codex_inject, "read_record", lambda *a, **k: {"tag": "test-"})
    channel = Channel([{"result": {}}, {"result": {}}])
    codex_inject.compact_thread("t-1", opener=lambda r: channel)
    assert [m["method"] for m in channel.sent] == ["thread/compact/start"]


def test_acknowledgement_with_no_completion_is_not_success(monkeypatch, tmp_path):
    setup_thread(monkeypatch, tmp_path)
    monkeypatch.setattr(codex_inject, "compact_thread", lambda *a, **k:
                        {"compacted": True, "detail": {}})
    got = codex_compact.compact("t-1", timeout=0.01)
    assert got["compacted"] is False


def test_sidecar_timeout_never_resubmits_on_another_server(monkeypatch, tmp_path):
    setup_thread(monkeypatch, tmp_path)
    monkeypatch.setattr(codex_inject, "compact_thread", lambda *a, **k:
                        {"compacted": False, "detail": "reply timed out"})
    attempts = []
    monkeypatch.setattr(codex_compact, "_through_host", lambda *a, **k:
                        attempts.append(a) or None)
    codex_compact.compact("t-1", timeout=0.01)
    assert attempts == []


def test_aborted_turn_is_idle_instead_of_running_forever(tmp_path):
    path = tmp_path / "aborted.jsonl"
    path.write_text(event("task_started") + event("turn_aborted"), encoding="utf-8")
    assert codex_meter.turn_state(path) == codex_meter.IDLE


def test_buffered_unrelated_replies_cannot_extend_the_deadline(monkeypatch):
    reads = []
    clock = iter(range(100))
    monkeypatch.setattr(codex_inject.time, "monotonic", lambda: next(clock))

    class Noisy:
        def read_line(self, stop):
            reads.append(stop)
            return '{"id":"other","result":{}}' if len(reads) < 20 else None

    assert codex_inject._await_reply(Noisy(), "ours", 3) is None
    assert len(reads) <= 3


def test_slow_control_reply_does_not_stop_other_desktop_sessions():
    blocked, release, forwarded = threading.Event(), threading.Event(), threading.Event()

    class Socket:
        def settimeout(self, timeout):
            pass

        def sendall(self, data):
            blocked.set()
            release.wait(1)

        def close(self):
            release.set()

    control = codex_sidecar.Control()
    conn = Socket()
    control.adopt(conn)
    lines = iter([b'{"id":"test-1","result":{}}\n'
                  b'{"method":"turn/started","params":{"threadId":"other"}}\n', b''])
    worker = threading.Thread(target=codex_sidecar.pump_to_desktop,
                              args=(lambda n: next(lines), lambda b: forwarded.set() or len(b),
                                    codex_sidecar.Lifter("test-"), control))
    worker.start()
    try:
        blocked.wait(0.2)
        passed_while_blocked = forwarded.wait(0.1)
    finally:
        release.set()
        worker.join(1)
        control.release(conn)
    assert passed_while_blocked


def test_cli_stop_returns_before_waiting_for_the_next_compaction(monkeypatch):
    monkeypatch.setattr(codex_cli_hook.sys, "stdin", io.StringIO(json.dumps(
        {"hook_event_name": "Stop", "session_id": "t-1"})))
    monkeypatch.setattr(codex_cli_hook, "hosted_by_conpact", lambda *a, **k: True)
    direct, spawned = [], []
    monkeypatch.setattr(codex_cli_hook, "run", lambda *a, **k: direct.append(a))
    monkeypatch.setattr(detach, "spawn", lambda argv, **kw: spawned.append(argv) or 123)
    codex_cli_hook.main()
    assert direct == [] and len(spawned) == 1
    assert "conpact.codex_arming" in spawned[0] and "--after-stop" in spawned[0]


def test_completed_target_rollout_is_required_after_sidecar_acceptance(monkeypatch, tmp_path):
    rollout = setup_thread(monkeypatch, tmp_path)

    def accepted(*a, **k):
        with rollout.open("a", encoding="utf-8") as out:
            out.write(event("task_started") + '{"type":"compacted","payload":{}}\n' +
                      event("task_complete"))
        return {"accepted": True, "detail": {}}

    monkeypatch.setattr(codex_inject, "compact_thread", accepted)
    got = codex_compact.compact("t-1", timeout=0.1)
    assert got["compacted"] and got["turn_id"] == "compact-1"


def test_foreign_global_sidecar_is_never_used_for_an_owned_request(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_inject.compaction, "STATE_DIR", tmp_path)
    (tmp_path / "codex-sidecar.json").write_text(json.dumps({
        "address": "127.0.0.1:202", "token": "secret", "tag": "foreign-",
        "pid": 202, "parent_pid": 202}), encoding="utf-8")
    opened = []
    channel = Channel([{"result": {}}, {"result": {}}])
    got = codex_inject.compact_thread("t-1", {"CONPACT_CODEX_OWNER_PID": "101"},
                                    opener=lambda r: opened.append(r["pid"]) or channel)
    assert got is None and opened == []


def test_owned_sidecar_is_used_even_when_another_server_overwrites_the_global_record(
        monkeypatch, tmp_path):
    monkeypatch.setattr(codex_inject.compaction, "STATE_DIR", tmp_path)
    foreign = {"address": "127.0.0.1:202", "token": "secret", "tag": "foreign-",
               "pid": 202, "parent_pid": 202}
    (tmp_path / "codex-sidecar.json").write_text(json.dumps(foreign), encoding="utf-8")
    owned = {**foreign, "address": "127.0.0.1:101", "pid": 99, "parent_pid": 101}
    folder = tmp_path / "codex-sidecars"
    folder.mkdir()
    (folder / "101.json").write_text(json.dumps(owned), encoding="utf-8")
    opened = []
    got = codex_inject.compact_thread("t-1", {"CONPACT_CODEX_OWNER_PID": "101"},
                                    opener=lambda r: opened.append(r["pid"]) or
                                    Channel([{"result": {}}]))
    assert opened == [99] and got["accepted"]


@pytest.mark.parametrize("close_raises", [False, True])
def test_control_record_failure_cannot_disconnect_desktop(monkeypatch, tmp_path, close_raises):
    child = SimpleNamespace(pid=123, stdin=io.BytesIO(), stdout=io.BytesIO(
        b'{"id":"desktop","result":{}}\n'), wait=lambda: 0)
    def close():
        if close_raises:
            raise OSError("control socket already closed")
    server = SimpleNamespace(getsockname=lambda: ("127.0.0.1", 5555), close=close)
    monkeypatch.setattr(codex_sidecar.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(codex_sidecar, "open_control", lambda: server)
    monkeypatch.setattr(codex_sidecar.codex_sidecar_log, "open_tap", lambda: None)
    def failed_record(*a, **k):
        raise OSError("control registry is unavailable")
    monkeypatch.setattr(codex_sidecar, "write_record", failed_record)
    class Immediate:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(codex_sidecar, "threading", SimpleNamespace(
        Lock=threading.Lock, Thread=Immediate))
    written = []
    code = codex_sidecar.proxy("real-codex", ["app-server"], home=tmp_path,
                              read_in=lambda _: b"", write_out=written.append)
    assert code == 0 and b"".join(written) == b'{"id":"desktop","result":{}}\n'


def test_host_resume_and_compact_share_one_deadline(monkeypatch):
    now, waits, closed = [0.0], [], []
    replies = iter([{"error": {"code": -32600, "message": "thread not found: t-1"}},
                    {"result": {}}, {"result": {}}])
    def request(method, params, timeout):
        waits.append(timeout)
        now[0] += 3.0
        return next(replies)
    server = SimpleNamespace(request=request, close=lambda: closed.append(True))
    monkeypatch.setattr(codex_compact.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(codex_compact.codex_host, "open_server", lambda *a, **k: (server, None))
    tracker = SimpleNamespace(wait=lambda stop: {"state": "completed", "turn_id": "c-1"})
    got = codex_compact._through_host("t-1", {}, timeout=10, tracker=tracker, stop=10)
    assert got["compacted"] and waits == [10, 7, 4] and closed == [True]


def test_host_record_replacement_cannot_redirect_an_owned_request(monkeypatch):
    from conpact import codex_appserver, codex_host
    records = iter([{"pid": 101}, {"pid": 202, "port": 5555, "token": "test"}])
    monkeypatch.setattr(codex_host, "read_record", lambda: next(records))
    monkeypatch.setattr(codex_host, "running", lambda *a: {"running": True})
    opened = []
    server = SimpleNamespace(request=lambda *a: {"error": {"message": "foreign server"}},
                             close=lambda: None)
    monkeypatch.setattr(codex_appserver, "connect_ws", lambda *a: opened.append(a) or server)
    got = codex_compact._through_host("t-1", {codex_inject.OWNER_ENV: "101"})
    assert opened == [] and got["compacted"] is False


def test_cli_stop_carries_the_owner_whose_ancestry_was_validated(monkeypatch):
    records = iter([{"pid": 101}, {"pid": 202}])
    monkeypatch.setattr(codex_cli_hook.codex_host, "read_record", lambda: next(records))
    monkeypatch.setattr(codex_cli_hook.os, "getppid", lambda: 101)
    monkeypatch.setattr(codex_cli_hook, "_parent_pid", lambda pid: None)
    envs = []
    got = codex_cli_hook.detach_stop({"hook_event_name": "Stop", "session_id": "t-1"},
        spawner=lambda argv, env: envs.append(env) or 123)
    assert got["action"] == "detached" and envs[0][codex_inject.OWNER_ENV] == "101"
