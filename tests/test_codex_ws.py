"""
@module tests.test_codex_ws
@description The stdlib WebSocket client: the upgrade it sends, the frames it
             writes, and every shape it refuses to guess at on the way back.
@input      conpact.codex_ws, against a socket that is a script
@output     assertions on the handshake bytes, masking, the three length
            encodings, reassembly, ping/pong and each refusal
@dependencies conpact.codex_ws; stdlib: struct
"""
import struct

import pytest

from conpact import codex_ws

UPGRADE = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n"


class FakeSocket:
    """A socket that hands back a script and remembers what was written."""

    def __init__(self, *chunks):
        self.incoming = list(chunks)
        self.sent, self.closed, self.timeout = b"", False, None

    def sendall(self, data):
        self.sent += data

    def recv(self, _size):
        return self.incoming.pop(0) if self.incoming else b""

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


def server_frame(opcode, payload=b"", final=True, masked=False):
    """One frame as a server would write it: never masked."""
    head = bytes([(0x80 if final else 0) | opcode])
    size = len(payload)
    flag = 0x80 if masked else 0
    if size < 126:
        head += bytes([flag | size])
    elif size < (1 << 16):
        head += bytes([flag | 126]) + struct.pack(">H", size)
    else:
        head += bytes([flag | 127]) + struct.pack(">Q", size)
    return head + payload


def opened(*chunks):
    sock = FakeSocket(UPGRADE, *chunks)
    return sock, codex_ws.connect("h", 1, "/rpc", opener=lambda address, timeout: sock)


class TestTheUpgrade:
    def test_it_asks_for_the_path_and_the_websocket_version(self):
        sock, connection = opened()
        head = sock.sent.decode()
        assert head.startswith("GET /rpc HTTP/1.1\r\n")
        assert "Upgrade: websocket\r\n" in head
        assert "Sec-WebSocket-Version: 13\r\n" in head
        assert head.endswith("\r\n\r\n")
        connection.close()

    def test_a_token_is_sent_as_a_bearer_header_and_never_in_the_url(self):
        sock = FakeSocket(UPGRADE)
        codex_ws.connect("h", 1, "/rpc", "s3cret", opener=lambda address, timeout: sock)
        head = sock.sent.decode()
        assert "Authorization: Bearer s3cret\r\n" in head
        assert "s3cret" not in head.split("\r\n")[0]

    def test_no_token_means_no_header(self):
        sock = FakeSocket(UPGRADE)
        codex_ws.connect("h", 1, "/rpc", None, opener=lambda address, timeout: sock)
        assert "Authorization" not in sock.sent.decode()

    def test_a_refused_upgrade_says_so_and_does_not_leave_the_socket_open(self):
        sock = FakeSocket(b"HTTP/1.1 401 Unauthorized\r\ncontent-length: 0\r\n\r\n")
        with pytest.raises(codex_ws.Refused) as refused:
            codex_ws.connect("h", 1, "/rpc", opener=lambda address, timeout: sock)
        assert "401" in str(refused.value)
        assert sock.closed is True

    def test_a_socket_that_closes_during_the_upgrade_is_an_error_not_a_hang(self):
        sock = FakeSocket(b"HTTP/1.1 101 ")
        with pytest.raises(codex_ws.Refused):
            codex_ws.connect("h", 1, "/rpc", opener=lambda address, timeout: sock)

    def test_a_status_that_merely_contains_101_is_not_an_upgrade(self):
        """"HTTP/1.1 500 error 101" must not read as success."""
        sock = FakeSocket(b"HTTP/1.1 500 code101\r\n\r\n")
        with pytest.raises(codex_ws.Refused):
            codex_ws.connect("h", 1, "/rpc", opener=lambda address, timeout: sock)

    def test_bytes_arriving_with_the_headers_are_kept_for_the_first_frame(self):
        """A server may put the first frame in the same packet as the upgrade."""
        sock = FakeSocket(UPGRADE + server_frame(codex_ws.TEXT, b"hi"))
        connection = codex_ws.connect("h", 1, "/rpc", opener=lambda address, timeout: sock)
        assert connection.recv() == "hi"


class TestSending:
    def test_a_client_frame_is_always_masked(self):
        """RFC 6455 requires it and the app-server closes an unmasked one."""
        sock, connection = opened()
        sock.sent = b""
        connection.send("hi")
        assert sock.sent[0] == 0x80 | codex_ws.TEXT
        assert sock.sent[1] & 0x80, "the mask bit must be set"
        assert sock.sent[1] & 0x7F == 2
        mask, body = sock.sent[2:6], sock.sent[6:]
        assert bytes(b ^ mask[i % 4] for i, b in enumerate(body)) == b"hi"

    @pytest.mark.parametrize("size, marker, extra", [
        (10, 10, 0), (200, 126, 2), (70000, 127, 8)])
    def test_each_length_encoding_is_the_one_the_size_calls_for(self, size, marker, extra):
        sock, connection = opened()
        sock.sent = b""
        connection.send("x" * size)
        assert sock.sent[1] & 0x7F == marker
        assert len(sock.sent) == 2 + extra + 4 + size


class TestReceiving:
    def test_one_text_frame_is_one_message(self):
        sock, connection = opened(server_frame(codex_ws.TEXT, b'{"id":"1"}'))
        assert connection.recv() == '{"id":"1"}'

    def test_a_message_split_across_frames_is_put_back_together(self):
        sock, connection = opened(
            server_frame(codex_ws.TEXT, b'{"id":', final=False),
            server_frame(codex_ws.CONTINUATION, b'"1"}'))
        assert connection.recv() == '{"id":"1"}'

    def test_a_ping_is_answered_and_does_not_end_the_wait(self):
        """Without the pong the app-server drops a long-lived connection."""
        sock, connection = opened(server_frame(codex_ws.PING, b"ka"),
                                  server_frame(codex_ws.TEXT, b"hi"))
        sock.sent = b""
        assert connection.recv() == "hi"
        assert sock.sent[0] == 0x80 | codex_ws.PONG
        assert sock.sent[1] & 0x80, "our pong must be masked too"

    def test_a_pong_is_ignored(self):
        sock, connection = opened(server_frame(codex_ws.PONG, b"ka"),
                                  server_frame(codex_ws.TEXT, b"hi"))
        assert connection.recv() == "hi"

    def test_a_close_frame_is_an_error_rather_than_an_empty_message(self):
        sock, connection = opened(server_frame(codex_ws.CLOSE))
        with pytest.raises(OSError):
            connection.recv()

    def test_a_binary_frame_is_refused_rather_than_decoded(self):
        sock, connection = opened(server_frame(codex_ws.BINARY, b"\x00\x01"))
        with pytest.raises(OSError):
            connection.recv()

    def test_an_unknown_opcode_is_refused_rather_than_guessed_at(self):
        sock, connection = opened(server_frame(0x7, b"?"))
        with pytest.raises(OSError):
            connection.recv()

    def test_a_masked_server_frame_is_refused(self):
        """A server must never mask; reading one as unmasked would give garbage."""
        sock, connection = opened(server_frame(codex_ws.TEXT, b"hi", masked=True))
        with pytest.raises(OSError):
            connection.recv()

    def test_a_socket_that_ends_mid_message_is_an_error_not_a_truncation(self):
        sock, connection = opened(server_frame(codex_ws.TEXT, b"hello")[:4])
        with pytest.raises(OSError):
            connection.recv()

    @pytest.mark.parametrize("size", [130, 70000])
    def test_the_longer_length_encodings_are_read_back(self, size):
        sock, connection = opened(server_frame(codex_ws.TEXT, b"y" * size))
        assert connection.recv() == "y" * size


class TestClosing:
    def test_closing_closes_the_socket(self):
        sock, connection = opened()
        connection.close()
        assert sock.closed is True

    def test_closing_a_socket_that_is_already_gone_does_not_raise(self):
        sock, connection = opened()

        def explode():
            raise OSError("already closed")

        sock.close = explode
        connection.close()
