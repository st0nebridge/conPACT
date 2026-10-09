"""
@module conpact.provenance
@description The provenance check of a compaction summary. Claude Code's summary
             lists constraints with no source, and the next summary copies the
             list forward, so a precaution the agent chose for itself comes to
             read like a rule the user set. Run as a SessionStart hook with the
             matcher "compact", this reads the summary just written, finds its
             constraints, and says for each where it can be traced: the user's own
             words (a transcript line), an instruction file (path:line), a file
             the agent itself wrote in this session, another session's message,
             or nothing. What it prints is added to the resumed session's context,
             unsourced constraints first, worded as "find the user's words before
             it blocks or narrows work" - never as "not binding", because the
             check misses paraphrase (calibrated against 916 hand-traced
             constraints, D-20261009-091). Every check is logged to
             ~/.conpact/provenance-log.jsonl, and --report summarises that log.
             It never fails the hook: errors go to stderr and it exits 0.
@input      hook JSON on stdin (transcript_path, cwd, session_id) or --transcript;
            optional extra source files (--source), a deadline, --report
@output     the report text on stdout; one JSON line per check in the log
@dependencies conpact.home, conpact.provenance_items, conpact.provenance_match,
              conpact.provenance_transcript; stdlib: argparse, collections,
              dataclasses, datetime, glob, json, os, pathlib, sys
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import glob
import json
import os
import pathlib
import sys

from . import home as conpact_home
from . import provenance_items, provenance_match, provenance_transcript

LOG_PATH = conpact_home.HOME / "provenance-log.jsonl"
VERDICTS = ("user", "file", "harness", "agent-file", "other", "contradicted", "none")
SOURCED = ("user", "file", "harness")
PROJECT_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "DECISIONS.md", os.path.join(".claude", "CLAUDE.md"))
CARRIED = 0.8          # share of an item's words an older summary must hold to count as carrying it
DEADLINE = 20.0        # seconds of reading before the check reports what it has


@dataclasses.dataclass
class Finding:
    item: str
    verdict: str
    where: str = ""
    quote: str = ""
    carried_since: str | None = None


@dataclasses.dataclass
class Report:
    transcript: str
    summary_line: int
    summary_ts: str
    findings: list
    partial: bool = False


def _file_sources(paths) -> list:
    out = []
    for path in paths:
        try:
            lines = pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        out += [provenance_match.Source("file", f"{path}:{n}", text) for n, text in enumerate(lines, 1) if text.strip()]
    return out


def rule_files(transcript, cwd=None, home=None, sources=()) -> list:
    """Every instruction file the check searches."""
    home = pathlib.Path(home) if home else pathlib.Path.home()
    paths = [home / ".claude" / "CLAUDE.md"]
    if cwd:
        paths += [pathlib.Path(cwd) / name for name in PROJECT_FILES]
    paths += sorted(pathlib.Path(transcript).parent.glob("memory/*.md"))
    for pattern in sources:
        paths += sorted(glob.glob(os.path.expanduser(pattern)))
    return paths


def _carried_since(item: str, older) -> str | None:
    want = provenance_match.tokens(item)
    for summary, have in older:
        if want and provenance_match.containment(want, have) >= CARRIED:
            return summary.ts[:10]
    return None


def _same_file(a: str, b: str) -> bool:
    def norm(p):
        return os.path.normcase(os.path.normpath(os.path.expanduser(p)))
    return norm(a) == norm(b)


def _judge(item, user, files, writes, others, older) -> Finding:
    """Where one constraint can be traced, in order: the user's words, an
    instruction file or the system prompt (unless the agent wrote that file entry
    itself this session), another session's message - or nowhere."""
    match = provenance_match.best(item, user) or provenance_match.best(item, files)
    if match is None:
        match = provenance_match.best(item, others)
    if match is None:
        return Finding(item, "none", carried_since=_carried_since(item, older))
    if provenance_match.opposes(item, match.quote):
        return Finding(item, "contradicted", match.source.ref, match.quote, _carried_since(item, older))
    verdict, where = match.source.kind, match.source.ref
    if verdict == "file":
        path = where.rsplit(":", 1)[0]
        mine = [w for w in writes if (_same_file(w.note, path) if w.note else os.path.basename(path) in w.text)]
        wrote = provenance_match.best(item, mine)
        if wrote is not None:
            verdict, where = "agent-file", f"{where}, written by the agent at {wrote.source.ref}"
    return Finding(item, verdict, where, match.quote)


def check(transcript, cwd=None, home=None, sources=(), deadline=None, upto=None) -> Report | None:
    """The provenance of every constraint in the transcript's latest summary."""
    t = provenance_transcript.read(transcript, deadline=deadline, upto=upto)
    if t.latest is None:
        return None
    Source = provenance_match.Source
    user = [Source("user", f"L{w.line} {w.ts[:10]} ({w.kind})", w.text) for w in t.user_words]
    files = _file_sources(rule_files(transcript, cwd, home, sources))
    if t.harness:
        files.append(Source("harness", "the system prompt", t.harness))
    writes = [Source("agent-file", f"L{w.line}", w.text, note=w.path) for w in t.agent_writes]
    others = [Source("other", f"{o.sender}, L{o.line} {o.ts[:10]}", o.text) for o in t.others]
    older = [(s, provenance_match.tokens(s.text)) for s in t.summaries[:-1]]
    findings = [_judge(item, user, files, writes, others, older)
                for item in provenance_items.extract(t.latest.text)]
    return Report(str(transcript), t.latest.line, t.latest.ts, findings, t.partial)


def _group(lines, title, findings, limit, show):
    if not findings:
        return
    lines.append(title)
    for f in findings[:limit]:
        lines.append(show(f))
    if len(findings) > limit:
        lines.append(f"  ... and {len(findings) - limit} more")


def render(report: Report, limit: int = 15) -> str:
    """The text added to the resumed session's context."""
    by = collections.defaultdict(list)
    for f in report.findings:
        by[f.verdict].append(f)
    n = len(report.findings)
    lines = [f"conPACT provenance check of the summary just written ({n} constraints). The summary was "
             "written by the agent, not the user; a constraint binds only with a source."]
    if report.partial:
        lines.append("The transcript was too long to read in time: the check stopped early, so more constraints "
                     "may have a source than it shows.")

    def since(f):
        return f" (in summaries since {f.carried_since})" if f.carried_since else ""

    _group(lines, f"Contradicted ({len(by['contradicted'])}): the closest source seems to say the opposite; read "
                  "it before following the summary.", by["contradicted"], limit,
           lambda f: f'  - "{f.item}"{since(f)} -> {f.where}: "{f.quote[:160]}"')
    _group(lines, f"No source found ({len(by['none'])}): before it blocks or narrows work, find the user's words "
                  f"for it in the transcript ({report.transcript}); if they are not there, it is the agent's own "
                  "working choice, not the user's rule.", by["none"], limit, lambda f: f'  - "{f.item}"{since(f)}')
    _group(lines, f"In a file the agent wrote itself in this session ({len(by['agent-file'])}): check it reflects "
                  "the user's words before relying on it.", by["agent-file"], limit,
           lambda f: f'  - "{f.item}" -> {f.where}')
    _group(lines, f"From another session or agent, not the user's ({len(by['other'])}): it holds only for the "
                  "window it was given.", by["other"], limit, lambda f: f'  - "{f.item}" -> {f.where}')
    sourced = [f for v in SOURCED for f in by[v]]
    _group(lines, f"Sourced ({len(sourced)}):", sourced, limit,
           lambda f: f'  - "{f.item}" -> {f.where}' + (f': "{f.quote[:120]}"' if f.verdict == "user" else ""))
    return "\n".join(lines) + "\n"


def log(report: Report, path=LOG_PATH, session_id: str | None = None, now: str | None = None) -> None:
    """Append one JSON line describing the check."""
    counts = collections.Counter(f.verdict for f in report.findings)
    rec = {"at": now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "session_id": session_id, "transcript": report.transcript, "summary_line": report.summary_line,
           "summary_ts": report.summary_ts, "items": len(report.findings),
           "verdicts": {v: counts.get(v, 0) for v in VERDICTS},
           "unsourced": [f.item for f in report.findings if f.verdict == "none"], "partial": report.partial}
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def summarise(path, since: str = "") -> str:
    """What the logged checks since a date add up to."""
    recs = []
    try:
        for raw in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict) and str(rec.get("at", "")) >= since:
                recs.append(rec)
    except OSError:
        pass
    items = sum(int(r.get("items") or 0) for r in recs)
    totals = collections.Counter()
    for r in recs:
        totals.update({k: int(v) for k, v in (r.get("verdicts") or {}).items()})
    repeated = collections.Counter(u for r in recs for u in r.get("unsourced") or [])

    def pct(k):
        return f"{totals[k]} ({round(100 * totals[k] / items) if items else 0}%)"

    lines = [f"Provenance checks since {since or 'the start'}: {len(recs)} compactions, {items} constraints.",
             f"  the user's words: {pct('user')}; a file: {pct('file')}; the system prompt: {pct('harness')}; "
             f"a file the agent wrote: {pct('agent-file')}; another session: {pct('other')}; contradicted: "
             f"{pct('contradicted')}; no source found: {pct('none')}"]
    if repeated:
        lines.append("  Most repeated constraints with no source found:")
        lines += [f"    {text} ({count})" for text, count in repeated.most_common(15)]
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Trace each constraint in a compaction summary to its source.")
    ap.add_argument("--transcript", help="transcript to check (default: transcript_path from the hook input)")
    ap.add_argument("--cwd", help="project folder (default: cwd from the hook input)")
    ap.add_argument("--home", help="the user's home folder, for ~/.claude/CLAUDE.md (default: this user's)")
    ap.add_argument("--source", action="append", default=[], metavar="GLOB",
                    help="another instruction file to search, e.g. a skill's files (repeatable)")
    ap.add_argument("--upto", type=int, help="check the summary at or before this transcript line")
    ap.add_argument("--deadline", type=float, default=DEADLINE, help="seconds of reading before reporting")
    ap.add_argument("--log", default=str(LOG_PATH), help="where checks are logged")
    ap.add_argument("--no-log", action="store_true", help="do not log this check")
    ap.add_argument("--report", action="store_true", help="summarise the logged checks instead")
    ap.add_argument("--since", default="", help="with --report: only checks on or after this date (YYYY-MM-DD)")
    return ap


def main(argv=None, stdin=None) -> int:
    args = _parser().parse_args(argv)
    # A hook's stdout is a pipe, which Windows Python would encode as cp1252;
    # one dash from a summary would then lose the whole report.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.report:
        sys.stdout.write(summarise(args.log, args.since))
        return 0
    try:
        raw = (stdin or sys.stdin).read()
        hook = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"conPACT provenance check: unreadable hook input ({type(exc).__name__})\n")
        hook = {}
    if not isinstance(hook, dict):
        hook = {}
    transcript = args.transcript or hook.get("transcript_path")
    if not transcript:
        return 0
    try:
        report = check(transcript, cwd=args.cwd or hook.get("cwd"), home=args.home, sources=args.source,
                       deadline=args.deadline, upto=args.upto)
        if report is None:
            return 0
        sys.stdout.write(render(report))
        if not args.no_log:
            log(report, args.log, session_id=hook.get("session_id"))
    except Exception as exc:  # a hook must never fail the session it serves
        sys.stderr.write(f"conPACT provenance check: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
