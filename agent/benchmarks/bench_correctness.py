"""Correctness gate: every reference function must produce the canonical answers.

This is the hard gate — if score < 100 the iteration is reverted no matter how fast
or clean the candidate is. It also discriminates broken code (so the anti-gaming
meta-check can tell a real benchmark from a rubber-stamp).
"""
from __future__ import annotations

from agent import solutions
from agent.benchmarks import _harness as h

NAME = "correctness"
SUITE = "correctness"
VERSION = 1


def _check(fn, cases) -> tuple[int, int]:
    passed = 0
    for args, expected in cases:
        try:
            got = fn(args) if not isinstance(args, tuple) else fn(*args)
        except Exception:
            continue
        if h.approx_equal(got, expected):
            passed += 1
    return passed, len(cases)


def run() -> dict:
    suites = [
        (solutions.fib, h.FIB_CASES, "fib"),
        (solutions.is_prime, h.PRIME_CASES, "is_prime"),
        (solutions.has_duplicates, h.DUP_CASES, "has_duplicates"),
        (solutions.reverse_words, h.REVERSE_CASES, "reverse_words"),
        (solutions.word_count, h.WORDCOUNT_CASES, "word_count"),
    ]
    total_pass = total = 0
    breakdown = {}
    for fn, cases, label in suites:
        p, t = _check(fn, cases)
        breakdown[label] = f"{p}/{t}"
        total_pass += p
        total += t

    score = h.ratio_score(total_pass, total)
    return {
        "name": NAME,
        "suite": SUITE,
        "version": VERSION,
        "score": score,
        "passed": total_pass == total,
        "details": {"cases": f"{total_pass}/{total}", **breakdown},
    }
