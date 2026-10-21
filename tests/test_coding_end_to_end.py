"""End-to-end tests for the real coding workflow.

These tests exercise the whole pipeline against a *real* Git repository:

* a real coding provider process produces a change plan;
* the executor performs real file writes;
* the diff is captured from the real Git working tree;
* the project's own test command really runs and its exit code is preserved.

The provider used here is the real :class:`LocalCliCodingProvider` mechanism
driving a deterministic fixture CLI. The provider mechanism is real; the
fixture is a test double for the LLM that a deployment would use.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, TempDirTestCase, requires_git, run_git, write_test_project

from sidekick_execution.adapters.coding import CodingActionRequest, CodingAdapter
from sidekick_execution.providers.local_cli import LocalCliCodingProvider
from sidekick_execution.sandbox import CommandPolicy, CommandRunner
from sidekick_execution.workspace import WorkspacePolicy

FIXTURE_CLI = REPO_ROOT / "tests" / "fixtures" / "fixture_coding_cli.py"


def build_fixture_provider(break_tests: bool = False) -> LocalCliCodingProvider:
    """A real local-CLI provider wired to the deterministic fixture."""
    args = [
        str(FIXTURE_CLI),
        "--task",
        "{task}",
        "--workspace",
        "{workspace}",
    ]
    if break_tests:
        args.append("--break-tests")
    return LocalCliCodingProvider(cli=sys.executable, args=args)


class CodingEndToEndTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        requires_git(self)
        self.repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], self.repo)
        run_git(["config", "user.email", "tests@sidekick.invalid"], self.repo)
        run_git(["config", "user.name", "Sidekick Tests"], self.repo)
        run_git(["add", "-A"], self.repo)
        run_git(["commit", "-m", "initial"], self.repo)
        self.policy = WorkspacePolicy([str(self.tmp_path)])
        self.command_policy = CommandPolicy(timeout_seconds=120.0)

    def _adapter(self, provider) -> CodingAdapter:
        return CodingAdapter(
            self.policy,
            provider,
            runner=CommandRunner(self.command_policy),
        )

    def test_task_creates_real_file_change_and_real_diff(self) -> None:
        adapter = self._adapter(build_fixture_provider())
        request = CodingActionRequest(
            task="Add a greeting helper",
            workspace=str(self.repo),
            test_command=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        )

        outcome = adapter.execute(request)

        self.assertEqual(outcome.status, "succeeded", outcome.summary)
        self.assertEqual(outcome.outcome, "succeeded")
        self.assertIsNone(outcome.error)

        # 1. A real file change exists on disk.
        created = self.repo / "feature_added_by_fixture.py"
        self.assertTrue(created.is_file(), "the provider's edit was not written to disk")
        self.assertIn("def greet", created.read_text(encoding="utf-8"))

        # 2. The diff is real and contains the change.
        self.assertIn("feature_added_by_fixture.py", outcome.diff)
        self.assertIn("def greet", outcome.diff)

        # 3. The changed-file list matches the real Git status.
        real_status = run_git(["status", "--porcelain=v1"], self.repo).stdout
        real_paths = {
            line[3:].strip() for line in real_status.splitlines() if len(line) > 3
        }
        reported = {change["path"] for change in outcome.changed_files}
        self.assertEqual(reported, real_paths, "reported changes differ from the real Git status")

        # 4. The real test command ran and its exit code was preserved.
        self.assertIsNotNone(outcome.test_result)
        self.assertTrue(outcome.test_result.passed)
        self.assertEqual(outcome.test_result.exit_code, 0)
        # Counts are only reported when the runner actually printed them.
        # `unittest` prints "OK"/"FAILED", not "N passed", so counts stay
        # unavailable here rather than being fabricated.
        if outcome.test_result.counts_available:
            self.assertGreaterEqual(outcome.test_result.counts.get("passed", 0), 1)

        # 5. The provider was a real one, not the simulated substitute.
        self.assertEqual(outcome.provider["level"], "REAL")
        self.assertFalse(outcome.provider["simulated"])

    def test_failed_tests_do_not_report_success(self) -> None:
        adapter = self._adapter(build_fixture_provider(break_tests=True))
        request = CodingActionRequest(
            task="Add a greeting helper",
            workspace=str(self.repo),
            test_command=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        )

        outcome = adapter.execute(request)

        # The change was applied, but the required tests failed.
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.outcome, "partial")
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error.code, "test_failed")
        self.assertFalse(outcome.test_result.passed)
        self.assertNotEqual(outcome.test_result.exit_code, 0)
        self.assertTrue((self.repo / "feature_added_by_fixture.py").is_file())

    def test_required_tests_can_be_skipped_but_are_reported_as_not_run(self) -> None:
        adapter = self._adapter(build_fixture_provider())
        request = CodingActionRequest(
            task="Add a greeting helper",
            workspace=str(self.repo),
            require_tests=False,
        )

        outcome = adapter.execute(request)

        self.assertEqual(outcome.status, "succeeded")
        self.assertIsNone(outcome.test_result, "no test result must be reported when tests were not run")

    def test_diff_reports_the_new_head_sha(self) -> None:
        adapter = self._adapter(build_fixture_provider())
        request = CodingActionRequest(
            task="Add a greeting helper",
            workspace=str(self.repo),
            require_tests=False,
        )

        outcome = adapter.execute(request)
        head = run_git(["rev-parse", "HEAD"], self.repo).stdout.strip()
        self.assertEqual(outcome.head_sha, head)

    def test_patch_based_changes_are_applied_with_git(self) -> None:
        """A unified-diff plan is applied with a real `git apply`."""
        patch = (
            "diff --git a/patched_by_patch.py b/patched_by_patch.py\n"
            "new file mode 100644\n"
            "index 0000000..1234567\n"
            "--- /dev/null\n"
            "+++ b/patched_by_patch.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+PATCH_APPLIED = True\n"
            "+VALUE = 42\n"
        )
        provider = LocalCliCodingProvider(cli=sys.executable, args=[str(FIXTURE_CLI)])
        original_plan = provider.plan

        def fake_plan(request):
            result = original_plan(request)
            if result.plan is not None:
                result.plan.edits = [
                    type(result.plan.edits[0])(
                        path="patched_by_patch.py", patch=patch
                    )
                ]
            return result

        provider.plan = fake_plan  # type: ignore[method-assign]
        adapter = self._adapter(provider)
        request = CodingActionRequest(
            task="Apply a patch",
            workspace=str(self.repo),
            require_tests=False,
        )

        outcome = adapter.execute(request)

        self.assertEqual(outcome.status, "succeeded", outcome.summary)
        target = self.repo / "patched_by_patch.py"
        self.assertTrue(target.is_file())
        self.assertIn("PATCH_APPLIED = True", target.read_text(encoding="utf-8"))
        self.assertIn("patched_by_patch.py", outcome.diff)

    def test_provider_failure_is_reported_as_failure_not_success(self) -> None:
        """A provider that errors must not yield a successful action."""
        provider = LocalCliCodingProvider(cli=sys.executable, args=[str(FIXTURE_CLI)])

        def failing_plan(request):
            from sidekick_execution import errors
            from sidekick_execution.errors import SidekickError
            from sidekick_execution.providers.base import ProviderResult, ProviderStatus

            return ProviderResult(
                plan=None,
                status=ProviderStatus(False, "REAL", "boom"),
                error=SidekickError(errors.PROVIDER_ERROR, "the provider exploded"),
            )

        provider.plan = failing_plan  # type: ignore[method-assign]
        adapter = self._adapter(provider)
        request = CodingActionRequest(
            task="Anything", workspace=str(self.repo), require_tests=False
        )

        outcome = adapter.execute(request)

        self.assertEqual(outcome.status, "failed")
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error.code, "provider_error")


if __name__ == "__main__":
    unittest.main()
