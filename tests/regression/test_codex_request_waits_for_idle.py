"""@module tests.regression.test_codex_request_waits_for_idle
@description A delayed turn-end worker cannot compact a running turn.
@input Pending request and a scripted live turn-state reader.
@output Request stays pending until the thread is observably idle.
@dependencies conpact.codex_arming, conpact.codex_meter, conpact.compaction
"""
from conpact import codex_arming, codex_meter, compaction


def test_a_new_turn_preserves_the_request_until_it_ends(tmp_path, monkeypatch):
    compaction.request_compaction('thread', requests_dir=tmp_path)
    monkeypatch.setattr(codex_arming, '_turn_state', lambda *_: codex_meter.RUNNING, raising=False)
    ran = []
    result = codex_arming.queued_compaction(
        'thread', requests_dir=tmp_path,
        compacter=lambda tid: ran.append(tid) or {'compacted': True})
    assert ran == []
    assert result['action'] == 'deferred'
    assert compaction.pending_request('thread', requests_dir=tmp_path) is not None
    monkeypatch.setattr(codex_arming, '_turn_state', lambda *_: codex_meter.IDLE)
    assert codex_arming.queued_compaction(
        'thread', requests_dir=tmp_path, compacter=lambda tid: {'compacted': True})['action'] == 'compacted'


def test_a_request_replaced_during_the_claim_is_not_run_by_an_older_worker(tmp_path, monkeypatch):
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


def test_a_delayed_older_turn_end_does_not_spend_a_new_request(tmp_path, monkeypatch):
    compaction.request_compaction('thread', requests_dir=tmp_path)
    pending = compaction.pending_request('thread', requests_dir=tmp_path)
    monkeypatch.setattr(codex_arming, '_turn_state', lambda *_: codex_meter.IDLE)
    ran = []
    result = codex_arming.queued_compaction(
        'thread', requests_dir=tmp_path, ended_at_ns=pending['requested_at_ns'] - 1,
        compacter=lambda tid: ran.append(tid) or {'compacted': True})
    assert result['action'] == 'deferred'
    assert ran == []
    assert compaction.pending_request('thread', requests_dir=tmp_path) == pending


def test_an_unknown_turn_state_preserves_the_request(tmp_path, monkeypatch):
    compaction.request_compaction('thread', requests_dir=tmp_path)
    monkeypatch.setattr(codex_arming, '_turn_state', lambda *_: None)
    result = codex_arming.queued_compaction('thread', requests_dir=tmp_path)
    assert result['action'] == 'deferred'
    assert compaction.pending_request('thread', requests_dir=tmp_path) is not None


def test_resuming_during_measurement_prevents_execution(tmp_path, monkeypatch):
    compaction.request_compaction('thread', min_context_tokens=100, requests_dir=tmp_path)
    states = iter([codex_meter.IDLE, codex_meter.RUNNING])
    monkeypatch.setattr(codex_arming, '_turn_state', lambda *_: next(states))
    ran = []
    result = codex_arming.queued_compaction(
        'thread', requests_dir=tmp_path, measurer=lambda *_: 200,
        compacter=lambda tid: ran.append(tid) or {'compacted': True})
    assert result['action'] == 'skip'
    assert ran == []


def test_turn_state_reader_requires_the_exact_thread_and_boundary(tmp_path, monkeypatch):
    from conpact import codex_threads
    rollout = tmp_path / 'rollout.jsonl'
    rollout.write_text('{"type":"event_msg","payload":{"type":"task_complete"}}\n', encoding='utf-8')
    monkeypatch.setattr(codex_threads, 'threads', lambda _: [{'id': 't', 'rollout_path': str(rollout)}])
    assert codex_arming._turn_state('t', {}) == codex_meter.IDLE
    assert codex_arming._turn_state('missing', {}) is None

    def unreadable(_):
        raise OSError('store locked')

    monkeypatch.setattr(codex_threads, 'threads', unreadable)
    assert codex_arming._turn_state('t', {}) is None
