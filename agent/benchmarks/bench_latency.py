"""Latency probe: how fast do the reference functions run on fixed workloads?

The naive implementations (recursive fib, trial-division primes, O(n^2) duplicate
scan) are slow on purpose, so algorithmic improvements show up as a clear score gain.
"""
from __future__ import annotations

import time

from agent import solutions
from agent.benchmarks import _harness as h

NAME = "latency"
SUITE = "latency"
VERSION = 1

# Tuned so the naive code lands well under 100 and optimised code approaches it.
TARGET_SECONDS = 0.05


def run() -> dict:
    dup_list = list(range(400)) + [123]          # near-worst case for O(n^2) scan
    primes = [104729, 104723, 100003, 99991]     # forces deep trial division

    t0 = time.perf_counter()
    for _ in range(20):
        solutions.fib(24)
    for p in primes:
        solutions.is_prime(p)
    for _ in range(50):
        solutions.has_duplicates(dup_list)
    elapsed = time.perf_counter() - t0

    score = h.speed_score(elapsed, TARGET_SECONDS)
    return {
        "name": NAME,
        "suite": SUITE,
        "version": VERSION,
        "score": score,
        "passed": True,
        "details": {"seconds": round(elapsed, 5), "target_s": TARGET_SECONDS},
    }
