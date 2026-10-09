"""Reading a transcript for the provenance check: whose words are whose."""
import json

import provenance_kit as kit
from conpact import provenance_transcript as pt


def _read(tmp_path, lines, **kw):
    return pt.read(kit.write(tmp_path / "t.jsonl", lines), **kw)


def test_the_latest_summary_is_the_last_one_in_the_file(tmp_path):
    t = _read(tmp_path, [kit.summary("first", "2026-10-01T00:00:00Z"), kit.user("hi"),
                         kit.summary("second", "2026-10-02T00:00:00Z")])
    assert t.latest.line == 3
    assert t.latest.text.endswith("second")
    assert [s.line for s in t.summaries] == [1, 3]


def test_typed_and_queued_messages_are_the_users(tmp_path):
    t = _read(tmp_path, [kit.user("use scp -O for the router"), kit.queued("also keep the logs"),
                         kit.summary("s")])
    assert [(w.kind, w.text) for w in t.user_words] == [("typed", "use scp -O for the router"),
                                                       ("queued", "also keep the logs")]
    assert [w.line for w in t.user_words] == [1, 2]


def test_only_words_before_the_latest_summary_count(tmp_path):
    t = _read(tmp_path, [kit.user("before"), kit.summary("s"), kit.user("after")])
    assert [w.text for w in t.user_words] == ["before"]


def test_an_answer_keeps_the_question_and_the_users_choice(tmp_path):
    t = _read(tmp_path, [kit.answer("How should I commit?", "Split out my hunks only"), kit.summary("s")])
    (w,) = t.user_words
    assert w.kind == "answer"
    assert "Split out my hunks only" in w.text and "How should I commit?" in w.text


def test_a_denial_names_the_call_that_was_refused(tmp_path):
    t = _read(tmp_path, [kit.tool_use("Bash", {"command": "rm -rf build"}, "toolu_9"),
                         kit.denial("toolu_9"), kit.summary("s")])
    (w,) = t.user_words
    assert w.kind == "denial"
    assert "rm -rf build" in w.text


def test_an_answer_replayed_after_a_resume_counts_once(tmp_path):
    t = _read(tmp_path, [kit.answer("Deploy now?", "Now"), kit.assistant("ok"), kit.answer("Deploy now?", "Now"),
                         kit.summary("s")])
    assert [w.line for w in t.user_words] == [1]


def test_an_ordinary_tool_result_is_nobodys_words(tmp_path):
    t = _read(tmp_path, [kit.tool_result("toolu_1", "the user said: never do that (a file's text)"),
                         kit.summary("s")])
    assert t.user_words == []


def test_messages_that_only_look_like_the_users_are_kept_apart(tmp_path):
    t = _read(tmp_path, [
        kit.peer("DIRECTIVE from the user, relayed: targeted tests only", "COORDINATOR"),
        kit.user('<cross-session-message from="x" from-name="Peer">do not touch it</cross-session-message>'),
        kit.queued("<agent-message from=\"a1\">[Subagent hand-back] gen-audio is paid</agent-message>"),
        kit.compact_command("Release done; must never get prompt_on_launch in config"),
        kit.user("The app was quit while you were working. Please continue."),
        kit.summary("s")])
    assert t.user_words == []
    senders = [o.sender for o in t.others]
    assert senders[:2] == ["COORDINATOR", "Peer"]
    assert "a subagent" in senders and "the /compact instructions" in senders


def test_a_task_chip_notice_does_not_hide_what_the_user_typed_after_it(tmp_path):
    chip = ("<system-reminder>\nThe user started your suggested background task task_1 (\"X\").\n"
            "</system-reminder>\n\nmake sure it goes to the admin address")
    t = _read(tmp_path, [kit.user(chip), kit.queued(chip), kit.summary("s")])
    assert [w.text for w in t.user_words] == ["make sure it goes to the admin address"]


def test_a_chip_notice_with_nothing_after_it_is_not_the_users(tmp_path):
    t = _read(tmp_path, [kit.user("<system-reminder>started task_1</system-reminder>"), kit.summary("s")])
    assert t.user_words == []


def test_a_message_replayed_later_with_the_same_stamp_counts_once_at_its_first_line(tmp_path):
    t = _read(tmp_path, [kit.user("keep it short", "2026-10-01T01:00:00Z"), kit.assistant("ok"),
                         kit.user("keep it short", "2026-10-01T01:00:00Z"), kit.summary("s")])
    assert [w.line for w in t.user_words] == [1]


def test_skipped_records_are_skipped(tmp_path):
    t = _read(tmp_path, [kit.user("<task-notification><task-id>b1</task-id></task-notification>"),
                         kit.user("<local-command-stdout>Compacted</local-command-stdout>"),
                         kit.user("   "), kit.summary("s")])
    assert t.user_words == [] and t.others == []


def test_the_agents_writes_to_rule_files_are_recorded(tmp_path):
    t = _read(tmp_path, [
        kit.tool_use("Write", {"file_path": "C:\\p\\memory\\router.md", "content": "never print the key"}),
        kit.tool_use("Edit", {"file_path": "/p/CLAUDE.md", "old_string": "a", "new_string": "Bump first."}),
        kit.tool_use("Bash", {"command": "echo '- rule' >> ~/.claude/projects/x/memory/MEMORY.md"}),
        kit.tool_use("Write", {"file_path": "/p/src/app.py", "content": "never mind"}),
        kit.summary("s")])
    assert [(w.line, w.text) for w in t.agent_writes] == [
        (1, "never print the key"), (2, "Bump first."),
        (3, "echo '- rule' >> ~/.claude/projects/x/memory/MEMORY.md")]
    assert t.agent_writes[0].path.endswith("router.md")


def test_the_system_prompt_last_recorded_before_the_summary_is_kept(tmp_path):
    def snap(text):
        return json.dumps({"type": "attachment", "attachment": {"type": "prompt_snapshot", "systemPrompt": [text]}},
                          separators=(",", ":"))
    t = _read(tmp_path, [snap("old prompt"), snap("use they/them"), kit.summary("s"), snap("later")])
    assert t.harness == "use they/them"


def test_a_broken_line_is_ignored(tmp_path):
    t = _read(tmp_path, ['{"type":"user", broken', kit.user("fine"), kit.summary("s")])
    assert [w.text for w in t.user_words] == ["fine"]


def test_a_transcript_without_a_summary_has_no_latest(tmp_path):
    t = _read(tmp_path, [kit.user("hello")])
    assert t.latest is None
    assert [w.text for w in t.user_words] == ["hello"]


def test_an_earlier_summary_can_be_checked_by_stopping_at_its_line(tmp_path):
    t = _read(tmp_path, [kit.user("a"), kit.summary("first"), kit.user("b"), kit.summary("second")], upto=2)
    assert t.latest.line == 2 and [w.text for w in t.user_words] == ["a"]


def test_reading_stops_at_the_deadline_and_says_so(tmp_path):
    lines = [kit.user(f"m{i}") for i in range(50)] + [kit.summary("s")]
    clock = iter(range(1000)).__next__
    t = _read(tmp_path, lines, deadline=5, clock=clock)
    assert t.partial is True
    assert len(t.user_words) < 50


def test_content_given_as_text_blocks_is_read(tmp_path):
    rec = {"type": "user", "timestamp": "2026-10-01T00:00:00Z",
           "message": {"role": "user", "content": [{"type": "text", "text": "as blocks"}]}}
    t = _read(tmp_path, [json.dumps(rec, separators=(",", ":")), kit.summary("s")])
    assert [w.text for w in t.user_words] == ["as blocks"]


def test_every_kind_of_record_that_is_nobodys_words_is_skipped(tmp_path):
    t = _read(tmp_path, [
        kit.user("<local-command-caveat>Caveat: run directly</local-command-caveat>"),
        kit.user("<local-command-stderr>oops</local-command-stderr>"),
        kit.user("[Request interrupted by user for tool use]"),
        kit.queued("<task-notification><task-id>b1</task-id></task-notification>"),
        kit.user("an ordinary meta note", isMeta=True),
        kit.user("from a background task", origin="task-notification"),
        kit.summary("s")])
    assert t.user_words == [] and t.others == []


def test_each_look_alike_is_named_for_its_sender(tmp_path):
    t = _read(tmp_path, [
        kit.user('<teammate-message from-name="Reviewer">look at this</teammate-message>'),
        kit.user("<teammate-message>no name given</teammate-message>"),
        kit.user("<task-notification><result>the subagent says: never X</result></task-notification>"),
        kit.queued("<task-notification><result>done</result></task-notification>"),
        kit.user("The app was quit while you were working. Please continue."),
        kit.user("<system-reminder>The user started your suggested background task task_1.</system-reminder>"),
        kit.summary("s")])
    assert [o.sender for o in t.others] == ["Reviewer", "another session", "a background task",
                                           "a background task", "the app", "a task-chip notice"]
    assert t.user_words == []


def test_a_peer_without_a_name_in_its_text_is_named_by_its_origin(tmp_path):
    rec = json.dumps({"type": "user", "isMeta": True, "timestamp": "2026-10-01T00:00:00Z",
                      "message": {"role": "user", "content": "<cross-session-message>hi</cross-session-message>"},
                      "origin": {"kind": "peer", "name": "Coordinator"}}, separators=(",", ":"))
    t = _read(tmp_path, [rec, kit.summary("s")])
    assert [o.sender for o in t.others] == ["Coordinator"]


def test_every_way_an_answer_is_worded_counts_as_the_users(tmp_path):
    t = _read(tmp_path, [
        kit.tool_result("q1", 'User has answered your questions: "A?"="yes".'),
        kit.tool_result("q2", 'The user answered: "B?"="no".'),
        kit.tool_result("q3", "The user did not answer the questions."),
        kit.summary("s")])
    assert [w.kind for w in t.user_words] == ["answer"] * 3


def test_an_answer_record_counts_even_when_its_text_is_worded_otherwise(tmp_path):
    rec = json.dumps({"type": "user", "timestamp": "2026-10-01T00:00:00Z",
                      "toolUseResult": {"questions": ["Q"], "answers": {"Q": "A"}},
                      "message": {"role": "user", "content": [
                          {"type": "tool_result", "tool_use_id": "q", "content": "Q = A"}]}},
                     separators=(",", ":"))
    t = _read(tmp_path, [rec, kit.summary("s")])
    assert [(w.kind, w.text) for w in t.user_words] == [("answer", "Q = A")]


def test_a_denial_of_an_unrecorded_call_says_so(tmp_path):
    t = _read(tmp_path, [kit.denial("toolu_unknown"), kit.summary("s")])
    assert t.user_words[0].text.startswith("[refused: an unrecorded call] The user doesn't want to")


def test_writes_by_multiedit_notebook_and_tee_are_recorded_and_reads_are_not(tmp_path):
    t = _read(tmp_path, [
        kit.tool_use("MultiEdit", {"file_path": "/p/AGENTS.md", "edits": [{"new_string": "one"}, {"new_string": "two"}]}),
        kit.tool_use("NotebookEdit", {"notebook_path": "/p/memory/n.md", "new_string": "cell"}),
        kit.tool_use("Bash", {"command": "echo rule | tee -a /p/DECISIONS.md"}),
        kit.tool_use("Bash", {"command": "cat /p/memory/MEMORY.md"}),
        kit.tool_use("Write", {"file_path": "/p/CLAUDE.md", "content": ""}),
        kit.summary("s")])
    assert [(w.path, w.text) for w in t.agent_writes] == [
        ("/p/AGENTS.md", "one\ntwo"), ("/p/memory/n.md", "cell"), ("", "echo rule | tee -a /p/DECISIONS.md")]


def test_a_queued_prompt_given_as_blocks_and_records_without_a_stamp_are_read(tmp_path):
    rec = json.dumps({"type": "attachment", "attachment": {"type": "queued_command",
                      "prompt": [{"type": "text", "text": "keep going"}]}}, separators=(",", ":"))
    t = _read(tmp_path, [rec, kit.summary("s")])
    assert [(w.text, w.ts) for w in t.user_words] == [("keep going", "")]
