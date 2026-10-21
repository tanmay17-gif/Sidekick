"""Tests for the outcome contract of a coding job.

The point of these tests is that a caller - the core, the browser, a demo -
cannot mistake one situation for another:

* *proposed* changes from *applied* changes;
* a successful edit from a partial one;
* a passing test from a failing one;
* a cancellation from a timeout from a provider failure;
* a clean diff from *no changes* from *no diff available*;
* a finished job from an interrupted one.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, TempDirTestCase, requires_git, run_git, write_test_project

from sidekick_execution.adapters.coding import (
    DIFF_CHANGES,
    DIFF_NO_CHANGES,
    DIFF_UNAVAILABLE,
    CodingActionRequest,
    CodingAdapter,
)
from sidekick_execution.errors import SidekickError
from sidekick_execution.providers.base import (
    ChangePlan,
    FileEdit,
    ProviderResult,
    ProviderStatus,
)
from sidekick_execution.providers.local_cli import LocalCliCodingProvider
from sidekick_execution.sandbox import CommandPolicy, CommandRunner
from sidekick_execution.workspace import WorkspacePolicy

FIXTURE_CLI = REPO_ROOT / "tests" / "fixtures" / "fixture_coding_cli.py"
TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]


class FixedPlanProvider(LocalCliCodingProvider):
    """A provider that returns exactly the edits it is given."""

    def __init__(self, edits, *, level: str = "REAL") -> None:
        super().__init__(cli=sys.executable, args=["--help"])
        # The provider identifies itself; the outcome must carry that identity.
        self.name = "fixed"
        self._edits = edits
        self._level = level

    def plan(self, request):
        return ProviderResult(
            plan=ChangePlan(edits=self._edits, summary="a fixed plan"),
            status=ProviderStatus(True, self._level, "ok", {"provider": "fixed"}),
        )


class OutcomeContractTests(TempDirTestCase):
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

    def _run(self, edits, workspace=None, **kwargs):
        adapter = CodingAdapter(
            self.policy,
            FixedPlanProvider(edits),
            runner=CommandRunner(CommandPolicy(timeout_seconds=60)),
        )
        request = CodingActionRequest(
            task="do the thing",
            workspace=str(workspace or self.repo),
            test_command=TEST_COMMAND,
            **kwargs,
        )
        return adapter.execute(request)

    # -- proposed vs applied ----------------------------------------------
    def test_proposed_changes_are_reported_separately_from_applied_ones(self) -> None:
        outcome = self._run(
            [FileEdit(path="new_file.py", content="VALUE = 1\n")],
            require_tests=False,
        )
        self.assertEqual(outcome.outcome, "succeeded")
        # What the provider proposed.
        self.assertEqual(len(outcome.proposed_edits), 1)
        self.assertEqual(outcome.proposed_edits[0]["path"], "new_file.py")
        # What was really written.
        self.assertEqual(outcome.applied_files, ["new_file.py"])
        self.assertTrue((self.repo / "new_file.py").is_file())
        # And what Git says differs.
        self.assertIn("new_file.py", [c["path"] for c in outcome.changed_files])

    def test_a_plan_that_cannot_be_applied_reports_the_proposal_but_no_application(self) -> None:
        outcome = self._run(
            [FileEdit(path="../escape.py", content="PWNED")],
            require_tests=False,
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error.code, "edit_outside_workspace")
        # The proposal is visible ...
        self.assertEqual(len(outcome.proposed_edits), 1)
        # ... but nothing was written.
        self.assertEqual(outcome.applied_files, [])
        self.assertFalse((self.tmp_path / "escape.py").exists())

    def test_a_partially_applied_plan_says_so(self) -> None:
        outcome = self._run(
            [
                FileEdit(path="first.py", content="A = 1\n"),
                FileEdit(path="../escape.py", content="PWNED"),
            ],
            require_tests=False,
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error.code, "edit_outside_workspace")
        # The first edit really landed, the second did not.
        self.assertEqual(outcome.applied_files, ["first.py"])
        self.assertTrue((self.repo / "first.py").is_file())
        self.assertFalse((self.tmp_path / "escape.py").exists())

    # -- diff state --------------------------------------------------------
    def test_a_real_change_is_reported_as_changes(self) -> None:
        outcome = self._run(
            [FileEdit(path="changed.py", content="X = 1\n")], require_tests=False
        )
        self.assertEqual(outcome.diff_state, DIFF_CHANGES)
        self.assertTrue(outcome.diff)

    def test_writing_identical_content_is_reported_as_no_changes(self) -> None:
        # Line endings are part of the bytes, so the comparison is only
        # meaningful in a repository that does not rewrite them.
        run_git(["config", "core.autocrlf", "false"], self.repo)
        stable = "STABLE = True\n"
        (self.repo / "stable.py").write_text(stable, encoding="utf-8", newline="\n")
        run_git(["add", "-A"], self.repo)
        run_git(["commit", "-m", "add stable"], self.repo)

        outcome = self._run(
            [FileEdit(path="stable.py", content=stable)], require_tests=False
        )
        # The task ran and the tests passed, but the workspace is identical
        # to HEAD. That is not the same as "there is a diff".
        self.assertEqual(outcome.diff_state, DIFF_NO_CHANGES)
        self.assertEqual(outcome.outcome, "succeeded")
        self.assertEqual(outcome.changed_files, [])

    def test_a_workspace_that_is_not_a_repository_reports_no_diff_available(self) -> None:
        plain = self.tmp_path / "plain"
        plain.mkdir()
        outcome = self._run(
            [FileEdit(path="file.py", content="X = 1\n")],
            workspace=plain,
            require_tests=False,
        )
        self.assertEqual(outcome.diff_state, DIFF_UNAVAILABLE)
        self.assertEqual(outcome.diff, "")
        self.assertIsNone(outcome.head_sha)
        # The file was still really written.
        self.assertTrue((plain / "file.py").is_file())

    # -- test result -------------------------------------------------------
    def test_the_real_test_command_and_exit_code_are_reported(self) -> None:
        outcome = self._run(
            [FileEdit(path="new_file.py", content="VALUE = 1\n")], require_tests=False
        )
        self.assertIsNone(outcome.test_result, "no test may be reported when none ran")

        outcome = self._run([FileEdit(path="new_file2.py", content="VALUE = 2\n")])
        self.assertIsNotNone(outcome.test_result)
        self.assertEqual(outcome.test_result.argv, TEST_COMMAND)
        self.assertEqual(outcome.test_result.exit_code, 0)
        self.assertTrue(outcome.test_result.passed)

    def test_a_failing_test_is_never_a_success(self) -> None:
        outcome = self._run(
            [FileEdit(path="tests/test_sample.py", content="import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(False)\n")]
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.outcome, "partial")
        self.assertEqual(outcome.error.code, "test_failed")
        self.assertFalse(outcome.test_result.passed)
        self.assertNotEqual(outcome.test_result.exit_code, 0)
        # The real diff is still attached, so the failure is visible.
        self.assertEqual(outcome.diff_state, DIFF_CHANGES)
        self.assertIn("tests/test_sample.py", outcome.diff)

    # -- provider identity -------------------------------------------------
    def test_the_provider_identity_is_reported(self) -> None:
        outcome = self._run(
            [FileEdit(path="new_file.py", content="VALUE = 1\n")], require_tests=False
        )
        self.assertEqual(outcome.provider["name"], "fixed")
        self.assertEqual(outcome.provider["level"], "REAL")
        self.assertFalse(outcome.provider["simulated"])

    def test_a_simulated_provider_is_labelled_as_such_in_the_outcome(self) -> None:
        outcome = self._run(
            [FileEdit(path="new_file.py", content="VALUE = 1\n")],
            require_tests=False,
        )
        # The same mechanism, but with the simulated level: the outcome must
        # say so, so nobody can present it as a real model.
        adapter = CodingAdapter(
            self.policy,
            FixedPlanProvider(
                [FileEdit(path="sim.py", content="X = 1\n")], level="SIMULATED"
            ),
            runner=CommandRunner(CommandPolicy(timeout_seconds=60)),
        )
        simulated = adapter.execute(
            CodingActionRequest(
                task="t",
                workspace=str(self.repo),
                require_tests=False,
            )
        )
        self.assertEqual(simulated.provider["level"], "SIMULATED")
        self.assertTrue(simulated.provider["simulated"])


if __name__ == "__main__":
    unittest.main()
