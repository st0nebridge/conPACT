"""
@module conpact.codex_caller_log
@description Retain the latest binding refusal per MCP helper for diagnosis.
@input Owner pid, method, refusal reason and content-free identity evidence
@output A bounded atomic record under conPACT's state, or False on failure
@dependencies conpact.home; stdlib: json, os, time
"""
from __future__ import annotations

import json
import os
import time

from . import home

MAX_BYTES = 8192
EVIDENCE_KEYS = ("attempts", "native", "rollouts")


def record(parent_pid, method, reason, evidence, clock=time.time) -> bool:
    """Diagnostics cannot change a refusal, and carry no arguments or source."""
    temporary = None
    try:
        body = json.dumps({"at": clock(), "pid": os.getpid(),
            "parent_pid": parent_pid, "method": method, "reason": reason,
            "evidence": {k: evidence[k] for k in EVIDENCE_KEYS if k in evidence}})
        if len(body.encode("utf-8")) > MAX_BYTES:
            return False
        path = home.HOME / "codex-caller" / (str(os.getpid()) + ".json")
        temporary = path.with_suffix(".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, path)
        return True
    except (OSError, ValueError, TypeError):
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
