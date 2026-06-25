"""Token-cost / efficiency proxy: how compact is the solution source?

Uses a cheap ~4-chars-per-token estimate over ``solutions.py``. Tighter code that
keeps correctness scores higher; bloated code scores lower. Bounded so it can't be
gamed by deleting functionality (correctness would crater and gate the iteration).
"""
from __future__ import annotations

import os

from agent.benchmarks import _harness as h

NAME = "tokens"
SUITE = "efficiency"
VERSION = 1

TARGET_TOKENS = 220  # ~token budget that scores 50; under it climbs toward 100
_SOURCE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "solutions.py")


def _estimate_tokens(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return TARGET_TOKENS
    # Ignore the module docstring/comments — measure code density, ~4 chars/token.
    code = "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return max(1, len(code) // 4)


def run() -> dict:
    tokens = _estimate_tokens(_SOURCE)
    score = h.size_score(tokens, TARGET_TOKENS)
    return {
        "name": NAME,
        "suite": SUITE,
        "version": VERSION,
        "score": score,
        "passed": True,
        "details": {"est_tokens": tokens, "target": TARGET_TOKENS},
    }
