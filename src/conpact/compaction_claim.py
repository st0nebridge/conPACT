"""@module conpact.compaction_claim
@description Atomically claim only a request that preceded a Codex turn end.
@input A request path and the observed turn-end timestamp in nanoseconds.
@output The claimed request or None, preserving newer queued intent.
@dependencies conpact.compaction_claim_lock; stdlib: json, os, uuid
"""
import json
import os
import uuid

from . import compaction_claim_lock


def requested_at_ns(request):
    """Legacy timestamps require the entire second to precede the event."""
    stamp = request.get("requested_at_ns")
    if stamp is None:
        stamp = (request.get("requested_at", 0) + 1) * 1_000_000_000
    if not isinstance(stamp, int) or isinstance(stamp, bool):
        raise ValueError("invalid request timestamp")
    return stamp


def before(path, ended_at_ns):
    """Serialize consumers before renaming; Windows can move an already-open file.

    A rename alone is not a cross-process claim on that platform. Busy consumers
    return without touching a generation, and process exit releases the lease.
    """
    with compaction_claim_lock.hold(path) as owned:
        return _before(path, ended_at_ns) if owned else None


def _before(path, ended_at_ns):
    """Moving to a unique name claims one complete generation, never its replacement.

    A newer request is restored with a hard link: atomic creation refuses to
    overwrite a still newer request. Nothing has executed when it is restored.
    """
    claimed = path.with_name(f".{path.name}.{uuid.uuid4().hex}.claim")
    try:
        os.replace(path, claimed)
    except OSError:
        return None
    try:
        request = json.loads(claimed.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            return None
        if requested_at_ns(request) > ended_at_ns:
            try:
                os.link(claimed, path)
            except FileExistsError:
                pass
            return None
    except ValueError:
        return None
    finally:
        # Failure to delete fails closed, just as the existing Stop-hook claim.
        claimed.unlink()
    return request
