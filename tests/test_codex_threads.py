"""
@module tests.test_codex_threads
@description Which Codex threads exist, what kind each one is, and which of them
             a running app currently holds open.
@input      conpact.codex_threads, against a stand-in state database
@output     assertions on normalisation, the spin-off and archived guards, and
            the writer lock
@dependencies conpact.codex_threads, conpact.codex_home; stdlib: sqlite3
"""
import sqlite3

import pytest

from conpact import codex_threads

SCHEMA = """
create table threads (
    id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, cwd TEXT NOT NULL,
    name TEXT, title TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0, updated_at_ms INTEGER,
    thread_source TEXT, model TEXT, source TEXT NOT NULL DEFAULT '')
"""
ROW = dict(id="019e0000-0000-7000-a000-000000000001", rollout_path=r"C:\r\a.jsonl",
           cwd=r"C:\src\Example", name=None, title="Encryption review",
           tokens_used=1523374,
           archived=0, updated_at_ms=1789_900_000_000, thread_source="user",
           model="gpt-6-astra", source="vscode")


@pytest.fixture
def state(tmp_path):
    """A stand-in for Codex's state_5.sqlite, with the columns we actually read.
    Yields the function that adds a thread to it."""
    path = tmp_path / "state_5.sqlite"
    con = sqlite3.connect(str(path))
    con.execute(SCHEMA)
    con.commit()

    def add(**over):
        record = {**ROW, **over}
        con.execute(f"insert into threads ({','.join(record)}) "
                    f"values ({','.join('?' * len(record))})", tuple(record.values()))
        con.commit()
        return record["id"]

    yield add
    con.close()


@pytest.fixture
def env(tmp_path):
    return {"CODEX_HOME": str(tmp_path)}


class TestReadingThreads:
    def test_a_thread_is_normalised_to_the_fields_we_use(self, state, env):
        state()
        (got,) = codex_threads.threads(env)
        assert got["id"] == ROW["id"]
        assert got["cwd"] == r"C:\src\Example"
        assert got["title"] == "Encryption review"
        assert got["kind"] == "user"
        assert got["archived"] is False
        assert got["updated_at_ms"] == ROW["updated_at_ms"]

    def test_the_extended_length_prefix_is_stripped_from_both_paths(self, state, env):
        """Codex writes \\\\?\\C:\\... for roughly half its rows; a caller comparing
        a cwd against one it holds must not have to know which half it got."""
        state(cwd=r"\\?\C:\src\Example", rollout_path=r"\\?\C:\r\a.jsonl")
        (got,) = codex_threads.threads(env)
        assert got["cwd"] == r"C:\src\Example"
        assert got["rollout_path"] == r"C:\r\a.jsonl"

    def test_threads_come_back_newest_first(self, state, env):
        state(id="a" * 8, updated_at_ms=1000)
        state(id="b" * 8, updated_at_ms=3000)
        state(id="c" * 8, updated_at_ms=2000)
        assert [t["id"] for t in codex_threads.threads(env)] == ["b" * 8, "c" * 8, "a" * 8]

    def test_a_row_with_no_timestamp_is_kept_and_sorts_last(self, state, env):
        """`updated_at_ms` was added to the schema later; the oldest rows have none,
        and dropping them would hide a thread the user can still open."""
        state(id="old", updated_at_ms=None)
        state(id="new", updated_at_ms=5000)
        assert [t["id"] for t in codex_threads.threads(env)] == ["new", "old"]

    def test_one_thread_can_be_looked_up_by_id(self, state, env):
        state(id="wanted")
        state(id="other")
        assert codex_threads.thread("wanted", env)["id"] == "wanted"

    def test_an_id_that_is_not_there_reads_as_nothing(self, state, env):
        state()
        assert codex_threads.thread("absent", env) is None

    def test_a_codex_that_was_never_installed_reads_as_no_threads(self, tmp_path):
        assert codex_threads.threads({"CODEX_HOME": str(tmp_path / "nowhere")}) == []

    def test_the_limit_is_applied_by_the_query_not_by_the_caller(self, state, env):
        for n in range(5):
            state(id=f"t{n}", updated_at_ms=1000 + n)
        assert [t["id"] for t in codex_threads.threads(env, limit=2)] == ["t4", "t3"]


class TestKind:
    @pytest.mark.parametrize("source, kind", [
        ("user", "user"), ("subagent", "subagent"),
        ("guardian_review", "guardian_review"), (None, "unknown"), ("", "unknown")])
    def test_the_thread_source_column_names_the_kind(self, state, env, source, kind):
        state(thread_source=source)
        assert codex_threads.threads(env)[0]["kind"] == kind

    def test_a_subagent_thread_is_a_spin_off(self, state, env):
        state(thread_source="subagent")
        assert codex_threads.is_spin_off(codex_threads.threads(env)[0]) is True

    def test_a_guardian_review_thread_is_a_spin_off(self, state, env):
        """Codex spawns one of these per auto-review; 55 of this machine's 105
        threads were guardian reviews, and none of them is ever resumed."""
        state(thread_source="guardian_review")
        assert codex_threads.is_spin_off(codex_threads.threads(env)[0]) is True

    def test_a_user_thread_is_not_a_spin_off(self, state, env):
        state(thread_source="user")
        assert codex_threads.is_spin_off(codex_threads.threads(env)[0]) is False

    def test_a_kind_we_do_not_recognise_fails_open_and_is_not_a_spin_off(self, state, env):
        """The column postdates the oldest threads, and Codex adds kinds. Refusing
        on an unknown value would silently stop compacting a real user thread."""
        state(thread_source=None)
        assert codex_threads.is_spin_off(codex_threads.threads(env)[0]) is False
        assert codex_threads.is_spin_off({"kind": "something_new"}) is False

    @pytest.mark.parametrize("record", [None, {}, {"kind": None}, "not a record"])
    def test_anything_that_is_not_a_record_fails_open(self, record):
        assert codex_threads.is_spin_off(record) is False


class TestArchived:
    def test_the_archived_column_is_read_as_a_boolean(self, state, env):
        state(archived=1)
        got = codex_threads.threads(env)[0]
        assert got["archived"] is True
        assert codex_threads.is_archived(got) is True

    def test_a_live_thread_is_not_archived(self, state, env):
        state(archived=0)
        assert codex_threads.is_archived(codex_threads.threads(env)[0]) is False

    @pytest.mark.parametrize("record", [None, {}, "not a record"])
    def test_a_record_that_says_nothing_reads_as_not_archived(self, record):
        assert codex_threads.is_archived(record) is False


class TestLoaded:
    """A thread Codex currently has open holds a byte-range lock on
    `thread-writer-locks/<id>.lock`. That lock is the one safe answer to "may I
    touch this thread's rollout", it is the app's own mechanism rather than ours,
    and the guard fails closed in every direction but two."""

    @pytest.fixture
    def locks(self, tmp_path):
        folder = tmp_path / "thread-writer-locks"
        folder.mkdir(exist_ok=True)
        return folder

    def test_no_lock_file_means_no_app_holds_the_thread(self, locks, env):
        """101 of this machine's 105 threads look exactly like this."""
        assert codex_threads.is_loaded("019e0000", env) is False

    def test_a_lock_we_cannot_take_means_a_running_app_holds_the_thread(self, locks, env):
        (locks / "held.lock").write_bytes(b"")
        assert codex_threads.is_loaded("held", env, prober=lambda path: True) is True

    def test_a_lock_file_left_behind_by_a_dead_app_does_not_hold_the_thread(self, locks, env):
        """Codex leaves the file in place; what it takes is the lock, not the name.
        Treating a stale file as held would stop us for ever."""
        (locks / "stale.lock").write_bytes(b"")
        assert codex_threads.is_loaded("stale", env) is False

    def test_a_missing_locks_folder_reads_as_nothing_held(self, tmp_path):
        assert codex_threads.is_loaded("x", {"CODEX_HOME": str(tmp_path / "nowhere")}) is False

    def test_an_error_we_did_not_expect_reads_as_held_rather_than_as_free(self, locks, env):
        """Fail closed: the cost of a wrong "free" is writing into a rollout a
        running app is writing to, and the cost of a wrong "held" is one skipped
        compaction."""
        def boom(path):
            raise OSError(5, "device error")
        assert codex_threads.is_loaded("x", env, prober=boom) is True

    @pytest.mark.parametrize("thread_id", [None, "", 7, "../escape", "a/b", "a\\b"])
    def test_an_id_that_is_not_a_plain_name_reads_as_held(self, thread_id, env):
        """The id becomes a file name, so anything with a separator in it is
        refused rather than joined onto a path - and refused means held, because
        an id we cannot check is not an id we may act on."""
        assert codex_threads.lock_path(thread_id, env) is None
        assert codex_threads.is_loaded(thread_id, env) is True


class TestTheProbeItself:
    """The probe is the part that was wrong first time round, so it is measured
    against a real lock rather than a stand-in."""

    def test_it_sees_a_lock_another_handle_is_holding(self, tmp_path):
        msvcrt = pytest.importorskip("msvcrt")
        path = tmp_path / "x.lock"
        path.write_bytes(b"")
        holder = path.open("r+b")
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            assert codex_threads._probe(path) is True
        finally:
            msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
            holder.close()

    def test_an_unlocked_file_reads_as_free_and_is_left_unlocked(self, tmp_path):
        """Opening is no test at all - a byte-range lock leaves the file freely
        openable - and the probe must give back whatever it took."""
        pytest.importorskip("msvcrt")
        path = tmp_path / "x.lock"
        path.write_bytes(b"")
        assert codex_threads._probe(path) is False
        assert codex_threads._probe(path) is False      # nothing was left held

    def test_it_writes_nothing_to_the_file_it_probes(self, tmp_path):
        pytest.importorskip("msvcrt")
        path = tmp_path / "x.lock"
        path.write_bytes(b"codex wrote this")
        codex_threads._probe(path)
        assert path.read_bytes() == b"codex wrote this"


HOLDER = """
import fcntl, sys
handle = open(sys.argv[1], "r+b")
if sys.argv[2] == "flock":
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
else:
    fcntl.lockf(handle.fileno(), fcntl.LOCK_EX, 1)
print("held", flush=True)
sys.stdin.read()
"""


class TestThePosixProbe:
    """macOS and Linux have two kinds of lock that do not see each other, and
    which one Codex takes there has not been measured, so the probe must see
    both. Each is held by another process, because a byte-range lock is per
    process: one taken by this process would never conflict with itself."""

    @pytest.fixture
    def hold(self, tmp_path):
        import subprocess
        import sys
        pytest.importorskip("fcntl")
        holders = []

        def start(kind):
            path = tmp_path / f"{kind}.lock"
            path.write_bytes(b"")
            holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(path), kind],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            holders.append(holder)
            if holder.stdout.readline().strip() != "held":
                raise RuntimeError(f"the {kind} holder never took its lock")
            return path
        yield start
        for holder in holders:
            holder.stdin.close()
            holder.wait(timeout=10)

    @pytest.mark.parametrize("kind", ["flock", "lockf"])
    def test_a_lock_of_either_kind_held_elsewhere_reads_as_held(self, hold, kind):
        assert codex_threads._probe_posix(hold(kind)) is True

    def test_a_file_nobody_holds_reads_as_free_and_is_left_free(self, tmp_path):
        pytest.importorskip("fcntl")
        path = tmp_path / "x.lock"
        path.write_bytes(b"codex wrote this")
        assert codex_threads._probe_posix(path) is False
        assert codex_threads._probe_posix(path) is False      # nothing was left held
        assert path.read_bytes() == b"codex wrote this"


    def test_off_windows_the_dispatcher_takes_the_posix_probe(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(codex_threads, "_msvcrt", None)
        monkeypatch.setattr(codex_threads, "_probe_posix", lambda path: seen.append(path) or False)
        assert codex_threads._probe(tmp_path / "x.lock") is False
        assert seen == [tmp_path / "x.lock"]

    def test_with_no_way_to_probe_at_all_every_thread_reads_as_held(self, tmp_path, monkeypatch):
        """Fail closed: a platform with neither module cannot say a thread is free."""
        locks = tmp_path / "thread-writer-locks"
        locks.mkdir()
        (locks / "x.lock").write_bytes(b"")
        monkeypatch.setattr(codex_threads, "_msvcrt", None)
        monkeypatch.setattr(codex_threads, "_fcntl", None)
        assert codex_threads.is_loaded("x", {"CODEX_HOME": str(tmp_path)}) is True


class TestEdges:
    @pytest.mark.parametrize("thread_id", [None, "", 7, []])
    def test_looking_a_thread_up_by_something_that_is_not_an_id_reads_as_nothing(self, state, env,
                                                                                 thread_id):
        state()
        assert codex_threads.thread(thread_id, env) is None

    def test_a_lock_that_will_not_unlock_is_still_released_by_closing_the_handle(self, tmp_path,
                                                                                 monkeypatch):
        """The window in which we hold Codex's lock must not outlive the call even
        when the explicit unlock fails, so the close is the real guarantee."""
        msvcrt = pytest.importorskip("msvcrt")
        path = tmp_path / "x.lock"
        path.write_bytes(b"")
        real = msvcrt.locking

        def no_unlock(fd, mode, nbytes):
            if mode == msvcrt.LK_UNLCK:
                raise OSError(13, "will not unlock")
            return real(fd, mode, nbytes)

        monkeypatch.setattr(codex_threads._msvcrt, "locking", no_unlock)
        assert codex_threads._probe(path) is False
        monkeypatch.undo()
        assert codex_threads._probe(path) is False      # the close let it go anyway


class TestLabel:
    """The desktop app shows a thread's `name`, not the first prompt it was
    opened with, so that is what a user recognises it by - the user asked for a
    thread by its name, and a listing that shows only `title` cannot be matched
    against what he sees."""

    def test_the_name_is_what_a_thread_is_labelled_by(self, state, env):
        state(name="a long-running review thread",
              title="review the example project and tell me what the research missed")
        got = codex_threads.threads(env)[0]
        assert got["name"] == "a long-running review thread"
        assert got["label"] == "a long-running review thread"

    def test_the_first_prompt_is_the_label_until_a_thread_has_a_name(self, state, env):
        state(name=None, title="review the example project")
        got = codex_threads.threads(env)[0]
        assert got["name"] is None
        assert got["label"] == "review the example project"

    def test_the_raw_title_is_still_there_beside_the_label(self, state, env):
        state(name="Short name", title="the long first prompt")
        assert codex_threads.threads(env)[0]["title"] == "the long first prompt"

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_a_blank_name_is_not_a_label(self, state, env, name):
        state(name=name, title="the first prompt")
        got = codex_threads.threads(env)[0]
        assert got["name"] is None
        assert got["label"] == "the first prompt"

    def test_a_name_with_padding_is_trimmed(self, state, env):
        state(name="  Padded  ", title="x")
        assert codex_threads.threads(env)[0]["label"] == "Padded"


class TestTheNamesAndTheLimit:
    def test_the_kinds_codex_spawns_for_itself_are_named_as_literals(self):
        """The two values come out of someone else's schema; comparing them
        against this module's own constant cannot catch a rename."""
        assert codex_threads.SPIN_OFF_KINDS == {"subagent", "guardian_review"}
        assert codex_threads.UNKNOWN == "unknown"
        assert codex_threads.LOCK_SUFFIX == ".lock"

    def test_asking_for_no_threads_returns_no_threads(self, state, env):
        """A limit of 0 is a limit, not an absent one - a caller computing a page
        size would otherwise get every thread on the machine."""
        for n in range(3):
            state(id=f"t{n}", updated_at_ms=n)
        assert codex_threads.threads(env, limit=0) == []
        assert len(codex_threads.threads(env, limit=2)) == 2

    @pytest.mark.parametrize("limit", [-1, "2", 2.0, True, None])
    def test_a_limit_that_is_not_a_whole_count_is_ignored_rather_than_guessed(self, state, env,
                                                                              limit):
        for n in range(3):
            state(id=f"t{n}", updated_at_ms=n)
        assert len(codex_threads.threads(env, limit=limit)) == 3
