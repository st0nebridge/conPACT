#!/bin/sh
# Stop-hook entry for conPACT on macOS and Linux; tools/stop_compact.cmd is its
# Windows twin and the two must agree. Claude Code passes the hook JSON on stdin,
# which Python inherits. Always exits 0: a Stop hook must never block the stop.
#
# Python runs when a compaction request is pending or the idle notifier is on
# (the default). With the notifier switched off (idle-notify.off exists) and no
# request pending, a turn end starts no Python at all. "Pending" means any of the
# three requests folders: conPACT's own home, and the two that MCP servers
# started before a move may still write to (D-20260922-044, D-20260923-048).
#
# CONPACT_PYTHON names the interpreter when `python3` on PATH is not the one to use.

pending() {
    for request in "$HOME/.conpact/requests/"*.json "$HOME/.claude/conpact/requests/"*.json \
                   "$HOME/.claude/clautomatic/requests/"*.json; do
        [ -e "$request" ] && return 0
    done
    return 1
}

if [ -e "$HOME/.conpact/idle-notify.off" ] && ! pending; then
    exit 0
fi

root=$(cd "$(dirname "$0")/.." && pwd) || exit 0
PYTHONPATH="$root/src" "${CONPACT_PYTHON:-python3}" -m conpact.closure_hook
exit 0
