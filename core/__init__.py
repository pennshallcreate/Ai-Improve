"""Core backend for the Self-Improving Local AI Agent.

Modules:
    config      - typed configuration backed by the SQLite ``config`` table
    db          - SQLite persistence (benchmark history, iterations, sessions, chat)
    git_ops     - thin, scope-aware wrapper around the ``git`` CLI
    sandbox     - killable subprocess runner with timeouts
    ollama_client - local Ollama chat/generate client (degrades gracefully)
    benchmarks  - discovers + runs the self-authored benchmark suite
    bench_worker - subprocess entrypoint that executes benchmarks in isolation
    improver    - proposes one scope-locked improvement (LLM or deterministic)
    scheduler   - authorized-window logic + APScheduler driver
    loop        - the governed self-improvement loop (the heart of the agent)
"""

__all__ = [
    "config",
    "db",
    "git_ops",
    "sandbox",
    "ollama_client",
    "benchmarks",
    "improver",
    "scheduler",
    "loop",
]
