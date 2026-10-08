"""
@module conpact.codex_home
@description Where ChatGPT Desktop (Codex) keeps its state on this machine, and
             how to read it without ever writing to it. Codex keeps a SQLite
             state store (`state_5.sqlite`, one row per thread), a follow-up
             queue (`queue_1.sqlite`), one JSONL rollout per thread under
             `sessions/`, and an exclusive lock file per *loaded* thread under
             `thread-writer-locks/`. Every database here belongs to a running
             app; this module opens each one `mode=ro` so that a mistake upstream
             cannot become a write into the user's live Codex state, and answers
             "nothing" for a file that is missing, busy or not a database at all.
@input      the process environment (CODEX_HOME overrides the default location)
@output     the paths Codex's own files sit at, read-only connections to them,
            and query results as plain dicts
@dependencies stdlib: os, pathlib, sqlite3
"""
from __future__ import annotations

import os
import pathlib
import sqlite3

HOME_VAR = "CODEX_HOME"
FOLDER = ".codex"
STATE_DB = "state_5.sqlite"
QUEUE_DB = "queue_1.sqlite"
LOCKS = "thread-writer-locks"
SESSIONS = "sessions"

# Windows' extended-length prefixes. Codex records a thread's cwd and its
# rollout path with them about half the time, and without them the rest.
PREFIX_UNC = "\\\\?\\UNC\\"
PREFIX = "\\\\?\\"
TIMEOUT = 5.0


def _environ(environ) -> dict:
    return os.environ if environ is None else environ


def home(environ=None) -> pathlib.Path:
    """Codex's state folder. A blank CODEX_HOME is ignored, because an empty
    path resolves to the working directory rather than to nothing."""
    override = _environ(environ).get(HOME_VAR)
    if isinstance(override, str) and override.strip():
        return pathlib.Path(override)
    return pathlib.Path(os.path.expanduser("~")) / FOLDER


def state_db(environ=None) -> pathlib.Path:
    return home(environ) / STATE_DB


def queue_db(environ=None) -> pathlib.Path:
    return home(environ) / QUEUE_DB


def locks_dir(environ=None) -> pathlib.Path:
    return home(environ) / LOCKS


def sessions_dir(environ=None) -> pathlib.Path:
    return home(environ) / SESSIONS


def plain_path(value):
    """A path as every other tool prints it, or None for anything that is not
    one. `\\\\?\\UNC\\server\\share` is a share, so it keeps its two leading
    slashes; `\\\\?\\C:\\x` is an ordinary local path with a prefix bolted on."""
    if not isinstance(value, str):
        return None
    text = value
    if text.startswith(PREFIX_UNC):
        text = "\\\\" + text[len(PREFIX_UNC):]
    elif text.startswith(PREFIX):
        text = text[len(PREFIX):]
    text = text.strip()
    return text or None


def read_only(path) -> sqlite3.Connection | None:
    """A read-only connection to one of Codex's databases, or None when there is
    nothing readable there. `mode=ro` is what makes a write impossible: these
    files belong to a running app, and nothing here has any business changing
    them."""
    try:
        if not pathlib.Path(path).is_file():
            return None
    except OSError:
        return None
    uri = pathlib.Path(path).as_uri().replace("file://", "file:", 1) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=TIMEOUT)
        con.row_factory = sqlite3.Row
        con.execute("select 1 from sqlite_master limit 1").fetchone()
        return con
    except sqlite3.Error:
        return None


def rows(path, sql: str, params=()) -> list[dict]:
    """Every row a query returns, as plain dicts, with the connection closed
    behind it. A schema we do not recognise - Codex numbers its databases and
    renames tables between versions - reads as no rows, never as an exception
    escaping into a hook."""
    con = read_only(path)
    if con is None:
        return []
    try:
        return [dict(row) for row in con.execute(sql, params)]
    except sqlite3.Error:
        return []
    finally:
        con.close()
