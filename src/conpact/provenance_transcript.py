"""
@module conpact.provenance_transcript
@description Reads a Claude Code transcript for the provenance check and sorts
             what it holds by whose words they are. The user's own words are
             what they typed, what they queued while the agent worked, their
             AskUserQuestion answers and their permission denials. Text that only
             looks like a user message is kept apart, with its sender: another
             session's message, a subagent's or background task's report, a
             task-chip notice, the app's own notices, and a /compact - whose
             instructions the agent writes. The agent's own writes to rule files
             (CLAUDE.md, AGENTS.md, DECISIONS.md, memory, skills) are recorded so
             a rule the agent filed itself can be told from one the user set.
             Every compaction summary is kept; only words before the latest one
             count. Lines are filtered as text before any is parsed, so a
             transcript of hundreds of megabytes is read in seconds, and an
             optional deadline stops the read and marks the result partial.
@input      a transcript path; optionally a deadline in seconds and a clock, and
            the line to stop at (to check an earlier summary)
@output     a Transcript: summaries, the latest one, user_words, others,
            agent_writes, partial
@dependencies stdlib: dataclasses, json, re, time
"""
from __future__ import annotations

import dataclasses
import json
import re
import time

# User-role records that are not anyone's message at all.
SKIP_PREFIXES = ("<task-notification>", "<local-command-stdout>", "<local-command-caveat>",
                 "<local-command-stderr>", "[Request interrupted by user")
# User-role records written by someone other than the user, and who that is.
OTHER_SENDERS = (
    ("Another Claude session sent a message", None),
    ("<cross-session-message", None),
    ("<teammate-message", None),
    ("<agent-message", "a subagent"),
    ("<task-notification>", "a background task"),
    ("<command-name>/compact", "the /compact instructions"),
    ("The app was quit while you were working", "the app"),
    ("<system-reminder>", "a task-chip notice"),
)
# How a tool result that carries the user's own answer or refusal begins.
ANSWER_STARTS = ("Your questions have been answered", "User has answered your questions",
                 "The user answered", "The user did not answer")
DENIAL_START = "The user doesn't want to"
# Cheap text tests that decide whether a line is worth parsing at all.
_ANSWER_HINTS = tuple(s[:24] for s in ANSWER_STARTS) + ("doesn't want to", '"answers":')
RULE_FILE = re.compile(r"(CLAUDE(\.local)?\.md|AGENTS\.md|DECISIONS\.md|(^|[\\/\s'\"=])memory[\\/]|MEMORY\.md"
                       r"|SKILL\.md)", re.IGNORECASE)
_CHIP = re.compile(r"^(\s*<system-reminder>.*?</system-reminder>)+", re.DOTALL)
_SENDER = re.compile(r'from-name="([^"]+)"')


@dataclasses.dataclass(frozen=True)
class Summary:
    line: int
    ts: str
    text: str


@dataclasses.dataclass(frozen=True)
class Words:
    line: int
    ts: str
    kind: str          # typed | queued | answer | denial
    text: str


@dataclasses.dataclass(frozen=True)
class Other:
    line: int
    ts: str
    sender: str
    text: str


@dataclasses.dataclass(frozen=True)
class AgentWrite:
    line: int
    ts: str
    path: str
    text: str


@dataclasses.dataclass
class Transcript:
    summaries: list
    user_words: list
    others: list
    agent_writes: list
    partial: bool = False
    harness: str = ""      # the system prompt as last recorded before the latest summary

    @property
    def latest(self):
        return self.summaries[-1] if self.summaries else None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _result_text(block: dict) -> str:
    c = block.get("content")
    return c if isinstance(c, str) else _text(c)


def sender_of(text: str, origin: dict | None = None) -> str | None:
    """Who wrote a user-role text that is not the user's, or None if it is theirs."""
    stripped = text.lstrip()
    for prefix, name in OTHER_SENDERS:
        if stripped.startswith(prefix):
            if name is None:
                m = _SENDER.search(text)
                return m.group(1) if m else ((origin or {}).get("name") or "another session")
            return name
    return None


class _Reader:
    def __init__(self):
        self.summaries, self.words, self.others, self.writes, self.harness = [], [], [], [], []
        self.seen = set()
        self.calls = {}

    def _keep(self, line, ts, text, origin=None, kind="typed"):
        rest = _CHIP.sub("", text, count=1) if text.lstrip().startswith("<system-reminder>") else text
        if rest is not text and rest.strip():
            text = rest.strip()
        head = text.lstrip()
        if not head:
            return
        if head.startswith("<task-notification>"):
            if "<result>" not in head:
                return
        elif head.startswith(SKIP_PREFIXES):
            return
        # The first time a text appears is where it was said; a queued message
        # and its later copy, or a replay after a resume, add nothing.
        if text in self.seen:
            return
        self.seen.add(text)
        who = sender_of(text, origin)
        if who:
            self.others.append(Other(line, ts, who, text))
        else:
            self.words.append(Words(line, ts, kind, text))

    def _once(self, words):
        """Keep an answer or denial the first time it appears (a resume replays them)."""
        if (words.kind, words.text) not in self.seen:
            self.seen.add((words.kind, words.text))
            self.words.append(words)

    def user(self, line, rec):
        ts = rec.get("timestamp") or ""
        msg = rec.get("message") or {}
        content = msg.get("content")
        origin = rec.get("origin") if isinstance(rec.get("origin"), dict) else None
        if rec.get("isCompactSummary"):
            self.summaries.append(Summary(line, ts, _text(content)))
            return
        if rec.get("isMeta"):
            if (origin or {}).get("kind") == "peer":
                self._keep(line, ts, _text(content), origin)
            return
        if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            answered = isinstance(rec.get("toolUseResult"), dict) and "answers" in rec["toolUseResult"]
            for b in content:
                if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                    continue
                text = _result_text(b).strip()
                if text.startswith(DENIAL_START):
                    call = self.calls.get(b.get("tool_use_id"), "an unrecorded call")
                    self._once(Words(line, ts, "denial", f"[refused: {call}] {text}"))
                elif answered or text.startswith(ANSWER_STARTS):
                    self._once(Words(line, ts, "answer", text))
            return
        if (origin or {}).get("kind") == "task-notification":
            return
        self._keep(line, ts, _text(content), origin)

    def attachment(self, line, rec):
        att = rec.get("attachment") or {}
        if att.get("type") == "queued_command":
            self.queued(line, rec)
        elif att.get("type") == "prompt_snapshot":
            prompt = att.get("systemPrompt")
            text = "\n".join(p if isinstance(p, str) else json.dumps(p) for p in prompt) \
                if isinstance(prompt, list) else str(prompt or "")
            self.harness.append((line, text))

    def queued(self, line, rec):
        prompt = (rec.get("attachment") or {}).get("prompt")
        text = prompt if isinstance(prompt, str) else _text(prompt)
        if text.lstrip().startswith("<task-notification>") and "<result>" not in text:
            return
        self._keep(line, rec.get("timestamp") or "", text, kind="queued")

    def assistant(self, line, rec):
        for b in (rec.get("message") or {}).get("content") or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            name, inp = b.get("name") or "", b.get("input") or {}
            self.calls[b.get("id")] = f"{name} {json.dumps(inp, ensure_ascii=False)[:300]}"
            path = str(inp.get("file_path") or inp.get("notebook_path") or "")
            if name == "Bash":
                cmd = str(inp.get("command") or "")
                if RULE_FILE.search(cmd) and re.search(r">>?|\btee\b|cat\s*>", cmd):
                    self.writes.append(AgentWrite(line, rec.get("timestamp") or "", "", cmd))
            elif path and RULE_FILE.search(path):
                text = inp.get("content") or inp.get("new_string") or ""
                if not text and isinstance(inp.get("edits"), list):
                    text = "\n".join(e.get("new_string") or "" for e in inp["edits"] if isinstance(e, dict))
                if text:
                    self.writes.append(AgentWrite(line, rec.get("timestamp") or "", path, str(text)))


def _wanted(raw: str) -> str | None:
    """Which reader a raw line goes to, judged from its text alone."""
    if '"type":"assistant"' in raw:
        return "assistant" if '"tool_use"' in raw else None
    if '"queued_command"' in raw or '"prompt_snapshot"' in raw:
        return "attachment"
    if '"type":"user"' not in raw:
        return None
    if '"tool_result"' in raw and '"isCompactSummary"' not in raw:
        return "user" if any(h in raw for h in _ANSWER_HINTS) else None
    return "user"


def read(path, deadline: float | None = None, clock=time.monotonic, upto: int | None = None) -> Transcript:
    """Read a transcript; words after its latest summary are dropped. With
    `upto`, reading stops after that line, so an earlier summary can be checked."""
    r = _Reader()
    partial = False
    start = clock()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            if upto is not None and line_no > upto:
                break
            if deadline is not None and clock() - start > deadline:
                partial = True
                break
            kind = _wanted(raw)
            if kind is None:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            getattr(r, kind)(line_no, rec)
    t = Transcript(r.summaries, r.words, r.others, r.writes, partial)
    cut = t.latest.line if t.latest else None
    if cut:
        t.user_words = [w for w in t.user_words if w.line < cut]
        t.others = [o for o in t.others if o.line < cut]
        t.agent_writes = [w for w in t.agent_writes if w.line < cut]
    prompts = [text for line, text in r.harness if cut is None or line < cut]
    t.harness = prompts[-1] if prompts else ""
    return t
