"""
@module conpact.codex_ws
@description The smallest WebSocket client that can carry Codex's newline
             JSON-RPC, written to the stdlib because everything here is. A Codex
             app-server started with `--listen ws://IP:PORT` speaks RFC 6455 on
             `/rpc`, and that is the one transport an ordinary process can hold
             open on Windows: the shared daemon's control socket is AF_UNIX,
             which Python here cannot open at all. Only what that conversation
             needs is implemented - text frames, client masking, continuation
             frames on receive, and a pong for every ping so a long-lived
             connection is not dropped - and anything else on the wire is an
             error rather than a silent guess.
@input      a host, a port, a path and the bearer token the server was told the
            SHA-256 of
@output     an open connection with `send` / `recv` / `close`, or an OSError
@dependencies stdlib: base64, os, socket, struct, time
"""
from __future__ import annotations

import base64
import os
import socket
import struct
import time

TEXT = 0x1
BINARY = 0x2
CLOSE = 0x8
PING = 0x9
PONG = 0xA
CONTINUATION = 0x0

FINAL = 0x80
MASKED = 0x80
UPGRADED = "101"

VERSION = "13"
CHUNK = 65536
HEAD = 4096


class Refused(OSError):
    """The server answered the upgrade with something other than 101."""


def _masked(payload: bytes) -> bytes:
    """A client MUST mask every frame it sends (RFC 6455 §5.3)."""
    mask = os.urandom(4)
    return mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))


def _length(size: int) -> bytes:
    if size < 126:
        return bytes([MASKED | size])
    if size < (1 << 16):
        return bytes([MASKED | 126]) + struct.pack(">H", size)
    return bytes([MASKED | 127]) + struct.pack(">Q", size)


class WebSocket:
    """One open connection. Not thread-safe: one caller, one request at a time,
    which is how every caller here uses it."""

    def __init__(self, sock, buffer: bytes = b""):
        self.sock = sock
        self.buffer = buffer
        self.deadline = None

    def send(self, text: str) -> None:
        payload = text.encode()
        self.sock.sendall(bytes([FINAL | TEXT]) + _length(len(payload)) + _masked(payload))

    def _take(self, size: int) -> bytes:
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("the WebSocket request deadline expired")
            self.sock.settimeout(remaining)
        while len(self.buffer) < size:
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("the WebSocket request deadline expired")
                self.sock.settimeout(remaining)
            chunk = self.sock.recv(CHUNK)
            if not chunk:
                raise OSError("the app-server closed the connection")
            self.buffer += chunk
        taken, self.buffer = self.buffer[:size], self.buffer[size:]
        return taken

    def _frame(self):
        first, second = self._take(2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack(">H", self._take(2))[0]
        elif size == 127:
            size = struct.unpack(">Q", self._take(8))[0]
        if second & MASKED:                          # a server never masks
            raise OSError("the app-server masked a frame, which a server must not do")
        return first & 0x0F, bool(first & FINAL), self._take(size)

    def _pong(self, payload: bytes) -> None:
        self.sock.sendall(bytes([FINAL | PONG]) + _length(len(payload)) + _masked(payload))

    def recv(self) -> str:
        """One whole text message, reassembled across continuation frames."""
        parts: list[bytes] = []
        while True:
            opcode, final, payload = self._frame()
            if opcode == PING:
                self._pong(payload)
                continue
            if opcode == PONG:
                continue
            if opcode == CLOSE:
                raise OSError("the app-server closed the connection")
            if opcode == BINARY:
                raise OSError("the app-server sent a binary frame, which it never should")
            if opcode not in (TEXT, CONTINUATION):
                raise OSError(f"the app-server sent an unknown opcode {opcode}")
            parts.append(payload)
            if final:
                return b"".join(parts).decode(errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def connect(host: str, port: int, path: str, token=None, timeout: float = 30.0,
            opener=None) -> WebSocket:
    """Open one connection, or raise. The token goes in the Authorization header
    the app-server reads; it is never put in the URL, where it would end up in
    somebody's log."""
    sock = (opener or socket.create_connection)((host, port), timeout=timeout)
    stop = time.monotonic() + timeout
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}",
             "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", f"Sec-WebSocket-Version: {VERSION}"]
    if token:
        lines.append(f"Authorization: Bearer {token}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())

    buffer = b""
    while b"\r\n\r\n" not in buffer:
        remaining = stop - time.monotonic()
        if remaining <= 0:
            sock.close()
            raise TimeoutError("the WebSocket upgrade deadline expired")
        sock.settimeout(remaining)
        chunk = sock.recv(HEAD)
        if not chunk:
            sock.close()
            raise Refused("the app-server closed the connection during the upgrade")
        buffer += chunk
    head, buffer = buffer.split(b"\r\n\r\n", 1)
    status = head.split(b"\r\n")[0].decode(errors="replace")
    if UPGRADED not in status.split(" "):
        sock.close()
        raise Refused(f"the app-server refused the upgrade: {status}")
    return WebSocket(sock, buffer)
