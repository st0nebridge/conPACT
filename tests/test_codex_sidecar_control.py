"""
@module tests.test_codex_sidecar_control
@description Bounded asynchronous reply delivery and client replacement.
@input      scripted sockets with explicit completion barriers
@output     assertions on delivery, overload, disconnection and isolation
@dependencies conpact.codex_sidecar_control; stdlib: threading
"""
import threading

from conpact import codex_sidecar_control as cc


class Socket:
    def __init__(self, blocked=False, fail=False):
        self.entered, self.release, self.delivered = (threading.Event() for _ in range(3))
        if not blocked:
            self.release.set()
        self.closed, self.fail, self.sent = False, fail, []

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, line):
        self.entered.set()
        self.release.wait(1)
        if self.closed or self.fail:
            raise OSError("closed")
        self.sent.append(line)
        self.delivered.set()

    def close(self):
        self.closed = True
        self.release.set()


def test_delivery_is_serial_and_connection_has_a_send_timeout():
    control, client = cc.Control(), Socket()
    control.adopt(client)
    control.give(b"one")
    assert client.delivered.wait(1)
    control.release(client)
    control.sender.join(1)
    assert client.sent == [b"one\n"] and client.timeout == 5.0
    assert not control.sender.is_alive()


def test_full_queue_drops_the_client_without_waiting_for_its_reply():
    control, client = cc.Control(), Socket(blocked=True)
    control.adopt(client)
    control.give(b"first")
    assert client.entered.wait(1)
    for _ in range(cc.MAX_REPLIES + 1):
        control.give(b"queued")
    control.sender.join(1)
    assert control.client is None and client.closed
    assert not control.sender.is_alive()


def test_old_sender_failure_cannot_drop_a_replacement_client():
    control, old, new = cc.Control(), Socket(blocked=True), Socket()
    control.adopt(old)
    control.give(b"old reply")
    assert old.entered.wait(1)
    old_sender = control.sender
    control.adopt(new)
    old_sender.join(1)
    control.give(b"new reply")
    assert new.delivered.wait(1)
    assert control.client is new and new.sent == [b"new reply\n"]
    control.release(new)
    control.sender.join(1)


def test_send_failure_drops_and_ends_its_sender():
    control, client = cc.Control(), Socket(fail=True)
    control.adopt(client)
    control.give(b"reply")
    control.sender.join(1)
    assert client.closed and control.client is None and not control.sender.is_alive()


def test_releasing_a_client_can_survive_its_close_failure():
    class Broken(Socket):
        def close(self):
            raise OSError("closed already")
    control, client = cc.Control(), Broken()
    control.adopt(client)
    control.release(client)
    control.sender.join(1)
    assert control.client is None and not control.sender.is_alive()


def test_release_of_an_unrelated_broken_socket_preserves_the_current_client():
    class Broken(Socket):
        def close(self):
            raise OSError("closed already")
    control, client = cc.Control(), Socket()
    control.adopt(client)
    control.release(Broken())
    assert control.client is client
    control.release(client)
    control.sender.join(1)
