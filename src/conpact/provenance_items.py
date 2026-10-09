"""
@module conpact.provenance_items
@description Finds the constraints a compaction summary carries: every bullet of
             a list headed as constraints, rules, preferences, directives or the
             like (a heading, a bold line, or a bullet ending in a colon that
             opens a nested list), every part of a labelled line such as
             "Standing constraints: a; b; c", and every sentence elsewhere worded
             as a rule for the agent ("never print", "must not", "only on
             request", "without asking", "is the user's call", "no further
             actions"). The summary's quotes of the user's messages and the
             harness text appended after it are not items, but a constraints list
             filed inside the user-messages section is. Descriptions of how code
             behaves are not items unless worded as a rule. Markdown emphasis is
             dropped, a wrapped bullet is one item, duplicates collapse, and an
             item is cut at MAX_ITEM_CHARS.
@input      a summary's text
@output     the list of constraint items, in the order they appear
@dependencies stdlib: re
"""
from __future__ import annotations

import re

MAX_ITEM_CHARS = 300

# Claude Code appends these after the summary itself.
_TAIL = re.compile(r"\n[ \t]*(If you need specific details from before compaction|Continue the conversation "
                   r"from where it left off|The messages after this summary are)", re.IGNORECASE)
_CONSTRAINT_HEAD = re.compile(r"\b(constraints?|rules?|preferences?|binding|guardrails?|agreements?|standing"
                              r"|polic(y|ies)|safety|permissions?|in force|in effect|protocols|directives?"
                              r"|house rules|operating|normal operations|relayed|teammate)\b", re.IGNORECASE)
_EXCLUDED_HEAD = re.compile(r"\b(all user messages|user messages|user's messages|messages from the user)\b",
                            re.IGNORECASE)
# "Label: content" on one line, where the label names a list of constraints.
_LABELLED = re.compile(r"^(?P<label>[^:]{3,100}?):\s+(?P<rest>\S.*)$")
_BULLET = re.compile(r"^(\s*)(?:[-*•]|\d+[.)])\s+(.*)$")
_TOP_NUMBERED = re.compile(r"^\d+\.\s+\S")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"`*(\[])")
_PART_END = re.compile(r";\s+|(?<=[.!?])\s+(?=[A-Z\"`*(\[])")
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")
# Directive wording. "never", "must" and "only" count only in directive form, so
# "the phase never advanced" or "the header must match" are not rules.
_VERBS = (r"print|push|commit|enter|run|use|touch|modify|change|delete|copy|stage|start|launch|click|install"
          r"|send|share|read|store|log|reset|edit|create|stop|kill|resume|power|bypass|work|hand|ask|pass|write"
          r"|expose|echo|display|retry|merge|deploy|restart|rebuild|reuse|move|remove|go|call|let|add|take|claim"
          r"|tell|word|treat|rewrite|skip|leave|drop|pursue|handle|extract|port|sign|open|attempt|try")
_SUBJECT = r"\b(?:i|we|you|claude|the agent|agents?|sub-agents?|subagents?|the user|sessions?|it)\b"
_RULE = re.compile(
    r"(^\W*(?:never|do not|don't|always|avoid)\b"
    r"|\b(?:must|should|will|may|to) never\b|\bnever (?:to )?(?:be )?(?:" + _VERBS + r")\b"
    r"|\bmust(?:n't| not| never)\b"
    r"|" + _SUBJECT + r"[^.]{0,40}\bmust\b"
    r"|" + _SUBJECT + r"[^.]{0,30}\b(?:do not|don't)\b|\b(?:do not|don't) (?:" + _VERBS + r")\b"
    r"|\bshould not\b|\bshouldn't\b|\bnot allowed\b|\bforbidden\b|\bprohibited\b|\boff-limits\b"
    r"|\bonly (?:if|when|after) (?:the user|asked|they|explicitly|requested|approved|authori[sz]ed|confirmed)"
    r"|\bonly on (?:explicit )?request|\bonly with (?:the user's|their|explicit)|\bexplicit[- ]request[- ]only"
    r"|\bwithout (?:asking|the user|explicit|approval|confirmation|a new request|their|the user's|permission)"
    r"|\buntil (?:they|the user|\w+ (?:answers|replies|confirms|asks))|\bunless (?:the user|asked|they ask)"
    r"|\b(?:is|are) (?:the user's|\w+'s) (?:call|decision|to (?:change|make|run|decide|drop|delete))"
    r"|\bthe user (?:installs|runs|must|decides|prefers|wants|makes|clicks|applies)"
    r"|\bno (?:new|further) (?:actions?|work|tool|code|changes|implementation)"
    r"|\b(?:needs?|requires?|awaits?) (?:the user's|explicit|their|\w+'s) (?:approval|permission|go-ahead|say-so"
    r"|decision|confirmation|call|word|direction)"
    r"|\b(?:await|wait for) (?:the user|their|\w+'s next)|\bnone (?:until|without)\b"
    r"|\bconfirm(?:ed)? with the user|\bnot (?:mine|ours) to (?:touch|change|judge|drop|edit))",
    re.IGNORECASE)


def is_rule(sentence: str) -> bool:
    """Whether a sentence is worded as a rule for the agent."""
    return bool(_RULE.search(sentence))


def _plain(text: str) -> str:
    return re.sub(r"\*\*|__|`", "", text).strip()


def _clean(text: str) -> str:
    text = " ".join(_plain(text).split())
    if len(text) > MAX_ITEM_CHARS:
        text = text[:MAX_ITEM_CHARS].rsplit(" ", 1)[0]
    return text


# A label names a list of constraints when, without its parentheses, it ends in
# such a noun ("Security/standing constraints", "Protocols in force") or opens
# with "standing" - so "Scrub policy gaps: ..." is a note, not a list.
_LABEL_NAMES_LIST = re.compile(r"(^standing\b|\b(constraints?|rules?|preferences?|directives?|guardrails?|policies"
                               r"|agreements?|in force|in effect|operations)$)", re.IGNORECASE)


def _labelled_constraints(text: str):
    """The constraints after a "Standing constraints: ..." style label, or None."""
    m = _LABELLED.match(_plain(text))
    if not m or _EXCLUDED_HEAD.search(m.group("label")):
        return None
    label = re.sub(r"\([^)]*\)", "", m.group("label")).strip(" -—")
    return m.group("rest") if _LABEL_NAMES_LIST.search(label) else None


def _heading(line: str) -> str | None:
    """The title of a section heading line (not a bullet), else None."""
    s = line.strip()
    if not s or (_BULLET.match(line) and not _TOP_NUMBERED.match(line)):
        return None
    plain = _plain(s)
    if s.startswith("#") or _TOP_NUMBERED.match(line):
        return plain
    if s.startswith("**") and (s.endswith("**") or s.endswith(":**") or s.endswith("**:")):
        return plain
    if plain.endswith(":") and len(plain) < 80:
        return plain
    return None


def _opener(text: str) -> bool:
    """Whether a bullet's text opens a nested list (it ends in a colon)."""
    plain = _plain(text)
    return plain.endswith(":") and (len(plain) < 80 or bool(_CONSTRAINT_HEAD.search(plain)))


def _units(lines):
    """(kind, text, indent) for each heading, bullet with its wrapped lines, or paragraph."""
    unit = None
    for line in lines:
        title = _heading(line)
        if title is not None:
            if unit:
                yield tuple(unit)
            unit = None
            yield ("heading", title, 0)
            continue
        if not line.strip():
            if unit and unit[0] == "para":
                yield tuple(unit)
                unit = None
            continue
        b = _BULLET.match(line)
        if b:
            if unit:
                yield tuple(unit)
            unit = ["bullet", b.group(2).strip(), len(b.group(1))]
        elif unit and not _labelled_constraints(line.strip()):
            unit[1] += " " + line.strip()
        else:
            # a "Standing constraints: ..." line opens its own unit even right
            # after a bullet, rather than being read as that bullet's wrap
            if unit:
                yield tuple(unit)
            unit = ["para", line.strip(), len(line) - len(line.lstrip())]
    if unit:
        yield tuple(unit)


def extract(summary: str) -> list[str]:
    """The constraint items a summary carries."""
    m = _TAIL.search(summary)
    body = summary[:m.start()] if m else summary
    body = re.sub(r"(?ms)^\s*```.*?^\s*```[^\n]*$", "", body)     # code is not a constraint
    items, seen = [], set()
    section_list = excluded = False
    section_lead = None    # a rule-worded heading, carried into each of its bullets
    # An open bullet-headed list: [opener indent, is_constraints, shape], where
    # shape is None until the next bullet shows it - "nested" (deeper) or
    # "flat" (siblings at the opener's own indent).
    nested = None

    def add(text):
        text = _clean(text)
        key = text.lower().rstrip(".")
        if text and key not in seen:
            seen.add(key)
            items.append(text)

    for kind, text, indent in _units(body.splitlines()):
        if kind == "heading":
            excluded = bool(_EXCLUDED_HEAD.search(text))
            section_lead = text.rstrip(":").strip() if not excluded and is_rule(text) else None
            section_list = not excluded and (bool(_CONSTRAINT_HEAD.search(text)) or section_lead is not None)
            nested = None
            continue
        if nested is not None:
            if kind == "bullet" and nested[2] is None:
                nested[2] = "nested" if indent > nested[0] else "flat" if indent == nested[0] else None
            ends = (kind != "bullet" or nested[2] is None
                    or (nested[2] == "nested" and indent <= nested[0])
                    or (nested[2] == "flat" and indent != nested[0]))
            if ends:
                nested = None
        if kind == "bullet" and _opener(text) or (kind == "para" and _plain(text).endswith(":") and is_rule(text)):
            plain = _plain(text)
            # a lead-in that is itself a rule ("Follow-ups, only if the user
            # asks:") carries into each bullet under it
            lead = plain.rstrip(":").strip() if is_rule(plain) else None
            named = bool(_CONSTRAINT_HEAD.search(plain)) and not _EXCLUDED_HEAD.search(plain)
            nested = [indent, named or lead is not None, None, lead]
            continue
        rest = _labelled_constraints(text)
        if rest is not None:
            # a labelled list counts even inside the user-messages section,
            # where some summaries file their constraints
            for part in _PART_END.split(rest):
                add(part)
            continue
        in_list = nested[1] if nested is not None else section_list
        if kind == "bullet" and in_list:
            lead = nested[3] if nested is not None else section_lead
            # one bullet often carries several rules, each with its own origin
            for part in _PART_END.split(text):
                add(f"{lead}: {part}" if lead else part)
            continue
        if excluded and nested is None:
            continue
        for sentence in _SENTENCE_END.split(text):
            # a quoted error or remark ("bare CR not allowed") is not a rule
            if is_rule(_QUOTED.sub("", sentence)):
                add(sentence)
    return items
