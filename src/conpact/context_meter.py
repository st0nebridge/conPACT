"""
@module conpact.context_meter
@description Measure how large a session's live context is, from its transcript.
             Claude Code writes each assistant message to the session's JSONL
             transcript together with the usage of the API call that produced
             it. The context the model saw on its latest call is that call's
             input (fresh + cache writes + cache reads) plus the output it
             added. Subagent (sidechain) and synthetic messages are skipped, and
             only the tail of the file is read unless more is needed.
@input      a transcript path (the Stop hook receives it as transcript_path),
            or a session id to find the transcript by
@output     the current context size in tokens, or None when it cannot be
            measured; a transcript path, or None
@dependencies conpact.session_registry; stdlib: json, os, pathlib
"""
from __future__ import annotations

import json
import os
import pathlib

from . import session_registry

PROJECTS_DIR = pathlib.Path(os.path.expanduser("~")) / ".claude" / "projects"

# The four usage counters that together make up the context of one API call.
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
TAIL_BYTES = 1 << 20


def usage_tokens(entry) -> int | None:
    """Context size implied by one transcript entry; None unless it is a
    main-thread assistant message with non-zero usage."""
    if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    message = entry.get("message")
    if not isinstance(message, dict) or message.get("model") == "<synthetic>":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    total = 0
    for field in USAGE_FIELDS:
        value = usage.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    return total or None


def entries_from_end(transcript_path, tail_bytes: int = TAIL_BYTES):
    """
    The transcript's entries (JSON objects), newest first. The file is read
    backwards in windows that grow 4x, each line is parsed once, and a line cut
    by a window's start is left for the next, larger window. Blank, partial and
    non-object lines are skipped; a missing or unreadable file yields nothing.
    """
    if not transcript_path:
        return
    path = pathlib.Path(transcript_path)
    try:
        with path.open("rb") as fh:
            end = path.stat().st_size  # everything before `end` is still unread
            window = tail_bytes
            while end > 0:
                start = max(0, end - window)
                fh.seek(start)
                lines = fh.read(end - start).split(b"\n")
                if start > 0:
                    # The first piece may be the tail of a cut line: re-read it whole later.
                    end = start + len(lines[0])
                    lines = lines[1:]
                    window *= 4
                else:
                    end = 0
                for raw in reversed(lines):
                    try:
                        entry = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(entry, dict):
                        yield entry
    except OSError:
        return


def current_context_tokens(transcript_path, tail_bytes: int = TAIL_BYTES) -> int | None:
    """The context size of the session's most recent main-thread API call."""
    for entry in entries_from_end(transcript_path, tail_bytes):
        tokens = usage_tokens(entry)
        if tokens is not None:
            return tokens
    return None


def find_transcript(session_id, projects_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    """The session's transcript, ~/.claude/projects/<project>/<session_id>.jsonl."""
    if not session_registry.is_valid_session_id(session_id):
        return None
    directory = projects_dir or PROJECTS_DIR
    try:
        matches = sorted(directory.glob(f"*/{session_id}.jsonl"))
    except OSError:
        return None
    return matches[0] if matches else None
