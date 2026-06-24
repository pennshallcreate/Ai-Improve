"""Parent-side benchmark runner: launch the worker, parse results, persist runs.

Owns the subprocess boundary so the rest of the loop deals in plain dicts. Also
exposes the anti-gaming meta-check used when an iteration touches ``agent/benchmarks/``.
"""
from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional

from . import sandbox
from .bench_worker import SENTINEL


@dataclass
class SuiteResult:
    ok: bool
    aggregate: float
    passed: bool
    tasks: list[dict] = field(default_factory=list)
    error: str = ""


def _parse(stdout: str) -> Optional[dict]:
    for line in stdout.splitlines():
        if line.startswith(SENTINEL):
            try:
                return json.loads(line[len(SENTINEL):])
            except json.JSONDecodeError:
                return None
    return None


def run_suite(
    repo_dir: str,
    timeout: float,
    kill_event: Optional[threading.Event] = None,
) -> SuiteResult:
    """Execute the full benchmark suite in a fresh subprocess and return scores."""
    res = sandbox.run(
        [sys.executable, "-m", "core.bench_worker"],
        cwd=repo_dir,
        timeout=timeout,
        kill_event=kill_event,
    )
    if res.killed:
        return SuiteResult(False, 0.0, False, error="killed")
    if res.timed_out:
        return SuiteResult(False, 0.0, False, error="benchmark suite timed out")

    parsed = _parse(res.stdout)
    if parsed is None:
        return SuiteResult(
            False, 0.0, False,
            error=f"could not parse benchmark output (rc={res.returncode}): "
                  f"{res.stderr.strip()[:400]}",
        )
    return SuiteResult(
        ok=bool(parsed.get("ok")),
        aggregate=float(parsed.get("aggregate", 0.0)),
        passed=bool(parsed.get("passed", False)),
        tasks=list(parsed.get("tasks", [])),
    )


def meta_check(
    repo_dir: str,
    bench_names: list[str],
    timeout: float,
    kill_event: Optional[threading.Event] = None,
) -> dict:
    """Validate edited benchmark modules. Returns {'ok': bool, 'report': {...}}."""
    if not bench_names:
        return {"ok": True, "report": {}}
    res = sandbox.run(
        [sys.executable, "-m", "core.bench_worker", "--meta-check", ",".join(bench_names)],
        cwd=repo_dir,
        timeout=timeout,
        kill_event=kill_event,
    )
    parsed = _parse(res.stdout)
    if parsed is None:
        return {"ok": False, "report": {}, "error": res.stderr.strip()[:400]}
    return parsed
