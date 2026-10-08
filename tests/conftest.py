"""Test bootstrap: put the package's src/ root on sys.path, and keep every test
away from the real ~/.claude, the real ~/.conpact, the network, and the user's
screens and keyboard."""
import contextlib
import os
import shutil
import sys
import tempfile

import pytest

import window_guard

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# The home every test runs under, and every process a test starts inherits.
# The fixture below patches module constants, which reaches nothing outside this
# process: on 2026-09-23 a test that ran `tools/settings.py --help` as a child
# started conPACT with the real home, and its first act - moving the old state
# folder into ~/.conpact/ - moved the user's live settings. So the environment
# the constants are computed from is itself a throwaway, set before any conpact
# module is imported, and the real value is kept only to prove it is not seen.
_HOME_VARIABLES = ("HOME", "USERPROFILE")
REAL_HOME = os.path.expanduser("~")
_saved = {name: os.environ.get(name) for name in _HOME_VARIABLES}
FAKE_HOME = tempfile.mkdtemp(prefix="conpact-test-home-")
for _name in _HOME_VARIABLES:
    os.environ[_name] = FAKE_HOME


def pytest_unconfigure(config):
    for name, value in _saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    shutil.rmtree(FAKE_HOME, ignore_errors=True)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_paths: read the real module path constants (the test must not write)")
    config.addinivalue_line("markers", "real_spawn: may call detach.spawn (with an injected popen)")
    config.addinivalue_line("markers", "real_ui: may put a real toast window on screen")
    config.addinivalue_line(
        "markers", "real_open: tests desktop.open_url itself (with an injected starter, never the shell)")
    config.addinivalue_line(
        "markers", "real_present: tests toast_view.present itself (with the desktop calls injected, "
                   "so no window is ever mapped)")
    config.addinivalue_line(
        "markers", "real_settings_run: tests settings_window.run itself, or the module run as -m, "
                   "whose fresh namespace the guard below cannot reach (the window is never mapped "
                   "and never takes the keyboard)")


@pytest.fixture(scope="session", autouse=True)
def _spend_tk_first_activation():
    """Tk activates the first window a thread creates, even one never shown,
    which takes the keyboard from the user (CU-20260924-063). It happens here,
    once, before any test, on a window that is never shown, so that no test's
    window is ever the first."""
    if window_guard.WINDOWS:
        import tkinter
        window_guard.spend_first_activation(tkinter)


@pytest.fixture(autouse=True)
def _a_uid_where_the_os_has_none(monkeypatch):
    """The macOS tests run on every platform, and the launchd code asks for the
    caller's uid; Windows has no os.getuid, so there it reads a typical Mac's
    first user. Where the OS has one, the real uid is used."""
    if not hasattr(os, "getuid"):
        monkeypatch.setattr(os, "getuid", lambda: 501, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_state(request, monkeypatch, tmp_path_factory):
    """
    No test may reach the network, start a detached process, show a toast,
    open the settings window, hand a url to the desktop, or
    read or write the real credentials, session records, requests, idle state
    or logs. Nor, unless it is `real_ui`, may a window of the test take the
    keyboard, be shown as anything a window manager would move, or land on a
    screen (window_guard). A test that forgets to inject a fake fails loudly
    here instead of touching the user's live setup.

    Each guard also records the breach, because raising is not enough: the
    watcher swallows whatever a presenter raises, so that a broken toast can
    never crash it. A breach that never reaches the test still fails it here.
    A test whose point is that a guard fires takes this fixture by name and
    clears the list it yields.
    """
    from conpact import (bridge_client, closure_hook, codex_appserver, codex_env, codex_host,
                             codex_inject, codex_sidecar_window, compaction, context_meter, desktop,
                             detach, home, keychain, session_registry, settings_window, toast_view,
                             token_store)
    breaches = []

    def guard(what):
        def refuse(*a, **k):
            breaches.append(what)
            raise AssertionError(f"tests must not {what}")
        return refuse

    no_network = guard("reach the network")
    monkeypatch.setattr(token_store, "_post_token", no_network)
    # On a Mac the default credentials lookup reads the real Keychain, which
    # holds the user's live login; every test hands in its own reader.
    monkeypatch.setattr(keychain, "_run", guard("read the real Keychain"))
    monkeypatch.setattr(bridge_client, "_urlopen", no_network)
    # Starting a real `codex app-server` would load one of the user's own Codex
    # threads and could spend tokens on their account; every test injects a fake.
    monkeypatch.setattr(codex_appserver, "start_process", guard("start a codex app-server"))
    # Our own app-server outlives the process that starts it, and enrolling it
    # changes the user's ChatGPT account; no test may start or signal one.
    monkeypatch.setattr(codex_host, "free_port", guard("bind a real port"))
    monkeypatch.setattr(codex_host, "_kill", guard("signal a real process"))
    # The sidecar channel reaches the desktop's own live app-server; a test that
    # opens it for real would inject into the user's running ChatGPT.
    monkeypatch.setattr(codex_inject, "_open", guard("open the sidecar channel"))
    # Installing writes CODEX_CLI_PATH into the user's own environment; no test
    # may touch the real registry, run launchctl, broadcast the change, or write
    # the real login agent / environment.d drop-in.
    monkeypatch.setattr(codex_env, "_win_open", guard("open the user environment key"))
    monkeypatch.setattr(codex_env, "_win_broadcast", guard("broadcast an environment change"))
    monkeypatch.setattr(codex_env, "_run", guard("run a real environment command"))
    monkeypatch.setattr(codex_env, "_winreg", guard("import the real registry module"))
    if not request.node.get_closest_marker("real_spawn"):
        monkeypatch.setattr(detach, "spawn", guard("start detached processes"))
    if not request.node.get_closest_marker("real_open"):
        monkeypatch.setattr(desktop, "open_url", guard("open anything on the desktop"))
    if not request.node.get_closest_marker("real_ui"):
        if not request.node.get_closest_marker("real_present"):
            monkeypatch.setattr(toast_view, "present", guard("show toasts"))
        if not request.node.get_closest_marker("real_settings_run"):
            monkeypatch.setattr(settings_window, "run", guard("open the settings window"))
            monkeypatch.setattr(codex_sidecar_window, "run",
                                guard("open the sidecar window"))
    if request.node.get_closest_marker("real_paths"):
        # The real constants, read and never written: moving the user's own
        # state folder is the one thing such a test could still do by accident.
        monkeypatch.setattr(home, "migrate", guard("move the real state folder"))
    else:
        user = tmp_path_factory.mktemp("home")
        claude = user / ".claude"
        state = user / ".conpact"
        monkeypatch.setattr(session_registry, "CLAUDE_DIR", claude)
        monkeypatch.setattr(session_registry, "SESSIONS_DIR", claude / "sessions")
        monkeypatch.setattr(token_store, "CREDENTIALS", claude / ".credentials.json")
        # conPACT's own home, and the two earlier folders the move reads from:
        # all three are real paths under the user's home, and every entry point
        # now moves the old one's contents - so each is isolated, or a test
        # moves or reads the machine's live state.
        monkeypatch.setattr(home, "HOME", state)
        monkeypatch.setattr(home, "PREVIOUS", claude / "conpact")
        monkeypatch.setattr(home, "CLAUTOMATIC", claude / "clautomatic")
        monkeypatch.setattr(compaction, "STATE_DIR", state)
        monkeypatch.setattr(compaction, "REQUESTS_DIR", state / "requests")
        monkeypatch.setattr(compaction, "PREVIOUS_REQUESTS_DIR", claude / "conpact" / "requests")
        monkeypatch.setattr(compaction, "LEGACY_REQUESTS_DIR", claude / "clautomatic" / "requests")
        monkeypatch.setattr(closure_hook, "LOG_PATH", state / "hook-log.jsonl")
        monkeypatch.setattr(context_meter, "PROJECTS_DIR", claude / "projects")
        # ChatGPT Desktop's state is the user's too: a test that forgets to pass
        # a CODEX_HOME reads an empty folder rather than their 105 live threads.
        monkeypatch.setenv("CODEX_HOME", str(tmp_path_factory.mktemp("codex")))
        # The macOS login agent and the Linux environment.d drop-in are written
        # under a home; no test may write the user's own.
        monkeypatch.setattr(codex_env, "HOME", tmp_path_factory.mktemp("envhome"))
    # A window guard cannot raise: its breach happens inside Tk, which would
    # swallow the error, so it only records - which the assertion below reads.
    desktop_guard = (contextlib.nullcontext() if request.node.get_closest_marker("real_ui")
                     else window_guard.Guard(record=breaches.append))
    with desktop_guard:
        yield breaches
    assert breaches == [], f"a guard fired during the test: {breaches}"
