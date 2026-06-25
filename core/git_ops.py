"""Scope-aware wrapper around the ``git`` CLI.

The self-improvement loop owns the working tree while it runs: it stages changes
under ``agent/``, commits one iteration at a time, and either keeps the commit or
hard-resets it away on regression. ``GitError`` surfaces any non-zero git exit so
the loop can record a clean failure reason instead of corrupting the repo.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


class GitError(RuntimeError):
    pass


@dataclass
class CommitInfo:
    hash: str
    short: str
    subject: str
    timestamp: str


class GitRepo:
    def __init__(self, repo_dir: str, scope_dir: str = "agent"):
        self.repo_dir = os.path.abspath(repo_dir)
        self.scope_dir = scope_dir.rstrip("/")

    # -- low-level -----------------------------------------------------------
    def _run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed ({proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout.strip()

    # -- state ---------------------------------------------------------------
    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD")

    def head(self) -> str:
        return self._run("rev-parse", "HEAD")

    def short_head(self) -> str:
        return self._run("rev-parse", "--short", "HEAD")

    def is_clean(self) -> bool:
        return self._run("status", "--porcelain") == ""

    def dirty_paths(self) -> list[str]:
        out = self._run("status", "--porcelain")
        return [line[3:] for line in out.splitlines()] if out else []

    def log(self, limit: int = 50) -> list[CommitInfo]:
        fmt = "%H%x1f%h%x1f%s%x1f%cI"
        out = self._run("log", f"-{limit}", f"--pretty=format:{fmt}", check=False)
        commits: list[CommitInfo] = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(CommitInfo(*parts))
        return commits

    # -- scope guard ---------------------------------------------------------
    def assert_in_scope(self, rel_paths: list[str]) -> None:
        """Raise unless every path is inside the scope dir (no escapes, no system files)."""
        for rel in rel_paths:
            norm = os.path.normpath(rel)
            if norm.startswith("..") or os.path.isabs(norm):
                raise GitError(f"path escapes repo: {rel}")
            top = norm.split(os.sep)[0]
            if top != self.scope_dir:
                raise GitError(
                    f"out-of-scope edit blocked: {rel} (only '{self.scope_dir}/' is writable)"
                )

    def staged_paths(self) -> list[str]:
        out = self._run("diff", "--cached", "--name-only")
        return out.splitlines() if out else []

    def changed_paths_in(self, commit: str) -> list[str]:
        out = self._run(
            "diff-tree", "--no-commit-id", "--name-only", "-r", commit, check=False
        )
        return out.splitlines() if out else []

    # -- mutation ------------------------------------------------------------
    def stage_scope(self) -> list[str]:
        """Stage only changes under the scope dir; refuse if anything else is dirty."""
        self._run("add", "--", self.scope_dir + "/")
        staged = self.staged_paths()
        self.assert_in_scope(staged)
        return staged

    def commit(self, message: str) -> str:
        self._run("commit", "--no-verify", "-m", message)
        return self.head()

    def reset_hard(self, ref: str = "HEAD") -> None:
        self._run("reset", "--hard", ref)

    def clean_scope(self) -> None:
        """Remove untracked files under the scope dir (used by the kill switch)."""
        self._run("clean", "-fd", "--", self.scope_dir + "/")

    def discard_working_changes(self) -> None:
        """Revert uncommitted edits + remove untracked scope files → clean tree."""
        self.reset_hard("HEAD")
        self.clean_scope()

    def revert_last_commit(self) -> None:
        """Drop the most recent (candidate) commit entirely."""
        self.reset_hard("HEAD~1")

    def rollback_to(self, commit: str) -> None:
        """One-click rollback: move the working branch to an earlier commit."""
        self.discard_working_changes()
        self.reset_hard(commit)

    def restore_scope_to_head(self) -> None:
        """Reset tracked scope files to HEAD (undo any stray edits, e.g. from a
        meta-check that temporarily swapped a file). No-op when already in sync."""
        self._run("checkout", "--", self.scope_dir + "/")
