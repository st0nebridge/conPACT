"""Regression test for CU-20261009-113 (D-20261009-091).

On 2026-09-24 an agent chose, for itself, to let a screenshot harness send only
read-only requests to a live API ("allowing read-only calls only"). A summary
on 2026-09-25 listed "The live API is read-only for Claude (GET only)" among its
standing constraints, every later summary copied it, and on 2026-10-09 the agent
refused a diagnostic request and told the user it was their rule. The user had
never said it. The post-compaction provenance check must report such a
constraint as having no source - with how long summaries have carried it and
the instruction to find the user's words before it blocks work - while a
constraint the user did state is traced to their message.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

import provenance_kit as kit
from conpact import provenance as pv

ROOT = Path(__file__).resolve().parents[2]


def _transcript(tmp_path):
    return kit.write(tmp_path / "session.jsonl", [
        kit.user("go add screenshots to the app", "2026-09-24T00:23:00Z"),
        kit.assistant("I'm mapping the window's calls onto your app's API, allowing read-only calls only.",
                      "2026-09-24T00:29:00Z"),
        kit.user("in both repos remove the phase prefix from commit messages", "2026-09-24T01:00:00Z"),
        kit.summary("Constraints:\n- Screenshots use only read-only API routes.\n", "2026-09-24T04:34:00Z"),
        kit.summary("Standing constraints:\n- The live API is read-only for Claude (GET only).\n"
                    "- Commit messages carry no phase prefix in both repos.\n", "2026-09-25T20:28:00Z"),
        kit.user("current stream has no audio", "2026-10-09T08:38:00Z"),
        kit.summary("Standing constraints (still binding, carried from earlier):\n"
                    "- The live API is read-only for Claude (GET only).\n"
                    "- Commit messages carry no phase prefix in both repos.\n", "2026-10-09T08:40:00Z"),
    ])


def test_the_self_chosen_get_only_rule_is_reported_without_a_source(tmp_path):
    report = pv.check(_transcript(tmp_path), home=tmp_path)
    by_item = {f.item: f for f in report.findings}
    get_only = by_item["The live API is read-only for Claude (GET only)."]
    assert get_only.verdict == "none"
    assert get_only.carried_since == "2026-09-25"
    users = by_item["Commit messages carry no phase prefix in both repos."]
    assert users.verdict == "user" and users.where.startswith("L3 2026-09-24")
    text = pv.render(report)
    assert "No source found (1)" in text and "before it blocks or narrows work" in text


def test_the_hook_entry_in_tools_prints_the_check(tmp_path):
    hook = json.dumps({"transcript_path": str(_transcript(tmp_path)), "session_id": "anchor"})
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "compact_provenance.py"), "--home", str(tmp_path),
                           "--no-log"], input=hook, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0
    assert "GET only" in done.stdout and "No source found" in done.stdout
