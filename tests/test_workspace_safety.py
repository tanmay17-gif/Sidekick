"""Tests for workspace authorization and command safety.

The rules under test come straight from the safety requirements: ambiguous or
unauthorized paths are refused, destructive commands are blocked, and the
sandbox enforces its allowlist, timeout, output bound and environment
scrubbing.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from tests.support import TempDirTestCase

from sidekick_execution import errors
from sidekick_execution.errors import SidekickError
from sidekick_execution.sandbox import CommandPolicy, CommandRunner
from sidekick_execution.workspace import WorkspacePolicy


class WorkspacePolicyTests(TempDirTestCase):
    def test_absolute_existing_directory_is_accepted(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)])
        workspace = policy.validate(str(self.tmp_path))
        self.assertEqual(workspace.root, self.tmp_path.resolve())

    def test_relative_path_is_rejected_as_ambiguous(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)])
        with self.assertRaises(SidekickError) as ctx:
            policy.validate("some/relative/path")
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_INVALID)

    def test_empty_path_is_rejected(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)])
        with self.assertRaises(SidekickError) as ctx:
            policy.validate("   ")
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_INVALID)

    def test_missing_directory_is_rejected(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)])
        with self.assertRaises(SidekickError) as ctx:
            policy.validate(str(self.tmp_path / "nope"))
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_NOT_FOUND)

    def test_path_outside_allowed_roots_is_unauthorized(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path / "allowed")])
        (self.tmp_path / "allowed").mkdir()
        (self.tmp_path / "other").mkdir()
        with self.assertRaises(SidekickError) as ctx:
            policy.validate(str(self.tmp_path / "other"))
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_UNAUTHORIZED)

    def test_traversal_out_of_authorized_root_is_unauthorized(self) -> None:
        allowed = self.tmp_path / "allowed"
        allowed.mkdir()
        (self.tmp_path / "secret").mkdir()
        policy = WorkspacePolicy([str(allowed)])
        with self.assertRaises(SidekickError) as ctx:
            policy.validate(str(allowed / ".." / "secret"))
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_UNAUTHORIZED)

    def test_file_path_is_not_a_directory(self) -> None:
        target = self.tmp_path / "a_file.txt"
        target.write_text("x", encoding="utf-8")
        policy = WorkspacePolicy([str(self.tmp_path)])
        with self.assertRaises(SidekickError) as ctx:
            policy.validate(str(target))
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_NOT_A_DIRECTORY)

    def test_resolve_child_rejects_escape(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)])
        workspace = policy.validate(str(self.tmp_path))
        with self.assertRaises(SidekickError) as ctx:
            workspace.resolve_child("../outside.txt")
        self.assertEqual(ctx.exception.code, errors.EDIT_OUTSIDE_WORKSPACE)

    def test_disposable_workspace_is_created_and_destroyed(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)], disposable_root=str(self.tmp_path))
        workspace = policy.create_disposable()
        self.assertTrue(workspace.root.is_dir())
        self.assertTrue(workspace.disposable)
        policy.destroy_disposable(workspace)
        self.assertFalse(workspace.root.exists())

    def test_non_disposable_workspace_is_never_destroyed(self) -> None:
        policy = WorkspacePolicy([str(self.tmp_path)])
        workspace = policy.validate(str(self.tmp_path))
        with self.assertRaises(SidekickError):
            policy.destroy_disposable(workspace)
        self.assertTrue(self.tmp_path.exists())


class CommandSafetyTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runner = CommandRunner(CommandPolicy(timeout_seconds=20.0))

    def test_executable_outside_allowlist_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run(["reg", "query", "HKCU"], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.COMMAND_NOT_ALLOWED)

    def test_shell_launcher_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run(["cmd", "/c", "dir"], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.COMMAND_NOT_ALLOWED)

    def test_destructive_git_command_is_blocked(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run(["git", "reset", "--hard"], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.DESTRUCTIVE_ACTION_BLOCKED)

    def test_destructive_git_clean_is_blocked(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run(["git", "clean", "-fdx"], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.DESTRUCTIVE_ACTION_BLOCKED)

    def test_destructive_force_push_is_blocked(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run(["git", "push", "--force", "origin", "main"], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.DESTRUCTIVE_ACTION_BLOCKED)

    def test_empty_argv_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run([], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    def test_missing_executable_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.runner.run(["definitely-not-a-real-binary"], cwd=self.tmp_path)
        self.assertEqual(ctx.exception.code, errors.COMMAND_NOT_ALLOWED)


class CommandExecutionTests(TempDirTestCase):
    def test_real_command_runs_and_exit_code_is_preserved(self) -> None:
        runner = CommandRunner(CommandPolicy(timeout_seconds=20.0))
        result = runner.run([sys.executable, "-c", "print('hello')"], cwd=self.tmp_path)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello", result.stdout)
        self.assertTrue(result.ok)

    def test_failing_command_keeps_its_exit_code(self) -> None:
        runner = CommandRunner(CommandPolicy(timeout_seconds=20.0))
        result = runner.run([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=self.tmp_path)
        self.assertEqual(result.exit_code, 3)
        self.assertFalse(result.ok)

    def test_timeout_is_reported_honestly(self) -> None:
        runner = CommandRunner(CommandPolicy(timeout_seconds=1.5))
        result = runner.run(
            [sys.executable, "-c", "import time; time.sleep(30)"], cwd=self.tmp_path
        )
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)
        self.assertLess(result.duration_ms, 20000)

    def test_output_is_bounded_and_truncation_is_reported(self) -> None:
        runner = CommandRunner(CommandPolicy(timeout_seconds=30.0, max_output_bytes=2048))
        result = runner.run(
            [sys.executable, "-c", "print('x' * 100000)"], cwd=self.tmp_path
        )
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.stdout), 4096)

    def test_environment_is_scrubbed(self) -> None:
        os.environ["SIDEKICK_TEST_SECRET"] = "leak-me"
        self.addCleanup(os.environ.pop, "SIDEKICK_TEST_SECRET", None)
        runner = CommandRunner(CommandPolicy(timeout_seconds=20.0))
        result = runner.run(
            [
                sys.executable,
                "-c",
                "import os; print('SIDEKICK_TEST_SECRET' in os.environ)",
            ],
            cwd=self.tmp_path,
        )
        self.assertIn("False", result.stdout)

    def test_registered_secrets_are_redacted_from_output(self) -> None:
        policy = CommandPolicy(timeout_seconds=20.0)
        policy.add_secret("hunter2-very-secret")
        runner = CommandRunner(policy)
        result = runner.run(
            [sys.executable, "-c", "print('token=hunter2-very-secret')"], cwd=self.tmp_path
        )
        self.assertNotIn("hunter2-very-secret", result.stdout)
        self.assertIn("redacted", result.stdout)

    def test_cancellation_stops_a_running_command(self) -> None:
        import threading

        runner = CommandRunner(CommandPolicy(timeout_seconds=30.0))
        cancel = threading.Event()
        timer = threading.Timer(1.0, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        result = runner.run_cancellable(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=self.tmp_path,
            cancel_event=cancel,
        )
        self.assertTrue(result.cancelled)
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
