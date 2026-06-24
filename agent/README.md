# `agent/` — the self-modification scope

**This is the only directory the self-improvement loop may write to.** The scope lock
in `core/git_ops.py` rejects any staged change outside `agent/`, so the agent can never
touch system files, network config, secrets, the UI, or the loop itself.

## Contents

- **`solutions.py`** — the code under improvement. It ships intentionally *naive*
  (recursive `fib`, trial-division `is_prime`, O(n²) `has_duplicates`, no docstrings)
  so there is real, measurable headroom. The public API is fixed:
  `fib, is_prime, has_duplicates, sum_multiples, reverse_words, word_count`.
  Benchmarks and the heuristic improver both rely on these names/behaviours.

- **`benchmarks/`** — the agent’s self-authored, versioned benchmark suite. Each
  `bench_*.py` exposes `NAME`, `SUITE`, `VERSION` and a `run() -> dict` returning a
  `score` in 0–100 plus a `passed` flag. The runner discovers them automatically.

  | Module | Suite | Measures |
  |---|---|---|
  | `bench_correctness.py` | correctness | canonical I/O cases (hard gate — must be 100) |
  | `bench_latency.py` | latency | wall-time on fixed workloads |
  | `bench_throughput.py` | latency | ops completed in a fixed slice |
  | `bench_tokens.py` | efficiency | source size (≈token) cost |
  | `bench_quality.py` | quality | docstrings, no bare-except / `eval`, line length |

  `_harness.py` holds the shared correctness cases and scoring helpers — it is **not**
  a benchmark (only `bench_*` modules are discovered).

## How improvement is scored

The aggregate is the mean of all benchmark scores. An iteration is kept only if the
correctness suite still passes **and** the aggregate does not regress. Optimising a
function (e.g. iterative `fib`, 6k±1 primes, set-based de-dup) raises latency/throughput;
adding docstrings raises quality; tighter code raises efficiency — all while correctness
stays pinned at 100.

## Anti-gaming

Editing a benchmark to inflate the score is caught: such iterations are flagged, and
each edited benchmark must pass a meta-check proving it still *discriminates* broken code
from correct code. See the top-level `README.md` for details.
