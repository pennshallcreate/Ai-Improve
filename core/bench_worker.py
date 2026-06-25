"""Subprocess entrypoint that executes the self-authored benchmark suite.

Run as ``python -m core.bench_worker`` from the repo root. Importing benchmarks in a
fresh process guarantees the just-modified ``agent`` code is what gets measured (no
stale bytecode cache) and lets the parent kill a runaway run.

Modes:
    (default)            run every ``bench_*`` module, print aggregated JSON
    --meta-check a,b,c   validate the named benchmark modules (anti-gaming guard)

Output is a single line prefixed with ``@@RESULT@@`` followed by JSON, so the parent
can ignore any incidental stdout from the benchmarks themselves.
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import sys
import traceback

SENTINEL = "@@RESULT@@"


def _discover() -> list[str]:
    import agent.benchmarks as pkg
    names = []
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("bench_"):
            names.append(f"agent.benchmarks.{mod.name}")
    return sorted(names)


def _run_one(modname: str) -> dict:
    mod = importlib.import_module(modname)
    result = mod.run()
    # Normalise + clamp so a malformed benchmark cannot poison the aggregate.
    score = float(result.get("score", 0.0))
    result["score"] = max(0.0, min(100.0, score))
    result.setdefault("name", modname.rsplit(".", 1)[-1])
    result.setdefault("suite", "unknown")
    result.setdefault("passed", True)
    result.setdefault("details", {})
    return result


def run_suite() -> dict:
    tasks = []
    for modname in _discover():
        try:
            tasks.append(_run_one(modname))
        except Exception:  # noqa: BLE001 - a broken benchmark scores 0, never crashes the run
            tasks.append({
                "name": modname.rsplit(".", 1)[-1],
                "suite": "error",
                "score": 0.0,
                "passed": False,
                "details": {"error": traceback.format_exc(limit=3)},
            })

    aggregate = round(sum(t["score"] for t in tasks) / len(tasks), 3) if tasks else 0.0
    # Hard gate: every correctness-suite benchmark must pass.
    passed = all(t["passed"] for t in tasks if t["suite"] == "correctness")
    return {"ok": True, "aggregate": aggregate, "passed": passed, "tasks": tasks}


# A trivially-broken solutions module: wrong answers, no docstrings, tiny source.
# A real benchmark — runtime OR source-reading — must score this differently from the
# genuine code. A benchmark hard-wired to return a constant cannot, so it is rejected.
_STUB_SOLUTIONS = (
    "def fib(n): return 0\n"
    "def is_prime(n): return False\n"
    "def has_duplicates(items): return False\n"
    "def sum_multiples(limit): return 0\n"
    "def reverse_words(s): return ''\n"
    "def word_count(text): return {}\n"
)


def _discriminates(mod, modname: str) -> tuple[bool, float, float]:
    """True if the benchmark scores genuine code differently from stub code.

    Temporarily swaps ``agent/solutions.py`` for a trivial stub (restored in a
    ``finally`` no matter what) and reloads, so both behavioural benchmarks (which
    call the functions) and source-reading ones (latency/quality/tokens) are covered.
    """
    sol = importlib.import_module("agent.solutions")
    path = sol.__file__
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()
    s_ref = float(mod.run().get("score", -1.0))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_STUB_SOLUTIONS)
        importlib.reload(sol)
        s_broken = float(importlib.reload(mod).run().get("score", -1.0))
    finally:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(original)
        importlib.reload(sol)
        importlib.reload(mod)
    return abs(s_ref - s_broken) > 0.01, s_ref, s_broken


def meta_check(modnames: list[str]) -> dict:
    """Validate edited benchmarks: structurally sound AND actually discriminating.

    A legitimate benchmark scores deliberately-broken code differently from real code;
    a benchmark rewritten to rubber-stamp anything (e.g. ``return 100``) cannot, so an
    iteration is unable to raise its aggregate by gaming its own benchmarks.
    """
    report: dict[str, dict] = {}
    ok = True
    for modname in modnames:
        short = modname.rsplit(".", 1)[-1]
        try:
            mod = importlib.import_module(modname)
            ref = mod.run()
            score = float(ref.get("score", -1))
            structural = (
                {"name", "suite", "score", "passed"} <= set(ref)
                and 0.0 <= score <= 100.0
            )
            discriminates, s_ref, s_broken = _discriminates(mod, modname)
            entry = {"structural": structural, "discriminates": discriminates,
                     "ref_score": s_ref, "stub_score": s_broken}
            entry["pass"] = structural and discriminates
            ok = ok and entry["pass"]
            report[short] = entry
        except Exception:  # noqa: BLE001
            report[short] = {"pass": False, "error": traceback.format_exc(limit=3)}
            ok = False
    return {"ok": ok, "report": report}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--meta-check":
        mods = [f"agent.benchmarks.{n}" if not n.startswith("agent.") else n
                for n in argv[1].split(",") if n]
        result = meta_check(mods)
    else:
        result = run_suite()
    print(SENTINEL + json.dumps(result))
    return 0


if __name__ == "__main__":
    # Ensure the repo root is importable when launched as a module.
    sys.path.insert(0, os.getcwd())
    raise SystemExit(main(sys.argv[1:]))
