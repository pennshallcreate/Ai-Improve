"""Reference implementations the benchmark suite measures — and the agent improves.

These start intentionally naive (slow algorithms, missing docstrings) so the
self-improvement loop has real, measurable headroom: faster algorithms raise the
latency/throughput scores, tighter code raises the efficiency score, and docstrings
raise the quality score — all while correctness must stay at 100%.

Public API (kept stable so benchmarks and the heuristic improver agree):
    fib(n), is_prime(n), has_duplicates(items), sum_multiples(limit),
    reverse_words(s), word_count(text)
"""
from __future__ import annotations


def fib(n):
    if n < 0:
        raise ValueError("n must be non-negative")
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def is_prime(n):
    if n < 2:
        return False
    i = 2
    while i < n:
        if n % i == 0:
            return False
        i += 1
    return True


def has_duplicates(items):
    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            if items[i] == items[j]:
                return True
    return False


def sum_multiples(limit):
    total = 0
    for i in range(limit):
        if i % 3 == 0 or i % 5 == 0:
            total += i
    return total


def reverse_words(s):
    words = s.split()
    out = ""
    for w in words:
        if out:
            out = w + " " + out
        else:
            out = w
    return out


def word_count(text):
    counts = {}
    for word in text.split():
        key = word.lower()
        if key in counts:
            counts[key] = counts[key] + 1
        else:
            counts[key] = 1
    return counts
