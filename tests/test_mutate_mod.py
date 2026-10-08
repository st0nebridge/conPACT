"""
@module tests.test_mutate_mod
@description tools/mutate_mod.py, the mod's mutation tester: it reads
             JavaScript well enough to find every mutant and no false one -
             a regular expression is not a division, a comment and a template
             literal are left alone, an import path is not a string to change
             - and a mutant is applied at exactly its place.
@input      tools/mutate_mod.py, loaded from source
@dependencies stdlib: importlib, pathlib
"""
import importlib.util
import pathlib

TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "mutate_mod.py"


def _tool():
    spec = importlib.util.spec_from_file_location("mutate_mod_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ops(source):
    return [(s["op"], s["old"], s["new"]) for s in _tool().sites(source)]


def test_a_regular_expression_is_one_token_and_a_division_is_not():
    tool = _tool()
    kinds = [(k, v) for k, v, _ in tool.tokens("const r = /a\\/b[/]/g; const d = x / 2")]
    assert ("regex", "/a\\/b[/]/g") in kinds
    assert ("punct", "/") in kinds
    assert [v for k, v, _ in tool.tokens("return /x/.test(s)") if k == "regex"] == ["/x/"]


def test_comments_templates_and_import_paths_are_not_mutated():
    source = "import { a } from './a.js'\n// x === y\n/* true */\nconst t = `${a === b}`\n"
    assert _ops(source) == []


def test_each_operator_finds_its_sites():
    ops = _ops("if (a === b && !c) return x + 1\nconst s = 'hi'\nconst f = true\nlog(s)\n")
    assert ("cmp", "===", "!==") in ops
    assert ("bool", "&&", "||") in ops
    assert ("not", "!", "") in ops
    assert ("binop", "+", "-") in ops
    assert ("const", "1", "2") in ops
    assert ("const", "'hi'", "'XXhiXX'") in ops
    assert ("const", "true", "false") in ops
    assert ("del", "log(s)", "") in ops
    assert ("ret", "return", "return") in ops


def test_a_unary_minus_and_an_arrow_are_not_operators_to_swap():
    ops = _ops("const n = -1\nconst f = (x) => x\n")
    assert not any(op in ("binop", "cmp") for op, _, _ in ops)


def test_a_mutant_lands_exactly_where_it_was_found():
    tool = _tool()
    source = "function f(a) {\n  return a >= 2\n}\n"
    by_op = {s["op"]: s for s in tool.sites(source)}
    assert tool.apply(source, by_op["cmp"]) == "function f(a) {\n  return a < 2\n}\n"
    assert tool.apply(source, by_op["ret"]) == "function f(a) {\n  return\n}\n"
    assert tool.apply(source, by_op["const"]) == "function f(a) {\n  return a >= 3\n}\n"


def test_a_decimal_is_read_and_left_alone():
    ops = _ops("if (d > 0.5) go()\n")
    assert ("cmp", ">", "<=") in ops
    assert not any(old.startswith("0") for op, old, _ in ops if op == "const")


def test_every_mod_module_can_be_read():
    tool = _tool()
    found = tool.mutants()
    assert {m["module"] for m in found} == {f"src/mod/hooks/{n}" for n in
                                            ("register.js", "rules.js", "requests.js", "files.js", "tools.js",
                                             "run.js", "handoff.js", "band.js")}
    assert len(found) > 300
