@echo off
REM Stop-hook entry for conPACT. Claude Code passes the hook JSON on stdin,
REM which python inherits. Exits 0 and never blocks the stop.
REM Python runs when a compaction request is pending or the idle notifier is on
REM (the default). With the notifier switched off (idle-notify.off exists) and no
REM request pending, a turn end starts no Python at all. "Pending" means any of
REM the three requests folders: conPACT's own home, and the two that MCP servers
REM started before a move may still write to (D-20260922-044, D-20260923-048).
REM tools/stop_compact.sh is the macOS and Linux twin of this file, and the two
REM must agree.
if not exist "%USERPROFILE%\.conpact\requests\*.json" if not exist "%USERPROFILE%\.claude\conpact\requests\*.json" if not exist "%USERPROFILE%\.claude\clautomatic\requests\*.json" if exist "%USERPROFILE%\.conpact\idle-notify.off" exit /b 0
set "PYTHONPATH=%~dp0..\src"
python -m conpact.closure_hook
exit /b 0
