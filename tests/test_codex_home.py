"""
@module tests.test_codex_home
@description Where Codex's state lives, and that we only ever read it.
@input      conpact.codex_home
@output     assertions on path resolution, the extended-length prefix and
            read-only SQLite access
@dependencies conpact.codex_home; stdlib: pathlib, sqlite3
"""
import pathlib
import sqlite3

import pytest

from conpact import codex_home


def _make_db(path):
    con = sqlite3.connect(str(path))
    con.execute("create table t (id text primary key, n integer)")
    con.execute("insert into t values ('a', 1)")
    con.execute("insert into t values ('b', 2)")
    con.commit()
    con.close()
    return path


class TestHome:
    def test_it_defaults_to_the_dot_codex_folder_of_the_user(self):
        assert codex_home.home({}) == pathlib.Path.home() / ".codex"

    def test_codex_home_overrides_it(self, tmp_path):
        assert codex_home.home({"CODEX_HOME": str(tmp_path)}) == tmp_path

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_a_blank_override_is_ignored_rather_than_making_a_path_of_nothing(self, value):
        """An empty CODEX_HOME would otherwise resolve to the current directory."""
        assert codex_home.home({"CODEX_HOME": value} if value is not None else {}) == \
            pathlib.Path.home() / ".codex"

    def test_the_named_files_hang_off_whatever_home_resolved_to(self, tmp_path):
        env = {"CODEX_HOME": str(tmp_path)}
        assert codex_home.state_db(env) == tmp_path / "state_5.sqlite"
        assert codex_home.queue_db(env) == tmp_path / "queue_1.sqlite"
        assert codex_home.locks_dir(env) == tmp_path / "thread-writer-locks"
        assert codex_home.sessions_dir(env) == tmp_path / "sessions"


class TestPlainPath:
    def test_it_strips_the_windows_extended_length_prefix(self):
        """Codex records a thread's cwd and rollout as \\\\?\\C:\\... about half the
        time; the same path without the prefix is what every other tool prints."""
        assert codex_home.plain_path(r"\\?\C:\src\Example") == r"C:\src\Example"

    def test_it_strips_the_unc_form_too(self):
        assert codex_home.plain_path(r"\\?\UNC\server\share\x") == r"\\server\share\x"

    def test_an_ordinary_path_is_returned_unchanged(self):
        assert codex_home.plain_path(r"C:\src\Example") == r"C:\src\Example"

    @pytest.mark.parametrize("value", [None, 7, b"bytes", []])
    def test_anything_that_is_not_a_string_reads_as_no_path(self, value):
        assert codex_home.plain_path(value) is None

    def test_the_prefix_alone_is_not_a_path(self):
        assert codex_home.plain_path(r"\\?\ ") is None


class TestReadOnly:
    def test_a_missing_database_reads_as_nothing_rather_than_raising(self, tmp_path):
        assert codex_home.read_only(tmp_path / "absent.sqlite") is None

    def test_a_directory_in_place_of_a_database_reads_as_nothing(self, tmp_path):
        assert codex_home.read_only(tmp_path) is None

    def test_it_opens_a_real_database_and_reads_rows_as_dicts(self, tmp_path):
        con = codex_home.read_only(_make_db(tmp_path / "x.sqlite"))
        assert con is not None
        try:
            got = [dict(r) for r in con.execute("select * from t order by id")]
        finally:
            con.close()
        assert got == [{"id": "a", "n": 1}, {"id": "b", "n": 2}]

    def test_the_connection_it_hands_back_cannot_write(self, tmp_path):
        """The whole module is read-only by contract; this is the contract enforced
        by SQLite itself rather than by our own care."""
        con = codex_home.read_only(_make_db(tmp_path / "x.sqlite"))
        with pytest.raises(sqlite3.OperationalError):
            con.execute("insert into t values ('c', 3)")
        con.close()

    def test_a_file_that_is_not_a_database_reads_as_nothing(self, tmp_path):
        bad = tmp_path / "bad.sqlite"
        bad.write_text("not a database at all", encoding="utf-8")
        assert codex_home.read_only(bad) is None


class TestRows:
    def test_it_returns_dicts_and_closes_the_connection_behind_itself(self, tmp_path):
        path = _make_db(tmp_path / "x.sqlite")
        assert codex_home.rows(path, "select id from t order by id") == [{"id": "a"}, {"id": "b"}]

    def test_parameters_are_bound_rather_than_pasted(self, tmp_path):
        path = _make_db(tmp_path / "x.sqlite")
        assert codex_home.rows(path, "select n from t where id = ?", ("b",)) == [{"n": 2}]

    def test_a_query_against_a_table_that_is_not_there_reads_as_no_rows(self, tmp_path):
        """Codex renames its tables between versions; a schema we do not recognise
        must read as "nothing to say", never as a crash in a Stop hook."""
        path = _make_db(tmp_path / "x.sqlite")
        assert codex_home.rows(path, "select * from threads") == []

    def test_a_missing_database_reads_as_no_rows(self, tmp_path):
        assert codex_home.rows(tmp_path / "absent.sqlite", "select 1") == []
