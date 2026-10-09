"""The provenance check of a fresh compaction summary, end to end."""
import io
import json

import provenance_kit as kit
from conpact import provenance as pv

SUMMARY = """\
1. Primary Request and Intent
   - "deploy it"

   Standing constraints:
   - Push only on explicit request.
   - Commit messages are plain, with no phase prefix.
   - Never print the router key into a transcript.
   - The live API is read-only for Claude: GET only.
   - Use the heavy job gate before long builds.
   - Never use conntrack for traffic figures.
"""


def _setup(tmp_path, extra_lines=()):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("# Rules\n- Pushing to a remote stays explicit-request only.\n",
                                                encoding="utf-8")
    project = tmp_path / "proj"
    (project / "memory").mkdir(parents=True)
    (project / "memory" / "router.md").write_text("Notes.\nNever print the router key into a transcript.\n",
                                                  encoding="utf-8")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / "DECISIONS.md").write_text("- D-8: traffic figures never come from conntrack counters.\n", encoding="utf-8")
    lines = [
        kit.summary("an older summary\n   - The live API is read-only for Claude: GET only.", "2026-09-25T20:00:00Z"),
        kit.user("make commit messages plain, with no phase prefix please", "2026-09-26T10:00:00Z"),
        kit.assistant("I'm allowing read-only calls only.", "2026-09-26T10:01:00Z"),
        kit.tool_use("Write", {"file_path": str(project / "memory" / "router.md"),
                               "content": "Never print the router key into a transcript."}, "t1", "2026-09-26T10:02:00Z"),
        kit.peer("Use the heavy job gate before long builds today.", "COORDINATOR", "2026-09-26T10:03:00Z"),
        *extra_lines,
        kit.summary(SUMMARY, "2026-09-27T10:00:00Z"),
    ]
    transcript = kit.write(project / "s.jsonl", lines)
    return transcript, cwd, home


def _verdicts(report):
    return {f.item: f.verdict for f in report.findings}


def test_each_constraint_gets_the_source_the_check_can_find(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    report = pv.check(transcript, cwd=cwd, home=home)
    v = _verdicts(report)
    assert v["Commit messages are plain, with no phase prefix."] == "user"
    assert v["Push only on explicit request."] == "file"
    assert v["Never print the router key into a transcript."] == "agent-file"
    assert v["Use the heavy job gate before long builds."] == "other"
    assert v["The live API is read-only for Claude: GET only."] == "none"
    assert v["Never use conntrack for traffic figures."] == "file"


def test_a_finding_says_where_its_source_is(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    by_item = {f.item: f for f in pv.check(transcript, cwd=cwd, home=home).findings}
    user = by_item["Commit messages are plain, with no phase prefix."]
    assert user.where.startswith("L2 2026-09-26")
    assert "no phase prefix" in user.quote
    assert by_item["Push only on explicit request."].where.endswith("CLAUDE.md:2")
    assert "written by the agent at L4" in by_item["Never print the router key into a transcript."].where
    assert by_item["Use the heavy job gate before long builds."].where.startswith("COORDINATOR, L5")


def test_an_unsourced_constraint_says_how_long_summaries_have_carried_it(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    by_item = {f.item: f for f in pv.check(transcript, cwd=cwd, home=home).findings}
    assert by_item["The live API is read-only for Claude: GET only."].carried_since == "2026-09-25"
    assert by_item["Push only on explicit request."].carried_since is None


def test_a_file_that_says_the_opposite_is_a_contradiction_not_a_source(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    (transcript.parent / "memory" / "no-get-only.md").write_text(
        "There is no GET-only rule on the live API for Claude.\n", encoding="utf-8")
    by_item = {f.item: f for f in pv.check(transcript, cwd=cwd, home=home).findings}
    f = by_item["The live API is read-only for Claude: GET only."]
    assert f.verdict == "contradicted" and f.where.endswith("no-get-only.md:1")
    assert f.carried_since == "2026-09-25"
    text = pv.render(pv.check(transcript, cwd=cwd, home=home))
    assert text.index("Contradicted") < text.index("Sourced")
    assert "No source found" not in text


def test_the_system_prompt_is_a_source(tmp_path):
    snap = json.dumps({"type": "attachment", "attachment": {"type": "prompt_snapshot",
                       "systemPrompt": ["When pronouns are unknown, use they/them pronouns."]}},
                      separators=(",", ":"))
    t = kit.write(tmp_path / "t.jsonl", [snap, kit.summary("Constraints:\n- Use they/them pronouns.\n")])
    (f,) = pv.check(t, home=tmp_path).findings
    assert (f.verdict, f.where) == ("harness", "the system prompt")


def test_a_rule_counts_as_agent_written_only_if_the_agent_wrote_that_same_file(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    text = transcript.read_text(encoding="utf-8").replace("memory\\\\router.md", "memory\\\\other.md")
    text = text.replace("memory/router.md", "memory/other.md")
    transcript.write_text(text, encoding="utf-8")
    v = _verdicts(pv.check(transcript, cwd=cwd, home=home))
    assert v["Never print the router key into a transcript."] == "file"


def test_extra_sources_are_searched(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    extra = tmp_path / "skill.md"
    extra.write_text("Never use conntrack for traffic figures, ever.\n", encoding="utf-8")
    (cwd / "DECISIONS.md").unlink()
    v = _verdicts(pv.check(transcript, cwd=cwd, home=home, sources=[str(extra)]))
    assert v["Never use conntrack for traffic figures."] == "file"


def test_a_transcript_without_a_summary_has_no_report(tmp_path):
    t = kit.write(tmp_path / "t.jsonl", [kit.user("hi")])
    assert pv.check(t, home=tmp_path) is None


def test_the_report_puts_the_unsourced_first_and_never_calls_them_the_users(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    text = pv.render(pv.check(transcript, cwd=cwd, home=home))
    assert text.index("No source found") < text.index("Sourced")
    assert "The live API is read-only for Claude: GET only." in text
    assert "before it blocks or narrows work" in text
    assert "in summaries since 2026-09-25" in text
    assert "COORDINATOR" in text and "not the user's" in text
    assert "written by the agent at L4" in text


def test_a_long_report_is_cut_with_a_count(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    report = pv.check(transcript, cwd=cwd, home=home)
    many = [pv.Finding(f"Never do thing number {i}.", "none") for i in range(40)]
    report.findings = many
    text = pv.render(report, limit=5)
    assert text.count("Never do thing number") == 5
    assert "and 35 more" in text


def test_a_partial_read_is_said(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    report = pv.check(transcript, cwd=cwd, home=home)
    report.partial = True
    assert "stopped early" in pv.render(report)


def test_the_log_records_counts_and_the_unsourced(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    log = tmp_path / "log.jsonl"
    pv.log(pv.check(transcript, cwd=cwd, home=home), log, session_id="s1", now="2026-09-27T10:01:00Z")
    rec = json.loads(log.read_text(encoding="utf-8"))
    assert rec["session_id"] == "s1" and rec["items"] == 6
    assert rec["verdicts"] == {"user": 1, "file": 2, "harness": 0, "agent-file": 1, "other": 1,
                               "contradicted": 0, "none": 1}
    assert rec["unsourced"] == ["The live API is read-only for Claude: GET only."]


def test_the_hook_entry_reads_its_input_and_prints_the_report(tmp_path, capsys):
    transcript, cwd, home = _setup(tmp_path)
    log = tmp_path / "log.jsonl"
    hook = {"session_id": "abc", "transcript_path": str(transcript), "cwd": str(cwd), "source": "compact"}
    code = pv.main(["--home", str(home), "--log", str(log)], stdin=io.StringIO(json.dumps(hook)))
    assert code == 0
    out = capsys.readouterr().out
    assert "provenance check" in out and "GET only" in out
    assert json.loads(log.read_text(encoding="utf-8"))["session_id"] == "abc"


def test_the_hook_entry_never_fails_the_hook(tmp_path, capsys):
    assert pv.main(["--home", str(tmp_path)], stdin=io.StringIO("not json")) == 0
    hook = {"transcript_path": str(tmp_path / "missing.jsonl")}
    assert pv.main(["--home", str(tmp_path), "--no-log"], stdin=io.StringIO(json.dumps(hook))) == 0
    assert capsys.readouterr().out == ""


def test_the_report_mode_summarises_the_log(tmp_path, capsys):
    log = tmp_path / "log.jsonl"
    recs = [{"at": "2026-10-10T00:00:00Z", "session_id": "a", "items": 10,
             "verdicts": {"user": 2, "file": 5, "agent-file": 1, "other": 0, "none": 2},
             "unsourced": ["Never do X.", "Never do Y."]},
            {"at": "2026-10-12T00:00:00Z", "session_id": "b", "items": 5,
             "verdicts": {"user": 1, "file": 2, "agent-file": 0, "other": 1, "none": 1}, "unsourced": ["Never do X."]},
            {"at": "2026-09-01T00:00:00Z", "session_id": "old", "items": 99, "verdicts": {"none": 99}, "unsourced": []}]
    log.write_text("\n".join(json.dumps(r) for r in recs) + "\nbroken\n", encoding="utf-8")
    assert pv.main(["--report", "--since", "2026-10-01", "--log", str(log)], stdin=io.StringIO("")) == 0
    out = capsys.readouterr().out
    assert "2 compactions" in out and "15 constraints" in out
    assert "no source found: 3 (20%)" in out
    assert "Never do X. (2)" in out


import pytest  # noqa: E402


@pytest.mark.parametrize("name", ["CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/CLAUDE.md"])
def test_each_project_instruction_file_is_a_source(tmp_path, name):
    cwd = tmp_path / "repo"
    (cwd / name).parent.mkdir(parents=True, exist_ok=True)
    (cwd / name).write_text("- Always rebase feature branches before review.\n", encoding="utf-8")
    t = kit.write(tmp_path / "t.jsonl", [kit.summary("Constraints:\n- Always rebase feature branches before review.\n")])
    (f,) = pv.check(t, cwd=cwd, home=tmp_path / "nohome").findings
    assert f.verdict == "file" and f.where == f"{cwd / name}:1"


def test_a_file_the_agent_wrote_through_the_shell_counts_as_its_own(tmp_path):
    project = tmp_path / "proj"
    (project / "memory").mkdir(parents=True)
    (project / "memory" / "notes.md").write_text("Never stop the redis on 16379.\n", encoding="utf-8")
    t = kit.write(project / "t.jsonl", [
        kit.tool_use("Bash", {"command": "echo 'Never stop the redis on 16379.' >> memory/notes.md"}),
        kit.summary("Constraints:\n- Never stop the redis on 16379.\n")])
    (f,) = pv.check(t, home=tmp_path).findings
    assert f.verdict == "agent-file" and f.where.endswith("notes.md:1, written by the agent at L1")


def test_where_names_the_line_the_date_and_the_kind_exactly(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    by_item = {f.item: f for f in pv.check(transcript, cwd=cwd, home=home).findings}
    assert by_item["Commit messages are plain, with no phase prefix."].where == "L2 2026-09-26 (typed)"
    assert by_item["Use the heavy job gate before long builds."].where == "COORDINATOR, L5 2026-09-26"


def test_the_sourced_list_quotes_the_users_words_but_not_a_files(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    text = pv.render(pv.check(transcript, cwd=cwd, home=home))
    sourced = text[text.index("Sourced"):]
    assert '-> L2 2026-09-26 (typed): "make commit messages plain' in sourced
    assert 'CLAUDE.md:2: "' not in sourced and "CLAUDE.md:2" in sourced


def test_the_default_report_lists_fifteen_of_a_group(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    report = pv.check(transcript, cwd=cwd, home=home)
    report.findings = [pv.Finding(f"Never do thing number {i}.", "none") for i in range(16)]
    text = pv.render(report)
    assert text.count("Never do thing number") == 15 and "and 1 more" in text


def test_a_log_record_has_every_field_and_its_folder_is_made(tmp_path):
    transcript, cwd, home = _setup(tmp_path)
    log = tmp_path / "new" / "deeper" / "log.jsonl"
    report = pv.check(transcript, cwd=cwd, home=home)
    pv.log(report, log, session_id="s1")
    pv.log(report, log, session_id="s2")
    recs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["session_id"] for r in recs] == ["s1", "s2"]
    assert set(recs[0]) == {"at", "session_id", "transcript", "summary_line", "summary_ts", "items", "verdicts",
                            "unsourced", "partial"}
    assert recs[0]["transcript"] == str(transcript) and recs[0]["summary_line"] == 6
    assert recs[0]["summary_ts"] == "2026-09-27T10:00:00Z" and recs[0]["partial"] is False
    assert recs[0]["at"][:2] == "20" and "T" in recs[0]["at"]


def test_the_report_mode_counts_every_verdict_and_says_when_it_counts_from(tmp_path, capsys):
    log = tmp_path / "log.jsonl"
    rec = {"at": "2026-10-10T00:00:00Z", "items": 10, "unsourced": [],
           "verdicts": {"user": 1, "file": 2, "harness": 1, "agent-file": 3, "other": 1, "contradicted": 1, "none": 1}}
    log.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert pv.main(["--report", "--log", str(log)], stdin=io.StringIO("")) == 0
    out = capsys.readouterr().out
    assert out.startswith("Provenance checks since the start: 1 compactions, 10 constraints.")
    for part in ("the user's words: 1 (10%)", "a file: 2 (20%)", "the system prompt: 1 (10%)",
                 "a file the agent wrote: 3 (30%)", "another session: 1 (10%)", "contradicted: 1 (10%)",
                 "no source found: 1 (10%)"):
        assert part in out
    assert "Most repeated" not in out
    assert pv.main(["--report", "--log", str(tmp_path / "none.jsonl")], stdin=io.StringIO("")) == 0
    assert "0 compactions, 0 constraints" in capsys.readouterr().out


def test_unreadable_hook_input_is_said_on_stderr(tmp_path, capsys):
    assert pv.main(["--home", str(tmp_path)], stdin=io.StringIO("{not json")) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "unreadable hook input" in captured.err


def test_the_hook_entry_searches_the_project_named_in_its_input(tmp_path, capsys):
    transcript, cwd, home = _setup(tmp_path)
    hook = {"transcript_path": str(transcript), "cwd": str(cwd)}
    pv.main(["--home", str(home), "--no-log"], stdin=io.StringIO(json.dumps(hook)))
    out = capsys.readouterr().out
    assert "DECISIONS.md:1" in out
