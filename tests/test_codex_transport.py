"""
@module tests.test_codex_transport
@description CU-20261003-090: HTTP opt-in reaches existing OpenAI histories
             without changing foreign providers, targets or ordinary traffic.
@input      Temporary config and native-shaped state database; JSON-RPC lines.
@output     Provider selection, fail-open and byte-preservation assertions.
@dependencies conpact.codex_transport, conpact.codex_sidecar; stdlib json,
              sqlite3, threading; pytest.
"""
import json
import contextlib
import sqlite3
import threading

import pytest

from conpact import codex_transport as transport, codex_sidecar as sidecar


CONFIG = '''model_provider = "openai-http"
[model_providers.openai-http]
name = "OpenAI"
requires_openai_auth = true
wire_api = "responses"
supports_websockets = false
'''


@pytest.fixture
def profile(tmp_path):
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    with contextlib.closing(sqlite3.connect(tmp_path / "state_5.sqlite")) as db:
        db.execute("CREATE TABLE threads (id TEXT, model_provider TEXT, rollout_path TEXT)")
        db.executemany("INSERT INTO threads VALUES (?, ?, ?)", [
            ("old", "openai", str(tmp_path / "old.jsonl")),
            ("foreign", "other-provider", str(tmp_path / "foreign.jsonl")),
        ])
        db.commit()
    return tmp_path, {"CODEX_HOME": str(tmp_path)}


def line(method="thread/resume", **params):
    return (json.dumps({"id": 7, "method": method, "params": {
        "threadId": "old", "excludeTurns": True, **params}}, indent=1)
        .replace("\n", " ") + "\r\n").encode()


@pytest.mark.parametrize("method", ["thread/resume", "thread/fork"])
@pytest.mark.parametrize("provider", [None, "openai"])
def test_old_openai_history_selects_http_without_changing_other_parameters(profile, method, provider):
    root, env = profile
    original = line(method, modelProvider=provider, path=str(root / "old.jsonl"), cwd="working")
    changed = transport.load(environ=env)(original)
    expected = json.loads(original)
    expected["params"]["modelProvider"] = "openai-http"
    assert json.loads(changed) == expected
    assert changed.endswith(b"\r\n")


def test_omitted_provider_and_history_path_are_supported(profile):
    _, env = profile
    assert json.loads(transport.load(environ=env)(line()))["params"]["modelProvider"] == "openai-http"


@pytest.mark.parametrize("method,params", [
    ("thread/start", {}), ("turn/start", {}), ("account/read", {}),
    ("thread/resume", {"threadId": "foreign"}),
    ("thread/resume", {"threadId": "unknown"}),
    ("thread/resume", {"modelProvider": "other-provider"}),
    ("thread/resume", {"modelProvider": "openai-http"}),
    ("thread/resume", {"path": "different-history.jsonl"}),
    ("thread/resume", {"history": []}),
    ("thread/resume", {"config": []}),
    ("thread/resume", {"config": {"model_provider": "other-provider"}}),
    ("thread/resume", {"config": {"profile": "other"}}),
    ("thread/resume", {"config": {"model_providers.openai-http.supports_websockets": True}}),
])
def test_unrelated_or_explicit_configuration_is_byte_preserved(profile, method, params):
    _, env = profile
    original = line(method, **params)
    assert transport.load(environ=env)(original) == original


@pytest.mark.parametrize("raw", [b"{invalid}\n", b"[]\n", b"null\n",
    b'{"id":7,"method":"thread/resume","params":null}\n',
    b'{"method":"thread/resume","params":{"threadId":"old"}}\n',
    b'{"id":7,"method":"thread/resume","params":{"threadId":[]}}\n', b"\xff\n"])
def test_unknown_wire_shapes_are_preserved(profile, raw):
    _, env = profile
    assert transport.load(environ=env)(raw) == raw


@pytest.mark.parametrize("config", ["", "broken = [", CONFIG.replace('"openai-http"', '"openai"', 1),
    CONFIG.replace("supports_websockets = false", "supports_websockets = true"),
    CONFIG.replace("requires_openai_auth = true", "requires_openai_auth = false"),
    CONFIG + 'base_url = "https://other.example"\n',
    'profile = "other"\n' + CONFIG, CONFIG + 'experimental_bearer_token = "synthetic"\n'])
def test_only_explicit_native_auth_default_endpoint_http_opt_in_enables_rewrite(profile, config):
    root, env = profile
    (root / "config.toml").write_text(config, encoding="utf-8")
    original = line()
    assert transport.load(environ=env)(original) == original


@pytest.mark.parametrize("args", [["app-server", "-p", "other"],
    ["app-server", "--profile=other"], ["app-server", "-c", 'model_provider="other"']])
def test_explicit_launch_provider_or_profile_takes_precedence(profile, args):
    _, env = profile
    original = line()
    assert transport.load(environ=env, args=args)(original) == original


def test_missing_or_unreadable_config_and_database_never_prevent_proxying(profile):
    root, env = profile
    (root / "config.toml").unlink()
    assert transport.load(environ=env)(line()) == line()
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")
    (root / "state_5.sqlite").unlink()
    assert transport.load(environ=env)(line()) == line()
    assert not (root / "state_5.sqlite").exists()
    (root / "state_5.sqlite").write_bytes(b"not a database")
    assert transport.load(environ=env)(line()) == line()


def test_read_only_snapshot_performs_no_disk_access_while_forwarding(profile, monkeypatch):
    root, env = profile
    before = (root / "state_5.sqlite").read_bytes()
    transform = transport.load(environ=env)
    def no_io(*args, **kwargs):
        raise AssertionError("I/O on the Desktop pipe")
    monkeypatch.setattr(transport.codex_home, "rows", no_io)
    monkeypatch.setattr(type(root), "read_text", no_io)
    assert json.loads(transform(line()))["params"]["modelProvider"] == "openai-http"
    assert (root / "state_5.sqlite").read_bytes() == before


def test_extended_windows_history_path_corroborates_the_same_target(profile):
    root, env = profile
    original = line(path="\\\\?\\" + str(root / "old.jsonl"))
    assert json.loads(transport.load(environ=env)(original))["params"]["modelProvider"] == "openai-http"


def test_provider_rewrite_also_preserves_a_final_line_without_newline(profile):
    _, env = profile
    original = line(config={"features.example": True}).rstrip(b"\r\n")
    changed = transport.load(environ=env)(original)
    assert not changed.endswith(b"\n")
    assert json.loads(changed)["params"]["modelProvider"] == "openai-http"


def test_a_known_custom_provider_is_preserved_even_when_select_is_given_all_metadata():
    import tomllib
    transform = transport.select(tomllib.loads(CONFIG), [
        {"id": "old", "model_provider": "foreign", "rollout_path": "history.jsonl"}])
    assert transform(line()) == line()


def test_desktop_pump_applies_opt_in_between_complete_lines(profile):
    _, env = profile
    original = line()
    chunks = [original[:9], original[9:], b'{"id":8,"method":"account/read"}\n', b""]
    class Sink:
        def __init__(self):
            self.data = bytearray()
        def write(self, data):
            self.data.extend(data)
            return len(data)
        def flush(self):
            pass
        def close(self):
            pass
    sink = Sink()
    sidecar.pump_to_child(lambda _: chunks.pop(0), sink, threading.Lock(),
                          transform=transport.load(environ=env))
    changed, untouched = bytes(sink.data).splitlines()
    assert json.loads(changed)["params"]["modelProvider"] == "openai-http"
    assert untouched == b'{"id":8,"method":"account/read"}'
