"""
@module conpact.provenance_match
@description Decides whether a constraint plausibly came from a given text: the
             user's words, an instruction file, another session's message, or a
             rule the agent filed itself. Both sides are reduced to content words
             (lowercase, at least three letters, common words dropped, simple
             endings folded), each source is cut into sentences and lines, and the
             score of a piece is the share of the constraint's words it contains.
             A match needs MIN_SCORE and at least MIN_SHARED shared words (fewer
             for a very short constraint), so a source that merely shares a
             topic word does not count. The threshold was set against 916
             hand-traced constraints (DECISIONS.md D-20261009-091). A match is
             evidence to look at, not a verdict: it carries the matching piece.
@input      a constraint's text and a list of Source(kind, ref, text)
@output     the best Match(source, score, quote), or None
@dependencies stdlib: dataclasses, re
"""
from __future__ import annotations

import dataclasses
import re

MIN_SCORE = 0.75
MIN_SHARED = 3
# Common words, and the words that name the parties: a summary says "the user"
# or the user's name where the user said "I", and that must not decide a match.
STOP = frozenset("""
the and are for not with from that this these those was were has have had its into than then them they their
there here when what which who will would should could can may might must shall about after before over under
also just only very more most some any all each every per via but yet our your you his her him she own out off
user users agent agents claude session sessions
""".split())
_WORD = re.compile(r"[a-z0-9_]+")
_PIECE = re.compile(r"(?<=[.!?])\s+|\n+|;\s*")


def _fold(word: str) -> str:
    for ending in ("ing", "ed", "es", "s"):
        if len(word) > len(ending) + 2 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def tokens(text: str) -> set:
    """The content words of a text."""
    return {_fold(w) for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in STOP}


_NEGATION = re.compile(r"\b(no|not|never|without|cannot|can't|don't|doesn't|isn't|aren't|wasn't|won't|shouldn't"
                       r"|mustn't|didn't)\b", re.IGNORECASE)
_BEFORE = 2    # how close before a shared word a negation must sit to negate it
# Verbs that say "no X" in other words ("remove the prefix", "scrub the names").
_UNDOING = re.compile(r"\b(remov|drop|retir|scrub|strip|stop|avoid|exclud|ban|forbid|prohibit|disabl|refus|declin"
                      r"|skip|omit|get rid)\w*", re.IGNORECASE)


def opposes(item: str, piece: str) -> bool:
    """Whether a matching piece seems to say the opposite. Either the item is
    plain and the piece negates one of the very words they share ("GET only"
    against "there is no GET-only rule"), or the item is negated and the piece
    has no negation at all ("never print the key" against "print the key when
    asked"). A negation elsewhere in a plain item's piece - a list ending "...,
    no AI trailer", "(never --global)" - decides nothing."""
    shared = tokens(item) - {"never"}
    words = re.findall(r"[A-Za-z0-9_']+", piece)
    hits = [i for i, w in enumerate(words) if _fold(w.lower()) in shared]
    if not hits:
        return False
    if _NEGATION.search(item):
        return not (_NEGATION.search(piece) or _UNDOING.search(piece))
    return any(_NEGATION.fullmatch(words[j]) for i in hits for j in range(max(0, i - _BEFORE), i))


def containment(item: set, other: set) -> float:
    """The share of the item's words found in the other."""
    return len(item & other) / len(item) if item else 0.0


def pieces(text: str) -> list:
    """A source cut into sentences, lines and semicolon parts."""
    return [p.strip() for p in _PIECE.split(text) if p and p.strip()]


@dataclasses.dataclass(frozen=True)
class Source:
    kind: str     # user | file | other | agent-file
    ref: str      # where it is: a transcript line, or path:line
    text: str
    note: str = ""


@dataclasses.dataclass(frozen=True)
class Match:
    source: Source
    score: float
    quote: str


def best(item: str, sources: list) -> Match | None:
    """The source piece that best contains the item's words, if it is a match."""
    want = tokens(item)
    if not want:
        return None
    need = MIN_SHARED if len(want) > 3 else 2
    top = None
    for src in sources:
        for piece in pieces(src.text):
            have = tokens(piece)
            shared = len(want & have)
            if shared < need:
                continue
            score = shared / len(want)
            if score >= MIN_SCORE and (top is None or score > top.score):
                top = Match(src, score, piece)
    return top
