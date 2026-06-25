"""Code-quality probe: static checks over the solution source.

Rewards documented, safe, readable code. Each public function should have a
docstring; the module should avoid bare excepts, ``eval``/``exec`` and over-long
lines. Score is the fraction of checks that pass.
"""
from __future__ import annotations

import ast
import os

from agent.benchmarks import _harness as h

NAME = "quality"
SUITE = "quality"
VERSION = 1

MAX_LINE = 100
_SOURCE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "solutions.py")


def run() -> dict:
    try:
        with open(_SOURCE, "r", encoding="utf-8") as fh:
            text = fh.read()
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return {
            "name": NAME, "suite": SUITE, "version": VERSION,
            "score": 0.0, "passed": False, "details": {"error": "unparseable"},
        }

    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
             and not n.name.startswith("_")]
    documented = sum(1 for f in funcs if ast.get_docstring(f))
    doc_ratio = documented / len(funcs) if funcs else 1.0

    has_bare_except = any(
        isinstance(n, ast.ExceptHandler) and n.type is None for n in ast.walk(tree)
    )
    has_dangerous = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in {"eval", "exec"}
        for n in ast.walk(tree)
    )
    long_lines = sum(1 for line in text.splitlines() if len(line) > MAX_LINE)

    checks = {
        "docstrings": doc_ratio,                 # 0..1
        "no_bare_except": 0.0 if has_bare_except else 1.0,
        "no_eval_exec": 0.0 if has_dangerous else 1.0,
        "line_length": 1.0 if long_lines == 0 else max(0.0, 1.0 - long_lines / 10),
    }
    score = round(100.0 * sum(checks.values()) / len(checks), 3)
    return {
        "name": NAME,
        "suite": SUITE,
        "version": VERSION,
        "score": score,
        "passed": True,
        "details": {
            "documented": f"{documented}/{len(funcs)}",
            "bare_except": has_bare_except,
            "long_lines": long_lines,
        },
    }
