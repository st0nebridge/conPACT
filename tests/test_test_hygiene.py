"""
The suite's own rule, enforced rather than remembered (D-20260920-018).

The watcher deliberately swallows whatever a presenter raises, so that a broken
toast can never crash it. That also swallows an `assert` a test makes inside the
callback it hands over - the assertion never reaches the test, and the test
passes whatever the code does. Mutation testing found six of those; writing this
feature added a seventh within the hour, which is why it is a test now.

The rule: a test asserts in its own body. A function it defines and hands to the
code under test collects; the test checks what was collected afterwards.
"""
import ast
import pathlib

TESTS = pathlib.Path(__file__).resolve().parent
RULE = ("assert in a nested function: whatever it raises may be swallowed by the code under test. "
        "Collect there and assert in the test body instead.")


def _nested_asserts(tree):
    """(outer, inner, line) for every function defined inside a function that asserts."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for statement in node.body:
            for inner in ast.walk(statement):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                        isinstance(sub, ast.Assert) for sub in ast.walk(inner)):
                    found.append(f"{node.name} -> {inner.name}, line {inner.lineno}")
    return found


def test_no_test_asserts_inside_a_callback_it_hands_over():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        if path == pathlib.Path(__file__).resolve():
            continue
        for hit in _nested_asserts(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(TESTS.parent)}: {hit}")
    assert offenders == [], RULE + "\n  " + "\n  ".join(offenders)


def test_the_rule_is_what_it_says_it_is():
    """The check itself, on a sample: an assert in the test body is fine, in a callback is not."""
    good = ast.parse("def test_x():\n    states = []\n    run(lambda c: states.append(c.act()))\n"
                     "    assert states == [1]\n")
    bad = ast.parse("def test_x():\n    def present(c):\n        assert c.act() == 1\n    run(present)\n")
    assert _nested_asserts(good) == []
    assert _nested_asserts(bad) == ["test_x -> present, line 2"]
