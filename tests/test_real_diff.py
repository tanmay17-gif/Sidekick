"""Regression tests for the real diff.

These were written after a defect was found: the tracked-file diff used an
invalid git option, so ``git diff`` failed and the service reported **no
diff at all** for a modified tracked file. Only *new* files had shown up in
the diff, because they are produced by a different git invocation.

The rule these tests protect: a diff that is empty must mean "nothing
changed", never "the diff command failed".
"""

from __future__ import annotations

import unittest

from tests.support import TempDirTestCase, requires_git, run_git, write_test_project

from sidekick_execution import errors
from sidekick_execution.errors import SidekickError
from sidekick_execution.sandbox import CommandPolicy, CommandRunner
from sidekick_execution.vcs import GitWorkspace


class RealDiffTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        requires_git(self)
        self.repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], self.repo)
        run_git(["config", "user.email", "t@sidekick.invalid"], self.repo)
        run_git(["config", "user.name", "Sidekick Tests"], self.repo)
        run_git(["add", "-A"], self.repo)
        run_git(["commit", "-m", "initial"], self.repo)
        self.git = GitWorkspace(self.repo, CommandRunner(CommandPolicy(timeout_seconds=60)))

    def test_a_modified_tracked_file_appears_in_the_diff(self) -> None:
        """The defect: a modified tracked file produced an empty diff."""
        target = self.repo / "calculator.py"
        target.write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")

        diff = self.git.diff()

        self.assertTrue(diff.diff.strip(), "a modified tracked file must produce a diff")
        self.assertIn("calculator.py", diff.diff)
        self.assertIn("+    return a + b + 1", diff.diff)
        self.assertIn("calculator.py", [c.path for c in diff.changed_files])

    def test_a_new_file_appears_in_the_diff(self) -> None:
        (self.repo / "brand_new.py").write_text("X = 1\n", encoding="utf-8")
        diff = self.git.diff()
        self.assertIn("brand_new.py", diff.diff)
        self.assertIn("+X = 1", diff.diff)

    def test_a_deleted_file_appears_in_the_diff(self) -> None:
        (self.repo / "calculator.py").unlink()
        diff = self.git.diff()
        self.assertIn("calculator.py", diff.diff)

    def test_an_unchanged_workspace_produces_an_empty_diff(self) -> None:
        diff = self.git.diff()
        self.assertEqual(diff.diff, "")
        self.assertEqual(diff.changed_files, [])
        self.assertTrue(diff.available)

    def test_a_failed_git_command_never_looks_like_no_changes(self) -> None:
        """A broken git command must fail loudly, not report 'nothing changed'."""
        with self.assertRaises(SidekickError) as ctx:
            self.git._git_checked(["this-is-not-a-git-command"], "testing the guard")
        self.assertEqual(ctx.exception.code, errors.VCS_ERROR)
        self.assertIn("stderr", ctx.exception.details)

    def test_a_missing_repository_is_reported_as_such(self) -> None:
        """A workspace without Git metadata is not 'a clean diff'."""
        # Git's object files are read-only on Windows, so the directory is
        # moved aside rather than deleted.
        (self.repo / ".git").rename(self.repo / ".git-moved")

        with self.assertRaises(SidekickError) as ctx:
            self.git.diff()
        self.assertEqual(ctx.exception.code, errors.VCS_NOT_A_REPOSITORY)

    def test_a_command_outside_the_allowlist_is_refused(self) -> None:
        broken = GitWorkspace(
            self.repo,
            CommandRunner(
                CommandPolicy(timeout_seconds=60, allowed_executables=("python",))
            ),
        )
        with self.assertRaises(SidekickError) as ctx:
            broken.diff()
        self.assertEqual(ctx.exception.code, errors.COMMAND_NOT_ALLOWED)

    def test_the_changed_file_list_matches_the_real_git_status(self) -> None:
        (self.repo / "calculator.py").write_text("changed = True\n", encoding="utf-8")
        (self.repo / "new.py").write_text("N = 1\n", encoding="utf-8")
        real = run_git(["status", "--porcelain=v1"], self.repo).stdout
        real_paths = {line[3:].strip() for line in real.splitlines() if len(line) > 3}
        reported = {c.path for c in self.git.diff().changed_files}
        self.assertEqual(reported, real_paths)


if __name__ == "__main__":
    unittest.main()
