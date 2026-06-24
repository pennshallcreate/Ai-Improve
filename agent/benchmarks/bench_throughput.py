"""Throughput probe: operations completed within a fixed time slice.

Complements the latency probe by measuring sustained work (string + dict ops) rather
than single-call cost. More ops/slice → higher score.
"""
from __future__ import annotations

import time

from agent import solutions
from agent.benchmarks import _harness as h

NAME = "throughput"
SUITE = "latency"
VERSION = 1

SLICE_SECONDS = 0.05
TARGET_OPS = 4000  # ops in one slice that earns ~50; more → toward 100


def run() -> dict:
    sentence = "the quick brown fox jumps over the lazy dog the fox runs"
    ops = 0
    deadline = time.perf_counter() + SLICE_SECONDS
    while time.perf_counter() < deadline:
        solutions.reverse_words(sentence)
        solutions.word_count(sentence)
        solutions.sum_multiples(200)
        ops += 1

    score = h.size_score(TARGET_OPS, max(ops, 1))  # more ops → smaller ratio → higher
    return {
        "name": NAME,
        "suite": SUITE,
        "version": VERSION,
        "score": score,
        "passed": True,
        "details": {"ops": ops, "slice_s": SLICE_SECONDS},
    }
