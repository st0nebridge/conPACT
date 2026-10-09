"""Matching a constraint to the words it may have come from."""
from conpact import provenance_match as pm


def test_tokens_drop_short_and_common_words_and_fold_simple_endings():
    assert pm.tokens("Never print the router keys") == {"never", "print", "router", "key"}
    assert pm.tokens("printing printed prints") == {"print"}
    assert pm.tokens("") == set()


def test_containment_is_the_share_of_the_items_words_found():
    assert pm.containment({"a1", "b1", "c1", "d1"}, {"a1", "b1", "zz"}) == 0.5
    assert pm.containment(set(), {"a1"}) == 0.0


def test_pieces_split_a_source_into_sentences_and_lines():
    assert pm.pieces("One rule here. Second rule there!\nThird line; fourth part") == [
        "One rule here.", "Second rule there!", "Third line", "fourth part"]


def test_the_best_source_needs_enough_shared_words():
    sources = [pm.Source("user", "L5", "use scp -O for the router copy"),
               pm.Source("user", "L9", "router is slow today")]
    m = pm.best("Use scp -O when copying to the router.", sources)
    assert m.source.ref == "L5" and m.score >= 0.6
    assert pm.best("Never print the router key.", sources) is None


def test_a_short_item_can_match_on_two_shared_words():
    m = pm.best("Branch first.", [pm.Source("file", "CLAUDE.md:3", "Branch-first: never commit onto main")])
    assert m is not None and m.source.ref == "CLAUDE.md:3"


def test_a_high_score_wins_over_a_long_partial_one():
    sources = [pm.Source("user", "L1", "keep the logs and push to the remote and deploy the router tonight please"),
               pm.Source("user", "L2", "push only when I ask")]
    m = pm.best("Push only when the user asks.", sources)
    assert m.source.ref == "L2"


def test_the_match_quotes_the_piece_that_matched():
    m = pm.best("Never use conntrack.", [pm.Source("file", "D.md:1", "Traffic: sta0 counters. Never use conntrack for it.")])
    assert m.quote == "Never use conntrack for it."


def test_a_piece_with_the_opposite_polarity_opposes():
    assert pm.opposes("The live API is read-only: GET only.", "There is no GET-only rule on the live API")
    assert not pm.opposes("Never use conntrack.", "figures never come from conntrack counters")
    assert not pm.opposes("Push only on request.", "Pushing stays explicit-request only")
    assert not pm.opposes("Don't deploy without asking.", "do not deploy it without asking first")
    assert not pm.opposes("Branch first.", "this is a project (branch-first, a changes entry, regression "
                                           "tests, plain commits, no AI trailer)")
    assert not pm.opposes("git config repo-local only", "git config is set repo-local only (never --global).")
    assert not pm.opposes("autonomous local commits at phase gates",
                          "Autonomous local commits are authorized at phase gates - do not re-prompt per commit.")
    assert pm.opposes("Commit messages are [Phase X] only", "plain messages with no phase prefix")
    assert pm.opposes("Never print the key.", "print the key when the user asks for it")
    assert not pm.opposes("Never print the key.", "the key is never printed")
    assert not pm.opposes("anything", "nothing in common here")
    assert not pm.opposes("Commit messages carry no phase prefix.", "remove the phase prefix from commit messages")


def test_no_sources_no_match():
    assert pm.best("anything at all here", []) is None


def test_common_words_and_the_parties_names_are_not_content():
    assert pm.tokens("the and are for with from that this the user users agent agents claude session") == set()


def test_endings_fold_only_on_words_long_enough():
    assert pm.tokens("bus uses boxes runs printed") == {"bus", "use", "box", "run", "print"}


def test_a_four_word_item_matches_on_three_shared_words_but_not_on_two():
    src = [pm.Source("file", "F:1", "never push remote today")]
    assert pm.best("never push remote main", src) is not None
    assert pm.best("never push remote main", [pm.Source("file", "F:1", "never push today")]) is None


def test_a_piece_sharing_enough_words_but_too_small_a_share_is_no_match():
    src = [pm.Source("file", "F:1", "router key print")]
    assert pm.best("never print the router key into a transcript or a log or a chat", src) is None


def test_the_better_of_two_matches_wins_whichever_comes_first():
    weak, strong = "push the branch to origin today", "push the branch to origin only when asked"
    item = "Push the branch to origin only when asked."
    for order in ((strong, weak), (weak, strong)):
        m = pm.best(item, [pm.Source("user", f"L{i}", text) for i, text in enumerate(order)])
        assert m.quote == strong


def test_a_negation_right_at_the_start_of_a_piece_counts():
    assert pm.opposes("GET only", "no GET-only rule") is True
    assert pm.opposes("anything", "nothing in common") is False
