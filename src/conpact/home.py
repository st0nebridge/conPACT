"""
@module conpact.home
@description Where conPACT keeps what it owns: ~/.conpact/, one folder for
             both apps, inside neither's (D-20260923-048). Claude Code's own
             files - its session records, transcripts, login and settings -
             stay where Claude Code keeps them, and ChatGPT Desktop's where it
             keeps them; this is only conPACT's.

             Until 2026-09-23 conPACT's folder was ~/.claude/conpact/. The first
             conPACT process to start after the upgrade moves what was there,
             and every later one finishes whatever could not be moved yet:
             - choices and records are moved, unless the new home already has
               one, which then wins and the old copy is dropped;
             - a log is moved, or appended to the one already here;
             - requests are never moved: the server that queued one may still
               withdraw it where it put it, so the readers look in the old
               folder instead (D-20260922-044);
             - what a running process keeps writing - a watch's marker, a
               toast's slot, the sidecar's heartbeat - is left to that process
               and removed once it is older than anything that could still be
               using it;
             - the old folder goes once it is empty.
             Nothing here raises: a file that cannot be moved now is left for
             the next pass.
@input      the user's home directory
@output     the paths; the list of what a pass moved
@dependencies stdlib: os, pathlib, shutil, time
"""
from __future__ import annotations

import os
import pathlib
import shutil
import time

_USER = pathlib.Path(os.path.expanduser("~"))

HOME = _USER / ".conpact"
# Where it lived until 2026-09-23, and the requests folder of the name before.
PREVIOUS = _USER / ".claude" / "conpact"
CLAUTOMATIC = _USER / ".claude" / "clautomatic"

CHOICES_AND_RECORDS = ("settings.json", "idle-notify.off", "codex-host.json", "codex-sidecar.json")
PER_SESSION = ("idle/auto", "idle/mute", "idle/hold")
LOGS = ("hook-log.jsonl", "idle-log.jsonl")
LIVE = ("idle/watch", "idle/toasts")
HEARTBEAT = "codex-active.json"
# Longer than any watch can last: a one-hour cache, the toast before it
# expires, and a compaction that follows.
STALE_AFTER = 2 * 3600.0


def _unlink(path: pathlib.Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _copy_in(source: pathlib.Path, target: pathlib.Path) -> bool:
    """For a filesystem without hard links: a whole copy under a temporary name,
    renamed into place only if the place is still free."""
    temp = target.with_name(target.name + ".moving")
    try:
        shutil.copy2(source, temp)
        if target.exists():
            _unlink(temp)
            return False
        os.rename(temp, target)
        return True
    except OSError:
        _unlink(temp)
        return False


def _move(source: pathlib.Path, target: pathlib.Path, drop_if_taken: bool = True) -> bool:
    """Move a file unless the target exists, in which case the new home's copy
    wins and the old one is dropped (or kept, for the caller to merge). Linking
    first makes "unless it exists" hold against a second pass racing this one,
    on every platform. A source still held open (Windows will not delete it) is
    left whole, and the half-made move undone, for the next pass."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)
    except FileExistsError:
        if drop_if_taken:
            _unlink(source)
        return False
    except OSError:
        if not source.is_file() or not _copy_in(source, target):
            return False
    if _unlink(source):
        return True
    _unlink(target)
    return False


def _append(source: pathlib.Path, target: pathlib.Path) -> bool:
    """Add an old log's lines to the one already here. The old log is taken
    out of the way first, so a line written to it meanwhile starts a new file
    for the next pass rather than being lost or copied twice."""
    held = source.with_name(source.name + ".moving")
    try:
        os.replace(source, held)
    except OSError:
        return False
    try:
        text = held.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
        with target.open("a", encoding="utf-8") as out:
            out.write(text)
    except OSError:
        try:
            os.rename(held, source)
        except OSError:
            pass
        return False
    _unlink(held)
    return True


def _stale(path: pathlib.Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime > STALE_AFTER
    except OSError:
        return False


def _files(folder: pathlib.Path):
    try:
        return sorted(p for p in folder.iterdir() if p.is_file())
    except OSError:
        return []


def _prune(folder: pathlib.Path, stop: pathlib.Path) -> None:
    """Remove empty folders from the bottom up, `stop` included."""
    try:
        for path in sorted((p for p in folder.rglob("*") if p.is_dir()), key=lambda p: len(p.parts),
                           reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        stop.rmdir()
    except OSError:
        pass


def migrate(previous: pathlib.Path | None = None, home: pathlib.Path | None = None,
            clock=time.time) -> list[str]:
    """Move what the old folder holds into the new home. Returns the paths,
    relative to the old folder, that this pass moved or appended."""
    old = PREVIOUS if previous is None else pathlib.Path(previous)
    new = HOME if home is None else pathlib.Path(home)
    if not old.is_dir():
        return []
    moved: list[str] = []
    now = clock()
    for name in CHOICES_AND_RECORDS:
        if (old / name).is_file() and _move(old / name, new / name):
            moved.append(name)
    for folder in PER_SESSION:
        for path in _files(old / folder):
            if _move(path, new / folder / path.name):
                moved.append(f"{folder}/{path.name}")
    for name in LOGS:
        source, target = old / name, new / name
        if not source.is_file():
            continue
        if _move(source, target, drop_if_taken=False) or (target.is_file() and _append(source, target)):
            moved.append(name)
    for folder in LIVE:
        for path in _files(old / folder):
            if _stale(path, now):
                try:
                    path.unlink()
                except OSError:
                    pass
    if _stale(old / HEARTBEAT, now):
        try:
            (old / HEARTBEAT).unlink()
        except OSError:
            pass
    _prune(old, old)
    return moved
