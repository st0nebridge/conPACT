"""
Mutation tester for the Claude Code mod in src/mod (no install needed): the
JavaScript twin of tools/mutate.py, with Claude Code's own test host as the
oracle. A mutant is killed when `claude plugin test` fails with it in place.

Operators (one mutant per site), as tools/mutate.py names them:
  cmp   comparison swap      === <-> !==, == <-> !=, < <-> >=, > <-> <=
  bool  boolean op swap      && <-> ||
  not   negation removal     !x -> x
  const constant change      true <-> false, integer n -> n+1, 'text' -> 'XXtextXX'
  binop arithmetic swap      binary + <-> -
  ret   return value drop    return x -> return
  del   statement deletion   a line that is one call statement -> nothing
Skipped: comments, template literals (like f-strings: prose and keys), import
specifiers, and regular-expression literals.

Every mutant runs the mod's whole suite (it takes about three seconds), in a
worker's own copy of the mod, so workers never see each other's mutants. A run
that does not finish in time is a "timeout", which is an unfinished measurement
and never a detection. Results are appended to <out>.jsonl as they finish; a
rerun resumes.

Usage: python tools/mutate_mod.py <out_prefix> [workers] [claude]
  [claude] is the Claude Code to test with: CONPACT_CLAUDE, else `claude` on PATH.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "mod"
TIMEOUT = 120

_TOKEN = re.compile(r"""
    (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<template>`(?:\\.|[^`\\])*`)
  | (?P<string>'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*")
  | (?P<decimal>\b\d[\d_]*\.\d+\b)
  | (?P<number>\b\d[\d_]*\b)
  | (?P<word>[A-Za-z_$][\w$]*)
  | (?P<punct>===|!==|==|!=|<=|>=|=>|&&|\|\||\?\?|\?\.|\.\.\.|[-+*/%<>=!?:;,.(){}\[\]&|^~])
  | (?P<space>\s+)
""", re.S | re.X)

# After these, a "/" starts a regular expression rather than dividing.
_REGEX_AFTER = {"(", ",", "=", ":", "[", "!", "&&", "||", "?", "{", "}", ";", "return", "=>", "??"}
_REGEX = re.compile(r"/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+/[a-z]*")

_SWAP = {"===": "!==", "!==": "===", "==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">",
         "&&": "||", "||": "&&"}
_VALUE_END = {"word", "number", "decimal", "string", "template", "regex"}


def tokens(text: str) -> list[tuple[str, str, int]]:
    """(kind, text, offset) for every token, regular expressions recognised by what precedes them."""
    out, pos, last = [], 0, None
    while pos < len(text):
        if text[pos] == "/" and (last is None or last[1] in _REGEX_AFTER) and not text.startswith(("//", "/*"), pos):
            found = _REGEX.match(text, pos)
            if found:
                out.append(("regex", found.group(0), pos))
                last, pos = out[-1], found.end()
                continue
        found = _TOKEN.match(text, pos)
        if not found:
            raise ValueError(f"cannot read the source at offset {pos}: {text[pos:pos + 20]!r}")
        kind = found.lastgroup
        if kind != "space":
            out.append((kind, found.group(0), pos))
            if kind != "comment":
                last = out[-1]
        pos = found.end()
    return out


def _significant(toks):
    return [t for t in toks if t[0] != "comment"]


def sites(text: str) -> list[dict]:
    """Every mutant of one file: where it is, which operator, and what replaces what."""
    toks = _significant(tokens(text))
    found = []

    def add(op, tok, new, length=None):
        found.append({"op": op, "offset": tok[2], "length": length or len(tok[1]), "old": tok[1], "new": new,
                      "line": text.count("\n", 0, tok[2]) + 1})

    for i, tok in enumerate(toks):
        kind, value = tok[0], tok[1]
        before = toks[i - 1] if i else None
        if kind == "punct":
            if value in _SWAP:
                add("bool" if value in ("&&", "||") else "cmp", tok, _SWAP[value])
            elif value in "+-" and before and (before[0] in _VALUE_END or before[1] in (")", "]")):
                add("binop", tok, "-" if value == "+" else "+")
            elif value == "!" and not (before and before[0] in _VALUE_END):
                add("not", tok, "")
        elif kind == "word" and value in ("true", "false"):
            add("const", tok, "false" if value == "true" else "true")
        elif kind == "number":
            add("const", tok, str(int(value.replace("_", "")) + 1))
        elif kind == "string" and not (before and before[1] in ("from", "import")):
            add("const", tok, tok[1][0] + "XX" + tok[1][1:-1] + "XX" + tok[1][0])
        elif kind == "word" and value == "return":
            following = toks[i + 1] if i + 1 < len(toks) else None
            if following and following[1] not in (";", "}"):
                end = _expression_end(toks, i + 1)
                add("ret", tok, "return", length=end - tok[2])
    found.extend(_deletions(text))
    return found


def _expression_end(toks, start):
    """Where the expression after `return` ends: the token before the next line's start at depth 0."""
    depth, end = 0, toks[start][2] + len(toks[start][1])
    for j in range(start, len(toks)):
        value = toks[j][1]
        if depth == 0 and j > start and value in (";", "}"):
            break
        if value in "([{":
            depth += 1
        elif value in ")]}":
            depth -= 1
            if depth < 0:
                break
        end = toks[j][2] + len(toks[j][1])
        nxt = toks[j + 1] if j + 1 < len(toks) else None
        if depth == 0 and nxt and nxt[0] == "word" and nxt[1] in ("if", "const", "let", "return", "for", "await"):
            break
    return end


_CALL_LINE = re.compile(r"^(?P<indent>[ \t]*)(?:await\s+)?[\w$.]+\((?P<args>.*)\)[ \t]*$")


def _deletions(text):
    out, offset = [], 0
    for number, line in enumerate(text.split("\n"), start=1):
        found = _CALL_LINE.match(line)
        if found and found.group("args").count("(") == found.group("args").count(")") and "=>" not in line:
            start = offset + len(found.group("indent"))
            out.append({"op": "del", "offset": start, "length": len(line) - len(found.group("indent")),
                        "old": line.strip(), "new": "", "line": number})
        offset += len(line) + 1
    return out


def apply(text: str, site: dict) -> str:
    return text[:site["offset"]] + site["new"] + text[site["offset"] + site["length"]:]


def _claude(argument=None):
    found = argument or os.environ.get("CONPACT_CLAUDE") or shutil.which("claude")
    if not found:
        raise SystemExit("no Claude Code found: pass its path, or set CONPACT_CLAUDE")
    return found


def run_suite(folder: pathlib.Path, claude: str, timeout: int = TIMEOUT) -> str:
    env = {**os.environ, "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"}
    try:
        done = subprocess.run([claude, "plugin", "test"], cwd=folder, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout"
    out = done.stdout + done.stderr
    if "hooks modules are" in out and ("turned off" in out or "not turned on" in out):
        raise SystemExit("this Claude Code cannot load mods: " + out.strip().splitlines()[-1])
    return "survived" if done.returncode == 0 and re.search(r"\b0 fail\b", out) else "killed"


def mutants() -> list[dict]:
    out = []
    for path in sorted((MOD / "hooks").glob("*.js")):
        for site in sites(path.read_text(encoding="utf-8")):
            out.append({"module": f"src/mod/hooks/{path.name}", **site})
    return out


def _key(m):
    return f"{m['module']}:{m['offset']}:{m['op']}:{m['new']}"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    out_prefix = pathlib.Path(argv[0])
    workers = int(argv[1]) if len(argv) > 1 else 4
    claude = _claude(argv[2] if len(argv) > 2 else None)
    if run_suite(MOD, claude) != "survived":
        raise SystemExit("the mod's tests do not pass unmutated; fix them first")
    results_path = out_prefix.with_suffix(".jsonl")
    done = {}
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["key"]] = row
    todo = [m for m in mutants() if _key(m) not in done]
    print(f"{len(todo) + len(done)} mutants ({len(done)} already done), {workers} workers", flush=True)
    base = pathlib.Path(tempfile.mkdtemp(prefix="cpmodmut"))
    folders = []
    for n in range(workers):
        folder = base / f"w{n}"
        shutil.copytree(MOD, folder)
        folders.append(folder)
    free = list(folders)

    def one(mutant):
        folder = free.pop()
        target = folder / mutant["module"].removeprefix("src/mod/")
        original = target.read_text(encoding="utf-8")
        try:
            target.write_text(apply(original, mutant), encoding="utf-8")
            outcome = run_suite(folder, claude)
        finally:
            target.write_text(original, encoding="utf-8")
            free.append(folder)
        return {**mutant, "key": _key(mutant), "outcome": outcome}

    with results_path.open("a", encoding="utf-8") as sink, \
            concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for count, row in enumerate(pool.map(one, todo), start=1):
            sink.write(json.dumps(row) + "\n")
            sink.flush()
            done[row["key"]] = row
            if count % 25 == 0:
                print(f"  {count}/{len(todo)}", flush=True)
    shutil.rmtree(base, ignore_errors=True)
    rows = list(done.values())
    summary = {"total": len(rows), "killed": sum(r["outcome"] == "killed" for r in rows), "modules": {}}
    summary["score"] = round(100 * summary["killed"] / summary["total"], 1) if rows else 0.0
    for row in rows:
        module = summary["modules"].setdefault(row["module"], {"killed": 0, "survived": 0, "timeout": 0})
        module[row["outcome"]] += 1
    for module in summary["modules"].values():
        module["score"] = round(100 * module["killed"] / sum(module.values()), 1)
    print(json.dumps(summary, indent=2))
    survivors = [r for r in rows if r["outcome"] != "killed"]
    print(f"survivors: {len(survivors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
