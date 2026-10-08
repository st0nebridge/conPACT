"""
@module tests.regression.test_timeout_is_not_detection
@description The mutation tester once counted a timed-out mutant as detected. It is
             not: the run hit its limit, which says nothing about whether a test
             would have failed. Re-checking the 39 timeouts behind this repo's
             published scores found 8 real survivors hiding in them, one of which
             silently disabled `python -m conpact.settings_window` (D-20260920-025).
@input      tools/mutate.py, loaded from source
@output     assertions on how a timeout is scored and how it is re-checked
@dependencies stdlib: importlib, pathlib, subprocess, sys
"""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "mutate.py"


@pytest.fixture(scope="module")
def mutate():
    spec = importlib.util.spec_from_file_location("mutate_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_timeout_is_never_counted_as_a_kill(mutate):
    """The bug in one line: with timeouts counted as detected, a module whose every
    mutant timed out scored 100%."""
    assert mutate.score({"killed": 0, "survived": 0, "uncovered": 0, "timeout": 10}) == 0.0
    assert mutate.score({"killed": 9, "survived": 1, "uncovered": 0, "timeout": 0}) == 90.0
    assert mutate.score({"killed": 8, "survived": 1, "uncovered": 1, "timeout": 0}) == 80.0
    # Every outcome that is not a kill sits in the denominator, and only there.
    assert mutate.score({"killed": 5, "survived": 1, "uncovered": 2, "timeout": 2}) == 50.0
    assert mutate.score({"killed": 0, "survived": 0, "uncovered": 0, "timeout": 0}) is None


def test_a_score_already_written_into_the_counts_is_not_counted_again(mutate):
    counts = {"killed": 3, "survived": 1, "uncovered": 0, "timeout": 0}
    counts["score"] = mutate.score(counts)
    assert mutate.score(counts) == 75.0      # re-scoring a summarised module is stable


def test_a_timed_out_mutant_is_re_asked_of_its_own_modules_tests(mutate):
    """What makes these mutants time out is that they are covered by the whole suite:
    a module-level constant maps to every test there is. The module's own test file
    is the subset that can answer in time."""
    covering = ["tests/test_toast_view.py::test_a", "tests/test_idle_watch.py::test_b",
                "tests/test_toast_text.py::test_c", "tests/test_toast_view.py::test_d"]
    assert mutate._own_tests("src/conpact/toast_view.py", covering) == [
        "tests/test_toast_view.py::test_a", "tests/test_toast_view.py::test_d"]
    # test_toast_text.py must not answer for toast_view.py on a prefix match.
    assert mutate._own_tests("src/conpact/toast.py", covering) == []


def test_the_retry_reaches_the_whole_suite_case_it_was_written_for(mutate, tmp_path, monkeypatch):
    """The bug this test used to assert as correct: a line executed only at import has
    no per-test coverage context, so line_to_tests maps it to the whole directory -
    the single entry ["tests"], which names no test file. _own_tests found nothing in
    it, the caller's `if own:` was false, and the mutant kept its timeout. Measured:
    92 of 93 timeouts in one run stopped dead at the first limit, never re-checked.
    The module's own test file is on disk whether or not a context named it."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_desktop.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(mutate, "_WORKDIR", str(tmp_path))
    assert mutate._own_tests("src/conpact/desktop.py", ["tests"]) == ["tests/test_desktop.py"]
    # A module with no test file of its own still has nothing to narrow to, and the
    # caller keeps the timeout rather than inventing a verdict.
    assert mutate._own_tests("src/conpact/untested.py", ["tests"]) == []


def test_a_retry_is_never_invented_without_a_workdir_to_look_in(mutate, monkeypatch):
    monkeypatch.setattr(mutate, "_WORKDIR", None)
    assert mutate._own_tests("src/conpact/desktop.py", ["tests"]) == []


def test_the_limit_is_enforced_and_reported_as_a_timeout(mutate, tmp_path, monkeypatch):
    """The real subprocess path: a test that never returns is killed and recorded as
    a timeout, not as a pass and not as a kill."""
    (tmp_path / "test_hangs.py").write_text("import time\n\n\ndef test_hangs():\n    time.sleep(90)\n",
                                            encoding="utf-8")
    (tmp_path / "test_passes.py").write_text("def test_passes():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(mutate, "_WORKDIR", str(tmp_path))
    env = {**dict(__import__("os").environ), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    assert mutate._pytest(["test_hangs.py"], env, limit=3) == "timeout"
    assert mutate._pytest(["test_passes.py"], env, limit=120) == "survived"


def test_the_tool_still_runs(mutate):
    """It is the instrument behind every score in the README; a syntax error in it
    would otherwise only show up an hour into a run."""
    done = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True)
    assert done.returncode != 0                      # it needs arguments
    assert "Traceback" not in done.stderr or "IndexError" in done.stderr
