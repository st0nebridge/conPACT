"""Thin entry point -> conpact.provenance: trace a compaction summary's constraints to their sources.

As a Claude Code SessionStart hook with the matcher "compact" (reads the hook JSON on stdin and
prints the check, which Claude Code adds to the resumed session's context):

    python tools/compact_provenance.py [--source GLOB ...]

By hand:

    python tools/compact_provenance.py --transcript <session.jsonl> [--cwd <project>] [--upto LINE]
    python tools/compact_provenance.py --report [--since YYYY-MM-DD]   summarise the logged checks
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.provenance import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
