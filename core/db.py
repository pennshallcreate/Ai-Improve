"""SQLite persistence for benchmark history, iterations, sessions, config and chat.

Every method opens a short-lived connection so the module is safe to call from the
UI thread, the scheduler thread and the loop worker thread simultaneously. WAL mode
keeps concurrent readers from blocking the loop's writes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

# Single writer lock — SQLite handles concurrency but serialising writes from the
# loop/scheduler/UI threads avoids 'database is locked' churn under WAL.
_WRITE_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    trigger         TEXT,                 -- 'manual' | 'auto'
    max_iterations  INTEGER,
    max_minutes     INTEGER,
    iterations_used INTEGER DEFAULT 0,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS iterations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER,
    created_at    TEXT NOT NULL,
    target        TEXT,                   -- improvement category
    source        TEXT,                   -- 'llm' | 'heuristic'
    description   TEXT,
    files_changed TEXT,                   -- JSON list of repo-relative paths
    commit_hash   TEXT,
    parent_hash   TEXT,
    baseline_score REAL,
    new_score     REAL,
    score_delta   REAL,
    status        TEXT,                   -- 'kept' | 'reverted' | 'skipped' | 'error'
    reason        TEXT,
    flagged       INTEGER DEFAULT 0,      -- anti-gaming flag
    duration_ms   INTEGER
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_id INTEGER,                 -- NULL for the seeded baseline
    created_at   TEXT NOT NULL,
    commit_hash  TEXT,
    aggregate    REAL,
    passed       INTEGER,                 -- 1 if the correctness gate held
    label        TEXT                     -- 'baseline' | 'kept' | 'reverted'
);

CREATE TABLE IF NOT EXISTS task_scores (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   INTEGER NOT NULL,
    name     TEXT,
    suite    TEXT,
    score    REAL,
    passed   INTEGER,
    details  TEXT                         -- JSON
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    role       TEXT,                      -- 'user' | 'assistant'
    content    TEXT
);
"""


def utcnow() -> str:
    """ISO-8601 UTC timestamp used everywhere for consistent ordering."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._init_schema()

    # -- connection plumbing -------------------------------------------------
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _write(self, sql: str, params: Iterable[Any] = ()) -> int:
        with _WRITE_LOCK, self._conn() as c:
            cur = c.execute(sql, tuple(params))
            return cur.lastrowid

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._conn() as c:
            return list(c.execute(sql, tuple(params)).fetchall())

    # -- config --------------------------------------------------------------
    def get_config(self, key: str) -> Optional[str]:
        rows = self._query("SELECT value FROM config WHERE key=?", (key,))
        return rows[0]["value"] if rows else None

    def set_config(self, key: str, value: str) -> None:
        self._write(
            "INSERT INTO config(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def all_config(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._query("SELECT key, value FROM config")}

    # -- sessions ------------------------------------------------------------
    def open_session(self, trigger: str, max_iterations: int, max_minutes: int) -> int:
        return self._write(
            "INSERT INTO sessions(started_at, trigger, max_iterations, max_minutes) "
            "VALUES(?, ?, ?, ?)",
            (utcnow(), trigger, max_iterations, max_minutes),
        )

    def close_session(self, session_id: int, note: str = "") -> None:
        self._write(
            "UPDATE sessions SET ended_at=?, note=? WHERE id=? AND ended_at IS NULL",
            (utcnow(), note, session_id),
        )

    def bump_session_iterations(self, session_id: int) -> None:
        self._write(
            "UPDATE sessions SET iterations_used = iterations_used + 1 WHERE id=?",
            (session_id,),
        )

    def get_session(self, session_id: int) -> Optional[dict]:
        rows = self._query("SELECT * FROM sessions WHERE id=?", (session_id,))
        return dict(rows[0]) if rows else None

    def active_session(self) -> Optional[dict]:
        rows = self._query(
            "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        )
        return dict(rows[0]) if rows else None

    # -- iterations ----------------------------------------------------------
    def insert_iteration(self, **fields: Any) -> int:
        cols = (
            "session_id", "created_at", "target", "source", "description",
            "files_changed", "commit_hash", "parent_hash", "baseline_score",
            "new_score", "score_delta", "status", "reason", "flagged", "duration_ms",
        )
        fields.setdefault("created_at", utcnow())
        if isinstance(fields.get("files_changed"), (list, tuple)):
            fields["files_changed"] = json.dumps(list(fields["files_changed"]))
        values = [fields.get(c) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        return self._write(
            f"INSERT INTO iterations({', '.join(cols)}) VALUES({placeholders})", values
        )

    def recent_iterations(self, limit: int = 100) -> list[dict]:
        rows = self._query(
            "SELECT * FROM iterations ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    # -- benchmark runs ------------------------------------------------------
    def insert_run(
        self,
        *,
        aggregate: float,
        passed: bool,
        commit_hash: str,
        label: str,
        iteration_id: Optional[int],
        tasks: list[dict],
    ) -> int:
        run_id = self._write(
            "INSERT INTO benchmark_runs(iteration_id, created_at, commit_hash, "
            "aggregate, passed, label) VALUES(?, ?, ?, ?, ?, ?)",
            (iteration_id, utcnow(), commit_hash, aggregate, int(passed), label),
        )
        for t in tasks:
            self._write(
                "INSERT INTO task_scores(run_id, name, suite, score, passed, details) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    t.get("name"),
                    t.get("suite"),
                    t.get("score"),
                    int(bool(t.get("passed", True))),
                    json.dumps(t.get("details", {})),
                ),
            )
        return run_id

    def latest_run(self) -> Optional[dict]:
        rows = self._query("SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def baseline_score(self) -> Optional[float]:
        """Most recent KEPT (or baseline) aggregate — the bar a candidate must clear."""
        rows = self._query(
            "SELECT aggregate FROM benchmark_runs "
            "WHERE label IN ('baseline', 'kept') ORDER BY id DESC LIMIT 1"
        )
        return rows[0]["aggregate"] if rows else None

    def runs_for_graph(self) -> list[dict]:
        rows = self._query("SELECT * FROM benchmark_runs ORDER BY id ASC")
        return [dict(r) for r in rows]

    def task_scores_for_runs(self) -> list[dict]:
        rows = self._query(
            "SELECT ts.*, br.created_at AS run_at FROM task_scores ts "
            "JOIN benchmark_runs br ON br.id = ts.run_id ORDER BY ts.run_id ASC"
        )
        return [dict(r) for r in rows]

    def run_count(self) -> int:
        return self._query("SELECT COUNT(*) AS n FROM benchmark_runs")[0]["n"]

    # -- chat ----------------------------------------------------------------
    def add_chat(self, role: str, content: str) -> int:
        return self._write(
            "INSERT INTO chat_messages(created_at, role, content) VALUES(?, ?, ?)",
            (utcnow(), role, content),
        )

    def chat_history(self, limit: int = 200) -> list[dict]:
        rows = self._query(
            "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in reversed(rows)]
