"""Shared fixtures + scoring helpers for the benchmark suite.

Kept separate from the ``bench_*`` modules so the runner only auto-discovers actual
benchmarks. The canonical correctness cases live here as the single source of truth
that the agent must never break.
"""
from __future__ import annotations

import math

# Canonical (input, expected) cases. The agent may make the code faster or cleaner
# but these answers are immutable — they are how "correctness" is defined.
FIB_CASES = [(0, 0), (1, 1), (2, 1), (7, 13), (10, 55), (15, 610), (20, 6765)]

PRIME_CASES = [
    (1, False), (2, True), (3, True), (4, False), (17, True),
    (18, False), (97, True), (100, False), (7919, True), (7920, False),
]

DUP_CASES = [
    ([1, 2, 3, 4], False),
    ([1, 2, 2, 4], True),
    ([], False),
    (["a", "b", "c"], False),
    (["a", "b", "a"], True),
]

REVERSE_CASES = [
    ("hello world", "world hello"),
    ("one two three", "three two one"),
    ("single", "single"),
    ("a b c d", "d c b a"),
]

WORDCOUNT_CASES = [
    ("the cat the dog", {"the": 2, "cat": 1, "dog": 1}),
    ("A a A", {"a": 3}),
    ("", {}),
]


def speed_score(seconds: float, target: float) -> float:
    """Map elapsed time to a bounded 0-100 score (faster → higher).

    score = 100 / (1 + seconds/target): 0s → 100, target → 50, slow → toward 0.
    Monotonic and stable, so it cannot be gamed by returning a constant.
    """
    if seconds <= 0:
        return 100.0
    return round(100.0 / (1.0 + (seconds / target)), 3)


def size_score(units: float, target: float) -> float:
    """Map a 'cost' quantity (token/byte proxy) to 0-100 (smaller → higher)."""
    if units <= 0:
        return 100.0
    return round(100.0 / (1.0 + (units / target)), 3)


def ratio_score(passed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * passed / total, 3)


def approx_equal(a, b, tol: float = 1e-9) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=tol, abs_tol=tol)
    return a == b
