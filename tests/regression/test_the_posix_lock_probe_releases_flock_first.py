"""
Regression test for CU-20260924-069 (the full suite passes on a real Mac).

macOS makes flock and lockf conflict even on one descriptor, so the POSIX lock probe
releases its flock before it tries lockf. Contributed by Lance Sandino (pull request
#1 of the public repository); moved here from tests/test_codex_threads.py when it was
brought into this history, unchanged but for leaving its class.
"""
import pytest

from conpact import codex_threads


def test_the_flock_probe_is_released_before_the_lockf_probe(tmp_path, monkeypatch):
    """macOS makes the two lock kinds conflict even on our own descriptor."""
    pytest.importorskip("fcntl")
    path = tmp_path / "x.lock"
    path.write_bytes(b"")
    calls = []

    class MacLocks:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 8

        @staticmethod
        def flock(_fd, mode):
            calls.append(("flock", mode))

        @staticmethod
        def lockf(_fd, mode, _length):
            calls.append(("lockf", mode))
            if not (len(calls) >= 2 and calls[-2] == ("flock", MacLocks.LOCK_UN)):
                raise OSError(35, "Resource temporarily unavailable")

    monkeypatch.setattr(codex_threads, "_fcntl", MacLocks)
    assert codex_threads._probe_posix(path) is False
    assert calls == [
        ("flock", MacLocks.LOCK_EX | MacLocks.LOCK_NB),
        ("flock", MacLocks.LOCK_UN),
        ("lockf", MacLocks.LOCK_EX | MacLocks.LOCK_NB),
        ("lockf", MacLocks.LOCK_UN),
    ]
