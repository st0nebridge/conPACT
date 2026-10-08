"""
@module conpact.codex_threads
@description Which Codex threads exist and what kind each one is, read from
             ChatGPT Desktop's own state store. One row per thread carries its
             rollout path, working directory, title, archived flag and - the
             field that matters most here - `thread_source`, which separates a
             real user thread from the ones Codex spawns for itself: a subagent
             or one of the guardian reviews it runs after a turn. Those are the
             Codex counterpart of a `.claude/worktrees/...` checkout (D-028):
             never resumed, so never worth compacting. It also answers whether a
             running app currently holds a thread, by testing the app's own
             exclusive lock rather than by guessing from a timestamp.
@input      a thread id, and the process environment (for CODEX_HOME)
@output     normalised thread records; whether one is a spin-off, archived, or
            held open by a running app
@dependencies conpact.codex_home; stdlib: fcntl (macOS, Linux), msvcrt (Windows),
              pathlib, re
"""
from __future__ import annotations

import pathlib
import re

from . import codex_home

try:                                     # Windows only
    import msvcrt as _msvcrt
except ImportError:                      # pragma: no cover - not reachable on Windows
    _msvcrt = None
try:                                     # macOS and Linux. With neither module,
    import fcntl as _fcntl               # is_loaded fails closed.
except ImportError:                      # pragma: no cover - not reachable off Windows
    _fcntl = None

UNKNOWN = "unknown"
# The kinds Codex spawns for itself. Everything else - including a kind we have
# never seen and the empty column on threads older than it - fails open.
SPIN_OFF_KINDS = frozenset({"subagent", "guardian_review"})
LOCK_SUFFIX = ".lock"
_PLAIN = re.compile(r"[A-Za-z0-9_-]{1,128}")

COLUMNS = ("id", "rollout_path", "cwd", "name", "title", "tokens_used", "archived",
           "updated_at_ms", "thread_source", "model", "source")



def _record(row: dict) -> dict:
    """One state-store row as the rest of conPACT wants to see it."""
    kind = row.get("thread_source")
    name, title = row.get("name"), row.get("title")
    return {
        "platform": "codex",
        "id": row.get("id"),
        "rollout_path": codex_home.plain_path(row.get("rollout_path")),
        "cwd": codex_home.plain_path(row.get("cwd")),
        "name": name if isinstance(name, str) and name.strip() else None,
        "title": title or "",
        # What the desktop app shows, and so what a user recognises a thread by:
        # its name once it has one, and the first prompt until then.
        "label": (name.strip() if isinstance(name, str) and name.strip() else (title or "")),
        "kind": kind if isinstance(kind, str) and kind else UNKNOWN,
        "archived": bool(row.get("archived")),
        "updated_at_ms": row.get("updated_at_ms"),
        "tokens_spent": row.get("tokens_used"),
        "model": row.get("model"),
        "source": row.get("source"),
    }


def threads(environ=None, limit: int | None = None) -> list[dict]:
    """Every thread Codex knows about, newest first. A thread whose
    `updated_at_ms` is null - the column postdates the oldest rows - keeps its
    place at the end rather than being dropped, because the user can still open
    it."""
    sql = (f"select {', '.join(COLUMNS)} from threads "
           "order by coalesce(updated_at_ms, -1) desc, id desc")
    params: tuple = ()
    if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
        sql += " limit ?"
        params = (limit,)
    return [_record(row) for row in codex_home.rows(codex_home.state_db(environ), sql, params)]


def thread(thread_id, environ=None) -> dict | None:
    """One thread by id, or None when the store has no such row."""
    if not isinstance(thread_id, str) or not thread_id:
        return None
    found = codex_home.rows(codex_home.state_db(environ),
                            f"select {', '.join(COLUMNS)} from threads where id = ?",
                            (thread_id,))
    return _record(found[0]) if found else None


def is_spin_off(record) -> bool:
    """True only for a kind we positively recognise as one Codex spawned for
    itself. Everything else fails open and compacts as before (D-028)."""
    if not isinstance(record, dict):
        return False
    return record.get("kind") in SPIN_OFF_KINDS


def is_archived(record) -> bool:
    """True only when the store says the user archived this thread."""
    if not isinstance(record, dict):
        return False
    return bool(record.get("archived"))


def lock_path(thread_id, environ=None) -> pathlib.Path | None:
    """Where Codex keeps this thread's writer lock, or None for an id we will
    not turn into a file name."""
    if not isinstance(thread_id, str) or not _PLAIN.fullmatch(thread_id):
        return None
    return codex_home.locks_dir(environ) / (thread_id + LOCK_SUFFIX)


def _probe(path: pathlib.Path) -> bool:
    """Whether Codex's lock on this file is already held: the Windows probe
    where there is msvcrt, the POSIX one elsewhere."""
    if _msvcrt is not None:
        return _probe_windows(path)
    return _probe_posix(path)


def _probe_windows(path: pathlib.Path) -> bool:
    """Whether Codex's lock on this file is already held, measured by trying to
    take it for one byte and giving it straight back.

    Measured, not assumed: Codex takes a *byte-range* lock (LockFileEx), which
    leaves the file freely openable - all four locks held on this machine opened
    without error in both "r+b" and "ab". Opening is therefore no test at all,
    and an earlier version of this function reported every live thread as free.
    `msvcrt.locking` is what actually sees it.

    Taking the lock to test it does open a window of a few microseconds in which
    Codex would find it held; there is no read-only way to ask about a byte-range
    lock on Windows. Closing the handle releases the lock even if the explicit
    unlock fails, so the window cannot outlive this call.
    """
    handle = path.open("r+b")
    try:
        try:
            _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        try:
            _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return False
    finally:
        handle.close()


def _probe_posix(path: pathlib.Path) -> bool:
    """The same test on macOS and Linux, where there are two kinds of lock and
    they do not see each other: flock(2) takes the whole file, fcntl(2) takes a
    byte range. Which one Codex uses there has not been measured - its Linux
    binary is statically linked, so its imports do not say - so both are tried,
    and the thread is held if either is. A held lock of either kind makes the
    attempt fail at once, because both are asked not to wait.

    As on Windows, testing means taking the lock for a moment and giving it
    back. Closing the file releases both kinds whatever else fails, so nothing
    this takes can outlive the call.
    """
    handle = path.open("r+b")
    try:
        fd = handle.fileno()
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            return True
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            _fcntl.lockf(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB, 1)
        except OSError:
            return True
        try:
            _fcntl.lockf(fd, _fcntl.LOCK_UN, 1)
        except OSError:
            pass
        return False
    finally:
        handle.close()


def is_loaded(thread_id, environ=None, prober=_probe) -> bool:
    """Whether a running Codex holds this thread open. This is the one question
    that decides whether the thread's rollout may be touched, so it fails closed:
    an id we will not turn into a file name, a platform whose lock we cannot
    probe, or any error we did not expect all read as "held". Only two things
    read as free - no lock file at all (which is how 101 of this machine's 105
    threads look), and a file whose lock we could take ourselves, which is what a
    lock left behind by an app that has since exited looks like."""
    path = lock_path(thread_id, environ)
    if path is None or (_msvcrt is None and _fcntl is None):
        return True
    try:
        return prober(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
