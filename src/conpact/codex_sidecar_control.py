"""
@module conpact.codex_sidecar_control
@description Deliver injected replies on a bounded queue outside the Desktop
             stdout pump. Each adopted client has its own sender and queue;
             slow, disconnected or overloaded clients cannot stall other chats
             or receive another client's queued replies.
@input      authenticated control sockets and reply lines
@output     queued replies or a dropped control connection
@dependencies stdlib: queue, threading
"""
from __future__ import annotations

import queue
import threading

IO_SECONDS = 5.0
MAX_REPLIES = 16


class Control:
    def __init__(self):
        self.lock = threading.Lock()
        self.client = self.outbox = self.sender = None

    def adopt(self, conn):
        with self.lock:
            self._drop()
            conn.settimeout(IO_SECONDS)
            outbox = queue.Queue(maxsize=MAX_REPLIES)
            self.client, self.outbox = conn, outbox
            self.sender = threading.Thread(target=self._send, args=(conn, outbox), daemon=True)
            self.sender.start()

    def _drop(self):
        if self.client is not None:
            try:
                self.client.close()
            except OSError:
                pass
            try:
                self.outbox.put_nowait(None)
            except queue.Full:
                pass
        self.client = self.outbox = None

    def release(self, conn):
        with self.lock:
            if self.client is conn:
                self._drop()
            else:
                try:
                    conn.close()
                except OSError:
                    pass

    def _send(self, conn, outbox):
        while True:
            line = outbox.get()
            if line is None:
                return
            try:
                conn.sendall(line)
            except OSError:
                self.release(conn)
                return

    def give(self, line):
        with self.lock:
            if self.client is None:
                return
            try:
                self.outbox.put_nowait(line + b"\n")
            except queue.Full:
                self._drop()
