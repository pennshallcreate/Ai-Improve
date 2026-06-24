"""Self-authored, versioned benchmark suite.

The agent owns and evolves these tasks. Each ``bench_*.py`` module exposes:

    NAME    : str    - unique benchmark name
    SUITE   : str    - 'correctness' | 'latency' | 'efficiency' | 'quality'
    VERSION : int    - bump when the task definition changes
    run()   -> dict  - {'name','suite','score' (0-100),'passed' (bool),'details'}

The runner discovers every ``bench_*.py`` here, executes it in an isolated
subprocess, and aggregates the scores. Correctness benchmarks act as a hard gate:
an iteration is only kept if all of them pass.
"""
