"""Real version-control integration for Sidekick execution.

Captures genuine diffs from a workspace's Git repository. Nothing here
synthesizes a diff: every patch comes from running ``git`` against the real
working tree.

Supported operations:

* ``head_sha`` -- the current commit.
* ``status`` -- porcelain status parsed into structured file entries.
* ``diff`` -- a unified diff of tracked modifications *plus* untracked files
  (untracked files are diffed against an empty file so they appear as real
  additions).
* ``changed_files`` -- the list of files the diff touches.

The repository's index is never mutated: untracked content is obtained with
``git diff --no-index`` rather than ``git add --intent-to-add``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import errors
from .errors import SidekickError
from .sandbox import CommandRunner

DEFAULT_MAX_DIFF_BYTES = 512 * 1024


@dataclass
class FileChange:
    """One changed file."""

    path: str
    status: str  # modified | added | deleted | renamed | untracked | unknown

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "status": self.status}


@dataclass
class DiffResult:
    """A real diff captured from the workspace."""

    diff: str
    changed_files: List[FileChange] = field(default_factory=list)
    truncated: bool = False
    head_sha: Optional[str] = None
    #: False when the workspace is not a repository, so there is no diff to
    #: report. A missing diff is never reported as "no changes".
    available: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "diff": self.diff,
            "changed_files": [c.to_dict() for c in self.changed_files],
            "truncated": self.truncated,
            "head_sha": self.head_sha,
            "available": self.available,
            "file_count": len(self.changed_files),
        }


class GitWorkspace:
    """Reads real Git state from a workspace directory."""

    def __init__(self, root: Path, runner: Optional[CommandRunner] = None) -> None:
        self.root = Path(root)
        self.runner = runner or CommandRunner()

    # -- helpers -----------------------------------------------------------
    def _git(self, args: Sequence[str], *, check: bool = True) -> str:
        result = self.runner.run(["git", *args], cwd=self.root, timeout=60)
        if check and result.exit_code != 0:
            raise SidekickError(
                errors.VCS_ERROR,
                f"git {' '.join(args)} failed with exit code {result.exit_code}.",
                details={
                    "argv": list(args),
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[-2000:],
                },
            )
        return result.stdout

    def _git_checked(self, args: Sequence[str], what: str) -> str:
        """Run a git command and fail loudly.

        A git command that fails must never look like "there was nothing to
        report": an empty diff because the command was rejected is a lie.
        """
        result = self.runner.run(["git", *args], cwd=self.root, timeout=60)
        if result.exit_code != 0:
            raise SidekickError(
                errors.VCS_ERROR,
                f"git {' '.join(args)} failed while {what}.",
                details={
                    "argv": list(args),
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[-2000:],
                },
            )
        return result.stdout

    def is_repository(self) -> bool:
        result = self.runner.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=self.root, timeout=60
        )
        return result.exit_code == 0 and result.stdout.strip() == "true"

    def head_sha(self) -> Optional[str]:
        result = self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.root, timeout=60)
        if result.exit_code != 0:
            return None
        sha = result.stdout.strip()
        return sha or None

    # -- status ------------------------------------------------------------
    def status(self) -> List[FileChange]:
        """Return the real porcelain status of the working tree."""
        raw = self._git(["status", "--porcelain=v1", "--untracked-files=all"], check=False)
        changes: List[FileChange] = []
        for line in raw.splitlines():
            if len(line) < 3:
                continue
            code = line[:2]
            path = line[3:].strip()
            if " -> " in path:  # rename: "old -> new"
                path = path.split(" -> ", 1)[1]
            if code == "??":
                changes.append(FileChange(path=path, status="untracked"))
            elif code == "!!":
                continue
            else:
                if "D" in code:
                    status = "deleted"
                elif "A" in code:
                    status = "added"
                elif "R" in code:
                    status = "renamed"
                elif "M" in code:
                    status = "modified"
                else:
                    status = "unknown"
                changes.append(FileChange(path=path, status=status))
        return changes

    # -- diff --------------------------------------------------------------
    def diff(self, *, max_bytes: int = DEFAULT_MAX_DIFF_BYTES) -> DiffResult:
        """Capture a real unified diff of the working tree.

        Raises:
            SidekickError: ``vcs_not_a_repository`` when the workspace is not
                a Git repository, ``diff_too_large`` when the diff exceeds
                ``max_bytes``.
        """
        if not self.is_repository():
            raise SidekickError(
                errors.VCS_NOT_A_REPOSITORY,
                "The workspace is not a version-controlled repository, so no real diff exists.",
                details={"path": str(self.root)},
            )
        parts: List[str] = []
        truncated = False
        total = 0

        # The tracked modifications. ``git diff`` compares the working tree
        # with the index, so this is the real patch for every tracked file
        # that was modified, added to the index or deleted.
        tracked = self._git_checked(
            ["diff", "--no-color", "--no-ext-diff"], "capturing the tracked diff"
        )
        if tracked:
            total += len(tracked)
            parts.append(tracked)

        untracked_paths = [c.path for c in self.status() if c.status == "untracked"]
        for rel in untracked_paths:
            patch = self._untracked_patch(rel)
            if not patch:
                continue
            total += len(patch)
            parts.append(patch)

        body = "".join(parts)
        if total > max_bytes:
            truncated = True
            body = body[:max_bytes]

        changes = self.status()
        return DiffResult(
            diff=body,
            changed_files=changes,
            truncated=truncated,
            head_sha=self.head_sha(),
        )

    def _untracked_patch(self, rel: str) -> str:
        """Diff an untracked file against an empty file without touching the index."""
        abs_path = self.root / rel
        if not abs_path.is_file():
            return ""
        result = self.runner.run(
            [
                "git",
                "diff",
                "--no-color",
                "--no-ext-diff",
                "--no-index",
                "--",
                os.devnull,
                rel,
            ],
            cwd=self.root,
            timeout=60,
        )
        # `git diff --no-index` exits 1 when the files differ; that is success
        # for our purposes. Any other exit code means the patch could not be
        # produced, and the file is reported as changed without a patch
        # rather than being silently dropped.
        if result.exit_code not in (0, 1):
            raise SidekickError(
                errors.VCS_ERROR,
                f"Could not produce a diff for the untracked file {rel!r}.",
                details={
                    "path": rel,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[-2000:],
                },
            )
        return result.stdout

    def changed_files(self) -> List[str]:
        return [c.path for c in self.status()]
