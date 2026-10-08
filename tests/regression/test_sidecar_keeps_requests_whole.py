"""@module tests.regression.test_sidecar_keeps_requests_whole
@description Control injection cannot splice into a split Desktop JSON line.
@input Fragmented request streams and a recording child pipe.
@output Two independently parseable requests, without lost bytes.
@dependencies conpact.codex_sidecar; stdlib: json, threading
"""
import json
import threading

from conpact import codex_sidecar as sc


class Pipe:
    def __init__(self):
        self.data = bytearray()

    def write(self, chunk):
        self.data.extend(chunk)
        return len(chunk)

    def flush(self):
        pass

    def close(self):
        pass


def test_injection_between_reads_does_not_split_a_desktop_request():
    pipe, lock = Pipe(), threading.Lock()
    reads = iter([b'{"id":"desktop",', b'"method":"account/read"}\n', b''])
    count = 0

    def read(_):
        nonlocal count
        count += 1
        if count == 2:
            sc._write_child(pipe, lock, b'{"id":"conpact-1-x","method":"thread/compact/start"}\n')
        return next(reads)

    sc.pump_to_child(read, pipe, lock)
    messages = [json.loads(line) for line in pipe.data.splitlines()]
    assert sorted(message['id'] for message in messages) == ['conpact-1-x', 'desktop']
    assert next(message for message in messages if message['id'] == 'desktop')['method'] == 'account/read'


def test_a_control_reply_has_a_finite_send_timeout():
    class Client:
        def __init__(self):
            self.timeout = None
            self.sent = []
            self.send_timeouts = []
            self.delivered = threading.Event()

        def settimeout(self, timeout):
            self.timeout = timeout

        def sendall(self, data):
            self.send_timeouts.append(self.timeout)
            self.sent.append(data)
            self.delivered.set()

        def close(self):
            pass

    control, client = sc.Control(), Client()
    control.adopt(client)
    control.give(b'{"id":"conpact-1-x"}')
    assert client.delivered.wait(1)
    control.release(client)
    assert client.sent == [b'{"id":"conpact-1-x"}\n']
    assert len(client.send_timeouts) == 1
    assert 0 < client.send_timeouts[0] <= 5


def test_a_desktop_reply_mentioning_the_tag_is_not_lifted():
    body = b'{"id":"desktop","result":{"text":"conpact-123-x"}}\n'
    assert sc.Lifter('conpact-123-').feed(body) == [(False, body)]


def test_missing_item_completion_does_not_leave_a_caller_after_turn_end():
    from conpact import codex_turns
    turns = codex_turns.Turns()
    turns.note(json.dumps({'method': 'item/started', 'params': {
        'threadId': 't', 'item': {'type': 'mcpToolCall', 'id': 'i', 'server': 'conpact'}}}).encode())
    turns.note(json.dumps({'method': 'turn/completed', 'params': {'threadId': 't'}}).encode())
    assert turns.calling() == set()


def test_fragmented_control_frames_leave_an_incomplete_request_unsent():
    from tests.test_codex_sidecar import FakeConn, FakeServer
    pipe, lock = Pipe(), threading.Lock()
    conn = FakeConn(says=[b'sec', b'ret\n{"id":"control",', b'"method":"read"}\n{"partial":'])
    sc.serve_control(FakeServer([conn]), sc.Control(), pipe, lock, 'secret')
    assert bytes(pipe.data) == b'{"id":"control","method":"read"}\n'
    assert conn.closed
