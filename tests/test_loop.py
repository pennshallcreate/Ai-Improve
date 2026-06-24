"""End-to-end tests for the governed self-improvement loop.

Runs standalone (``python tests/test_loop.py``) or under pytest. Each test builds a
throwaway git repo from the project files so nothing here touches the real history.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from core import improver, scheduler                      # noqa: E402
from core.benchmarks import SuiteResult                   # noqa: E402
from core.config import Config                            # noqa: E402
from core.db import Database                              # noqa: E402
from core.git_ops import GitError                         # noqa: E402
from core.improver import Proposal                        # noqa: E402
from core.loop import LoopController                      # noqa: E402


def _make_repo() -> tuple[str, LoopController, Database, Config]:
    tmp = tempfile.mkdtemp(prefix="aiimprove_test_")
    shutil.copytree(
        REPO_ROOT, tmp, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "data", "*.sqlite*", ".venv"),
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp, check=True)

    db = Database(os.path.join(tmp, "data", "t.sqlite"))
    config = Config(db)
    config.set("authorized_windows", [scheduler.authorize_now_window(120)])
    config.set("improver_strategy", "heuristic")
    config.set("budget_max_iterations", 25)
    return tmp, LoopController(tmp, db, config), db, config


def _agent_dirty(repo: str) -> bool:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                         capture_output=True, text=True).stdout
    return any("agent/" in line for line in out.splitlines())


# --------------------------------------------------------------------------- #
def test_iterations_improve_and_stay_clean() -> None:
    repo, loop, db, _ = _make_repo()
    loop.ensure_baseline()
    base = db.baseline_score()
    assert base is not None and base < 70, f"baseline should have headroom, got {base}"

    kept = 0
    for _ in range(10):
        res = loop.run_one_iteration_blocking()
        if res.get("status") == "kept":
            kept += 1
        elif res.get("status") == "skipped":
            break
    final = db.baseline_score()
    assert kept >= 3, f"expected several kept iterations, got {kept}"
    assert final > base, f"score should climb: {base} -> {final}"
    assert not _agent_dirty(repo), "working tree must be clean after iterations"
    print(f"[ok] improve: {base:.1f} -> {final:.1f} over {kept} kept iterations")


def test_revert_on_broken_correctness() -> None:
    repo, loop, db, _ = _make_repo()
    loop.ensure_baseline()
    head_before = loop.git.head()

    def broken(repo_dir, **kw):
        src = open(os.path.join(repo_dir, "agent/solutions.py")).read()
        return Proposal("latency", "test", "break is_prime", "agent/solutions.py",
                        src.replace("    return True\n", "    return False\n", 1))

    orig, improver.propose = improver.propose, broken
    try:
        res = loop.run_one_iteration_blocking()
    finally:
        improver.propose = orig

    assert res["status"] == "reverted", res
    assert "correctness" in res["reason"]
    assert loop.git.head() == head_before, "broken commit must be reverted away"
    assert not _agent_dirty(repo)
    print("[ok] revert-on-broken-correctness")


def test_anti_gaming_meta_check() -> None:
    repo, loop, db, _ = _make_repo()
    loop.ensure_baseline()

    def gaming(repo_dir, **kw):
        return Proposal("quality", "test", "game quality benchmark",
                        "agent/benchmarks/bench_quality.py",
                        'NAME="quality"\nSUITE="quality"\nVERSION=99\n'
                        'def run():\n    return {"name":"quality","suite":"quality",'
                        '"score":100.0,"passed":True,"details":{}}\n')

    orig, improver.propose = improver.propose, gaming
    try:
        res = loop.run_one_iteration_blocking()
    finally:
        improver.propose = orig

    assert res["status"] == "reverted", res
    assert "meta-check" in res["reason"], res["reason"]
    assert not _agent_dirty(repo)
    print("[ok] anti-gaming meta-check reverts a rubber-stamp benchmark")


def test_kill_leaves_clean_tree() -> None:
    repo, loop, db, _ = _make_repo()
    loop.ensure_baseline()
    head_before = loop.git.head()

    import core.loop as loopmod

    def good(repo_dir, **kw):
        src = open(os.path.join(repo_dir, "agent/solutions.py")).read()
        return Proposal("latency", "test", "valid change", "agent/solutions.py",
                        src + "\n# touched\n")

    def killed_suite(repo_dir, timeout, kill_event=None):
        if kill_event is not None:
            kill_event.set()
        return SuiteResult(False, 0.0, False, error="killed")

    op, improver.propose = improver.propose, good
    os_suite, loopmod.benchmarks.run_suite = loopmod.benchmarks.run_suite, killed_suite
    try:
        res = loop.run_one_iteration_blocking()
    finally:
        improver.propose = op
        loopmod.benchmarks.run_suite = os_suite

    assert res["status"] == "killed", res
    assert loop.git.head() == head_before, "candidate commit must be undone on kill"
    assert not _agent_dirty(repo), "kill must leave no partial edits"
    print("[ok] kill switch leaves a clean tree")


def test_locked_outside_window() -> None:
    repo, loop, db, config = _make_repo()
    loop.ensure_baseline()
    config.set("authorized_windows", [{"type": "weekly", "days": [], "start": "00:00", "end": "00:00"}])
    res = loop.run_one_iteration_blocking()
    assert res["status"] == "locked", res
    assert not loop.authorized()
    print("[ok] loop locked outside authorized window")


def test_scope_lock_rejects_out_of_scope() -> None:
    repo, loop, _, _ = _make_repo()
    try:
        loop.git.assert_in_scope(["core/loop.py"])
        assert False, "should have rejected an out-of-scope path"
    except GitError:
        pass
    loop.git.assert_in_scope(["agent/solutions.py"])  # in-scope must pass
    print("[ok] scope lock rejects edits outside agent/")


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failures += 1
            print(f"[FAIL] {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[ERROR] {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
