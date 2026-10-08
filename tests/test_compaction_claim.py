"""@module tests.test_compaction_claim
@description A turn-end claim isolates one generation and preserves later intent.
@input Temporary requests, concurrent consumers and simulated I/O failures.
@output At most one claim, and newer requests still pending after deferral.
@dependencies conpact.compaction_claim; stdlib: concurrent.futures, json, pathlib, threading
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from conpact import compaction_claim as claim


def request(path, stamp=100, **extra):
    data = {'session_id': 't', 'requested_at_ns': stamp, **extra}
    path.write_text(json.dumps(data), encoding='utf-8')
    return data


def test_only_one_concurrent_worker_can_claim_a_generation(tmp_path):
    path = tmp_path / 't.json'
    data = request(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: claim.before(path, 101), range(12)))
    assert [result for result in results if result is not None] == [data]
    assert list(tmp_path.iterdir()) == []


def test_competing_workers_do_not_enter_a_rename_already_in_progress(tmp_path, monkeypatch):
    path = tmp_path / 't.json'
    data = request(path)
    entered, release = threading.Event(), threading.Event()
    replace = claim.os.replace

    def held_replace(source, destination):
        entered.set()
        if not release.wait(3):
            raise TimeoutError('rename probe was not released')
        return replace(source, destination)

    monkeypatch.setattr(claim.os, 'replace', held_replace)
    with ThreadPoolExecutor(max_workers=4) as pool:
        winner = pool.submit(claim.before, path, 101)
        assert entered.wait(1)
        losers = [pool.submit(claim.before, path, 101) for _ in range(3)]
        try:
            assert [future.result(timeout=1) for future in losers] == [None] * 3
        finally:
            release.set()
        assert winner.result(timeout=3) == data
    assert list(tmp_path.iterdir()) == []


def test_a_newer_request_is_restored_for_its_own_turn_end(tmp_path):
    path = tmp_path / 't.json'
    data = request(path, 102)
    assert claim.before(path, 101) is None
    assert json.loads(path.read_text(encoding='utf-8')) == data
    assert list(tmp_path.iterdir()) == [path]


def test_restoration_never_overwrites_an_even_newer_request(tmp_path, monkeypatch):
    path = tmp_path / 't.json'
    request(path, 102)
    original = claim.os.link
    latest = {'session_id': 't', 'requested_at_ns': 103, 'focus': 'latest'}

    def newer_then_link(source, destination):
        path.write_text(json.dumps(latest), encoding='utf-8')
        original(source, destination)

    monkeypatch.setattr(claim.os, 'link', newer_then_link)
    assert claim.before(path, 101) is None
    assert json.loads(path.read_text(encoding='utf-8')) == latest


@pytest.mark.parametrize('raw', ['not json', '[]', '{"requested_at_ns":true}',
                                '{"requested_at_ns":"100"}'])
def test_an_invalid_generation_never_becomes_a_claim(tmp_path, raw):
    path = tmp_path / 't.json'
    path.write_text(raw, encoding='utf-8')
    assert claim.before(path, 101) is None
    assert list(tmp_path.iterdir()) == []


def test_legacy_timestamps_require_the_full_second_to_precede_the_end():
    assert claim.requested_at_ns({'requested_at': 2}) == 3_000_000_000


def test_delete_failure_cannot_return_an_executable_claim(tmp_path, monkeypatch):
    path = tmp_path / 't.json'
    request(path)

    def locked(_):
        raise PermissionError('claim is locked')

    monkeypatch.setattr(Path, 'unlink', locked)
    with pytest.raises(PermissionError):
        claim.before(path, 101)


def test_a_missing_generation_is_no_claim(tmp_path):
    assert claim.before(tmp_path / 'missing.json', 101) is None


def test_a_newer_current_request_prevents_claiming_a_legacy_request(tmp_path, monkeypatch):
    from conpact import compaction
    current, previous, legacy = (tmp_path / name for name in ('current', 'previous', 'legacy'))
    for folder in (current, previous, legacy):
        folder.mkdir()
    monkeypatch.setattr(compaction, 'REQUESTS_DIR', current)
    monkeypatch.setattr(compaction, 'PREVIOUS_REQUESTS_DIR', previous)
    monkeypatch.setattr(compaction, 'LEGACY_REQUESTS_DIR', legacy)
    newer = request(current / 't.json', 102)
    older = request(previous / 't.json', 100)
    assert compaction.consume_request('t', not_after_ns=101) is None
    assert json.loads((current / 't.json').read_text(encoding='utf-8')) == newer
    assert json.loads((previous / 't.json').read_text(encoding='utf-8')) == older
