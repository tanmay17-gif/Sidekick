"""Integration tests for the core <-> execution service adapter.

These tests drive the **real** core against a **real** execution service
process (an HTTP server started by the test). Nothing is mocked between the
two halves: the core submits a real HTTP request, the execution service runs
real commands, and the result travels back over the real API.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, TempDirTestCase, requires_git, run_git, write_test_project

from sidekick.core.catalog import ArgumentSpec, ToolSpec
from sidekick.core.registry import ToolContext, ToolResult
from sidekick.core.schemas import Action, ActionStatus, RiskLevel
from sidekick.tools.execution import ExecutionServiceAdapter, ExecutionServiceError

from sidekick_execution.http_service import serve_in_thread
from sidekick_execution.providers.local_cli import LocalCliCodingProvider
from sidekick_execution.service import ExecutionService
from sidekick_execution.workspace import WorkspacePolicy

FIXTURE_CLI = REPO_ROOT / "tests" / "fixtures" / "fixture_coding_cli.py"


def build_execution_service(roots, *, break_tests: bool = False) -> ExecutionService:
    """A real execution service with the deterministic fixture provider.

    The fixture provider is a *test double for the model*. Everything else -
    the HTTP surface, the workspace checks, the sandbox, the diff and the
    test run - is real.
    """
    args = [str(FIXTURE_CLI), "--task", "{task}", "--workspace", "{workspace}"]
    if break_tests:
        args.append("--break-tests")
    provider = LocalCliCodingProvider(cli=sys.executable, args=args)
    return ExecutionService.create(
        provider=provider,
        workspace_policy=WorkspacePolicy([str(r) for r in roots]),
    )


class ExecutionAdapterTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = build_execution_service([self.tmp_path])
        self.httpd, _ = serve_in_thread(self.service, "127.0.0.1", 0)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.service.job_manager.shutdown)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.adapter = ExecutionServiceAdapter(base_url=self.base_url)

    # -- capability reporting ---------------------------------------------
    def test_capability_status_reports_the_real_provider(self) -> None:
        status = self.adapter.capability_status()
        self.assertEqual(status["status"], "REAL")
        self.assertIn("detail", status)

    def test_capability_status_is_not_configured_without_a_url(self) -> None:
        adapter = ExecutionServiceAdapter(base_url="")
        status = adapter.capability_status()
        self.assertEqual(status["status"], "NOT_CONFIGURED")
        self.assertIn("SIDEKICK_EXECUTION_URL", status["detail"])

    def test_capability_status_is_unavailable_when_the_service_is_down(self) -> None:
        adapter = ExecutionServiceAdapter(base_url="http://127.0.0.1:9")
        status = adapter.capability_status()
        self.assertEqual(status["status"], "UNAVAILABLE")
        self.assertIn("not reachable", status["detail"])

    # -- execution ---------------------------------------------------------
    def test_unconfigured_adapter_fails_honestly(self) -> None:
        adapter = ExecutionServiceAdapter(base_url="")
        action = Action(tool="coding.execute", arguments={"task": "x", "workspace": "y"})
        result = adapter.execute(action, {"task": "x", "workspace": "y"}, ToolContext("s", "a"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "execution_service_not_configured")
        self.assertFalse(result.error.retryable)

    def test_unreachable_service_produces_a_retryable_error(self) -> None:
        adapter = ExecutionServiceAdapter(base_url="http://127.0.0.1:9")
        action = Action(tool="coding.execute", arguments={"task": "x", "workspace": "y"})
        result = adapter.execute(action, {"task": "x", "workspace": "y"}, ToolContext("s", "a"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "execution_service_unavailable")
        self.assertTrue(result.error.retryable)

    def test_missing_arguments_are_refused_before_any_request(self) -> None:
        action = Action(tool="coding.execute", arguments={})
        result = self.adapter.execute(action, {}, ToolContext("s", "a"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "invalid_task")

    def test_execute_reports_progress_and_completes_with_the_real_result(self) -> None:
        requires_git(self)
        repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], repo)
        run_git(["config", "user.email", "t@sidekick.invalid"], repo)
        run_git(["config", "user.name", "Sidekick Tests"], repo)
        run_git(["add", "-A"], repo)
        run_git(["commit", "-m", "initial"], repo)

        progress: list[tuple[str, dict]] = []
        completed: list[ToolResult] = []

        class RecordingContext(ToolContext):
            def progress(self, message, data=None):  # type: ignore[override]
                progress.append((message, dict(data or {})))

            def complete(self, result):  # type: ignore[override]
                completed.append(result)

        action = Action(
            tool="coding.execute",
            arguments={"task": "Add a greeting helper", "workspace": str(repo)},
        )
        context = RecordingContext(session_id="s1", action_id=action.action_id)
        outcome = self.adapter.execute(
            action,
            {"task": "Add a greeting helper", "workspace": str(repo)},
            context,
        )

        # The action is ongoing: the work continues in the execution service.
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.ongoing)
        self.assertEqual(action.job_id, outcome.data["job_id"])

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not completed:
            time.sleep(0.05)

        self.assertTrue(completed, "the adapter never reported the final outcome")
        final = completed[0]
        self.assertTrue(final.ok, final.error)
        self.assertEqual(final.data["outcome"], "succeeded")
        self.assertTrue((repo / "feature_added_by_fixture.py").is_file())
        self.assertIn("feature_added_by_fixture.py", final.data["diff"])
        self.assertTrue(final.data["test_result"]["passed"])
        self.assertEqual(final.data["test_result"]["exit_code"], 0)

        # Progress really travelled from the execution service into the core.
        self.assertTrue(progress, "no progress events were forwarded")
        self.assertTrue(any("progress" in str(data.get("execution_event_type", "")) for _, data in progress))

    def test_a_failing_test_command_is_not_reported_as_success(self) -> None:
        requires_git(self)
        repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], repo)
        run_git(["config", "user.email", "t@sidekick.invalid"], repo)
        run_git(["config", "user.name", "Sidekick Tests"], repo)
        run_git(["add", "-A"], repo)
        run_git(["commit", "-m", "initial"], repo)

        # A service whose provider really breaks the project's test suite.
        service = build_execution_service([self.tmp_path], break_tests=True)
        httpd, _ = serve_in_thread(service, "127.0.0.1", 0)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(service.job_manager.shutdown)
        adapter = ExecutionServiceAdapter(base_url=f"http://127.0.0.1:{httpd.server_address[1]}")

        completed: list[ToolResult] = []

        class RecordingContext(ToolContext):
            def complete(self, result):  # type: ignore[override]
                completed.append(result)

        action = Action(
            tool="coding.execute",
            arguments={"task": "break it", "workspace": str(repo)},
        )
        adapter.execute(
            action,
            {"task": "break it", "workspace": str(repo)},
            RecordingContext(session_id="s1", action_id=action.action_id),
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not completed:
            time.sleep(0.05)

        self.assertTrue(completed)
        final = completed[0]
        self.assertFalse(final.ok)
        self.assertIsNotNone(final.error)
        self.assertEqual(final.error.code, "test_failed")
        self.assertEqual(final.data["outcome"], "partial")
        # The failure still carries the real diff and the real test result.
        self.assertIn("feature_added_by_fixture.py", final.data["diff"])
        self.assertFalse(final.data["test_result"]["passed"])
        self.assertNotEqual(final.data["test_result"]["exit_code"], 0)

    def test_cancellation_reaches_the_real_job(self) -> None:
        requires_git(self)
        repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], repo)
        run_git(["config", "user.email", "t@sidekick.invalid"], repo)
        run_git(["config", "user.name", "Sidekick Tests"], repo)
        run_git(["add", "-A"], repo)
        run_git(["commit", "-m", "initial"], repo)

        # A test command that runs long enough to be cancelled.
        slow = [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ]
        action = Action(
            tool="coding.execute",
            arguments={"task": "slow", "workspace": str(repo)},
        )
        outcome = self.adapter.execute(
            action,
            {"task": "slow", "workspace": str(repo), "test_command": slow},
            ToolContext("s1", action.action_id),
        )
        self.assertTrue(outcome.ok)
        time.sleep(0.5)
        self.assertTrue(self.adapter.cancel(action.action_id))

        job_id = outcome.data["job_id"]
        deadline = time.monotonic() + 30
        state = None
        while time.monotonic() < deadline:
            state = self.service.job_manager.get(job_id).state
            if state in ("cancelled", "failed", "succeeded"):
                break
            time.sleep(0.05)
        self.assertIn(state, ("cancelled", "failed"))

    def test_cancel_of_an_unknown_action_returns_false(self) -> None:
        self.assertFalse(self.adapter.cancel("not-a-known-action"))


if __name__ == "__main__":
    unittest.main()
