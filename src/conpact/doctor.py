"""
@module conpact.doctor
@description Read-only health report for conPACT's installed integrations
             (`python tools/doctor.py`). The report deliberately separates Codex
             authentication from Claude Code's optional Keychain login. conPACT
             never reads a Codex token: it asks the Codex CLI whether its own
             login is usable and reaches ChatGPT Desktop through the
             already-authenticated app-server. Contributed by Lance Sandino.
@input      the environment; Codex's config.toml and hooks; the sidecar's status
@output     one line per check (OK, WARN, INFO or FAIL); exit 1 if any failed
@dependencies conpact.codex_cli, conpact.codex_home, conpact.codex_host,
              conpact.codex_sidecar_install, conpact.codex_threads,
              conpact.token_store; stdlib: dataclasses, os, platform, shutil,
              subprocess, sys, tomllib
"""
from __future__ import annotations

import dataclasses
import os
import platform
import shutil
import subprocess
import sys
import tomllib

from . import (codex_cli, codex_home, codex_host, codex_sidecar_install,
               codex_threads, token_store)


@dataclasses.dataclass(frozen=True)
class Check:
    level: str
    name: str
    detail: str


def _codex_login(runner=subprocess.run) -> Check:
    cli = shutil.which("codex")
    if not cli:
        return Check("FAIL", "Codex login", "codex is not on PATH")
    try:
        done = runner([cli, "login", "status"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return Check("FAIL", "Codex login", "codex login status could not run")
    output = done.stdout if done.returncode == 0 else ((done.stderr or "") + " " + (done.stdout or ""))
    text = " ".join((output or "").split())
    return Check("OK" if done.returncode == 0 else "FAIL", "Codex login",
                 text or ("authenticated (codex login status exited 0)" if done.returncode == 0
                          else f"codex login status exited {done.returncode}"))


def _mcp_config(environ=None) -> Check:
    path = codex_home.home(environ) / "config.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        server = data.get("mcp_servers", {}).get("conpact")
    except (OSError, ValueError, TypeError):
        server = None
    ok = isinstance(server, dict) and bool(server.get("command"))
    return Check("OK" if ok else "FAIL", "Codex MCP",
                 "conpact is configured" if ok else "conpact is missing from config.toml")


def _sidecar(environ=None) -> list[Check]:
    status = codex_sidecar_install.status(environ=environ)
    installed = bool(status.get("installed"))
    running = bool(status.get("sidecar_running"))
    newest = bool(status.get("codex_selected") and
                  status["codex_selected"] == status.get("codex_newest"))
    selected = status.get("codex_selected") or "not found"
    version = status.get("codex_bundle_version") or "unknown version"
    found = [
        Check("OK" if installed else "FAIL", "ChatGPT Desktop sidecar",
              "installed" if installed else "not installed"),
        Check("OK" if running else "FAIL", "ChatGPT Desktop connection",
              "sidecar is running" if running else "sidecar is not running; restart ChatGPT Desktop"),
        Check("OK" if newest else "WARN", "Bundled Codex",
              (f"next launch selects {version}: {selected}" if newest else
               f"next launch does not select the newest installed build: {selected}")),
    ]
    if status.get("platform") == "darwin":
        found.append(Check("WARN" if status.get("env_discrepancy") else "OK",
                           "Desktop environment",
                           "persistent, caller and GUI bootstrap values differ" if
                           status.get("env_discrepancy") else
                           "persistent, caller and GUI bootstrap values agree"))
    remaining = status.get("derived_override_paths") or []
    if remaining:
        found.append(Check("WARN", "Derived CODEX_CLI_PATH",
                           ", ".join(remaining)))
    return found


def _codex_state(environ=None) -> Check:
    try:
        rows = codex_threads.threads(environ) or []
    except Exception:
        rows = []
    return Check("OK" if rows else "FAIL", "Codex state",
                 f"{len(rows)} thread{'s' if len(rows) != 1 else ''} readable" if rows else
                 "no readable Codex threads")


def _codex_cli(environ=None) -> list[Check]:
    hook = codex_cli.hook_installed(environ)
    host = codex_host.running(environ)
    return [
        Check("OK" if hook else "WARN", "Codex CLI Stop hook",
              "installed" if hook else "not installed; run conpact-codex --install"),
        Check("OK" if host["ready"] else "INFO", "Codex CLI app-server",
              (f"running on 127.0.0.1:{host['port']}" if host["ready"] else
               "not running; conpact-codex starts it automatically")),
    ]


def _claude_login() -> Check:
    if sys.platform != "darwin":
        return Check("INFO", "Claude Code login", "Keychain check applies only on macOS")
    try:
        status = token_store.token_status()
    except token_store.TokenError:
        return Check("INFO", "Claude Code login",
                     "not configured; optional and not used by Codex or ChatGPT Desktop")
    source = status.get("source", "unknown")
    fresh = bool(status.get("fresh"))
    return Check("OK" if fresh else "WARN", "Claude Code login",
                 f"{source}, {'fresh' if fresh else 'expired'}; not used by Codex or ChatGPT Desktop")


def checks(environ=None, runner=subprocess.run) -> list[Check]:
    env = os.environ if environ is None else environ
    python_ok = sys.version_info >= (3, 11)
    found = [Check("OK" if python_ok else "FAIL", "Python",
                   f"{platform.python_version()} ({platform.machine()})")]
    found.append(_codex_login(runner))
    found.append(_mcp_config(env))
    found.extend(_sidecar(env))
    found.extend(_codex_cli(env))
    found.append(_codex_state(env))
    found.append(_claude_login())
    return found


def lines(found: list[Check]) -> list[str]:
    return ["conPACT doctor (read-only)", ""] + [
        f"[{check.level:<4}] {check.name}: {check.detail}" for check in found
    ]


def main() -> int:
    found = checks()
    print("\n".join(lines(found)))
    return 1 if any(check.level == "FAIL" for check in found) else 0


if __name__ == "__main__":
    raise SystemExit(main())
