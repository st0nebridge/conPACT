"""@module tests.regression.test_codex_rpc_waits_have_deadlines
@description Notifications cannot extend an RPC's overall timeout.
@input Scripted monotonic clock and notification-only transports.
@output Both transports expire despite continuous unrelated messages.
@dependencies conpact.codex_appserver; stdlib: types
"""
from types import SimpleNamespace

import pytest

from conpact import codex_appserver, codex_ws


class Clock:
    def __init__(self):
        self.at = 0

    def monotonic(self):
        self.at += 1
        return self.at


def test_stdio_notifications_do_not_restart_the_wait(monkeypatch):
    monkeypatch.setattr(codex_appserver, 'time', Clock(), raising=False)
    waits = []

    class Inbox:
        def get(self, timeout):
            waits.append(timeout)
            if len(waits) > 5:
                pytest.fail('notifications kept an expired request alive')
            return {'method': 'unrelated'}

    server = object.__new__(codex_appserver.AppServer)
    server.process = SimpleNamespace(stdin=SimpleNamespace(write=lambda _: None, flush=lambda: None))
    server.inbox = Inbox()
    with pytest.raises(TimeoutError):
        server.request('request', {}, 3)
    assert waits == [2, 1]


def test_websocket_notifications_do_not_restart_the_wait(monkeypatch):
    monkeypatch.setattr(codex_appserver, 'time', Clock(), raising=False)
    waits = []
    received = []

    def recv():
        received.append(True)
        if len(received) > 5:
            pytest.fail('notifications kept an expired request alive')
        return '{"method":"unrelated"}'

    connection = SimpleNamespace(sock=SimpleNamespace(settimeout=waits.append),
                                 send=lambda _: None, recv=recv)
    with pytest.raises(TimeoutError):
        codex_appserver.WebSocketServer(connection).request('request', {}, 3)
    assert waits == [3, 2, 1]


def test_websocket_pings_also_obey_the_request_deadline(monkeypatch):
    monkeypatch.setattr(codex_ws, 'time', Clock(), raising=False)
    reads = []

    def recv(_):
        reads.append(True)
        if len(reads) > 5:
            pytest.fail('ping frames kept an expired request alive')
        return b'\x89\x00'

    sock = SimpleNamespace(recv=recv, sendall=lambda _: None, settimeout=lambda _: None)
    connection = codex_ws.WebSocket(sock)
    connection.deadline = 3
    with pytest.raises(TimeoutError):
        connection.recv()
