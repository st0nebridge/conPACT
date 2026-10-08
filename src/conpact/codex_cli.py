"""
@module conpact.codex_cli
@description Launch Codex CLI through conPACT's reachable local app-server
             (`conpact-codex`). The terminal UI supports a remote app-server
             endpoint. conPACT already runs a loopback-only,
             capability-token-protected endpoint for Codex Remote Control, so
             the launcher starts (or reuses) it and execs the real CLI as its
             client. The token is passed through a named environment variable,
             never on the command line. A user-scope Stop hook, installed with
             `--install` and trusted by the user in Codex, then receives the
             exact task id and runs a queued compaction through that same
             owning app-server. Contributed by Lance Sandino.
@input      argv: --install, --uninstall, --status, or the arguments for codex
@output     the user's Codex hooks.json with conPACT's Stop handler merged in or
            taken out; or this process replaced by the Codex CLI
@dependencies conpact.codex_appserver, conpact.codex_home, conpact.codex_host,
              conpact.home; stdlib: contextlib, json, os, pathlib, shlex,
              shutil, subprocess, sys
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys

from . import codex_appserver, codex_home, codex_host, home

AUTH_ENV = "CONPACT_CODEX_AUTH_TOKEN"
HOOK_MODULE = "conpact.codex_cli_hook"
HOOK_ENTRY = pathlib.Path(__file__).with_name("codex_cli_hook_entry.py").resolve()
HOOK_TIMEOUT = 600


def hooks_path(environ=None) -> pathlib.Path:
    return codex_home.home(environ) / "hooks.json"


def hook_command(python: str | None = None, platform: str | None = None) -> str:
    argv = [python or sys.executable, str(HOOK_ENTRY)]
    return subprocess.list2cmdline(argv) if (platform or sys.platform) == "win32" \
        else " ".join(shlex.quote(part) for part in argv)


def hook_handler(python: str | None = None, platform: str | None = None) -> dict:
    return {"type": "command", "command": hook_command(python, platform),
            "timeout": HOOK_TIMEOUT,
            "statusMessage": "Running queued conPACT compaction"}


def _is_ours(handler) -> bool:
    if not isinstance(handler, dict):
        return False
    command = str(handler.get("command", ""))
    return (f"-m {HOOK_MODULE}" in command or
            str(HOOK_ENTRY) in command)


def hook_installed(environ=None) -> bool:
    try:
        data = json.loads(hooks_path(environ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for group in data.get("hooks", {}).get("Stop", []):
        if isinstance(group, dict) and any(_is_ours(item) for item in group.get("hooks", [])):
            return True
    return False


def _write_hooks(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".conpact.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(temp, 0o600)
    os.replace(temp, path)


def install_hook(environ=None, python: str | None = None, platform: str | None = None) -> dict:
    """Merge only conPACT's Stop handler into the user's existing hooks file."""
    path = hooks_path(environ)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as problem:
        return {"done": False, "message": f"could not read {path}: {problem}"}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        return {"done": False, "message": f"{path} is not a hooks object"}
    hooks = data.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        return {"done": False, "message": f"Stop in {path} is not a list"}
    if path.is_file():
        backup = path.with_name(path.name + ".conpact-backup")
        if not backup.exists():
            shutil.copy2(path, backup)
    replacement = hook_handler(python, platform)
    found = changed = False
    for group in stop:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for index, handler in enumerate(group["hooks"]):
            if _is_ours(handler):
                found = True
                if handler != replacement:
                    group["hooks"][index] = replacement.copy()
                    changed = True
    if found and not changed:
        return {"done": True, "changed": False, "path": str(path)}
    if not found:
        stop.append({"hooks": [replacement]})
    try:
        _write_hooks(path, data)
    except OSError as problem:
        return {"done": False, "message": f"could not write {path}: {problem}"}
    return {"done": True, "changed": True, "path": str(path)}


def uninstall_hook(environ=None) -> dict:
    """Remove only conPACT's handlers, preserving every other hook verbatim."""
    path = hooks_path(environ)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"done": True, "changed": False, "path": str(path)}
    except (OSError, ValueError) as problem:
        return {"done": False, "message": f"could not read {path}: {problem}"}
    stop = data.get("hooks", {}).get("Stop", []) if isinstance(data, dict) else []
    if not isinstance(stop, list):
        return {"done": False, "message": f"Stop in {path} is not a list"}
    kept = []
    changed = False
    for group in stop:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept.append(group)
            continue
        handlers = [item for item in group["hooks"] if not _is_ours(item)]
        changed = changed or len(handlers) != len(group["hooks"])
        if handlers:
            kept.append({**group, "hooks": handlers})
    if not changed:
        return {"done": True, "changed": False, "path": str(path)}
    data["hooks"]["Stop"] = kept
    try:
        _write_hooks(path, data)
    except OSError as problem:
        return {"done": False, "message": f"could not write {path}: {problem}"}
    return {"done": True, "changed": True, "path": str(path)}


def launch(argv, environ=None, starter=None, execer=None) -> int:
    """Start/reuse the host, then replace this process with its Codex client."""
    env = dict(os.environ if environ is None else environ)
    if not hook_installed(env):
        print("conPACT's Codex Stop hook is not installed. Run: conpact-codex --install",
              file=sys.stderr)
        return 1
    cli = codex_appserver.codex_cli(env)
    if cli is None:
        print("conPACT could not find the Codex CLI.", file=sys.stderr)
        return 1
    outcome = (starter or codex_host.start)(env)
    if not outcome.get("done"):
        print(f"conPACT could not start its local app-server: {outcome.get('message')}",
              file=sys.stderr)
        return 1
    record = codex_host.read_record()
    if not record or not record.get("token"):
        print("conPACT's local app-server has no usable connection record.", file=sys.stderr)
        return 1
    env[AUTH_ENV] = record["token"]
    remote = f"ws://{codex_host.HOST}:{record['port']}"
    command = [str(cli), "--remote", remote, "--remote-auth-token-env", AUTH_ENV, *argv]
    if execer is None:
        os.execvpe(command[0], command, env)
        raise AssertionError("exec returned")
    execer(command[0], command, env)
    return 0


def main(argv=None) -> int:
    home.migrate()
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--install"]:
        result = install_hook()
        if not result.get("done"):
            print(result.get("message", "hook installation failed"), file=sys.stderr)
            return 1
        verb = "installed" if result.get("changed") else "already installed"
        print(f"Codex CLI Stop hook {verb}: {result['path']}")
        print("On the next CLI start, review /hooks and trust the conPACT hook once.")
        return 0
    if args == ["--uninstall"]:
        result = uninstall_hook()
        if not result.get("done"):
            print(result.get("message", "hook removal failed"), file=sys.stderr)
            return 1
        print("Codex CLI Stop hook removed." if result.get("changed") else
              "Codex CLI Stop hook was not installed.")
        return 0
    if args == ["--status"]:
        running = codex_host.running()
        print(f"Codex CLI hook: {'installed' if hook_installed() else 'not installed'}")
        print(f"conPACT app-server: {'running' if running['ready'] else 'not running'}")
        return 0 if hook_installed() else 1
    return launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
