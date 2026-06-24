"""The governed self-improvement loop.

One iteration = read repo → propose ONE scope-locked change → commit on the working
branch → run the self-benchmark suite → keep iff (correctness holds AND aggregate ≥
baseline AND, for benchmark edits, the anti-gaming meta-check passes) → else hard-revert.
Every attempt (kept or reverted) is logged to SQLite so the graph and table tell the
whole story.

Governance is enforced here, not just in the UI:
* nothing runs outside an authorized window;
* nothing runs once the session budget (iterations or wall-clock minutes) is spent;
* the kill switch halts mid-iteration and leaves the repo with zero partial edits.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Optional

from . import benchmarks, improver, scheduler
from .config import Config
from .db import Database
from .git_ops import GitError, GitRepo
from .ollama_client import OllamaClient


class LoopController:
    def __init__(self, repo_dir: str, db: Database, config: Config):
        self.repo_dir = repo_dir
        self.db = db
        self.config = config
        self.git = GitRepo(repo_dir, scope_dir="agent")

        self.kill_event = threading.Event()
        self._busy = threading.Lock()           # at most one iteration at a time
        self._state_lock = threading.Lock()
        self._ollama_cache = {"up": False, "ts": 0.0}  # TTL-cached health probe
        self._state = {
            "status": "idle",                   # idle | running | locked | killing
            "message": "Ready.",
            "phase": "",
            "last_error": "",
        }

    # -- helpers -------------------------------------------------------------
    def _client(self) -> OllamaClient:
        return OllamaClient(
            self.config.get("ollama_url"),
            self.config.get("ollama_model"),
            int(self.config.get("ollama_timeout")),
        )

    def _set_state(self, **kw) -> None:
        with self._state_lock:
            self._state.update(kw)

    def is_running(self) -> bool:
        return self._busy.locked()

    def ollama_up(self) -> bool:
        """Cached Ollama health (TTL 10s) so the UI refresh never hammers the network."""
        now = time.time()
        if now - self._ollama_cache["ts"] > 10:
            self._ollama_cache["ts"] = now
            try:
                self._ollama_cache["up"] = self._client().is_up()
            except Exception:  # noqa: BLE001
                self._ollama_cache["up"] = False
        return self._ollama_cache["up"]

    # -- gating (governance) -------------------------------------------------
    def _session_budget(self) -> tuple[int, int]:
        return (
            int(self.config.get("budget_max_iterations")),
            int(self.config.get("budget_max_minutes")),
        )

    def _ensure_session(self, trigger: str) -> Optional[dict]:
        """Return an active, in-budget session, opening one if needed; else None."""
        max_iter, max_min = self._session_budget()
        sess = self.db.active_session()
        if sess is None:
            sid = self.db.open_session(trigger, max_iter, max_min)
            return self.db.get_session(sid)
        return sess

    def _budget_remaining(self, sess: dict) -> tuple[bool, str]:
        max_iter, max_min = self._session_budget()
        if sess["iterations_used"] >= max_iter:
            return False, f"session budget spent ({sess['iterations_used']}/{max_iter} iterations)"
        try:
            started = datetime.fromisoformat(sess["started_at"])
            elapsed_min = (datetime.now(started.tzinfo) - started).total_seconds() / 60.0
        except (ValueError, TypeError):
            elapsed_min = 0.0
        if elapsed_min >= max_min:
            return False, f"session time budget spent ({int(elapsed_min)}/{max_min} min)"
        return True, ""

    def authorized(self) -> bool:
        return scheduler.is_authorized(self.config.get("authorized_windows"))

    def close_session_if_locked(self) -> None:
        """Called by the ticker: end any session once its window closes (no roll-over)."""
        if not self.authorized():
            sess = self.db.active_session()
            if sess:
                self.db.close_session(sess["id"], note="window closed")

    # -- baseline ------------------------------------------------------------
    def ensure_baseline(self) -> Optional[dict]:
        """Seed exactly one baseline benchmark run so the graph has a first point."""
        if self.db.run_count() > 0:
            return None
        self._set_state(status="running", phase="baseline", message="Running baseline benchmark…")
        result = benchmarks.run_suite(
            self.repo_dir, float(self.config.get("benchmark_timeout"))
        )
        self.db.insert_run(
            aggregate=result.aggregate,
            passed=result.passed,
            commit_hash=self.git.short_head(),
            label="baseline",
            iteration_id=None,
            tasks=result.tasks,
        )
        self._set_state(status="idle", phase="", message="Baseline recorded.")
        return {"aggregate": result.aggregate, "passed": result.passed}

    # -- kill / rollback -----------------------------------------------------
    def kill(self) -> dict:
        """Halt mid-iteration and leave the repo clean (no partial edits)."""
        self.kill_event.set()
        self._set_state(status="killing", message="Kill requested — reverting uncommitted work…")
        if not self.is_running():
            # Nothing in flight: clean up directly so the tree is guaranteed pristine.
            try:
                self.git.discard_working_changes()
            except GitError:
                pass
            self._set_state(status="idle", message="Killed. Working tree clean.")
        return self.status_snapshot()

    def rollback_to(self, commit: str) -> dict:
        if self.is_running():
            return {"ok": False, "error": "cannot roll back while an iteration is running"}
        try:
            self.git.rollback_to(commit)
        except GitError as exc:
            return {"ok": False, "error": str(exc)}
        # Re-baseline at the rolled-back commit so future comparisons are honest.
        result = benchmarks.run_suite(self.repo_dir, float(self.config.get("benchmark_timeout")))
        self.db.insert_run(
            aggregate=result.aggregate, passed=result.passed,
            commit_hash=self.git.short_head(), label="baseline",
            iteration_id=None, tasks=result.tasks,
        )
        return {"ok": True, "commit": self.git.short_head(), "aggregate": result.aggregate}

    # -- score summary for the LLM prompt ------------------------------------
    def _score_summary(self) -> str:
        run = self.db.latest_run()
        if not run:
            return "(no benchmark history yet)"
        rows = [r for r in self.db.task_scores_for_runs() if r["run_id"] == run["id"]]
        return "\n".join(f"- {r['name']} ({r['suite']}): {r['score']:.1f}/100" for r in rows)

    # -- the iteration -------------------------------------------------------
    def request_iteration(self, manual: bool = True) -> dict:
        """Run one iteration on a background thread (non-blocking for the UI)."""
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "status": "busy", "message": "An iteration is already running."}
        t = threading.Thread(target=self._run_guarded, args=(manual,), daemon=True)
        t.start()
        return {"ok": True, "status": "started"}

    def _run_guarded(self, manual: bool) -> None:
        try:
            self._run_one_iteration(manual)
        finally:
            self._busy.release()

    def run_one_iteration_blocking(self, manual: bool = True) -> dict:
        """Synchronous variant used by the seed script and tests."""
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "status": "busy"}
        try:
            return self._run_one_iteration(manual)
        finally:
            self._busy.release()

    def _run_one_iteration(self, manual: bool) -> dict:
        self.kill_event.clear()
        started = time.time()
        trigger = "manual" if manual else "auto"

        # --- gate 1: authorized window ---
        if not self.authorized():
            self._set_state(status="locked", message="Outside authorized window — loop is locked.")
            return {"ok": False, "status": "locked", "reason": "outside authorized window"}

        # --- gate 2: session budget ---
        sess = self._ensure_session(trigger)
        ok, reason = self._budget_remaining(sess) if sess else (False, "no session")
        if not ok:
            self.db.close_session(sess["id"], note=reason)
            self._set_state(status="locked", message=f"Locked — {reason}.")
            return {"ok": False, "status": "budget", "reason": reason}

        self._set_state(status="running", phase="prepare", message="Preparing working tree…", last_error="")

        # Start from a clean tree — the loop owns commits.
        if not self.git.is_clean():
            try:
                self.git.discard_working_changes()
            except GitError as exc:
                self._set_state(status="idle", message=f"Could not clean tree: {exc}")
                return {"ok": False, "status": "error", "reason": str(exc)}

        # Make sure there is a baseline to measure against.
        self.ensure_baseline()
        baseline = self.db.baseline_score()
        parent_hash = self.git.head()
        committed = False
        candidate_hash = ""

        try:
            # --- propose ---
            self._set_state(phase="propose", message="Selecting an improvement target…")
            if self.kill_event.is_set():
                return self._finish_killed(parent_hash, committed)

            client = self._client()
            proposal = improver.propose(
                self.repo_dir,
                strategy=self.config.get("improver_strategy"),
                client=client,
                score_summary=self._score_summary(),
            )
            if proposal is None:
                return self._record_skip(sess, parent_hash, baseline,
                                         "no improvement target found (code already optimised)")

            # --- scope lock + apply ---
            self.git.assert_in_scope([proposal.file_path])
            target_path = f"{self.repo_dir}/{proposal.file_path}"
            with open(target_path, "w", encoding="utf-8") as fh:
                fh.write(proposal.new_content)

            if self.kill_event.is_set():
                return self._finish_killed(parent_hash, committed)

            # --- commit candidate on the working branch ---
            self._set_state(phase="commit", message=f"Committing: {proposal.description}")
            staged = self.git.stage_scope()  # raises GitError if anything is out of scope
            if not staged:
                return self._record_skip(sess, parent_hash, baseline, "proposal produced no diff")
            commit_msg = f"agent: {proposal.description} [{proposal.source}/{proposal.target}]"
            candidate_hash = self.git.commit(commit_msg)
            committed = True
            changed = self.git.changed_paths_in(candidate_hash)
            touches_bench = any(p.startswith("agent/benchmarks/") for p in changed)

            # --- benchmark the candidate (killable subprocess) ---
            self._set_state(phase="benchmark", message="Running self-benchmark suite…")
            result = benchmarks.run_suite(
                self.repo_dir, float(self.config.get("benchmark_timeout")), self.kill_event
            )
            if self.kill_event.is_set() or result.error == "killed":
                return self._finish_killed(parent_hash, committed)

            new_score = result.aggregate
            delta = None if baseline is None else round(new_score - baseline, 3)

            # --- anti-gaming meta-check on benchmark edits ---
            flagged = 0
            meta_ok = True
            meta_reason = ""
            if touches_bench:
                changed_benches = [
                    p.rsplit("/", 1)[-1][:-3] for p in changed
                    if p.startswith("agent/benchmarks/")
                    and p.endswith(".py") and "/bench_" in p
                ]
                meta = benchmarks.meta_check(
                    self.repo_dir, changed_benches,
                    float(self.config.get("benchmark_timeout")), self.kill_event,
                )
                # The meta-check temporarily swaps solution source; make the working
                # tree match the committed candidate again before deciding keep/revert.
                self.git.restore_scope_to_head()
                meta_ok = bool(meta.get("ok"))
                if not meta_ok:
                    meta_reason = "benchmark meta-check failed: " + json.dumps(meta.get("report", {}))[:200]
                # Editing a benchmark AND raising your own score is the gaming signature.
                if baseline is not None and new_score > baseline:
                    flagged = 1

            # --- keep-or-revert decision ---
            regressed = baseline is not None and new_score < baseline - 1e-6
            keep = result.ok and result.passed and not regressed and meta_ok

            if keep:
                status = "kept"
                reason = self._keep_reason(new_score, baseline, flagged)
                label = "kept"
            else:
                status = "reverted"
                reason = self._revert_reason(result, regressed, meta_ok, meta_reason, baseline, new_score)
                label = "reverted"
                self.git.revert_last_commit()      # hard-reset the candidate away
                committed = False

            # --- persist iteration + benchmark run ---
            iteration_id = self.db.insert_iteration(
                session_id=sess["id"],
                target=proposal.target,
                source=proposal.source,
                description=proposal.description,
                files_changed=changed,
                commit_hash=candidate_hash if keep else f"{candidate_hash} (reverted)",
                parent_hash=parent_hash,
                baseline_score=baseline,
                new_score=new_score,
                score_delta=delta,
                status=status,
                reason=reason,
                flagged=flagged,
                duration_ms=int((time.time() - started) * 1000),
            )
            self.db.insert_run(
                aggregate=new_score, passed=result.passed,
                commit_hash=candidate_hash, label=label,
                iteration_id=iteration_id, tasks=result.tasks,
            )
            self.db.bump_session_iterations(sess["id"])

            self._set_state(
                status="idle", phase="",
                message=f"{status.title()} — {reason}",
            )
            return {
                "ok": True, "status": status, "reason": reason,
                "new_score": new_score, "baseline": baseline, "delta": delta,
                "flagged": bool(flagged), "iteration_id": iteration_id,
            }

        except GitError as exc:
            self._safe_cleanup(parent_hash, committed)
            self._record_error(sess, parent_hash, baseline, str(exc))
            self._set_state(status="idle", phase="", last_error=str(exc),
                            message=f"Iteration error: {exc}")
            return {"ok": False, "status": "error", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never leave the tree dirty on a crash
            self._safe_cleanup(parent_hash, committed)
            self._record_error(sess, parent_hash, baseline, repr(exc))
            self._set_state(status="idle", phase="", last_error=repr(exc),
                            message=f"Iteration crashed: {exc}")
            return {"ok": False, "status": "error", "reason": repr(exc)}

    # -- decision text -------------------------------------------------------
    @staticmethod
    def _keep_reason(new_score: float, baseline: Optional[float], flagged: int) -> str:
        base = "first baseline-beating run" if baseline is None else f"{new_score:.2f} ≥ baseline {baseline:.2f}"
        if flagged:
            return f"kept but FLAGGED (benchmarks edited + score rose): {base}"
        return f"kept: {base}"

    @staticmethod
    def _revert_reason(result, regressed, meta_ok, meta_reason, baseline, new_score) -> str:
        if not result.ok:
            return f"reverted: benchmark run failed ({result.error})"
        if not result.passed:
            return "reverted: correctness gate failed (a function returned wrong output)"
        if not meta_ok:
            return f"reverted: {meta_reason}"
        if regressed:
            return f"reverted: regression {new_score:.2f} < baseline {baseline:.2f}"
        return "reverted: did not meet keep criteria"

    # -- bookkeeping for non-kept outcomes -----------------------------------
    def _record_skip(self, sess, parent_hash, baseline, reason) -> dict:
        self.git.discard_working_changes()
        self.db.insert_iteration(
            session_id=sess["id"], target="none", source="loop", description=reason,
            files_changed=[], commit_hash=parent_hash, parent_hash=parent_hash,
            baseline_score=baseline, new_score=baseline, score_delta=0.0,
            status="skipped", reason=reason, flagged=0, duration_ms=0,
        )
        self.db.bump_session_iterations(sess["id"])
        self._set_state(status="idle", phase="", message=f"Skipped — {reason}")
        return {"ok": True, "status": "skipped", "reason": reason}

    def _record_error(self, sess, parent_hash, baseline, reason) -> None:
        if sess is None:
            return
        self.db.insert_iteration(
            session_id=sess["id"], target="none", source="loop", description="iteration error",
            files_changed=[], commit_hash=parent_hash, parent_hash=parent_hash,
            baseline_score=baseline, new_score=baseline, score_delta=0.0,
            status="error", reason=reason[:500], flagged=0, duration_ms=0,
        )

    def _finish_killed(self, parent_hash, committed) -> dict:
        self._safe_cleanup(parent_hash, committed)
        self._set_state(status="idle", phase="", message="Killed mid-iteration. Working tree is clean.")
        return {"ok": False, "status": "killed", "reason": "kill switch engaged"}

    def _safe_cleanup(self, parent_hash, committed) -> None:
        try:
            if committed:
                self.git.reset_hard(parent_hash)
            else:
                self.git.discard_working_changes()
        except GitError:
            pass

    # -- ticker callback -----------------------------------------------------
    def tick(self) -> None:
        """Invoked by the scheduler: open/close windows and auto-run when allowed."""
        if not self.authorized():
            self.close_session_if_locked()
            if not self.is_running() and self._state["status"] != "killing":
                self._set_state(status="locked", message="Outside authorized window — loop is locked.")
            return
        if self._state["status"] == "locked":
            self._set_state(status="idle", message="Authorized window open.")
        if not self.config.get("auto_run") or self.is_running():
            return
        sess = self.db.active_session() or self._ensure_session("auto")
        ok, _ = self._budget_remaining(sess) if sess else (False, "")
        if ok:
            self.request_iteration(manual=False)

    # -- snapshot for the UI -------------------------------------------------
    def status_snapshot(self) -> dict:
        with self._state_lock:
            state = dict(self._state)
        windows = self.config.get("authorized_windows")
        authorized = scheduler.is_authorized(windows)
        nxt = scheduler.next_window_start(windows)
        sess = self.db.active_session()
        max_iter, max_min = self._session_budget()
        latest = self.db.latest_run()
        try:
            branch = self.git.current_branch()
            head = self.git.short_head()
            clean = self.git.is_clean()
        except GitError:
            branch, head, clean = "?", "?", True
        return {
            **state,
            "authorized": authorized,
            "auto_run": bool(self.config.get("auto_run")),
            "current_window": scheduler.current_window(windows),
            "next_window": nxt.isoformat(timespec="minutes") if nxt else None,
            "session": {
                "active": sess is not None,
                "iterations_used": sess["iterations_used"] if sess else 0,
                "max_iterations": max_iter,
                "max_minutes": max_min,
                "started_at": sess["started_at"] if sess else None,
            },
            "ollama_up": self.ollama_up(),
            "model": self.config.get("ollama_model"),
            "baseline_score": self.db.baseline_score(),
            "latest_score": latest["aggregate"] if latest else None,
            "run_count": self.db.run_count(),
            "branch": branch,
            "head": head,
            "tree_clean": clean,
            "running": self.is_running(),
        }
