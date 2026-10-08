"""
@module tests.regression.test_codex_http_probe
@description Native regression test for CU-20261003-089: HTTP inference and
             compaction complete without a WebSocket upgrade.
@input      Explicit native Codex executable; optional --websocket-control.
@output     Wire assertions and recorded compaction; the control must fail.
@dependencies conpact.codex_appserver.AppServer, conpact.codex_transport,
              conpact.codex_home; stdlib argparse, http.server, json, os,
              pathlib, subprocess, tempfile, threading, time, tomllib.

Explicit opt-in: python tests/regression/test_codex_http_probe.py <codex executable>.
The native child uses synthetic credentials, localhost endpoints and a temporary
profile. It is independent of Desktop and never loads a user's existing chat.
"""
from pathlib import Path
import argparse
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from conpact.codex_appserver import AppServer
from conpact import codex_home, codex_transport


class SelectedInput:
    """Apply the production snapshot transform to complete native RPC lines."""
    def __init__(self, stream, transform):
        self.stream, self.transform = stream, transform

    def write(self, text):
        assert text.endswith("\n") and text.count("\n") == 1
        return self.stream.write(self.transform(text.encode()).decode())

    def flush(self):
        self.stream.flush()

    def close(self):
        self.stream.close()

    @property
    def closed(self):
        return self.stream.closed


class Backend(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append(("GET", self.path, self.headers.get("Upgrade")))
        self._reply(404 if self.headers.get("Upgrade") else 200,
                    "application/json", json.dumps({"models": []}).encode())

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append(("POST", self.path, self.headers.get("Upgrade")))
        if self.server.compacting:
            item = {"id": "comp_probe", "type": "compaction",
                    "encrypted_content": "offline-compaction-probe"}
        else:
            item = {"id": "msg_probe", "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text",
                        "text": "HTTP transport probe completed."}]}
        events = [
            {"type": "response.created", "response": {"id": "resp_probe"}},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp_probe",
                "status": "completed", "output": [item], "usage": {
                    "input_tokens": 20, "output_tokens": 7, "total_tokens": 27,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0}}}},
        ]
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
        self._reply(200, "text/event-stream", body)

    def _reply(self, status, kind, data):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def isolated_environment(owned):
    env = dict(os.environ)
    for key in list(env):
        if any(word in key.upper() for word in
               ("TOKEN", "API_KEY", "PROXY", "CONPACT", "CODEX", "OPENAI", "CHATGPT")):
            env.pop(key, None)
    for key in ("CODEX_HOME", "HOME", "USERPROFILE", "APPDATA",
                "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        env[key] = str(owned)
    env.pop("PYTHONPATH", None)
    return env


def test_probe_redirects_all_profile_fallbacks_and_clears_credentials(tmp_path, monkeypatch):
    """Ordinary suite assertion: a fallback in this probe owns only fake state."""
    for name in ("OPENAI_API_KEY", "CHATGPT_TOKEN", "HTTP_PROXY", "CODEX_HOME",
                 "CONPACT_CODEX_REAL", "PYTHONPATH"):
        monkeypatch.setenv(name, "synthetic-source-value")
    env = isolated_environment(tmp_path)
    for name in ("CODEX_HOME", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        assert env[name] == str(tmp_path)
    for name in ("OPENAI_API_KEY", "CHATGPT_TOKEN", "HTTP_PROXY", "CONPACT_CODEX_REAL", "PYTHONPATH"):
        assert name not in env
    assert os.environ["OPENAI_API_KEY"] == "synthetic-source-value"
    assert codex_home.home(env) == tmp_path


def test_documented_fragment_enables_only_native_auth_default_endpoint_http():
    config = tomllib.loads((ROOT / "docs/codex-http.toml").read_text(encoding="utf-8"))
    assert codex_transport.opted_in(config)
    assert set(config) == {"model_provider", "model_providers"}
    assert config["model_providers"]["openai-http"] == {
        "name": "OpenAI", "requires_openai_auth": True,
        "wire_api": "responses", "supports_websockets": False}


def request(server, method, params):
    reply = server.request(method, params, 15)
    assert "result" in reply, reply.get("error")
    return reply["result"]


def completed_turn(server):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        message = server.inbox.get(timeout=deadline - time.monotonic())
        assert message is not None, "native app-server exited"
        if message.get("method") == "turn/completed":
            turn = message["params"]["turn"]
            assert turn["status"] == "completed", turn.get("error")
            return
    raise TimeoutError("native turn did not complete")


def shutdown(process):
    """Allow native EOF cleanup before terminating an owned test process."""
    if not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    process.stdout.close()


def probe(cli, owned, websocket_control):
    backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend.requests, backend.compacting = [], False
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{backend.server_port}"
    original_fragment = (ROOT / "docs/codex-http.toml").read_text(encoding="utf-8")
    fragment = original_fragment
    if websocket_control:
        fragment = fragment.replace("supports_websockets = false",
                                    "supports_websockets = true")
    config = f'model = "gpt-6.1-sol"\ncli_auth_credentials_store = "file"\nopenai_base_url = "{url}"\n' + fragment
    config += f'\nbase_url = "{url}"\nmodel_catalog_url = "{url}/models"\n'
    config += '[features]\napps = false\nplugins = false\nmemories = false\n'
    (owned / "config.toml").write_text(config, encoding="utf-8")
    (owned / "auth.json").write_text(json.dumps({
        "OPENAI_API_KEY": "offline-probe-only"}), encoding="utf-8")
    with (owned / "stderr.log").open("w", encoding="utf-8") as err:
        process = subprocess.Popen([str(cli), "app-server"], cwd=owned,
            env=isolated_environment(owned), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        server = AppServer(process)
        try:
            request(server, "initialize", {"clientInfo": {
                "name": "conpact_transport_probe", "version": "1"},
                "capabilities": {"experimentalApi": True}})
            process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
            process.stdin.flush()
            config = request(server, "config/read", {"includeLayers": False})["config"]
            assert config["model_provider"] == "openai-http"
            assert config["model_providers"]["openai-http"]["requires_openai_auth"]
            assert request(server, "account/read", {"refreshToken": False})["account"]["type"] == "apiKey"
            result = request(server, "thread/start", {"cwd": str(owned),
                "approvalPolicy": "never", "sandbox": "read-only", "model": "gpt-6.1-sol",
                "modelProvider": "openai"})
            assert result["modelProvider"] == "openai"
            tid = result["thread"]["id"]
            request(server, "turn/start", {"threadId": tid, "input": [
                {"type": "text", "text": "Create an offline history under the previous provider."}]})
            completed_turn(server)
            shutdown(process)
            process = subprocess.Popen([str(cli), "app-server"], cwd=owned,
                env=isolated_environment(owned), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            # The policy sees the documented default-endpoint user opt-in and
            # the real history the first native process just saved. Only the
            # test child's endpoints are overridden to the local fake backend.
            histories = codex_home.rows(owned / "state_5.sqlite",
                "SELECT id, model_provider, rollout_path FROM threads")
            assert any(row["id"] == tid and row["model_provider"] == "openai"
                       for row in histories), histories
            process.stdin = SelectedInput(process.stdin,
                codex_transport.select(tomllib.loads(original_fragment), histories))
            server = AppServer(process)
            request(server, "initialize", {"clientInfo": {
                "name": "conpact_transport_probe", "version": "1"},
                "capabilities": {"experimentalApi": True}})
            process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
            process.stdin.flush()
            result = request(server, "thread/resume", {"threadId": tid,
                "modelProvider": None, "excludeTurns": True})
            assert result["modelProvider"] == "openai-http", result["modelProvider"]
            backend.requests.clear()
            request(server, "turn/start", {"threadId": tid, "input": [
                {"type": "text", "text": "Resume the offline protocol test over HTTP."}]})
            completed_turn(server)
            assert not any(upgrade for _, _, upgrade in backend.requests), backend.requests
            backend.compacting = True
            request(server, "thread/compact/start", {"threadId": tid})
            completed_turn(server)
            assert sum(method == "POST" and path.endswith("/responses")
                       for method, path, _ in backend.requests) == 2, backend.requests
            assert not any(upgrade for _, _, upgrade in backend.requests), backend.requests
            rollouts = list((owned / "sessions").rglob(f"*{tid}.jsonl"))
            assert len(rollouts) == 1, rollouts
            records = [json.loads(line) for line in rollouts[0].read_text(encoding="utf-8").splitlines()]
            assert any(record.get("type") == "compacted" for record in records)
            shutdown(process)
            histories = codex_home.rows(owned / "state_5.sqlite",
                "SELECT id, model_provider, rollout_path FROM threads")
            process = subprocess.Popen([str(cli), "app-server"], cwd=owned,
                env=isolated_environment(owned), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            process.stdin = SelectedInput(process.stdin,
                codex_transport.select(tomllib.loads(original_fragment), histories))
            server = AppServer(process)
            request(server, "initialize", {"clientInfo": {
                "name": "conpact_transport_probe", "version": "1"},
                "capabilities": {"experimentalApi": True}})
            process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
            process.stdin.flush()
            result = request(server, "thread/resume", {"threadId": tid,
                "modelProvider": None, "excludeTurns": True})
            assert result["modelProvider"] == "openai-http", (result["modelProvider"], histories)
            print("PASS: history from the built-in provider resumes under the configured HTTP provider")
            print("PASS: a second native restart/resume retains HTTP selection")
            print("PASS: native response and recorded compaction; two HTTP POSTs; zero WebSocket upgrades")
            print("PASS: synthetic credentials, file credential store, localhost endpoints and temporary state")
        finally:
            if sys.exc_info()[0] is not None:
                err.flush()
                print("PROBE FAILURE: observed localhost requests", backend.requests, flush=True)
                print("PROBE FAILURE: native diagnostic tail",
                      (owned / "stderr.log").read_text(encoding="utf-8", errors="replace")[-3000:],
                      flush=True)
            shutdown(process)
            backend.shutdown()
            backend.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codex", type=Path)
    parser.add_argument("--websocket-control", action="store_true")
    args = parser.parse_args()
    cli = args.codex.resolve(strict=True)
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="http-native-", dir=ROOT / "tmp") as directory:
        probe(cli, Path(directory), args.websocket_control)
