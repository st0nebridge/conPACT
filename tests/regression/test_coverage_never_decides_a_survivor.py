"""
Regression test for CU-20260923-061 (coverage never decides a survivor).

tools/mutate.py runs each mutant against the tests its line's coverage contexts
name. That is fast, and for a line that runs when the module is imported it is
wrong: a module is imported once per process, and the lines that run then are
credited to whatever ran them - collection, which is no test, and any test that
runs the module again through runpy - while every test that uses the module
depends on them. On 2026-09-23 `settings_window.WIDTH = 460 -> 461` met a single
runpy test and was recorded as surviving, although the window's own test file
asserts `sw.WIDTH == 460`. Ten of that module's twenty survivors were this
artefact, and an eleventh was killed by a test that reads the module's source,
which runs none of it, so no coverage context can name it either. The contract:

  1. A mutant its covering tests let through is run again, before it is
     recorded as surviving, against the tests written for its module: its own
     test file, whole, and every regression test that imports the module or
     names it in a string (runpy, a test that reads the source). A failure there
     is a kill.
  2. Those tests are found by what each file says, not by a file-name prefix:
     the anchor listing `settings_window` among the entry points is one of that
     module's tests; a test of `toast_view` is not one of `toast`'s.
  3. A timeout is still never a kill (D-20260920-025): a recheck that does not
     finish leaves the mutant a survivor.
  4. Nothing that has already answered is asked again: not a mutant whose tests
     were the whole suite, not a file that already ran whole, and not an
     uncovered mutant, which no test executes at all.
"""
import ast
import importlib.util
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "mutate.py"

WIDGET = '''\
WIDTH = 460


def main():
    return 0


if __name__ == "__main__":
    main()
'''

WIDGET_TESTS = '''\
import runpy

from conpact import widget


def test_the_module_runs_as_a_command():
    runpy.run_module("conpact.widget", run_name="__main__")


def test_the_width():
    assert widget.WIDTH == 460
'''


@pytest.fixture(scope="module")
def mutate():
    spec = importlib.util.spec_from_file_location("mutate_tool_survivors", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    """A repository in miniature: one module with a constant, its own test file
    (one test runs the module as a command, the other asserts the constant), and
    a src root put on the path the way this repo's conftest does it."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "src" / "conpact").mkdir(parents=True)
    (tmp_path / "src" / "conpact" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "conpact" / "widget.py").write_text(WIDGET, encoding="utf-8")
    (tmp_path / "tests" / "regression").mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_widget.py").write_text(WIDGET_TESTS, encoding="utf-8")
    return tmp_path


def _job(mutate, root, rel, desc, tests):
    """The job main() would build for the site described `desc` in `rel`."""
    tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    [(walk_index, op, sub, line)] = [(i, op, sub, line) for i, op, sub, line, d in mutate.sites(tree) if d == desc]
    return (f"{rel}#{walk_index}:{op}:{sub}", rel, walk_index, op, sub, int(line.split("/")[0]), desc, tests)


# 1 -------------------------------------------------------------------------

def test_1_an_import_time_constant_is_credited_to_the_test_that_re_ran_the_module(mutate, project, monkeypatch):
    """The cause, measured in miniature with the tool's own map: the constant ran
    at collection (no test) and again under runpy, so the map names that one
    test and not the test that asserts the value."""
    # A mutant's own test run switches plugin autoload off, and the map needs
    # pytest-cov: without this, the whole-suite run of every import-time mutant
    # would fail here and record a kill the mutant never earned.
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    mapping = mutate.line_to_tests(str(project))
    assert mapping["src/conpact/widget.py:1"] == ["tests/test_widget.py::test_the_module_runs_as_a_command"]


def test_coverage_map_owns_its_database(mutate, project, monkeypatch, tmp_path):
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    foreign = tmp_path / "outer.coverage"
    foreign.write_bytes(b"outer run must remain unchanged")
    monkeypatch.setenv("COVERAGE_FILE", str(foreign))
    mapping = mutate.line_to_tests(str(project))
    assert mapping["src/conpact/widget.py:1"]
    assert foreign.read_bytes() == b"outer run must remain unchanged"


def test_1_a_map_that_cannot_be_made_names_the_test_that_failed(mutate, project, monkeypatch):
    """Every verdict assumes the unmutated suite passes. When it did not, the tool
    used to die with a bare CalledProcessError, the failing test's name thrown away
    with the output it captured (seen on 2026-09-23 while measuring this change)."""
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    (project / "tests" / "test_flaky.py").write_text("def test_once_in_a_while():\n    assert False\n",
                                                     encoding="utf-8")
    with pytest.raises(SystemExit, match=r"FAILED tests/test_flaky\.py::test_once_in_a_while"):
        mutate.line_to_tests(str(project))


def test_1_the_survivor_is_asked_of_its_modules_tests_and_killed(mutate, project, monkeypatch):
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    covering = ["tests/test_widget.py::test_the_module_runs_as_a_command"]  # what the map gives line 1
    result = mutate._run(_job(mutate, project, "src/conpact/widget.py", "460->461", covering))
    assert result["outcome"] == "killed"
    assert result["recheck"] == "killed"
    # The mutant was put back: the next job starts from the real source.
    assert (project / "src" / "conpact" / "widget.py").read_text(encoding="utf-8") == WIDGET


def test_1_a_mutant_the_modules_tests_also_let_through_still_survives(mutate, project, monkeypatch):
    """Deleting main()'s call under the guard changes nothing any test observes:
    the recheck runs, finds nothing, and the verdict stands."""
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    covering = ["tests/test_widget.py::test_the_module_runs_as_a_command"]
    result = mutate._run(_job(mutate, project, "src/conpact/widget.py", "delete Expr", covering))
    assert (result["outcome"], result["recheck"]) == ("survived", "survived")


# 2 -------------------------------------------------------------------------

def test_2_the_settings_windows_tests_are_the_ones_that_killed_its_artefacts(mutate, monkeypatch):
    """This repository, read as the tool reads a worker's copy of it. The path is
    spelled so that this file does not name the module itself: it reads the
    window's tests, not the window, so it is not one of them."""
    monkeypatch.setattr(mutate, "_WORKDIR", str(ROOT))
    [window] = (ROOT / "src" / "conpact").glob("settings_win*.py")
    found = mutate._module_tests(window.relative_to(ROOT).as_posix())
    assert found[0] == "tests/test_settings_window.py"            # its own file, whole
    assert "tests/regression/test_settings_window_fits_the_screen.py" in found   # imports it
    assert "tests/regression/test_state_has_a_home_of_its_own.py" in found       # names it: reads its source
    # Its name in a docstring is prose, not a use: D-025's anchor quotes it there.
    assert "tests/regression/test_timeout_is_not_detection.py" not in found
    assert "tests/regression/test_codex_turn_end_is_a_hook.py" not in found
    assert "tests/regression/" + pathlib.Path(__file__).name not in found
    assert len(found) == len(set(found))                           # nothing twice


@pytest.mark.parametrize("text", [
    "from conpact import widget\n",
    "from conpact import settings, widget as w\n",
    "from conpact import (\n    settings,\n    widget,\n)\n",
    "import conpact.widget\n",
    "from conpact.widget import WIDTH\n",
    "import runpy\nrunpy.run_module('conpact.widget', run_name='__main__')\n",
    "MODULES = ['cli', 'widget']\n",
    "SOURCE = 'src/conpact/widget.py'\n",
    "PATH = 'widget.py'\n",
])
def test_2_a_regression_test_that_imports_or_names_the_module_is_one_of_its_tests(mutate, project, monkeypatch, text):
    (project / "tests" / "regression" / "test_anchor.py").write_text(text, encoding="utf-8")
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    assert mutate._module_tests("src/conpact/widget.py") == ["tests/test_widget.py",
                                                             "tests/regression/test_anchor.py"]


@pytest.mark.parametrize("text", [
    "from conpact import widgets\n",                   # a different module with the same prefix
    "from conpact.widgets import widget\n",            # a name inside a different module
    "import widget\n",                                 # not this package's module
    "'''The widget module once ran a widget.'''\n",    # prose
    "X = 'conpact.widget_view'\n",
    "this is not python (\n",                          # unreadable: skipped, not fatal
])
def test_2_one_that_only_resembles_it_is_not(mutate, project, monkeypatch, text):
    (project / "tests" / "regression" / "test_anchor.py").write_text(text, encoding="utf-8")
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    assert mutate._module_tests("src/conpact/widget.py") == ["tests/test_widget.py"]


def test_2_a_module_with_no_tests_of_its_own_has_none_to_ask(mutate, project, monkeypatch):
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    assert mutate._module_tests("src/conpact/untested.py") == []
    monkeypatch.setattr(mutate, "_WORKDIR", None)
    assert mutate._module_tests("src/conpact/widget.py") == []


# 3 and 4: what is asked, and what a verdict becomes, without running pytest --

class Answers:
    """Stands in for mutate._pytest: records what it was asked, answers in turn."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, tests, env, limit=120):
        self.asked.append((list(tests), limit))
        return self.answers.pop(0)


def _run(mutate, project, monkeypatch, covering, *answers):
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    (project / "tests" / "regression" / "test_anchor.py").write_text("from conpact import widget\n", encoding="utf-8")
    fake = Answers(*answers)
    monkeypatch.setattr(mutate, "_pytest", fake)
    return mutate._run(_job(mutate, project, "src/conpact/widget.py", "460->461", covering)), fake.asked


COVERING = ["tests/test_widget.py::test_the_module_runs_as_a_command"]
MODULE_TESTS = ["tests/test_widget.py", "tests/regression/test_anchor.py"]


def test_3_a_recheck_that_does_not_finish_is_not_a_kill(mutate, project, monkeypatch):
    result, asked = _run(mutate, project, monkeypatch, COVERING, "survived", "timeout")
    assert (result["outcome"], result["recheck"]) == ("survived", "timeout")
    assert asked == [(COVERING, 120), (MODULE_TESTS, 300)]


def test_3_a_kill_needs_no_recheck(mutate, project, monkeypatch):
    result, asked = _run(mutate, project, monkeypatch, COVERING, "killed")
    assert result["outcome"] == "killed" and "recheck" not in result
    assert asked == [(COVERING, 120)]


def test_3_the_timeout_retry_is_unchanged_and_a_survivor_it_finds_is_rechecked(mutate, project, monkeypatch):
    """D-025 and D-029 first: the whole suite timed out, the module's own file
    answered "survived" at 300 seconds - and only then is the rest asked."""
    result, asked = _run(mutate, project, monkeypatch, ["tests"], "timeout", "survived", "killed")
    assert result["outcome"] == "killed"
    assert asked == [(["tests"], 120), (["tests/test_widget.py"], 300), (["tests/regression/test_anchor.py"], 300)]


def test_3_a_timeout_that_does_not_settle_stays_a_timeout(mutate, project, monkeypatch):
    result, asked = _run(mutate, project, monkeypatch, ["tests"], "timeout", "timeout")
    assert result["outcome"] == "timeout" and "recheck" not in result
    assert len(asked) == 2


def test_4_a_survivor_of_the_whole_suite_is_not_asked_again(mutate, project, monkeypatch):
    result, asked = _run(mutate, project, monkeypatch, ["tests"], "survived")
    assert result["outcome"] == "survived" and "recheck" not in result
    assert asked == [(["tests"], 120)]


def test_4_a_file_that_already_ran_whole_is_not_run_again(mutate, project, monkeypatch):
    result, asked = _run(mutate, project, monkeypatch, ["tests/test_widget.py"], "survived", "survived")
    assert asked == [(["tests/test_widget.py"], 120), (["tests/regression/test_anchor.py"], 300)]
    assert (result["outcome"], result["recheck"]) == ("survived", "survived")


def test_4_nothing_left_to_ask_leaves_the_verdict_as_it_was(mutate, project, monkeypatch):
    (project / "tests" / "regression" / "test_anchor.py").unlink(missing_ok=True)
    monkeypatch.setattr(mutate, "_WORKDIR", str(project))
    fake = Answers("survived")
    monkeypatch.setattr(mutate, "_pytest", fake)
    result = mutate._run(_job(mutate, project, "src/conpact/widget.py", "460->461", ["tests/test_widget.py"]))
    assert result["outcome"] == "survived" and "recheck" not in result
    assert len(fake.asked) == 1


def test_4_an_uncovered_mutant_runs_nothing(mutate, project, monkeypatch):
    result, asked = _run(mutate, project, monkeypatch, [])
    assert result["outcome"] == "uncovered" and asked == []


def test_the_rule_is_written_where_the_tool_is_read(mutate):
    """The docstring is the tool's manual; it must not still say the map decides."""
    doc = " ".join(mutate.__doc__.split())
    assert "before it is recorded as survived" in doc
    assert os.path.basename(__file__) in (ROOT / "docs" / "verification.md").read_text(encoding="utf-8")
