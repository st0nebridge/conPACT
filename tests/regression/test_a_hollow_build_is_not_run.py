"""
Regression test for CU-20261002-082 (a hollow codex build is never run).

Codex prunes a superseded build by deleting its folder, but a `codex.exe` that a
running process still holds open cannot be deleted - so the prune leaves the
folder holding the bare executable and nothing else. Measured on 2026-10-02: the
sidecar's marker, written at install, still named such a build two days after
Codex had moved on. The name passed the "still a file" test (D-20260922-041), so
ChatGPT Desktop ran it, and every command it tried failed with "failed to spawn
code-mode host ...\\codex-code-mode-host.exe: The system cannot find the file
specified". Nothing could be run until the desktop was restarted against a
corrected marker. The contract (D-20261002-063):

  1. A name conPACT wrote for codex is used only while the build it names is
     whole: when the newest install holds a file beside its codex that the named
     build's folder lacks, the named build is hollow and the newest runs instead.
  2. The marker is a fallback. An installed update wins even when the old
     build is whole (D-20261003-066 supersedes this part of D-20261002-063).
  3. CONPACT_CODEX_REAL is the user saying which build, and is not second-guessed.
"""
import os

from conpact import codex_appserver
from conpact import codex_sidecar as sc

HELPERS = ("codex-command-runner.exe", "codex-code-mode-host.exe",
           "codex-windows-sandbox-setup.exe")


def _build(root, name, mtime, helpers=HELPERS):
    folder = root / "OpenAI" / "Codex" / "bin" / name
    folder.mkdir(parents=True)
    exe = folder / "codex.exe"
    exe.write_text("", encoding="utf-8")
    for helper in helpers:
        (folder / helper).write_text("", encoding="utf-8")
    os.utime(exe, (mtime, mtime))
    return exe


def _marker(beside, exe):
    (beside / codex_appserver.REAL_CODEX_MARKER).write_text(str(exe), encoding="utf-8")


def _shim(root):
    folder = root / "sidecar"
    folder.mkdir()
    shim = folder / "codex_sidecar.exe"
    shim.write_text("", encoding="utf-8")
    return shim


def test_1_the_sidecar_does_not_run_a_build_codex_has_hollowed_out(tmp_path):
    """The exact shape of 2026-10-02: the marker names a folder holding only
    codex.exe, and the build Codex installed since has its helpers beside it."""
    hollow = _build(tmp_path, "ca9abb0b4d8ac692", 1_790_729_000.0, helpers=())
    newest = _build(tmp_path, "c6fe824d725f02d7", 1_790_754_000.0)
    _marker(tmp_path, hollow)

    found = sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path)

    assert found == str(newest), "a build without its helpers cannot run a command"


def test_1_conpacts_own_tooling_does_not_reach_a_hollow_build_through_the_shim(tmp_path):
    hollow = _build(tmp_path, "ca9abb0b4d8ac692", 1_790_729_000.0, helpers=())
    newest = _build(tmp_path, "c6fe824d725f02d7", 1_790_754_000.0)
    shim = _shim(tmp_path)
    _marker(shim.parent, hollow)

    found = codex_appserver.codex_cli({"LOCALAPPDATA": str(tmp_path),
                                       "CODEX_CLI_PATH": str(shim)})

    assert found == newest


def test_1_a_build_missing_only_one_helper_is_still_hollow(tmp_path):
    partial = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_790_729_000.0, helpers=HELPERS[:1])
    newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0)
    _marker(tmp_path, partial)

    assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path) == str(newest)


def test_2_an_older_build_that_is_whole_gives_way_to_the_update(tmp_path):
    older = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_790_729_000.0)
    newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0)
    _marker(tmp_path, older)

    assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path) == str(newest)
    shim = _shim(tmp_path)
    _marker(shim.parent, older)
    assert codex_appserver.codex_cli({"LOCALAPPDATA": str(tmp_path),
                                      "CODEX_CLI_PATH": str(shim)}) == newest


def test_2_the_marker_naming_the_newest_build_is_that_build(tmp_path):
    _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_790_729_000.0, helpers=())
    newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0)
    _marker(tmp_path, newest)

    assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path) == str(newest)


def test_2_a_marker_outside_the_install_folders_is_judged_against_them(tmp_path):
    """Even a complete custom marker is a fallback; use the environment to pin."""
    newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0)
    own = tmp_path / "mine"
    own.mkdir()
    for name in ("codex.exe",) + HELPERS:
        (own / name).write_text("", encoding="utf-8")
    _marker(tmp_path, own / "codex.exe")

    assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)},
                         beside=tmp_path) == str(newest)


def test_2_with_nothing_installed_to_compare_the_marker_stands(tmp_path):
    lone = tmp_path / "codex.exe"
    lone.write_text("", encoding="utf-8")
    _marker(tmp_path, lone)

    assert sc.real_codex({"LOCALAPPDATA": str(tmp_path / "empty")},
                         beside=tmp_path) == str(lone)


def test_3_the_environment_pin_is_not_second_guessed(tmp_path):
    hollow = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_790_729_000.0, helpers=())
    _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0)
    env = {"LOCALAPPDATA": str(tmp_path), "CONPACT_CODEX_REAL": str(hollow)}

    assert sc.real_codex(env, beside=tmp_path) == str(hollow)
    assert codex_appserver.codex_cli(env) == hollow


def test_1_a_folder_that_cannot_be_listed_is_not_called_hollow(tmp_path):
    """Listing a folder can fail; that is not evidence the build is broken."""
    named = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_790_729_000.0, helpers=())
    newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0)

    def unlistable(_folder):
        raise OSError("access is denied")

    assert codex_appserver.hollow(named, newest) is True
    assert codex_appserver.hollow(named, newest, lister=unlistable) is False


def test_1_the_newest_build_is_never_hollow_beside_itself(tmp_path):
    newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_790_754_000.0, helpers=())

    assert codex_appserver.hollow(newest, newest) is False
    assert codex_appserver.hollow(newest, None) is False


def test_1_with_no_install_to_fall_back_to_the_marker_is_kept_as_it_was(tmp_path):
    """No newer build to run instead: the marker's name is passed on unchanged,
    as before this rule, so the failure is codex's own rather than ours."""
    shim = _shim(tmp_path)
    gone = tmp_path / "pruned" / "codex.exe"
    _marker(shim.parent, gone)

    found = codex_appserver.codex_cli({"LOCALAPPDATA": str(tmp_path / "empty"),
                                       "CODEX_CLI_PATH": str(shim)})

    assert found == gone
