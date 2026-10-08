"""Regression: the real codex is chosen by recency, never by folder name.

Codex installs each build into a folder named by a content hash, so the names
carry no order. Sorting them and taking the last picked whichever hash happened
to sort last: measured on 2026-09-22, that was the 2026-09-18 build rather than
the 2026-09-19 one actually installed. Two things follow from pinning the wrong
one, and both were real - the sidecar keeps launching a superseded codex, and
the superseded folder may hold a bare `codex.exe` where the current one ships
the helper binaries codex resolves relative to itself.
"""
import os

import pytest

from conpact import codex_appserver


def _build(root, name, mtime, helpers=()):
    folder = root / "OpenAI" / "Codex" / "bin" / name
    folder.mkdir(parents=True)
    exe = folder / "codex.exe"
    exe.write_text("", encoding="utf-8")
    for helper in helpers:
        (folder / helper).write_text("", encoding="utf-8")
    os.utime(exe, (mtime, mtime))
    return exe


def test_the_newest_build_wins_even_when_its_name_sorts_first(tmp_path):
    """The exact shape that bit: the newer build's hash sorts before the older."""
    older = _build(tmp_path, "cdef5aaf3e41ab53", 1_789_723_284.0)
    newer = _build(tmp_path, "247581e40ee272fb", 1_789_811_209.0,
                   helpers=("codex-command-runner.exe", "codex-code-mode-host.exe"))

    chosen = codex_appserver.newest_install(tmp_path)

    assert chosen == newer, "a content hash is not a version; recency is"
    assert chosen != older
    assert (chosen.parent / "codex-command-runner.exe").is_file(), \
        "the chosen build must be the one its helper binaries sit beside"


def test_codex_cli_resolves_through_the_newest_build(tmp_path):
    _build(tmp_path, "cdef5aaf3e41ab53", 1_789_723_284.0)
    newer = _build(tmp_path, "247581e40ee272fb", 1_789_811_209.0)

    found = codex_appserver.codex_cli({"LOCALAPPDATA": str(tmp_path)})

    assert found == newer


def test_a_build_that_vanishes_mid_scan_does_not_lose_the_lookup(tmp_path):
    """A folder removed between the scan and the stat is skipped, not fatal:
    Codex prunes old builds, and a sweep can land in the middle of one."""
    good = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_789_723_284.0)
    gone = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_789_811_209.0)
    gone.unlink()

    class Scan:
        def glob(self, _pattern):
            return iter([good, gone])

    assert codex_appserver.newest_install(Scan()) == good


def test_a_scan_that_fails_outright_is_none_not_a_crash():
    class Broken:
        def glob(self, _pattern):
            raise OSError("the volume is gone")

    assert codex_appserver.newest_install(Broken()) is None


def test_no_install_at_all_is_none_not_an_error(tmp_path):
    assert codex_appserver.newest_install(tmp_path) is None


@pytest.mark.parametrize("name", ["codex-command-runner.exe",
                                  "codex-code-mode-host.exe"])
def test_helpers_are_not_mistaken_for_the_cli(tmp_path, name):
    """Only `codex.exe` is the CLI; its siblings must never be returned."""
    _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_789_723_284.0, helpers=(name,))

    assert codex_appserver.newest_install(tmp_path).name == "codex.exe"


class TestThePinIsOneLever:
    """`CONPACT_CODEX_REAL` is the escape hatch the recency rule leaves open
    (D-20260922-039). It has to reach both paths: the shim, and the app-servers
    conPACT starts itself. Pinning only one of them is how a machine ends up
    running two different codex builds without anyone noticing."""

    def test_the_shim_and_the_resolver_read_the_same_variable(self):
        from conpact import codex_sidecar
        assert codex_sidecar.REAL_ENV == codex_appserver.REAL_CODEX_ENV

    def test_the_pin_beats_the_newest_build(self, tmp_path):
        pinned = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_789_723_284.0)
        newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_789_811_209.0)

        found = codex_appserver.codex_cli({"CONPACT_CODEX_REAL": str(pinned),
                                           "LOCALAPPDATA": str(tmp_path)})

        assert found == pinned and found != newest

    def test_the_pin_beats_codex_cli_path_too(self, tmp_path):
        pinned = _build(tmp_path, "aaaaaaaaaaaaaaaa", 1_789_723_284.0)
        other = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_789_811_209.0)

        found = codex_appserver.codex_cli({"CONPACT_CODEX_REAL": str(pinned),
                                           "CODEX_CLI_PATH": str(other)})

        assert found == pinned

    @pytest.mark.parametrize("value", ["", "   ", r"C:\nowhere\codex.exe"])
    def test_a_pin_that_names_nothing_usable_is_ignored(self, value, tmp_path):
        newest = _build(tmp_path, "bbbbbbbbbbbbbbbb", 1_789_811_209.0)

        found = codex_appserver.codex_cli({"CONPACT_CODEX_REAL": value,
                                           "LOCALAPPDATA": str(tmp_path)})

        assert found == newest, "an unusable pin must not blank the lookup"
