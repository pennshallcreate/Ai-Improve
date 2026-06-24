"""Single entry point: launches the dashboard UI and the background self-improvement loop.

    python main.py                 # http://localhost:8080
    python main.py --port 9000     # custom port
    python main.py --no-browser    # don't auto-open a browser (servers/headless)

On first boot it records one baseline benchmark run so the graph has data immediately.
A background APScheduler tick enforces authorized windows and (when auto-run is on)
drives iterations; everything stays local — the only network call is to Ollama.
"""
from __future__ import annotations

import argparse
import os

from nicegui import app, ui

from core.config import Config
from core.db import Database
from core.loop import LoopController
from core.scheduler import Ticker
from ui.app import create_app

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(REPO_DIR, "data", "agent.sqlite")


def build() -> tuple[LoopController, Database, Config, Ticker]:
    db = Database(DB_PATH)
    config = Config(db)
    controller = LoopController(REPO_DIR, db, config)

    # Seed one baseline run if the DB is empty, so the graph isn't blank on first boot.
    controller.ensure_baseline()

    ticker = Ticker(int(config.get("scheduler_tick_seconds")), controller.tick)
    return controller, db, config, ticker


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-Improving Local AI Agent")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default local-only; use 0.0.0.0 to expose)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    controller, db, config, ticker = build()
    create_app(controller, db, config)

    # Start the governance ticker once the server is up; stop it cleanly on exit.
    app.on_startup(ticker.start)
    app.on_shutdown(ticker.shutdown)

    ui.run(
        title="Self-Improving Local AI Agent",
        host=args.host,
        port=args.port,
        show=not args.no_browser,
        reload=False,          # reload would fork the loop/scheduler — keep one process
        favicon="🛠️",
    )


# NiceGUI re-imports the module under __mt_* names; guard so the app builds once.
if __name__ in {"__main__", "__mp_main__"}:
    main()
