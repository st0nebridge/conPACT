"""
@module tests.test_platforms
@description One shape for a session on either desktop app, and one answer for
             why it cannot be compacted.
@input      conpact.platforms, against stand-in state for both platforms
@output     assertions on normalisation, the blocking order and what "installed"
            means
@dependencies conpact.platforms; stdlib: json, sqlite3
"""
import json
import sqlite3

import pytest

from conpact import codex_threads, platforms, session_registry

STATE = """
create table threads (
    id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, cwd TEXT NOT NULL,
    name TEXT, title TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0, updated_at_ms INTEGER,
    thread_source TEXT, model TEXT, source TEXT NOT NULL DEFAULT '')
"""


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """A stand-in Codex home. Yields the function that adds a thread with a
    rollout beside it."""
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    (home / "thread-writer-locks").mkdir()
    con = sqlite3.connect(str(home / "state_5.sqlite"))
    con.execute(STATE)
    con.commit()

    def add(thread_id="t1", *, kind="user", archived=0, tokens=150504, window=258400,
            state="task_complete", title="A thread", updated=1000):
        rollout = home / "sessions" / f"{thread_id}.jsonl"
        lines = [{"type": "token_usage_record", "payload": {"usage": {"total_tokens": tokens}}},
                 {"type": "event_msg", "payload": {"type": state, "model_context_window": window}}]
        rollout.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
        con.execute("insert into threads (id, rollout_path, cwd, title, archived, updated_at_ms,"
                    " thread_source) values (?,?,?,?,?,?,?)",
                    (thread_id, str(rollout), r"C:\Dev\x", title, archived, updated, kind))
        con.commit()
        return thread_id

    yield add
    con.close()


@pytest.fixture
def env(tmp_path):
    return {"CODEX_HOME": str(tmp_path / "codex")}


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """A stand-in for Claude Code's live session records."""
    folder = tmp_path / "claude-sessions"
    folder.mkdir()
    monkeypatch.setattr(session_registry, "SESSIONS_DIR", folder)

    def add(pid=1, **over):
        record = {"sessionId": "11111111-2222-3333-4444-555555555555", "name": "A session",
                  "cwd": r"C:\Dev\x", "bridgeSessionId": "bridge-1", **over}
        (folder / f"{pid}.json").write_text(json.dumps(record), encoding="utf-8")
        return record

    return add


class TestBlocked:
    def test_a_session_with_nothing_wrong_is_not_blocked(self):
        assert platforms.blocked(platforms._session(platform=platforms.CODEX)) is None

    def test_a_spin_off_outranks_every_other_reason(self):
        """It is not worth compacting whatever else is true of it, so the answer
        must not depend on which check happens to run first."""
        session = platforms._session(spin_off=True, archived=True, busy=True, reachable=False)
        assert platforms.blocked(session) == platforms.SPIN_OFF

    def test_an_archived_session_outranks_busy_and_unreachable(self):
        assert platforms.blocked(
            platforms._session(archived=True, busy=True, reachable=False)) == platforms.ARCHIVED

    def test_a_held_thread_outranks_unreachable(self):
        assert platforms.blocked(platforms._session(busy=True, reachable=False)) == platforms.BUSY

    def test_a_session_with_no_route_to_it_is_unreachable(self):
        assert platforms.blocked(platforms._session(reachable=False)) == platforms.UNREACHABLE

    @pytest.mark.parametrize("value", [None, "", 7, []])
    def test_anything_that_is_not_a_session_is_unreachable_rather_than_fine(self, value):
        """Fail closed: a caller that asks about nonsense must not be told to
        go ahead."""
        assert platforms.blocked(value) == platforms.UNREACHABLE

    def test_every_reason_has_words_to_show_a_user(self):
        for reason in (platforms.SPIN_OFF, platforms.ARCHIVED, platforms.BUSY, platforms.UNREACHABLE):
            assert platforms.REASONS[reason]


class TestFill:
    def test_it_is_the_context_over_the_window(self):
        assert platforms.fill(platforms._session(context_tokens=129200, context_window=258400)) == 0.5

    @pytest.mark.parametrize("fields", [
        {"context_tokens": None, "context_window": 258400},
        {"context_tokens": 100, "context_window": None},
        {"context_tokens": 100, "context_window": 0},
    ])
    def test_a_number_that_is_missing_or_zero_makes_it_unanswerable(self, fields):
        assert platforms.fill(platforms._session(**fields)) is None

    def test_anything_that_is_not_a_session_is_unanswerable(self):
        assert platforms.fill("not a session") is None


class TestCodexSessions:
    def test_a_thread_is_measured_and_normalised(self, codex, env):
        codex("t1", tokens=129200, window=258400)
        (got,) = platforms.codex_sessions(env)
        assert got["platform"] == platforms.CODEX
        assert got["id"] == "t1"
        assert got["context_tokens"] == 129200
        assert got["context_window"] == 258400
        assert got["state"] == "idle"
        assert platforms.fill(got) == 0.5
        assert platforms.blocked(got) is None

    def test_a_subagent_thread_comes_back_marked_as_a_spin_off(self, codex, env):
        codex("t1", kind="subagent")
        assert platforms.blocked(platforms.codex_sessions(env)[0]) == platforms.SPIN_OFF

    def test_an_archived_thread_comes_back_marked_archived(self, codex, env):
        codex("t1", archived=1)
        assert platforms.blocked(platforms.codex_sessions(env)[0]) == platforms.ARCHIVED

    def test_a_thread_a_running_app_holds_comes_back_busy(self, codex, env, monkeypatch):
        codex("t1")
        monkeypatch.setattr(codex_threads, "is_loaded", lambda *a, **k: True)
        assert platforms.blocked(platforms.codex_sessions(env)[0]) == platforms.BUSY

    def test_a_running_turn_is_reported_as_running(self, codex, env):
        codex("t1", state="task_started")
        assert platforms.codex_sessions(env)[0]["state"] == "running"

    def test_measuring_can_be_skipped_for_a_listing_that_only_wants_names(self, codex, env):
        codex("t1")
        (got,) = platforms.codex_sessions(env, measure=False)
        assert got["title"] == "A thread"
        assert (got["context_tokens"], got["context_window"], got["state"]) == (None, None, None)


class TestClaudeSessions:
    def test_a_live_session_is_normalised_to_the_same_shape(self, claude, tmp_path):
        claude()
        (got,) = platforms.claude_sessions(measure=False)
        assert got["platform"] == platforms.CLAUDE
        assert got["title"] == "A session"
        assert platforms.blocked(got) is None

    def test_a_session_with_remote_control_off_is_listed_as_unreachable_not_dropped(self, claude):
        """D-20260920-020: that state is the one the user most needs told about."""
        claude(bridgeSessionId=None)
        (got,) = platforms.claude_sessions(measure=False)
        assert platforms.blocked(got) == platforms.UNREACHABLE

    def test_a_worktree_session_is_a_spin_off_on_this_side_too(self, claude):
        claude(cwd=r"C:\Dev\x\.claude\worktrees\angry-dirac-98738b")
        assert platforms.blocked(platforms.claude_sessions(measure=False)[0]) == platforms.SPIN_OFF


class TestInstalled:
    def test_codex_counts_as_installed_once_its_state_store_exists(self, codex, env, tmp_path,
                                                                   monkeypatch):
        monkeypatch.setattr(session_registry, "SESSIONS_DIR", tmp_path / "nowhere")
        codex("t1")
        assert platforms.installed(env) == [platforms.CODEX]

    def test_a_machine_with_neither_app_has_no_platforms(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_registry, "SESSIONS_DIR", tmp_path / "nowhere")
        assert platforms.installed({"CODEX_HOME": str(tmp_path / "nowhere")}) == []

    def test_both_apps_are_reported_in_a_fixed_order(self, codex, env, claude):
        codex("t1")
        claude()
        assert platforms.installed(env) == [platforms.CLAUDE, platforms.CODEX]


class TestSessions:
    def test_it_returns_both_platforms_by_default(self, codex, env, claude):
        codex("t1")
        claude()
        assert {s["platform"] for s in platforms.sessions(environ=env, measure=False)} == \
            {platforms.CLAUDE, platforms.CODEX}

    @pytest.mark.parametrize("only", [platforms.CLAUDE, platforms.CODEX])
    def test_one_platform_can_be_asked_for_on_its_own(self, codex, env, claude, only):
        codex("t1")
        claude()
        got = platforms.sessions(only, environ=env, measure=False)
        assert [s["platform"] for s in got] == [only]


class TestPlatformsEdges:
    def test_a_record_that_is_not_a_record_becomes_an_unreachable_session(self):
        got = platforms.codex_session_of("not a record")
        assert got["platform"] == platforms.CODEX
        assert platforms.blocked(got) == platforms.UNREACHABLE

    def test_a_thread_with_no_rollout_is_listed_without_being_measured(self, codex, env, tmp_path):
        """A row whose rollout has been tidied away is still a thread the user can
        see, so it is listed rather than dropped."""
        con = sqlite3.connect(str(tmp_path / "codex" / "state_5.sqlite"))
        con.execute("insert into threads (id, rollout_path, cwd, title, archived, updated_at_ms,"
                    " thread_source) values ('t9', '', 'C:/x', 'Gone', 0, 5, 'user')")
        con.commit()
        con.close()
        (got,) = [s for s in platforms.codex_sessions(env) if s["id"] == "t9"]
        assert got["context_tokens"] is None
        assert got["title"] == "Gone"


class TestTheNamesAreSpelledOut:
    """The platform names reach a user through the CLI's --platform choices, and
    the reason keys are what a caller branches on. Asserting them against the
    module's own constants cannot catch a rename; a mutation run found all ten
    surviving."""

    def test_the_two_platform_names(self):
        assert platforms.CLAUDE == "claude"
        assert platforms.CODEX == "codex"
        assert platforms.PLATFORMS == ("claude", "codex")

    def test_the_four_reasons_a_session_cannot_be_compacted(self):
        assert platforms.SPIN_OFF == "spin_off"
        assert platforms.ARCHIVED == "archived"
        assert platforms.BUSY == "busy"
        assert platforms.UNREACHABLE == "unreachable"

    def test_every_reason_reads_as_a_sentence_rather_than_a_key(self):
        """"Truthy" was the old assertion, which any replacement string passed."""
        for reason in platforms.REASONS:
            words = platforms.REASONS[reason]
            assert len(words.split()) >= 4, f"{reason} has no explanation"
            assert reason.replace("_", " ") not in words or len(words) > 20

    def test_a_session_carries_every_field_a_caller_reads(self):
        """The keys are the shape both platforms promise; a renamed one would
        silently read as None at every call site."""
        assert set(platforms._session()) == {
            "platform", "id", "title", "cwd", "transcript", "context_tokens",
            "context_window", "state", "archived", "spin_off", "busy", "reachable"}

    def test_listing_measures_unless_it_is_told_not_to(self, codex, env):
        """The default is what a bare call gets, so it is asserted on a bare call."""
        codex("t1", tokens=4242)
        assert platforms.codex_sessions(env)[0]["context_tokens"] == 4242
        assert platforms.sessions(platforms.CODEX, environ=env)[0]["context_tokens"] == 4242
        assert platforms.codex_session_of(
            codex_threads.threads(env)[0], env)["context_tokens"] == 4242
