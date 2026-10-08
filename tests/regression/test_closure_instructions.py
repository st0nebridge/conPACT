"""
Regression test for CU-20260919-015 (agents are told when to queue a compaction).

Seen 2026-09-19: a 12-hour build session, run under the user's own closure
procedures, finished at 17:16Z at
745,683 tokens - final gate, commit, tag, final report - and never queued a
compaction. The conpact tools were listed (deferred) and the server's
instructions were in its context, but they only said to queue "when an overall
piece of work is verifiably complete", and the tool itself said "Use it only
when". The contract for what every session is told:

  1. The server's instructions name the closures that call for it (a finished
     feature, fix or build, a completed implementation plan, an explicit wrap-up
     of the session, the user asking), make it the last action after the final
     commit, and say how to discover the deferred tool in the client's catalog.
  2. Neither the instructions nor the tool's description hedge it as optional.

CU-20260923-057 restated the closures in terms any user has. They used to name
workflows from one person's setup by their private names, which meant nothing
to anyone else; what this anchor guards - named
closures, no hedge - remains. Routine read-only answers are excluded.
"""
from conpact import mcp_server, mcp_tools


def _queue_description():
    return next(t["description"] for t in mcp_tools.TOOLS if t["name"] == mcp_tools.QUEUE)


def test_1_the_instructions_name_the_closures_and_how_to_load_the_tool():
    text = mcp_server.INSTRUCTIONS
    for phrase in ("finished feature, fix or build", "multi-step plan", "wrap-up of the session",
                   "user explicitly asks", "last action", "tool catalog", "queue_compaction"):
        assert phrase in text, phrase


def test_2_nothing_hedges_it_as_optional():
    for text in (mcp_server.INSTRUCTIONS, _queue_description()):
        for hedge in ("only when", "where compaction is wanted", "if compaction is wanted"):
            assert hedge not in text, hedge
