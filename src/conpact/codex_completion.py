"""
@module conpact.codex_completion
@description Observe new records in one Codex rollout after a compaction request.
             Success needs both a compaction record and completion of its turn;
             an RPC acknowledgement alone proves neither. Reads are bounded and
             never write the rollout or interrupt an unconfirmed operation.
@input      the exact target rollout and an absolute monotonic deadline
@output     completed, failed or unobserved with the observed turn id
@dependencies conpact.codex_completion_record; stdlib: json, os, pathlib, time
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from .codex_completion_record import CompactedRecord

CHUNK = 262144
MAX_LINE = 8 * 1024 * 1024
POLL = 0.2


class Rollout:
    def __init__(self, path):
        if not path:
            raise ValueError("no target rollout to observe")
        self.path = pathlib.Path(path)
        with self.path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
        self.identity = (stat.st_dev, stat.st_ino)
        self.offset = stat.st_size
        self.held = b""
        self.large = None
        self.turn_id = self.current = None
        self.compacted = False
        self.error = None

    def _event(self, row):
        if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
            return None
        payload = row["payload"]
        kind = payload.get("type")
        if row.get("type") == "compacted":
            if self.current == self.turn_id and self.turn_id is not None:
                self.compacted = True
            return None
        if row.get("type") != "event_msg":
            return None
        turn = payload.get("turn_id")
        if kind == "task_started" and isinstance(turn, str) and turn:
            self.current = turn
            if self.turn_id is None:
                self.turn_id = turn
        elif kind == "error" and self.current == self.turn_id:
            self.error = str(payload.get("message") or "Codex reported a compaction error")[:500]
        elif kind == "context_compacted" and self.current == self.turn_id and self.turn_id:
            self.compacted = True
        elif turn is not None and turn == self.turn_id:
            if kind == "turn_aborted":
                return self._result("failed", "compaction was interrupted")
            if kind == "task_complete":
                return self._result("completed" if self.compacted else "failed",
                                    None if self.compacted else self.error or
                                    "turn finished without recording a compaction")
        return None

    def _result(self, state, detail=None):
        return {"state": state, "turn_id": self.turn_id, "detail": detail}

    def poll(self):
        with self.path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            if (stat.st_dev, stat.st_ino) != self.identity or stat.st_size < self.offset:
                raise OSError("the target rollout was replaced or truncated")
            stream.seek(self.offset)
            self.held += stream.read(CHUNK)
            self.offset = stream.tell()
        while self.held:
            line, end, rest = self.held.partition(b"\n")
            if self.large is None and len(line) > MAX_LINE:
                self.large = CompactedRecord(line, MAX_LINE)
            if self.large is not None:
                self.large.feed(line)
                self.held = rest
                if not end:
                    return None
                entry = self.large.finish()
                self.large = None
                self._event(entry)
                continue
            if not end:
                break
            self.held = rest
            try:
                result = self._event(json.loads(line))
            except (ValueError, UnicodeDecodeError):
                continue
            if result is not None:
                return result
        return None

    def wait(self, stop, clock=None, sleep=None):
        now, pause = clock or time.monotonic, sleep or time.sleep
        while now() < stop:
            try:
                result = self.poll()
            except (OSError, ValueError) as exc:
                return self._result("unobserved", f"completion could not be observed: {exc}")
            if result is not None:
                return result
            left = stop - now()
            if left > 0:
                pause(min(POLL, left))
        return self._result("unobserved", "Codex accepted compaction, but completion was not "
                            "observed before timeout; it may still be running")
