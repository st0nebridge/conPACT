"""
Regression test for CU-20260923-057 (the docs stand on their own).

The README, every page under docs/ and the text the MCP server hands every
agent are read by people and agents who have never seen how this project was
built. They named workflows from one person's private setup by their private
names, in the server's instructions and in docs/how-it-works.md, the process
acronyms behind them, a fitness score from a
tool that is not in the repository, and cited decision and change ids in place
of the reasons. The contract:

  1. Neither the server's instructions nor any tool description names a
     private workflow. They still say when to queue, in terms any user has
     (test_closure_instructions keeps that half).
  2. No user-facing page names one, names the process acronyms, or cites a
     decision or change id: a reason is stated where it is used, and the
     records (CHANGES.md, DECISIONS.md) are for contributors.
  3. No user-facing page sends the reader to the maintainer's working notes.
"""
import pathlib
import re

import pytest

import private_words
from conpact import mcp_server, mcp_tools

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

# The private vocabulary itself is in tests/private_words.py, kept as digests.
RECORD_ID = re.compile(r"\b(D|CU)-\d{8}-\d{3}\b|\bCU-\d{3}\b|\bD-\d{3}\b")


def _agent_facing_text():
    yield "server instructions", mcp_server.INSTRUCTIONS
    for tool in mcp_tools.TOOLS:
        yield tool["name"], tool["description"]


def test_1_no_agent_facing_text_names_a_private_workflow():
    for where, text in _agent_facing_text():
        assert private_words.found(text) == set(), where


def test_the_pages_exist():
    assert len(PAGES) > 5
    assert all(page.is_file() for page in PAGES)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name if p.parent == ROOT else f"docs/{p.name}")
def test_2_no_page_names_a_private_workflow_or_cites_a_record_id(page):
    text = page.read_text(encoding="utf-8")
    assert private_words.found(text) == set(), page.name
    found = RECORD_ID.search(text)
    assert found is None, f"{page.name}: {found.group(0)!r}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name if p.parent == ROOT else f"docs/{p.name}")
def test_3_no_page_sends_the_reader_to_the_working_notes(page):
    assert "HANDOFF.md" not in page.read_text(encoding="utf-8")
