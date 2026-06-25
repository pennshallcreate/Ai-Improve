#!/usr/bin/env bash
# ============================================================
#  Start the Self-Improving AI Agent (macOS / Linux).
#  Run with:  ./run.sh
#  Installs dependencies, launches the app, opens the browser.
# ============================================================
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "Python 3.11+ not found. Install it from https://www.python.org/downloads/"
    exit 1
fi

echo "Installing/updating dependencies (first run only)..."
"$PY" -m pip install -r requirements.txt --quiet

echo "Launching the dashboard... your browser will open shortly."
echo "If it doesn't, go to: http://localhost:8080"
exec "$PY" main.py
