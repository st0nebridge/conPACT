"""
@module tests.provenance_kit
@description Builds small Claude Code transcripts (JSONL lines) for the provenance
             tests: the user's typed and queued messages, AskUserQuestion answers,
             permission denials, messages that only look like the user's (another
             session, a subagent's report, a task chip, a /compact), the agent's
             text and tool calls, and compaction summaries. Every helper returns
             one JSON line exactly as Claude Code writes it (compact separators).
@input      the text and timestamp of each record
@output     JSONL strings and a written transcript file
@dependencies stdlib: json, pathlib
"""
from __future__ import annotations

import json
import pathlib


def _line(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"))


def user(text: str, ts: str = "2026-10-01T10:00:00.000Z", origin: str | None = "human", **extra) -> str:
    rec = {"type": "user", "message": {"role": "user", "content": text}, "timestamp": ts,
           "origin": {"kind": origin} if origin else None}
    rec.update(extra)
    return _line(rec)


def peer(text: str, sender: str = "COORDINATOR", ts: str = "2026-10-01T10:00:00.000Z") -> str:
    body = (f'Another Claude session sent a message:\n<cross-session-message from="uds:x" '
            f'from-name="{sender}">\n{text}\n</cross-session-message>')
    return _line({"type": "user", "isMeta": True, "message": {"role": "user", "content": body},
                  "timestamp": ts, "origin": {"kind": "peer", "name": sender}})


def queued(text: str, ts: str = "2026-10-01T10:00:00.000Z") -> str:
    return _line({"type": "attachment", "timestamp": ts,
                  "attachment": {"type": "queued_command", "prompt": text}})


def answer(question: str, choice: str, ts: str = "2026-10-01T10:00:00.000Z") -> str:
    text = (f'Your questions have been answered: "{question}"="{choice}". '
            "You can now continue with these answers in mind.")
    return _line({"type": "user", "timestamp": ts,
                  "toolUseResult": {"questions": [question], "answers": {question: choice}},
                  "message": {"role": "user", "content": [
                      {"type": "tool_result", "tool_use_id": "toolu_q", "content": text}]}})


def tool_result(tool_use_id: str, text: str, ts: str = "2026-10-01T10:00:00.000Z") -> str:
    return _line({"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": [{"type": "text", "text": text}]}]}})


def denial(tool_use_id: str, ts: str = "2026-10-01T10:00:00.000Z") -> str:
    return tool_result(tool_use_id, "The user doesn't want to proceed with this tool use. The tool use was "
                                    "rejected. STOP what you are doing and wait for the user to tell you how "
                                    "to proceed.", ts)


def assistant(text: str, ts: str = "2026-10-01T10:00:00.000Z") -> str:
    return _line({"type": "assistant", "timestamp": ts,
                  "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


def tool_use(name: str, inp: dict, tool_id: str = "toolu_1", ts: str = "2026-10-01T10:00:00.000Z") -> str:
    return _line({"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}})


def summary(text: str, ts: str = "2026-10-02T10:00:00.000Z") -> str:
    body = ("This session is being continued from a previous conversation that ran out of context. "
            "The summary below covers the earlier portion of the conversation.\n\nSummary:\n" + text)
    return _line({"type": "user", "isCompactSummary": True, "timestamp": ts,
                  "message": {"role": "user", "content": body}})


def compact_command(args: str = "", ts: str = "2026-10-02T09:59:00.000Z") -> str:
    return user(f"<command-name>/compact</command-name>\n<command-message>compact</command-message>\n"
                f"<command-args>{args}</command-args>", ts, origin=None)


def write(path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
