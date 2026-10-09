"""Regression test for CU-20261009-114 (D-20261009-090).

A compaction summary lists constraints with no source and reads the /compact
line as a user message. An audit of 55 summaries (2026-10-09) found 229 of 916
listed constraints with no source in the user's words or a file, and six
summaries that presented the agent's own focus text as something the user said.
Every compaction conPACT starts - the bridge's /compact, the mod's in-process
compaction, the mod's /compact in an SDK session and the idle toast's - must
therefore carry the same fixed provenance clause after the agent's focus, outside
the focus's own 500-character limit.
"""
import re
from pathlib import Path

from conpact import compaction

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "src" / "mod" / "hooks"


def test_the_bridges_compact_carries_the_clause_after_the_focus():
    record = {"bridgeSessionId": "b", "name": "n", "pid": 1, "sessionId": "s"}
    with_focus = compaction.compact_record(record, focus="keep the plan", dry_run=True)["text"]
    assert with_focus == "/compact keep the plan " + compaction.PROVENANCE_CLAUSE
    bare = compaction.compact_record(record, dry_run=True)["text"]
    assert bare == "/compact " + compaction.PROVENANCE_CLAUSE


def test_the_mod_carries_the_very_same_clause():
    rules = (HOOKS / "rules.js").read_text(encoding="utf-8")
    m = re.search(r"export const PROVENANCE_CLAUSE = `([^`]*)`", rules)
    assert m, "rules.js no longer defines PROVENANCE_CLAUSE as a template literal"
    assert m.group(1) == compaction.PROVENANCE_CLAUSE


def test_every_mod_compaction_is_built_with_the_clause():
    run = (HOOKS / "run.js").read_text(encoding="utf-8")
    handoff = (HOOKS / "handoff.js").read_text(encoding="utf-8")
    assert "session.compact({ instructions: compactInstructions(request.focus) })" in run
    assert "session.compact({ instructions: compactInstructions('') })" in handoff
    for source in (run, handoff):
        assert "session.compact({})" not in source
        assert "instructions: request.focus" not in source


def test_the_agent_is_told_to_write_its_focus_as_facts_not_as_the_users_decisions():
    from conpact import mcp_server, mcp_tools
    queue = next(t for t in mcp_tools.TOOLS if t["name"] == "queue_compaction")
    for text in (mcp_server.INSTRUCTIONS, queue["description"], queue["inputSchema"]["properties"]["focus"]["description"]):
        assert "as facts" in text or "of facts" in text
        assert "user's" in text
    assert "unless you quote the user" in queue["description"]
