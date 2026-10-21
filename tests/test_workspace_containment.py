"""Regression tests for workspace containment.

These cover the escapes that a *provider* could otherwise use to write
outside the authorized workspace:

* a Windows directory junction inside the workspace that points elsewhere;
* a symbolic link inside the workspace that points elsewhere;
* a unified diff whose paths point outside the repository.

Windows junctions are used because they can be created without elevated
privileges; POSIX symbolic links are covered by the same code path (the
containment check resolves the real path on both platforms).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import TempDirTestCase, requires_git, run_git, write_test_project

from sidekick_execution import errors
from sidekick_execution.adapters.coding import CodingActionRequest, CodingAdapter
from sidekick_execution.errors import SidekickError
from sidekick_execution.providers.base import ChangePlan, FileEdit
from sidekick_execution.sandbox import CommandPolicy, CommandRunner
from sidekick_execution.workspace import WorkspacePolicy

IS_WINDOWS = os.name == "nt"


def _make_junction(link: Path, target: Path) -> bool:
    """Create a Windows directory junction. Returns False when impossible."""
    if not IS_WINDOWS:
        return False
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


def _make_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target)
        return True
    except (OSError, NotImplementedError):
        return False


class LinkContainmentTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.tmp_path / "workspace"
        self.root.mkdir()
        self.outside = self.tmp_path / "outside"
        self.outside.mkdir()
        self.victim = self.outside / "victim.txt"
        self.victim.write_text("ORIGINAL", encoding="utf-8")
        self.policy = WorkspacePolicy([str(self.root)])

    def test_a_junction_cannot_redirect_a_write_outside_the_workspace(self) -> None:
        junction = self.root / "linked"
        if not _make_junction(junction, self.outside):
            self.skipTest("a directory junction could not be created on this machine")
        workspace = self.policy.validate(str(self.root))

        with self.assertRaises(SidekickError) as ctx:
            workspace.resolve_child("linked/victim.txt")

        self.assertEqual(ctx.exception.code, errors.EDIT_OUTSIDE_WORKSPACE)
        self.assertIn("link or junction", ctx.exception.message)
        # The file outside must be untouched.
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "ORIGINAL")

    def test_a_symlink_cannot_redirect_a_write_outside_the_workspace(self) -> None:
        link = self.root / "escape.txt"
        if not _make_symlink(link, self.victim):
            self.skipTest("a symbolic link could not be created on this machine")
        workspace = self.policy.validate(str(self.root))

        with self.assertRaises(SidekickError) as ctx:
            workspace.resolve_child("escape.txt")

        self.assertEqual(ctx.exception.code, errors.EDIT_OUTSIDE_WORKSPACE)
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "ORIGINAL")

    def test_an_absolute_path_is_still_refused(self) -> None:
        workspace = self.policy.validate(str(self.root))
        with self.assertRaises(SidekickError) as ctx:
            workspace.resolve_child(str(self.victim))
        self.assertEqual(ctx.exception.code, errors.EDIT_OUTSIDE_WORKSPACE)

    def test_a_path_inside_the_workspace_is_still_accepted(self) -> None:
        workspace = self.policy.validate(str(self.root))
        target = workspace.resolve_child("a/normal/file.txt")
        self.assertTrue(str(target).startswith(str(self.root.resolve())))

    def test_a_new_file_under_a_junction_is_refused(self) -> None:
        junction = self.root / "linked"
        if not _make_junction(junction, self.outside):
            self.skipTest("a directory junction could not be created on this machine")
        workspace = self.policy.validate(str(self.root))
        with self.assertRaises(SidekickError):
            workspace.resolve_child("linked/brand_new.txt")
        self.assertFalse((self.outside / "brand_new.txt").exists())


class ProviderPlanContainmentTests(TempDirTestCase):
    """The executor must refuse a plan that escapes, even if the plan is valid."""

    def setUp(self) -> None:
        super().setUp()
        requires_git(self)
        self.repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], self.repo)
        run_git(["config", "user.email", "t@sidekick.invalid"], self.repo)
        run_git(["config", "user.name", "Sidekick Tests"], self.repo)
        run_git(["add", "-A"], self.repo)
        run_git(["commit", "-m", "initial"], self.repo)
        self.policy = WorkspacePolicy([str(self.tmp_path)])

    def _adapter(self) -> CodingAdapter:
        from sidekick_execution.providers.base import ProviderResult, ProviderStatus
        from sidekick_execution.providers.local_cli import LocalCliCodingProvider

        class FixedProvider(LocalCliCodingProvider):
            def __init__(self, edits):
                super().__init__(cli=sys.executable, args=["--help"])
                self._edits = edits

            def plan(self, request):
                plan = ChangePlan(edits=self._edits)
                return ProviderResult(
                    plan=plan,
                    status=ProviderStatus(True, "REAL", "ok", {"provider": "test"}),
                )

        return CodingAdapter(
            self.policy,
            FixedProvider([FileEdit(path="../escaped.py", content="PWNED")]),
            runner=CommandRunner(CommandPolicy(timeout_seconds=30)),
        )

    def test_a_provider_plan_cannot_write_outside_the_workspace(self) -> None:
        adapter = self._adapter()
        outcome = adapter.execute(
            CodingActionRequest(
                task="escape", workspace=str(self.repo), require_tests=False
            )
        )
        self.assertEqual(outcome.status, "failed")
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error.code, errors.EDIT_OUTSIDE_WORKSPACE)
        self.assertFalse((self.tmp_path / "escaped.py").exists())

    def test_a_patch_cannot_write_outside_the_repository(self) -> None:
        """`git apply` must refuse a patch that touches a path outside the repo."""
        outside = self.tmp_path / "outside.txt"
        outside.write_text("ORIGINAL", encoding="utf-8")
        patch = (
            "diff --git a/../outside.txt b/../outside.txt\n"
            "--- a/../outside.txt\n"
            "+++ b/../outside.txt\n"
            "@@ -1 +1 @@\n"
            "-ORIGINAL\n"
            "+PWNED\n"
        )
        runner = CommandRunner(CommandPolicy(timeout_seconds=30))
        result = runner.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=self.repo,
            timeout=30,
            stdin_data=patch,
        )
        # The patch must not be applied. Either git refuses it, or it refuses
        # for another reason - what matters is that the file is untouched.
        self.assertNotEqual(outside.read_text(encoding="utf-8"), "PWNED")
        self.assertEqual(outside.read_text(encoding="utf-8"), "ORIGINAL")
        if result.exit_code == 0:  # pragma: no cover - would be a defect
            self.fail("git apply accepted a patch that escapes the repository")


if __name__ == "__main__":
    unittest.main()
