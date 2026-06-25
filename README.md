# Self-Improving Local AI Agent

A locally-running agent whose only job is to **improve its own codebase and runtime
efficiency** — and it is only allowed to do so inside **user-authorized time windows**,
within a **per-session budget**, and **scope-locked to `./agent/`**. It ships with a
desktop-style web dashboard (pure Python): chat, run controls, a live graph of
self-benchmark scores, and an iteration log with one-click rollback.

Everything is local. The only network call is to your local **Ollama** server.

```
┌─────────────────────────────────────────────────────────────┐
│  NiceGUI dashboard  (chat · controls · live graph · log)     │
├─────────────────────────────────────────────────────────────┤
│  LoopController — the governed self-improvement loop          │
│    window gate → budget gate → propose → commit → benchmark   │
│    → keep-or-revert → log                                     │
├───────────┬───────────┬───────────┬───────────┬──────────────┤
│  improver │ benchmarks│  git_ops  │ scheduler │  ollama       │
│ (LLM +    │ (subproc  │ (scope-   │ (windows  │  (local chat/ │
│  heuristic)│  runner) │  locked)  │  + ticker)│   generate)   │
├───────────┴───────────┴───────────┴───────────┴──────────────┤
│  SQLite — benchmark history · iterations · sessions · config  │
└─────────────────────────────────────────────────────────────┘
```

## Why it can demonstrate real self-improvement (even without a GPU)

`agent/solutions.py` starts with deliberately **naive** implementations (recursive
Fibonacci, trial-division primes, an O(n²) duplicate scan, undocumented functions).
The self-authored benchmark suite measures correctness, latency, throughput, code size
and quality. The agent rewrites *one* function per iteration; the benchmark gate keeps
the change only if it’s genuinely better. You watch the aggregate score climb from ~54
to ~81 (correctness and quality reach 100; the latency/throughput/efficiency scores are
asymptotic, so the aggregate ceiling sits in the low 80s) — each step a real git commit
you can inspect or roll back.

The improver has two strategies behind one interface:

- **`llm`** — asks your local Ollama model to rewrite the file (validated before use).
- **`heuristic`** — a registry of concrete, hand-verified optimizations. Deterministic,
  needs no model, and is how the seed/baseline runs work out of the box.

`auto` (default) prefers the LLM when Ollama is up and falls back to the heuristic engine.

## Setup

### 1. Install + run Ollama (local LLM)
```bash
# https://ollama.com/download
ollama pull qwen2.5-coder      # default model (set any model in the UI)
ollama serve                   # usually already running as a service
```
The agent still boots and runs iterations **without** Ollama — chat shows a clear
"Ollama unavailable" notice and the loop uses the deterministic heuristic improver.

### 2. Install Python deps
```bash
python -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt                        # nicegui, plotly, apscheduler, requests
```

### 3. (Optional) Seed a populated graph
```bash
python scripts/seed.py     # baseline + several real improvement iterations
```

### 4. Run
```bash
python main.py             # open http://localhost:8080
# python main.py --port 9000 --no-browser
```
First boot records a **baseline** benchmark run so the graph has a data point immediately.

## How the loop works

One iteration =

1. **Gate — authorized window.** Outside every configured window the loop is *locked*
   and refuses to run (the UI shows a red LOCKED chip).
2. **Gate — session budget.** A session is bounded by *max iterations* and *max
   wall-clock minutes*. Unused budget **does not roll** past the window’s end.
3. **Propose** exactly one improvement, **scope-locked to `agent/`** (paths outside it
   are rejected before anything is written).
4. **Commit** the candidate on the working branch and run the **full benchmark suite**
   in an isolated subprocess.
5. **Keep or revert.** Keep iff: the benchmark run succeeded **AND** every correctness
   benchmark passed **AND** the aggregate ≥ baseline **AND** (for benchmark edits) the
   anti-gaming meta-check passed. Otherwise **hard-revert** the commit.
6. **Log** the attempt (kept *or* reverted) to SQLite → a new graph point + a log row.

## Governance & safety (hard constraints)

| Constraint | How it’s enforced |
|---|---|
| **Authorized windows only** | `core/scheduler.py` evaluates weekly/once windows; the loop’s first gate refuses outside them. A background ticker locks/unlocks as windows open and close. |
| **Session budget, no roll-over** | `core/loop.py` opens a session per window; a closed window ends the session, discarding unused budget. |
| **Scope lock to `./agent/`** | `git_ops.assert_in_scope` blocks any staged path outside `agent/`; the loop never touches system files, network config or secrets. |
| **Kill switch** | The UI button sets a kill event; the running iteration’s benchmark subprocess is force-killed and any candidate commit/working edits are reverted — repo left **clean**. |
| **One-click rollback** | Each commit in the log has a Rollback button (`git reset --hard <commit>` + re-baseline). |

## Self-generated benchmarks & anti-gaming

The agent **owns** its benchmarks in `agent/benchmarks/` (5 seeded, versioned tasks
across `correctness`, `latency`, `efficiency`, `quality`). Each run records timestamp,
commit hash, per-task scores and an aggregate.

**Anti-gaming guard:** if an iteration edits any benchmark *and* raises its own score,
it is **flagged** (⚑ in the log). Benchmark edits must also pass a **meta-check**: each
edited benchmark must *discriminate* — it has to score deliberately-broken code
differently from real code. A benchmark rewritten to rubber-stamp anything (e.g.
`return 100`) fails the meta-check and the iteration is reverted.

## Dashboard tour

- **Dashboard** — aggregate score, baseline, run count, session budget; *Run one
  iteration*, *Kill switch*, per-suite breakdown toggle, and the live Plotly graph
  (green = kept, red ✕ = reverted, blue = baseline).
- **Chat** — streams from your local Ollama model.
- **Controls** — auto-run toggle, model/URL/strategy, budget, and the authorized-window
  editor (add weekly windows, delete, or “Authorize N minutes now”).
- **Iteration log** — every attempt with target, who proposed it, score delta, result
  and reason; plus recent commits with rollback.

## Repository layout

```
core/    loop, git ops, scheduler, db, benchmarks runner, improver, ollama client
ui/      NiceGUI app (app.py) + Plotly charts (charts.py)
agent/   self-mod target (solutions.py) + self-authored benchmarks/  ← the only writable scope
data/    SQLite database (gitignored)
scripts/ seed.py (populate the graph)
tests/   end-to-end loop + governance tests
main.py  single entry point (UI + background loop)
```

## Acceptance checklist

- ✅ Boots locally with one command (`python main.py`); UI loads; chat works via local Ollama.
- ✅ “Run one iteration” produces a git commit, a benchmark run and a new graph point.
- ✅ Outside the authorized window the loop refuses to run and the UI shows a locked state.
- ✅ Killing mid-run leaves the repo with no partial edits.

## Tests

```bash
python tests/test_loop.py        # standalone (no pytest required)
# or:  pytest tests/
```
Covers: climbing scores across real iterations, revert-on-regression, the anti-gaming
meta-check, the kill switch leaving a clean tree, and the authorized-window lock.
