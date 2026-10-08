"""
@module conpact.codex_transport
@description Opt-in HTTP provider selection for previously saved OpenAI
             histories. Snapshot configuration and native metadata at launch;
             forwarding then performs no I/O and never starts or resumes a chat.
@input      User Codex config, read-only thread metadata and Desktop JSON lines.
@output     Existing OpenAI resume/fork requests select the configured HTTP
            provider; every other line is preserved byte for byte.
@dependencies conpact.codex_home; stdlib json, os, tomllib.
"""
from __future__ import annotations

import json
import os
import tomllib

from . import codex_home

PROVIDER = "openai-http"
PROVIDER_KEYS = {"name", "requires_openai_auth", "wire_api", "supports_websockets"}


def unchanged(line):
    return line


def opted_in(config):
    providers = config.get("model_providers", {})
    provider = providers.get(PROVIDER) if isinstance(providers, dict) else None
    return (config.get("model_provider") == PROVIDER
            and not config.get("profile") and not config.get("openai_base_url")
            and isinstance(provider, dict) and not (set(provider) - PROVIDER_KEYS)
            and provider.get("requires_openai_auth") is True
            and provider.get("wire_api") == "responses"
            and provider.get("supports_websockets") is False)


def path_key(value):
    plain = codex_home.plain_path(value)
    return os.path.normcase(os.path.abspath(plain)) if plain else None


def select(config, histories):
    """Build a pure line transform from the explicit opt-in and known history.

    Unknown targets, custom providers and per-request provider/profile overrides
    keep native behavior. A supplied path must corroborate the recorded thread.
    """
    if not opted_in(config):
        return unchanged
    old = {row["id"]: path_key(row.get("rollout_path")) for row in histories
           if row.get("model_provider") == "openai" and isinstance(row.get("id"), str)}

    def transform(line):
        try:
            message = json.loads(line)
            if not isinstance(message, dict) or "id" not in message:
                return line
            if message.get("method") not in ("thread/resume", "thread/fork"):
                return line
            params = message.get("params")
            if not isinstance(params, dict):
                return line
            tid = params.get("threadId")
            if not isinstance(tid, str) or tid not in old:
                return line
            if params.get("modelProvider") not in (None, "openai"):
                return line
            if params.get("history") is not None:
                return line
            if params.get("path") is not None and path_key(params["path"]) != old[tid]:
                return line
            overrides = params.get("config")
            if overrides is not None:
                if not isinstance(overrides, dict) or any(
                    key.startswith(("model_provider", "profile", "openai_base_url"))
                    for key in overrides):
                    return line
            params["modelProvider"] = PROVIDER
            ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
            return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + ending
        except (ValueError, TypeError, UnicodeError):
            return line

    return transform


def load(environ=None, args=()):
    """Read once before starting the Desktop input pump; errors fail open."""
    if any(arg == "-p" or arg.startswith("--profile") or "model_provider" in arg
           for arg in args):
        return unchanged
    try:
        config = tomllib.loads((codex_home.home(environ) / "config.toml").read_text(encoding="utf-8"))
        if not opted_in(config):
            return unchanged
        histories = codex_home.rows(codex_home.state_db(environ),
            "SELECT id, model_provider, rollout_path FROM threads WHERE model_provider = ?", ("openai",))
        return select(config, histories)
    except (OSError, ValueError, TypeError):
        return unchanged
