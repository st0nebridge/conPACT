"""@module tests.regression.test_a_replacement_request_is_strictly_newer
@description A request that replaces another carries a later stamp, whatever the clock's resolution.
@input Two requests for one session written while the wall clock stands still.
@output The replacement's requested_at_ns exceeds the replaced one's, so a turn-end
    worker that saw only the first never claims the second.
@dependencies conpact.codex_arming, conpact.codex_meter, conpact.compaction
"""
from conpact import codex_arming, codex_meter, compaction


def _frozen_clock(monkeypatch, at=1_700_000_000_000_000_000):
    # Windows' wall clock under Python 3.11 ticks every 15.6 ms, so two writes
    # in one tick read the same time; a stopped clock makes that certain.
    monkeypatch.setattr(compaction.time, 'time_ns', lambda: at)
    return at


def test_a_replacement_written_in_the_same_tick_is_stamped_later(tmp_path, monkeypatch):
    at = _frozen_clock(monkeypatch)
    compaction.request_compaction('thread', focus='old', requests_dir=tmp_path)
    old = compaction.pending_request('thread', requests_dir=tmp_path)
    compaction.request_compaction('thread', focus='new', requests_dir=tmp_path)
    new = compaction.pending_request('thread', requests_dir=tmp_path)
    assert old['requested_at_ns'] == at
    assert new['requested_at_ns'] == at + 1
    assert new['requested_at'] == at // 1_000_000_000


def test_a_first_request_keeps_the_clock_reading(tmp_path, monkeypatch):
    at = _frozen_clock(monkeypatch)
    compaction.request_compaction('thread', requests_dir=tmp_path)
    assert compaction.pending_request('thread', requests_dir=tmp_path)['requested_at_ns'] == at


def test_a_clock_ahead_of_the_replaced_request_is_used_as_read(tmp_path, monkeypatch):
    _frozen_clock(monkeypatch, at=1_000)
    compaction.request_compaction('thread', requests_dir=tmp_path)
    _frozen_clock(monkeypatch, at=5_000)
    compaction.request_compaction('thread', requests_dir=tmp_path)
    assert compaction.pending_request('thread', requests_dir=tmp_path)['requested_at_ns'] == 5_000


def test_an_unreadable_or_legacy_predecessor_does_not_block_a_request(tmp_path, monkeypatch):
    at = _frozen_clock(monkeypatch)
    path = compaction.request_compaction('thread', requests_dir=tmp_path)
    path.write_text('not json', encoding='utf-8')
    compaction.request_compaction('thread', requests_dir=tmp_path)
    assert compaction.pending_request('thread', requests_dir=tmp_path)['requested_at_ns'] == at
    path.write_text('{"session_id": "thread", "requested_at_ns": true}', encoding='utf-8')
    compaction.request_compaction('thread', requests_dir=tmp_path)
    assert compaction.pending_request('thread', requests_dir=tmp_path)['requested_at_ns'] == at
    # A legacy request counts as the end of its second, as the claim reads it.
    path.write_text('{"session_id": "thread", "requested_at": 1700000000}', encoding='utf-8')
    compaction.request_compaction('thread', requests_dir=tmp_path)
    assert compaction.pending_request('thread', requests_dir=tmp_path)['requested_at_ns'] == 1_700_000_001_000_000_001


def test_an_older_worker_never_runs_a_replacement_from_its_own_tick(tmp_path, monkeypatch):
    _frozen_clock(monkeypatch)
    compaction.request_compaction('thread', focus='old', requests_dir=tmp_path)
    old = compaction.pending_request('thread', requests_dir=tmp_path)
    monkeypatch.setattr(codex_arming, '_turn_state', lambda *_: codex_meter.IDLE)
    consume = compaction.consume_request

    def replace_then_consume(*args, **kwargs):
        compaction.request_compaction('thread', focus='new', requests_dir=tmp_path)
        return consume(*args, **kwargs)

    monkeypatch.setattr(compaction, 'consume_request', replace_then_consume)
    ran = []
    result = codex_arming.queued_compaction(
        'thread', requests_dir=tmp_path, ended_at_ns=old['requested_at_ns'],
        compacter=lambda tid: ran.append(tid) or {'compacted': True})
    assert ran == []
    assert result['action'] == 'deferred'
    assert compaction.pending_request('thread', requests_dir=tmp_path)['focus'] == 'new'
