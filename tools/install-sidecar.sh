#!/bin/sh
# One click: open the Codex sidecar window (Install / Uninstall).
# On macOS, rename or symlink this to install-sidecar.command to make it
# double-clickable from Finder.
cd "$(dirname "$0")/.." || exit 1
exec python3 tools/codex_sidecar.py window
