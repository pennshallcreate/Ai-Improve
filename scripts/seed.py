"""Populate the graph with a baseline + several real improvement iterations.

Run once after install for a populated dashboard on first open:

    python scripts/seed.py

It authorizes a temporary 'now' window, forces the deterministic heuristic improver
(so it works with Ollama absent), and runs iterations until the code is fully
optimised. Every iteration is a genuine commit + benchmark run — nothing is faked.
The original authorized-window schedule is restored afterwards.
"""
from __future__ import annotations

import os
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_DIR)

from core.config import Config           # noqa: E402
from core.db import Database             # noqa: E402
from core.loop import LoopController     # noqa: E402
from core import scheduler               # noqa: E402

DB_PATH = os.path.join(REPO_DIR, "data", "agent.sqlite")


def main() -> None:
    db = Database(DB_PATH)
    config = Config(db)
    controller = LoopController(REPO_DIR, db, config)

    saved_windows = config.get("authorized_windows")
    saved_strategy = config.get("improver_strategy")
    saved_budget = config.get("budget_max_iterations")
    try:
        config.set("authorized_windows", [scheduler.authorize_now_window(120)])
        config.set("improver_strategy", "heuristic")
        config.set("budget_max_iterations", 25)

        base = controller.ensure_baseline()
        print(f"baseline aggregate: {db.baseline_score():.2f}")

        for i in range(12):
            res = controller.run_one_iteration_blocking(manual=True)
            status = res.get("status")
            print(f"  iter {i + 1:>2}: {status:<8} "
                  f"score={res.get('new_score')} delta={res.get('delta')} :: {res.get('reason')}")
            if status == "skipped":
                break
    finally:
        config.set("authorized_windows", saved_windows)
        config.set("improver_strategy", saved_strategy)
        config.set("budget_max_iterations", saved_budget)
        # End the temporary seed session so it doesn't bleed into real runs.
        sess = db.active_session()
        if sess:
            db.close_session(sess["id"], note="seed complete")

    print(f"\nfinal baseline: {db.baseline_score():.2f} over {db.run_count()} runs. "
          f"Start the app with `python main.py`.")


if __name__ == "__main__":
    main()
