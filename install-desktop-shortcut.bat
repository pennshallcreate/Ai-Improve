@echo off
REM ============================================================
REM  Double-click this ONCE to put an "AI Improve Agent" icon
REM  on your Desktop. After that, just use the desktop icon.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-desktop-shortcut.ps1"
echo.
pause
