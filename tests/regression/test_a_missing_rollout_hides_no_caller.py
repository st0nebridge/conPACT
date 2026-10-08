"""Regression: a thread whose rollout is not there is passed over, and a rollout
that is there but cannot be read still refuses.

When the sidecar names nobody, and always for the CLI, the Codex caller is
bound from Codex's own rollouts, exactly one or none (D-20260922-043,
D-20260924-057). Until 2026-09-25 one listed thread whose rollout file was
missing emptied the whole scan, so a caller that could be told exactly was
refused. Measured with rows [a thread whose file is gone, a thread with a fresh
running rollout], the scan found nothing; without the first row it found the
second. A missing rollout records no turn, just as an empty one does, so it
cannot be a candidate, and its row is passed over.

Looking at that found the opposite fault beside it. A recent rollout that is
there and cannot be opened was treated as one with no turn marker, because the
reader swallows the error, so a thread that might be the caller dropped out and
the other one was bound. Passing over a row whose state is unknown can turn two
candidates into one, which exact-one-or-none forbids, so that row refuses.
"""
import json
import os
import time

import pytest

from conpact import codex_active, codex_threads, mcp_tools

CALLER = "019d0000-0000-7000-a000-000000000003"
OTHER = "019d0000-0000-7000-a000-000000000004"
THIRD = "019d0000-0000-7000-a000-000000000005"
CODEX_ENV = {"CODEX_HOME": r"C:\Users\x\.codex",
             "CODEX_CLI_PATH": r"C:\shim\codex_sidecar.exe"}
# ChatGPT Desktop's own app-server, and the CLI: the two ways a rollout binds.
SURFACES = pytest.mark.parametrize("parent", ["codex app-server", "/usr/local/bin/codex"],
                                   ids=["desktop", "cli"])


def _ctx(parent):
    return mcp_tools.Context(environ=dict(CODEX_ENV), ppid=1, parent_command=parent)


def _rollout(tmp_path, thread_id, calling=True):
    """A fresh rollout whose turn is running, calling conPACT or not."""
    records = [{"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}}]
    if calling:
        records.append({"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec",
            "input": "const r=await tools.mcp__conpact__compaction_status({});"}})
    path = tmp_path / f"{thread_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _row(thread_id, path):
    return {"id": thread_id, "rollout_path": str(path), "kind": "user", "archived": False}


def _store(monkeypatch, *rows):
    codex_active.publish([])                   # the sidecar names nobody
    monkeypatch.setattr(codex_threads, "threads", lambda environ=None: list(rows))


@SURFACES
@pytest.mark.parametrize("calling", [True, False], ids=["calling conPACT", "only running"])
def test_a_thread_whose_rollout_is_gone_does_not_refuse_the_caller(tmp_path, monkeypatch,
                                                                    parent, calling):
    _store(monkeypatch, _row(OTHER, tmp_path / "gone.jsonl"),
           _row(CALLER, _rollout(tmp_path, CALLER, calling)))
    if calling:
        assert mcp_tools._bind_session(_ctx(parent)) == CALLER
    else:
        with pytest.raises(mcp_tools.ToolFailure):
            mcp_tools._bind_session(_ctx(parent))


@SURFACES
def test_a_missing_rollout_leaves_an_ambiguity_standing(tmp_path, monkeypatch, parent):
    _store(monkeypatch, _row(OTHER, tmp_path / "gone.jsonl"),
           _row(CALLER, _rollout(tmp_path, CALLER)), _row(THIRD, _rollout(tmp_path, THIRD)))
    with pytest.raises(mcp_tools.ToolFailure) as refused:
        mcp_tools._bind_session(_ctx(parent))
    assert "will not guess which of 2 recent Codex rollouts" in str(refused.value)


@SURFACES
def test_a_recent_rollout_that_cannot_be_read_refuses(tmp_path, monkeypatch, parent):
    """A folder where the rollout should be: it is there and recent, and
    opening it fails, so what it records cannot be known."""
    unreadable = tmp_path / "unreadable.jsonl"
    unreadable.mkdir()
    _store(monkeypatch, _row(OTHER, unreadable), _row(CALLER, _rollout(tmp_path, CALLER)))
    with pytest.raises(mcp_tools.ToolFailure):
        mcp_tools._bind_session(_ctx(parent))


@SURFACES
def test_an_old_rollout_that_cannot_be_read_is_passed_over(tmp_path, monkeypatch, parent):
    """Too old to be in flight, whatever it says, so it is no candidate."""
    unreadable = tmp_path / "unreadable.jsonl"
    unreadable.mkdir()
    old = time.time() - codex_active.MAX_AGE_SECONDS - 60
    os.utime(unreadable, (old, old))
    _store(monkeypatch, _row(OTHER, unreadable), _row(CALLER, _rollout(tmp_path, CALLER)))
    assert mcp_tools._bind_session(_ctx(parent)) == CALLER
