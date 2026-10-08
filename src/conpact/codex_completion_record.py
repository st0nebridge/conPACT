"""
@module conpact.codex_completion_record
@description Validate an oversized Codex compaction envelope without retaining
             its replacement history. String contents are checked and erased;
             stdlib JSON validates the remaining structure at the record end.
             Only Codex's top-level compacted envelope is eligible.
@input      a bounded envelope prefix, byte chunks and a buffer limit
@output     a validated compaction marker or a refused observation
@dependencies stdlib: codecs, json, re
"""
from __future__ import annotations

import codecs
import json
import re

_HEADER = re.compile(
    rb'^\s*\{(?P<timestamp>\s*"timestamp"\s*:\s*"(?:[^"\\]|\\.)*"\s*,)?'
    rb'(?P<ordinal>\s*"ordinal"\s*:\s*\d+\s*,)?'
    rb'\s*"type"\s*:\s*"compacted"\s*,\s*"payload"\s*:\s*\{')


class CompactedRecord:
    def __init__(self, prefix, limit):
        header = _HEADER.match(prefix)
        if not header:
            raise ValueError("an incomplete rollout record exceeded the observation limit")
        self.fields = 2 + bool(header["timestamp"]) + bool(header["ordinal"])
        self.limit = limit
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.structure = bytearray()
        self.string = self.escape = False
        self.unicode_left = 0

    def feed(self, data):
        for char in self.decoder.decode(data):
            if self.unicode_left:
                if char not in "0123456789abcdefABCDEF":
                    raise ValueError("invalid Unicode escape in compaction record")
                self.unicode_left -= 1
            elif self.escape:
                if char == "u":
                    self.unicode_left = 4
                elif char not in '"\\/bfnrt':
                    raise ValueError("invalid escape in compaction record")
                self.escape = False
            elif self.string:
                if char == '"':
                    self.string = False
                    self.structure.append(ord(char))
                elif char == "\\":
                    self.escape = True
                elif ord(char) < 32:
                    raise ValueError("invalid control character in compaction record")
            else:
                if char == '"':
                    self.string = True
                if ord(char) > 127:
                    raise ValueError("invalid character outside a JSON string")
                self.structure.append(ord(char))
            if len(self.structure) > self.limit:
                raise ValueError("compaction record structure exceeded the observation limit")

    def finish(self):
        self.decoder.decode(b"", final=True)
        if self.string or self.escape or self.unicode_left:
            raise ValueError("incomplete string in compaction record")
        # Erasing string contents preserves JSON grammar. The header above
        # establishes the event kind; history values are never used as evidence.
        envelope = json.loads(self.structure, object_pairs_hook=tuple)
        if len(envelope) != self.fields:
            raise ValueError("unexpected fields after the compaction payload")
        return {"type": "compacted", "payload": {}}
