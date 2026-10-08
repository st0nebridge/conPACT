@echo off
rem One click: open the Codex sidecar window (Install / Uninstall).
setlocal
cd /d "%~dp0\.."
start "" pythonw tools\codex_sidecar.py window || python tools\codex_sidecar.py window
