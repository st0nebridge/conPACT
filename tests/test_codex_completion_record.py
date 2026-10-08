"""
@module tests.test_codex_completion_record
@description Large compaction envelopes retain strict JSON validation without
             keeping string contents, including escapes split across reads.
@input      isolated byte chunks, valid and malformed JSON histories
@output     bounded structure, exact envelope and syntax validation assertions
@dependencies conpact.codex_completion_record; stdlib: json
"""
import json

import pytest

from conpact.codex_completion_record import CompactedRecord

HEADER = b'{"type":"compacted","payload":'


@pytest.mark.parametrize("value", [
    {"text": 'quotes " slashes \\ newline\n \t \r \b \f 😀'},
    {"nested": [None, True, False, 42, -3.125e10, [], {}, ["foo", "bar"]]},
    {"text": "x" * 50000},
])
@pytest.mark.parametrize("chunk", [1, 7, 1024])
def test_valid_histories_are_checked_across_arbitrary_chunks(value, chunk):
    raw = HEADER + json.dumps(value, ensure_ascii=False).encode() + b'}'
    record = CompactedRecord(HEADER + b'{', 512)
    for pos in range(0, len(raw), chunk):
        record.feed(raw[pos:pos + chunk])
        assert len(record.structure) <= 512
    assert record.finish() == {"type": "compacted", "payload": {}}
    assert b'foo' not in record.structure and b'xxx' not in record.structure


@pytest.mark.parametrize("body", [
    b'{"text":"bad\\z"}', b'{"text":"bad\\u12xy"}',
    b'{"text":"bad\x01"}', b'{"text":"bad\xff"}',
    b'{"text":"unterminated}', b'{"text":"escape\\',
    b'{"text":"unicode\\u12', b'{"text":"utf8\xf0\x9f',
    b'{"text":}', b'{"text":"ok",}', b'{"text":"ok"',
    b'{"text":"ok"}} false', b'{"text":bareword}', '{"text":é}'.encode(),
])
def test_malformed_history_cannot_supply_a_compaction_marker(body):
    record = CompactedRecord(HEADER + b'{', 512)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        record.feed(HEADER + body + b'}')
        record.finish()


def test_large_structure_without_large_strings_still_fails_closed():
    record = CompactedRecord(HEADER + b'{', 64)
    with pytest.raises(ValueError, match="structure exceeded"):
        record.feed(HEADER + b'{"numbers":[' + b'0,' * 100 + b'0]}}')


def test_a_trailing_type_cannot_override_the_observed_envelope():
    record = CompactedRecord(HEADER + b'{', 512)
    record.feed(HEADER + b'{},"type":"response_item"}')
    with pytest.raises(ValueError, match="unexpected fields"):
        record.finish()


def test_live_codex_envelope_includes_an_ordinal():
    raw = (b'{"timestamp":"2026-10-07T23:01:07.765Z","ordinal":50165,'
           b'"type":"compacted","payload":{"replacement_history":[]}}')
    record = CompactedRecord(raw, 512)
    record.feed(raw)
    assert record.finish()["type"] == "compacted"


@pytest.mark.parametrize("prefix", [
    b'{"type":"response_item","payload":{"type":"compacted"}',
    b'{"type":"compacted","payload":[]}',
    b'{"type":"compacted","payload":null}',
])
def test_only_the_top_level_compacted_object_envelope_is_eligible(prefix):
    with pytest.raises(ValueError, match="observation limit"):
        CompactedRecord(prefix, 512)
