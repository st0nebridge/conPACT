"""
Regression test for CU-20260919-008 (conditional compaction).

A request may carry min_context_tokens. It is evaluated once, by the Stop hook
that claims the request, against the context size measured from the session's
transcript (the usage of the last main-thread assistant message):

  1. at or above the minimum -> /compact is sent;
  2. below it -> nothing is sent, the request is discarded rather than kept
     armed, and the outcome is logged as "below_threshold" with both numbers;
  3. if the size cannot be measured -> nothing is sent (fail closed), "error";
  4. without a minimum nothing changes, and the measured size is still logged.
"""
import io
import json
import sys

import pytest

from conpact import cli, closure_hook, compaction, session_registry


def _transcript(tmp_path, tokens):
    path = tmp_path / "transcript.jsonl"
    entry = {"type": "assistant", "isSidechain": False,
             "message": {"model": "claude-opus-5",
                         "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0,
                                   "cache_read_input_tokens": tokens, "output_tokens": 0}}}
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return str(path)


def _hook_input(transcript):
    return {"session_id": "sess-a", "transcript_path": transcript, "hook_event_name": "Stop"}


def _firing(calls):
    def fire(**kw):
        calls.append(kw)
        return {"sent": True, "http_status": 200, "token_refreshed": False}
    return fire


def _never(**kw):
    raise AssertionError("must not send")


@pytest.mark.parametrize("tokens", [1500, 1000])
def test_at_or_above_the_minimum_compacts(tmp_path, tokens):
    compaction.request_compaction("sess-a", min_context_tokens=1000)
    calls = []
    status = closure_hook.run(_hook_input(_transcript(tmp_path, tokens)), compactor=_firing(calls))
    assert status["action"] == "compacted"
    assert (status["context_tokens"], status["min_context_tokens"]) == (tokens, 1000)
    assert len(calls) == 1


def test_below_the_minimum_discards_without_sending(tmp_path):
    compaction.request_compaction("sess-a", min_context_tokens=1000)
    status = closure_hook.run(_hook_input(_transcript(tmp_path, 999)), compactor=_never)
    assert status["action"] == "below_threshold"
    assert (status["context_tokens"], status["min_context_tokens"]) == (999, 1000)
    assert "999" in status["reason"] and "1000" in status["reason"]
    # Discarded, not kept armed: the next turn end finds nothing.
    assert closure_hook.run(_hook_input(_transcript(tmp_path, 5000)), compactor=_never)["action"] == "skip"


@pytest.mark.parametrize("transcript", [None, "", "C:/no/such/transcript.jsonl"])
def test_unmeasurable_context_fails_closed(transcript):
    compaction.request_compaction("sess-a", min_context_tokens=1000)
    status = closure_hook.run(_hook_input(transcript), compactor=_never)
    assert status["action"] == "error"
    assert "could not be measured" in status["reason"]
    assert status["min_context_tokens"] == 1000


def test_an_invalid_stored_minimum_fails_closed(tmp_path):
    compaction.REQUESTS_DIR.mkdir(parents=True)
    (compaction.REQUESTS_DIR / "sess-a.json").write_text(
        json.dumps({"session_id": "sess-a", "focus": "", "min_context_tokens": "lots"}), encoding="utf-8")
    status = closure_hook.run(_hook_input(_transcript(tmp_path, 5000)), compactor=_never)
    assert status["action"] == "error"
    assert "min_context_tokens" in status["reason"]


def test_without_a_minimum_behaviour_is_unchanged_and_size_is_logged(tmp_path, monkeypatch):
    compaction.request_compaction("sess-a")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_hook_input(_transcript(tmp_path, 42)))))
    real_run = closure_hook.run
    monkeypatch.setattr(closure_hook, "run", lambda hook_input, **kw: real_run(hook_input, compactor=_firing([])))
    assert closure_hook.main() == 0
    entry = json.loads(closure_hook.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["action"] == "compacted"
    assert entry["context_tokens"] == 42
    assert entry["min_context_tokens"] is None


def test_below_threshold_is_logged_with_both_numbers(tmp_path, monkeypatch):
    compaction.request_compaction("sess-a", min_context_tokens=100_000)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_hook_input(_transcript(tmp_path, 60_000)))))
    assert closure_hook.main() == 0
    entry = json.loads(closure_hook.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["action"] == "below_threshold"
    assert (entry["context_tokens"], entry["min_context_tokens"]) == (60_000, 100_000)


@pytest.mark.parametrize("bad", [0, -5, True, "100", 1.5, compaction.MAX_CONTEXT_TOKENS + 1])
def test_minimum_must_be_a_positive_whole_number(bad):
    with pytest.raises(ValueError):
        compaction.request_compaction("sess-a", min_context_tokens=bad)
    assert compaction.pending_request("sess-a") is None


@pytest.mark.parametrize("good", [None, 1, compaction.MAX_CONTEXT_TOKENS])
def test_minimum_accepts_none_and_the_valid_range(good):
    compaction.request_compaction("sess-a", min_context_tokens=good)
    assert compaction.pending_request("sess-a")["min_context_tokens"] == good


def _self(monkeypatch):
    record = dict(name="Me", pid=1, sessionId="sess-a", hostSessionId="local_a", bridgeSessionId="bridge_a")
    monkeypatch.setattr(session_registry, "resolve_self", lambda **k: dict(record))


@pytest.mark.parametrize("given,stored", [("150000", 150000), ("150k", 150000), ("1.5M", 1500000), ("2m", 2000000)])
def test_cli_records_the_minimum(monkeypatch, given, stored):
    _self(monkeypatch)
    assert cli.main(["--self", "--request", "--min-context-tokens", given]) == 0
    assert compaction.pending_request("sess-a")["min_context_tokens"] == stored


@pytest.mark.parametrize("argv", [
    ["--self", "--compact", "--min-context-tokens", "5000"],
    ["--self", "--request", "--min-context-tokens", "lots"],
    ["--self", "--request", "--min-context-tokens", "0"],
    ["--self", "--request", "--min-context-tokens", "-10k"],
    ["--self", "--request", "--min-context-tokens", "1.2345k"],
    ["--self", "--request", "--min-context-tokens", "inf"],
    ["--self", "--request", "--min-context-tokens", "nan"],
    ["--self", "--request", "--min-context-tokens", "k"],
])
def test_cli_rejects_a_misplaced_or_invalid_minimum(monkeypatch, argv):
    _self(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert compaction.pending_request("sess-a") is None


def test_outcome_reasons_are_exact(tmp_path):
    compaction.request_compaction("sess-a", min_context_tokens=1000)
    assert closure_hook.run(_hook_input(_transcript(tmp_path, 999)), compactor=_never)["reason"] == (
        "context 999 tokens < minimum 1000; not compacting")
    compaction.request_compaction("sess-a", min_context_tokens=1000)
    assert closure_hook.run(_hook_input(None), compactor=_never)["reason"] == (
        "context size could not be measured; not compacting")
    compaction.REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    (compaction.REQUESTS_DIR / "sess-a.json").write_text(
        json.dumps({"session_id": "sess-a", "min_context_tokens": 0}), encoding="utf-8")
    assert closure_hook.run(_hook_input(None), compactor=_never)["reason"] == (
        "invalid request: min_context_tokens must be a whole number from 1 to 10000000; not compacting")


def test_the_upper_bound_is_ten_million():
    assert compaction.MAX_CONTEXT_TOKENS == 10_000_000


def test_cli_request_output_states_the_condition(monkeypatch, capsys):
    _self(monkeypatch)
    assert cli.main(["--self", "--request", "--min-context-tokens", "150k"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2].startswith("request  : recorded at ")
    assert lines[-1] == "condition: fires only if the context is at least 150000 tokens at turn end"
    assert cli.main(["--self", "--request"]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("request  : recorded at ")


def test_cli_misplaced_minimum_says_why(monkeypatch, capsys):
    _self(monkeypatch)
    with pytest.raises(SystemExit):
        cli.main(["--self", "--compact", "--min-context-tokens", "5000"])
    assert capsys.readouterr().err.rstrip().endswith("error: --min-context-tokens only applies to --request")
