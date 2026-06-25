@echo off
REM ============================================================
REM  Double-click this file to start the Self-Improving AI Agent.
REM  It installs dependencies (first run only takes a minute),
REM  launches the app, and opens it in your browser.
REM ============================================================
cd /d "%~dp0"

echo.
echo  Installing/updating dependencies (first run only)...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo  Could not install dependencies. Is Python installed?
    echo  Get it from https://www.python.org/downloads/ ^(tick "Add to PATH"^).
    echo.
    pause
    exit /b 1
)

echo.
echo  Launching the dashboard... your browser will open shortly.
echo  Keep this window open while you use the app.
echo  If your browser doesn't open, go to:  http://localhost:8080
echo.
python main.py

echo.
echo  The app has stopped. If you saw a red error above, copy it to Claude.
pause
