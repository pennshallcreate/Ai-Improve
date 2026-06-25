"""Killable subprocess runner with timeouts.

Benchmarks run in a fresh subprocess so each iteration sees freshly-modified agent
code (no stale import cache) and so a runaway task can be force-killed — by timeout
or by the UI kill switch via a shared ``threading.Event``.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    killed: bool


def run(
    cmd: list[str],
    cwd: str,
    timeout: float,
    kill_event: threading.Event | None = None,
    env: dict | None = None,
    poll: float = 0.2,
) -> RunResult:
    """Run ``cmd`` in ``cwd``; terminate on timeout or when ``kill_event`` is set.

    The child is started in its own process group so we can take down any
    grandchildren it spawned (e.g. a benchmark that shells out).
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    # Keep stdlib importable from the repo root inside the worker subprocess.
    full_env["PYTHONPATH"] = cwd + os.pathsep + full_env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=full_env,
        start_new_session=True,  # own process group → group kill works
    )

    timed_out = False
    killed = False
    waited = 0.0
    while True:
        try:
            proc.wait(timeout=poll)
            break
        except subprocess.TimeoutExpired:
            waited += poll
            if kill_event is not None and kill_event.is_set():
                killed = True
                _terminate(proc)
                break
            if waited >= timeout:
                timed_out = True
                _terminate(proc)
                break

    out, err = proc.communicate()
    return RunResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=out or "",
        stderr=err or "",
        timed_out=timed_out,
        killed=killed,
    )


def _terminate(proc: subprocess.Popen) -> None:
    """SIGTERM the whole process group, then SIGKILL if it lingers."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
