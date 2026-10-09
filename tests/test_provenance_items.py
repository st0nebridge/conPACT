"""Finding the constraints in a compaction summary."""
from conpact import provenance_items as pi

SUMMARY = """\
1. **Primary Request and Intent**

   - "deploy latest version to ulysses"

2. **Key Technical Concepts**
   - The guard refuses any Origin on every route.
   - Middleware forwards only read-only GETs to 8770.
   - Never print the router key into a transcript.

6. **All user messages**
   - "never mind the logs, do both"

   **Standing constraints (still binding, carried from earlier):**
   - The live API is read-only for Claude: GET only.
   - Commit messages are plain, with NO [Phase] prefix
     and no AI trailer.
   - Use they/them pronouns.

9. **Optional Next Step**

   Write the final report.

   No new actions without the user's word.

If you need specific details from before compaction (like exact code snippets), read the full transcript.
Continue the conversation from where it left off without asking the user any further questions.
"""


def test_every_bullet_of_a_constraints_list_is_an_item():
    items = pi.extract(SUMMARY)
    assert "The live API is read-only for Claude: GET only." in items
    assert "Use they/them pronouns." in items


def test_a_wrapped_bullet_is_one_item():
    assert "Commit messages are plain, with NO [Phase] prefix and no AI trailer." in pi.extract(SUMMARY)


def test_a_rule_worded_sentence_elsewhere_is_an_item():
    items = pi.extract(SUMMARY)
    assert "Never print the router key into a transcript." in items
    assert "No new actions without the user's word." in items


def test_descriptions_of_code_are_not_items():
    items = pi.extract(SUMMARY)
    assert not any("guard refuses" in i for i in items)
    assert not any("Middleware forwards" in i for i in items)
    assert not any("final report" in i for i in items)


def test_the_users_messages_section_and_the_harness_tail_are_not_items():
    items = pi.extract(SUMMARY)
    assert not any("never mind the logs" in i for i in items)
    assert not any("without asking the user any further" in i for i in items)


def test_headings_in_other_shapes_open_a_constraints_list():
    for heading in ("### Constraints", "User preferences:", "- Rules in force:", "**Binding rules**"):
        text = f"{heading}\n- Push only on explicit request.\n- Keep the band small.\n\n3. Files\n- src/a.py\n"
        items = pi.extract(text)
        assert items == ["Push only on explicit request.", "Keep the band small."], heading


def test_a_bullet_ending_in_a_colon_opens_a_nested_list_even_among_the_users_messages():
    text = ("6. All user messages:\n   - \"Review the CPU\"\n   - **Standing constraints from earlier, still in "
            "effect:**\n     - Large outputs go to D:\\Dev.\n     - Resuming the VM is a separate matter.\n"
            "   - \"proceed\"\n")
    assert pi.extract(text) == ["Large outputs go to D:\\Dev.", "Resuming the VM is a separate matter."]


def test_a_long_lead_in_that_names_rules_opens_a_list_which_ends_when_the_indent_returns():
    text = ("1. Primary Request\n   - **Teammate directives.** COORDINATOR (a coordinating session) set these "
            "operating rules for every session that it coordinates today:\n     - At most 1 heavy job per session.\n"
            "     - Fewer parallel sub-agents.\n   - The current request was the enhancement pass.\n")
    assert pi.extract(text) == ["At most 1 heavy job per session.", "Fewer parallel sub-agents."]


def test_a_short_lead_in_that_names_no_rules_does_not_make_its_bullets_items():
    text = "## Files\n- Changed:\n  - src/app.py\n  - Never run cargo here.\n"
    assert pi.extract(text) == ["Never run cargo here."]


def test_a_lead_in_worded_as_a_rule_carries_into_each_bullet():
    for lead in ("Possible follow-ups, only if the user asks:", "   - Optional work that needs the user's go-ahead:"):
        text = f"7. Pending\n{lead}\n     - A real-BFE VM check.\n     - Delete old branches.\n"
        items = pi.extract(text)
        base = lead.strip().lstrip("- ").rstrip(":")
        assert items == [f"{base}: A real-BFE VM check.", f"{base}: Delete old branches."], lead


def test_a_bullet_carrying_several_rules_gives_one_item_each():
    text = "Constraints:\n- Never print the key. Filter output with an allow-list; use scp -O.\n"
    assert pi.extract(text) == ["Never print the key.", "Filter output with an allow-list", "use scp -O."]


def test_a_label_that_only_mentions_a_policy_is_a_note_not_a_list():
    text = "4. Errors and fixes\n- **Scrub policy gaps:** a manual check found two titles in the snapshot.\n"
    assert pi.extract(text) == []


def test_relayed_house_rules_are_a_constraints_list():
    text = "- Normal operations (from COORDINATOR): use the heavy gate; fewer parallel sub-agents.\n"
    assert pi.extract(text) == ["use the heavy gate", "fewer parallel sub-agents."]


def test_a_quoted_error_outside_a_constraints_list_is_not_a_rule():
    text = '4. Errors\n- **Heredoc escapes:** a heredoc made bare carriage returns ("bare CR not allowed").\n'
    assert pi.extract(text) == []


def test_descriptive_negations_and_code_are_not_rules():
    for s in ("No measurable gain; the user later reverted it.", "plan.featureForecast and five siblings don't exist.",
              "Most tracks do not loop."):
        assert not pi.is_rule(s), s
    text = "## Notes\n```powershell\n# never run this twice\nexit 2\n```\nDo not run the probe twice.\n"
    assert pi.extract(text) == ["Do not run the probe twice."]


def test_holds_and_named_owners_are_rules():
    for s in ("Plugin adoption is Alex's call.", "then await the user's next verdict before any changes.",
              "None until Alex replies.", "The found items require the user's decision.",
              "E3 should be confirmed with the user before starting.", "That commit is not mine to touch."):
        assert pi.is_rule(s), s


def test_a_constraints_list_ends_at_the_next_heading():
    text = "Constraints:\n- Branch first.\n\n## Files and Code\n- src/app.py was changed.\n"
    assert pi.extract(text) == ["Branch first."]


def test_prose_rules_are_split_into_sentences():
    text = "## Notes\nThe build is green. Do not restart the router without checking /api/state. It runs 0.28.\n"
    assert pi.extract(text) == ["Do not restart the router without checking /api/state."]


def test_markdown_emphasis_is_dropped_and_duplicates_collapse():
    text = "Constraints:\n- **Never** push to `main`.\n- Never push to main.\n"
    assert pi.extract(text) == ["Never push to main."]


def test_an_empty_or_rule_free_summary_has_no_items():
    assert pi.extract("") == []
    assert pi.extract("1. Primary Request\n- build the thing\n") == []


def test_an_overlong_item_is_cut():
    text = "Constraints:\n- " + "word " * 200 + "\n"
    (item,) = pi.extract(text)
    assert len(item) <= pi.MAX_ITEM_CHARS


def test_a_labelled_line_of_constraints_is_split_into_items():
    text = ("1. Intent\n   Standing constraints (from CLAUDE.md, in effect verbatim): **Git rules** - local commits at "
            "phase gates; push is explicit-request only; branch-first.\n\n2. Concepts\n- Protocols in force: "
            "Structure (measured), Changes (CHANGES.md entries), Git (branch-first)\n")
    items = pi.extract(text)
    assert "Git rules - local commits at phase gates" in items
    assert "push is explicit-request only" in items
    assert "branch-first." in items
    assert "Structure (measured), Changes (CHANGES.md entries), Git (branch-first)" in items


def test_narrative_and_specifications_are_not_rules():
    for s in ("Eight-way stem splits never landed for the 5 tracks.", "The phase never advanced.",
              "HEAD must be 0.00% at untouched instants.", "Header X-Admin-Token must match ADMIN_TOKEN.",
              "Sign mipmaps only on opaque boards.", "finish yields Staged only when ready_notice.",
              "vendor/ is gitignored, so this file is never committed."):
        assert not pi.is_rule(s), s


def test_directives_in_those_words_are_rules():
    for s in ("prompt_on_launch must NEVER be written to their config.", "Sub-agents must not run builds.",
              "I must not work around this denial.", "Never stage RESUME.md.", "We never push from here.",
              "Deploy 1.2.165 needs the user's approval.", "Avoid touching the router."):
        assert pi.is_rule(s), s


def test_rule_words_are_recognised():
    for s in ("Never use conntrack.", "Do not modify system settings.", "Don't enter passwords.",
              "Root changes go to the user, who must apply them.", "Deploy only after the user asks.",
              "Take no server action until they answer.", "Resuming the VM is the user's call.",
              "The user installs the app themselves.", "Push only on explicit request."):
        assert pi.is_rule(s), s
    for s in ("The guard refuses any Origin.", "It returns only the first row.", "The build is green."):
        assert not pi.is_rule(s), s


def test_bold_headings_with_the_colon_inside_or_outside_open_a_list():
    for heading in ("**Standing constraints:**", "**Standing constraints**:"):
        assert pi.extract(f"{heading}\n- Keep the band small.\n") == ["Keep the band small."], heading


def test_a_long_line_ending_in_a_colon_is_not_a_heading():
    long_line = "Here is a sentence that is quite long and just happens to end in a colon after many words:"
    assert len(long_line) >= 80
    text = f"Constraints:\n{long_line}\n- Keep the band small.\n"
    assert "Keep the band small." in pi.extract(text)


def test_a_flat_list_under_a_lead_in_ends_where_its_indent_changes():
    text = ("## Notes\n- Rules in force:\n- Keep the band small.\n- Keep the toast quiet.\n"
            "  - a nested remark\n- Later prose about the build.\n")
    assert pi.extract(text) == ["Keep the band small.", "Keep the toast quiet."]


def test_a_paragraph_ends_at_a_blank_line_and_a_heading_ends_a_bullet():
    text = "Constraints:\n- Branch first\n## Files\nDo not run the probe twice.\n\nIt is fine.\n"
    assert pi.extract(text) == ["Branch first", "Do not run the probe twice."]
