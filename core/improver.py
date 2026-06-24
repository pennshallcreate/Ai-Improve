"""Proposes ONE scope-locked improvement per iteration.

Two strategies behind a single ``propose`` call:

* **heuristic** - a registry of concrete, hand-verified optimisation passes that
  rewrite a single function in ``agent/solutions.py`` (recursive→iterative fib,
  trial-division→6k±1 primes, O(n²)→set duplicate scan, docstrings, …). Fully
  local, deterministic, needs no model — so the loop works end-to-end even with
  Ollama absent, which is how the seed/baseline demo runs.
* **llm** - asks the local Ollama model to rewrite the whole file, then validates
  the result parses and preserves the public API before it is ever applied.

Both paths return a :class:`Proposal`; the loop applies it on a working branch and
the benchmark gate decides keep-or-revert. The improver never writes to disk itself.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from typing import Optional

from .ollama_client import OllamaClient

SOLUTIONS_REL = "agent/solutions.py"
PUBLIC_FNS = ["fib", "is_prime", "has_duplicates", "sum_multiples",
              "reverse_words", "word_count"]


@dataclass
class Proposal:
    target: str               # improvement category
    source: str               # 'heuristic' | 'llm'
    description: str
    file_path: str            # repo-relative, always under agent/
    new_content: str
    touches_benchmarks: bool = False


# --------------------------------------------------------------------------- #
# Source surgery: replace a single top-level function by name (AST-accurate).
# --------------------------------------------------------------------------- #
def replace_function(source: str, name: str, new_src: str) -> Optional[str]:
    """Return ``source`` with top-level function ``name`` replaced by ``new_src``.

    Returns None if the function is absent or the replacement would be a no-op.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    target = next(
        (n for n in tree.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
        None,
    )
    if target is None or target.end_lineno is None:
        return None

    lines = source.splitlines()
    start = target.lineno - 1            # inclusive, 0-based
    end = target.end_lineno              # exclusive upper bound
    existing = "\n".join(lines[start:end]).strip()
    if existing == new_src.strip():
        return None                      # already optimised → skip

    replacement = new_src.strip("\n").splitlines()
    new_lines = lines[:start] + replacement + lines[end:]
    return "\n".join(new_lines) + ("\n" if source.endswith("\n") else "")


# --------------------------------------------------------------------------- #
# Heuristic optimisation registry. Each pass targets one function with a faster,
# documented implementation. Applied one at a time, most impactful first.
# --------------------------------------------------------------------------- #
HEURISTIC_PASSES: list[dict] = [
    {
        "fn": "fib",
        "target": "latency",
        "desc": "Rewrite fib recursively→iteratively (O(2^n)→O(n)) and document it.",
        "code": '''def fib(n):
    """Return the n-th Fibonacci number iteratively in O(n) time."""
    if n < 0:
        raise ValueError("n must be non-negative")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a''',
    },
    {
        "fn": "is_prime",
        "target": "latency",
        "desc": "Primality test trial-division→6k±1 (O(n)→O(sqrt n)) and document it.",
        "code": '''def is_prime(n):
    """Return True if n is prime using 6k +/- 1 trial division, O(sqrt(n))."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True''',
    },
    {
        "fn": "has_duplicates",
        "target": "latency",
        "desc": "Duplicate scan O(n^2)→O(n) using a seen-set and document it.",
        "code": '''def has_duplicates(items):
    """Return True if any value in items repeats, in O(n) using a set."""
    seen = set()
    for item in items:
        if item in seen:
            return True
        seen.add(item)
    return False''',
    },
    {
        "fn": "sum_multiples",
        "target": "efficiency",
        "desc": "sum_multiples loop→closed-form (inclusion-exclusion) and document it.",
        "code": '''def sum_multiples(limit):
    """Sum naturals below limit divisible by 3 or 5 via inclusion-exclusion."""
    def _arith(k):
        m = (limit - 1) // k
        return k * m * (m + 1) // 2
    return _arith(3) + _arith(5) - _arith(15)''',
    },
    {
        "fn": "reverse_words",
        "target": "efficiency",
        "desc": "reverse_words manual loop→join(reversed(...)) and document it.",
        "code": '''def reverse_words(s):
    """Return the words of s in reverse order."""
    return " ".join(reversed(s.split()))''',
    },
    {
        "fn": "word_count",
        "target": "quality",
        "desc": "Tidy word_count with dict.get and document it.",
        "code": '''def word_count(text):
    """Return a case-insensitive mapping of word -> frequency."""
    counts = {}
    for word in text.split():
        key = word.lower()
        counts[key] = counts.get(key, 0) + 1
    return counts''',
    },
]


def _heuristic_proposal(repo_dir: str) -> Optional[Proposal]:
    path = os.path.join(repo_dir, SOLUTIONS_REL)
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    for p in HEURISTIC_PASSES:
        updated = replace_function(source, p["fn"], p["code"])
        if updated is not None:
            return Proposal(
                target=p["target"],
                source="heuristic",
                description=p["desc"],
                file_path=SOLUTIONS_REL,
                new_content=updated,
            )
    return None  # everything already optimised


# --------------------------------------------------------------------------- #
# LLM strategy (local Ollama).
# --------------------------------------------------------------------------- #
_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

_PROMPT = """You are a code optimiser improving a Python module in place.

Rules (hard):
- Keep EXACTLY these public functions with identical behaviour and signatures:
  {fns}
- Improve ONE thing: speed, memory, or readability. Do not change correctness.
- Add concise docstrings where missing.
- Return the COMPLETE updated file in a single ```python code block. No prose.

Current benchmark scores (higher is better, 0-100):
{scores}

Current file ({path}):
```python
{source}
```
"""


def _llm_proposal(
    repo_dir: str, client: OllamaClient, score_summary: str
) -> Optional[Proposal]:
    path = os.path.join(repo_dir, SOLUTIONS_REL)
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()

    prompt = _PROMPT.format(
        fns=", ".join(PUBLIC_FNS), scores=score_summary, path=SOLUTIONS_REL, source=source
    )
    raw = client.generate(prompt)
    if not raw:
        return None

    match = _CODE_BLOCK.search(raw)
    candidate = (match.group(1) if match else raw).strip() + "\n"

    # Validate before it ever touches the working tree.
    try:
        tree = ast.parse(candidate)
    except SyntaxError:
        return None
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if not set(PUBLIC_FNS) <= defined:
        return None
    if candidate.strip() == source.strip():
        return None

    return Proposal(
        target="llm",
        source="llm",
        description="LLM-proposed rewrite of solutions.py (public API preserved).",
        file_path=SOLUTIONS_REL,
        new_content=candidate,
    )


# --------------------------------------------------------------------------- #
# Public entrypoint.
# --------------------------------------------------------------------------- #
def propose(
    repo_dir: str,
    strategy: str,
    client: Optional[OllamaClient] = None,
    score_summary: str = "",
) -> Optional[Proposal]:
    """Return one Proposal, or None when no improvement is found.

    'auto' prefers the LLM when Ollama is reachable and falls back to the
    deterministic heuristic engine otherwise (or when the LLM yields nothing usable).
    """
    use_llm = strategy == "llm" or (
        strategy == "auto" and client is not None and client.is_up()
    )
    if use_llm and client is not None:
        proposal = _llm_proposal(repo_dir, client, score_summary)
        if proposal is not None:
            return proposal
        if strategy == "llm":
            return None  # explicit LLM mode: don't silently fall back

    return _heuristic_proposal(repo_dir)
