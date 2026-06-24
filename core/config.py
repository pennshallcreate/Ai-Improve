"""Typed configuration, persisted in the SQLite ``config`` table.

Defaults are applied lazily: reading a key that was never set returns the default
(and does not write it), so changing a default in code affects existing installs.
Authorized windows and budgets live here because the loop and UI both read them.
"""
from __future__ import annotations

import json
from typing import Any

from .db import Database

# Repo-relative directory the agent is allowed to modify. Everything else is off-limits.
SCOPE_DIR = "agent"

DEFAULTS: dict[str, Any] = {
    # --- LLM (all local via Ollama) ---
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen2.5-coder",
    "ollama_timeout": 120,
    # --- governance: authorized windows ---
    # A list of windows. 'weekly' repeats on given weekdays (0=Mon .. 6=Sun);
    # 'once' applies to a single date. Times are local "HH:MM"; "24:00" == end of day.
    "authorized_windows": [
        {"type": "weekly", "days": [0, 1, 2, 3, 4], "start": "22:00", "end": "24:00"},
    ],
    # --- governance: per-session budget (does NOT roll past a window) ---
    "budget_max_iterations": 10,
    "budget_max_minutes": 60,
    # --- loop behaviour ---
    "auto_run": False,            # background loop auto-runs inside windows when True
    "scheduler_tick_seconds": 20,
    "benchmark_timeout": 60,      # seconds per full suite run (subprocess)
    "iteration_timeout": 180,     # hard cap for a single iteration's work
    "improver_strategy": "auto",  # 'auto' | 'llm' | 'heuristic'
}


class Config:
    """Thin typed accessor over the DB config table with JSON-aware get/set."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> Any:
        raw = self.db.get_config(key)
        if raw is None:
            return DEFAULTS.get(key)
        default = DEFAULTS.get(key)
        # JSON-decode for non-string defaults (lists/dicts/bools/ints).
        if isinstance(default, (list, dict, bool, int, float)) and not isinstance(default, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default
        return raw

    def set(self, key: str, value: Any) -> None:
        if isinstance(value, (list, dict, bool)):
            raw = json.dumps(value)
        elif isinstance(value, (int, float)):
            raw = json.dumps(value)
        else:
            raw = str(value)
        self.db.set_config(key, raw)

    def as_dict(self) -> dict[str, Any]:
        merged = dict(DEFAULTS)
        for k in DEFAULTS:
            merged[k] = self.get(k)
        return merged
