"""Tests for conpact.session_registry: target selection and runtime self-binding."""
import json

import pytest

from conpact import session_registry as sr


def _write_record(directory, **fields):
    path = directory / f"{fields['pid']}.json"
    path.write_text(json.dumps(fields), encoding="utf-8")
    return path


def _record(**over):
    base = dict(
        name="Alpha", pid=111, status="idle",
        sessionId="sess-aaa", hostSessionId="local_aaa",
        bridgeSessionId="bridge_aaa",
    )
    base.update(over)
    return base


def test_resolve_target_by_name(tmp_path):
    _write_record(tmp_path, **_record())
    rec = sr.resolve_target(name="Alpha", sessions_dir=tmp_path)
    assert rec["bridgeSessionId"] == "bridge_aaa"


def test_resolve_target_no_match(tmp_path):
    _write_record(tmp_path, **_record())
    with pytest.raises(sr.TargetError):
        sr.resolve_target(name="Nope", sessions_dir=tmp_path)


def test_resolve_target_ambiguous(tmp_path):
    _write_record(tmp_path, **_record(pid=1, name="Dup"))
    _write_record(tmp_path, **_record(pid=2, name="Dup", sessionId="sess-bbb", hostSessionId="local_bbb"))
    with pytest.raises(sr.TargetError):
        sr.resolve_target(name="Dup", sessions_dir=tmp_path)


def test_resolve_target_missing_bridge(tmp_path):
    _write_record(tmp_path, **_record(bridgeSessionId=None))
    with pytest.raises(sr.TargetError):
        sr.resolve_target(name="Alpha", sessions_dir=tmp_path)


def test_resolve_self_binds_from_matching_env(tmp_path):
    _write_record(tmp_path, **_record())
    env = {sr.ENV_HOST: "local_aaa", sr.ENV_SESSION: "sess-aaa", sr.ENV_PID: "111"}
    rec = sr.resolve_self(environ=env, sessions_dir=tmp_path)
    assert rec["sessionId"] == "sess-aaa"


def test_resolve_self_rejects_conflicting_identity(tmp_path):
    # host matches but sessionId disagrees -> the record is a conflict, not a match.
    _write_record(tmp_path, **_record())
    env = {sr.ENV_HOST: "local_aaa", sr.ENV_SESSION: "sess-WRONG", sr.ENV_PID: "111"}
    with pytest.raises(sr.TargetError):
        sr.resolve_self(environ=env, sessions_dir=tmp_path)


def test_resolve_self_requires_corroboration(tmp_path):
    # Two identifiers present but only one agrees (the other is absent from the record).
    _write_record(tmp_path, **_record(hostSessionId=None))
    env = {sr.ENV_HOST: "local_aaa", sr.ENV_SESSION: "sess-aaa"}
    # The record has no host, so that axis is "no information" (skipped), not a
    # conflict. Only the session id agrees: 1 of the 2 identifiers present, which
    # is below the corroboration bar -> refused.
    with pytest.raises(sr.TargetError, match="insufficient corroboration"):
        sr.resolve_self(environ=env, sessions_dir=tmp_path)


def test_resolve_self_single_identifier_is_enough_when_it_is_all_there_is(tmp_path):
    _write_record(tmp_path, **_record())
    rec = sr.resolve_self(environ={sr.ENV_SESSION: "sess-aaa"}, sessions_dir=tmp_path)
    assert rec["bridgeSessionId"] == "bridge_aaa"


def test_resolve_self_refuses_to_guess_between_equal_matches(tmp_path):
    _write_record(tmp_path, **_record(pid=1, hostSessionId=None))
    _write_record(tmp_path, **_record(pid=2, hostSessionId=None))
    with pytest.raises(sr.TargetError, match="more than one record"):
        sr.resolve_self(environ={sr.ENV_SESSION: "sess-aaa"}, sessions_dir=tmp_path)


def test_resolve_self_prefers_the_better_corroborated_record(tmp_path):
    _write_record(tmp_path, **_record(pid=1, hostSessionId=None, name="weak"))
    _write_record(tmp_path, **_record(pid=2, name="strong"))
    env = {sr.ENV_HOST: "local_aaa", sr.ENV_SESSION: "sess-aaa"}
    assert sr.resolve_self(environ=env, sessions_dir=tmp_path)["name"] == "strong"


def test_resolve_self_pid_must_match_numerically(tmp_path):
    _write_record(tmp_path, **_record(pid="not-a-number"))
    with pytest.raises(sr.TargetError):
        sr.resolve_self(environ={sr.ENV_PID: "111", sr.ENV_SESSION: "sess-aaa"}, sessions_dir=tmp_path)


def test_resolve_self_rejects_a_record_without_a_bridge(tmp_path):
    _write_record(tmp_path, **_record(bridgeSessionId=None))
    env = {sr.ENV_HOST: "local_aaa", sr.ENV_SESSION: "sess-aaa", sr.ENV_PID: "111"}
    with pytest.raises(sr.TargetError, match="Remote Control is not connected"):
        sr.resolve_self(environ=env, sessions_dir=tmp_path)


def test_resolve_target_requires_a_selector(tmp_path):
    with pytest.raises(sr.TargetError, match="no target selector"):
        sr.resolve_target(sessions_dir=tmp_path)


def test_load_records_skips_unreadable_files_and_missing_dirs(tmp_path):
    _write_record(tmp_path, **_record())
    (tmp_path / "999.json").write_text("{not json", encoding="utf-8")
    assert [r["pid"] for r in sr.load_records(tmp_path)] == [111]
    assert sr.load_records(tmp_path / "absent") == []


def test_load_records_defaults_to_the_sessions_dir():
    sr.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _write_record(sr.SESSIONS_DIR, **_record())
    assert [r["pid"] for r in sr.load_records()] == [111]


def test_resolve_self_explicit_session_id_overrides_env(tmp_path):
    _write_record(tmp_path, **_record())
    # Only the stdin-supplied session id plus pid; both must agree.
    env = {sr.ENV_PID: "111"}
    rec = sr.resolve_self(environ=env, session_id="sess-aaa", sessions_dir=tmp_path)
    assert rec["hostSessionId"] == "local_aaa"


def test_resolve_self_no_identity(tmp_path):
    _write_record(tmp_path, **_record())
    with pytest.raises(sr.TargetError):
        sr.resolve_self(environ={}, sessions_dir=tmp_path)


@pytest.mark.real_paths
def test_runtime_names_and_paths():
    import os
    import pathlib
    assert sr.CLAUDE_DIR == pathlib.Path(os.path.expanduser("~")) / ".claude"
    assert sr.SESSIONS_DIR == sr.CLAUDE_DIR / "sessions"
    # The variable names Claude Code 2.1.275 sets for Bash, hooks and MCP servers.
    assert (sr.ENV_HOST, sr.ENV_SESSION, sr.ENV_PID) == (
        "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID")


@pytest.mark.parametrize("selector", [
    dict(pid=222), dict(host_session_id="local_bbb"), dict(session_id="sess-bbb"), dict(name="Beta"),
])
def test_resolve_target_by_each_selector(tmp_path, selector):
    _write_record(tmp_path, **_record())
    _write_record(tmp_path, **_record(pid=222, name="Beta", sessionId="sess-bbb",
                                      hostSessionId="local_bbb", bridgeSessionId="bridge_bbb"))
    assert sr.resolve_target(sessions_dir=tmp_path, **selector)["bridgeSessionId"] == "bridge_bbb"


def test_resolve_target_messages_are_exact(tmp_path):
    _write_record(tmp_path, **_record(pid=1, name="Dup"))
    _write_record(tmp_path, **_record(pid=2, name="Dup", sessionId="sess-bbb", hostSessionId="local_bbb"))
    with pytest.raises(sr.TargetError, match=r"^ambiguous target, matched pids: 1, 2$"):
        sr.resolve_target(name="Dup", sessions_dir=tmp_path)
    with pytest.raises(sr.TargetError, match=r"^no session record matched the selector$"):
        sr.resolve_target(name="Nope", sessions_dir=tmp_path)
    with pytest.raises(sr.TargetError, match=r"^no target selector provided$"):
        sr.resolve_target(sessions_dir=tmp_path)


def test_resolve_target_missing_bridge_names_the_session(tmp_path):
    _write_record(tmp_path, **_record(bridgeSessionId=None))
    with pytest.raises(sr.TargetError, match=r"^session 'Alpha' has no bridgeSessionId "
                                             r"\(Remote Control is not connected for it\)$"):
        sr.resolve_target(name="Alpha", sessions_dir=tmp_path)


def test_explicit_session_id_wins_over_a_stale_environment(tmp_path):
    _write_record(tmp_path, **_record())
    env = {sr.ENV_SESSION: "sess-old", sr.ENV_PID: "111"}
    assert sr.resolve_self(environ=env, session_id="sess-aaa", sessions_dir=tmp_path)["sessionId"] == "sess-aaa"


def test_resolve_self_messages_are_exact(tmp_path):
    with pytest.raises(sr.TargetError, match=r"^no runtime session identity available "):
        sr.resolve_self(environ={}, sessions_dir=tmp_path)
    with pytest.raises(sr.TargetError, match=r"^no session record matched the current runtime identity$"):
        sr.resolve_self(environ={sr.ENV_SESSION: "nobody"}, sessions_dir=tmp_path)
    _write_record(tmp_path, **_record(hostSessionId=None))
    with pytest.raises(sr.TargetError, match=r"^insufficient corroboration between runtime identifiers$"):
        sr.resolve_self(environ={sr.ENV_HOST: "local_aaa", sr.ENV_SESSION: "sess-aaa"}, sessions_dir=tmp_path)
    _write_record(tmp_path, **_record(pid=222, hostSessionId=None))
    with pytest.raises(sr.TargetError, match=r"^runtime identity matched more than one record; refusing to guess$"):
        sr.resolve_self(environ={sr.ENV_SESSION: "sess-aaa"}, sessions_dir=tmp_path)
