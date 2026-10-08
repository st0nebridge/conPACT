"""
Regression test for CU-20261002-081 (the published tree names no private setup).

The repository is published from this tree. Until 2026-10-02 the user-facing
pages were kept free of the maintainer's private workflow vocabulary
(D-20260923-047), but the rest of the tree was not: the change log quoted a
process tool's score under its private acronym in 37 places and quoted the old
server instructions word for word, test docstrings and a source comment named
the acronyms, test data carried the maintainer's machine name, and the
maintainer's working notes and commit manifest were published whole. The
contract (D-20261002-062):

  1. No tracked file that is published names the private setup: its workflow
     names, its process acronyms, or the private project and machine names that
     once sat in the records. tests/private_words.py holds the words, as digests.
  2. The detector sees what it is for, and an ordinary word is not caught.
  3. The maintainer's own files - the working notes and the commit manifest -
     are the only ones kept back, and they are still tracked, so the list of
     what is kept back cannot quietly go stale.
"""
import pathlib
import subprocess

import pytest

import private_words

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Tracked for the maintainer, never published: the publish commit is built from
# this tree without them.
MAINTAINER_ONLY = ("HANDOFF.md", "logs/")


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout, so there is no tree to publish")
    return [name for name in out.decode("utf-8").split("\0") if name]


def _published():
    return [name for name in _tracked() if not name.startswith(MAINTAINER_ONLY)]


def _text(name):
    data = (ROOT / name).read_bytes()
    if b"\0" in data:
        return None                       # binary: an image or a built file
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def test_1_no_published_file_names_the_private_setup():
    names = _published()
    assert len(names) > 100
    hits = {}
    for name in names:
        text = _text(name)
        if text is not None and private_words.found(text):
            hits[name] = sorted(private_words.found(text))
    assert hits == {}, (
        "say what the step is instead of naming the private workflow "
        f"(a structure check, a test run, the change log): {hits}")


def test_2_the_detector_sees_what_it_is_for(monkeypatch):
    acronym = "P" * 3
    assert private_words.found(f"a finished {acronym} run") == {acronym}
    assert private_words.found(f"an {acronym}-driven project") == {acronym}
    assert private_words.found("then /" + "wrap" + "up") == {"wrap" + "up"}
    # A machine name keeps its hyphen (an invented one stands in here).
    monkeypatch.setattr(private_words, "FOLDED", private_words.FOLDED | {private_words.digest("box-42")})
    assert private_words.found("on BOX-42 via chatgpt.com") == {"BOX-42"}
    # An ordinary word is not caught: case matters for an acronym, and a word
    # that only contains one is a different word.
    assert private_words.found(f"cap it at five; {acronym.lower()}; {acronym}X") == set()
    assert private_words.found("") == set()


def test_3_the_maintainer_files_are_tracked_and_the_only_ones_kept_back():
    tracked = _tracked()
    for kept_back in MAINTAINER_ONLY:
        assert any(name == kept_back or name.startswith(kept_back) for name in tracked), kept_back
    assert len(tracked) - len(_published()) == sum(
        name.startswith(MAINTAINER_ONLY) for name in tracked)
