"""@module tests.regression.test_codex_compaction_requires_its_caller
@description A running thread is not evidence that it called conPACT.
@input Fake sidecar state and rollout scan results.
@output Refusals for guessed identity and cross-process state.
@dependencies conpact.codex_active, conpact.codex_caller; stdlib: types
"""
from types import SimpleNamespace

import json
import pytest

from conpact import codex_active, codex_caller


def test_a_single_active_desktop_thread_is_not_assumed_to_be_the_caller(monkeypatch):
    codex_active.publish(['unrelated'])
    monkeypatch.setattr(codex_caller, 'recent_threads', lambda ctx: ([], ['unrelated']))
    monkeypatch.setattr(codex_caller.time, 'sleep', lambda _: None)
    thread, why = codex_caller.bind_desktop(SimpleNamespace(ppid=41, environ={}))
    assert thread is None
    assert 'call' in why


def test_another_app_servers_native_call_is_not_used(monkeypatch):
    codex_active.publish(['foreign'], calling=['foreign'], parent_pid=99)
    scanned = []
    monkeypatch.setattr(codex_caller, 'recent_threads',
                        lambda ctx: scanned.append(True) or (['foreign'], ['foreign']))
    thread, why = codex_caller.bind_desktop(SimpleNamespace(ppid=41, environ={}))
    assert thread is None
    assert 'another' in why
    assert scanned == []


@pytest.mark.parametrize('source', [
    '// await tools.mcp__conpact__queue_compaction({})',
    'text("await tools.mcp__conpact__queue_compaction({})");',
    'const label = `await tools.mcp__conpact__queue_compaction({})`;',
    'await tools.mcp__conpact__compaction_status({});',
])
def test_diagnostics_and_other_methods_are_not_a_queue_call(tmp_path, source):
    rollout = tmp_path / 'rollout.jsonl'
    rollout.write_text(json.dumps({'type': 'response_item', 'payload': {
        'type': 'custom_tool_call', 'name': 'exec', 'input': source}}), encoding='utf-8')
    assert not codex_caller.rollout_is_calling_conpact(rollout, 'queue_compaction')


def test_a_cli_running_thread_without_a_tool_call_is_refused(monkeypatch):
    monkeypatch.setattr(codex_caller, 'recent_threads', lambda ctx: ([], ['unrelated']))
    monkeypatch.setattr(codex_caller.time, 'sleep', lambda _: None)
    thread, _ = codex_caller.bind_cli_rollout(SimpleNamespace(environ={}))
    assert thread is None


def test_a_native_status_call_cannot_identify_a_queue_caller(monkeypatch):
    codex_active.publish(['other'], calling=['other'], parent_pid=41,
                         calling_tools={'compaction_status': ['other']})
    monkeypatch.setattr(codex_caller, 'recent_threads', lambda ctx: ([], ['other']))
    ctx = SimpleNamespace(ppid=41, environ={}, tool_name='queue_compaction')
    assert codex_caller.bind_desktop(ctx)[0] is None


def test_the_matching_native_method_binds_only_its_calling_thread():
    codex_active.publish(['a', 'b'], calling=['a', 'b'], parent_pid=41,
                         calling_tools={'compaction_status': ['a'], 'queue_compaction': ['b']})
    ctx = SimpleNamespace(ppid=41, environ={}, tool_name='queue_compaction')
    assert codex_caller.bind_desktop(ctx) == ('b', None)
