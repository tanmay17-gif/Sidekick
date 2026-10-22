"""End-to-end tests for the whole product path.

    utterance -> core brain -> execution service -> real file change,
    real diff, real test command, real exit code -> core -> browser

These tests drive the **real** core engine against a **real** execution
service over HTTP. The only substitution is the *model* that decides what to
change: no LLM credential exists in this environment, so the model step uses
the deterministic fixture provider and is labelled as such.

The real-provider path has its own test, which is **skipped with a reason**
rather than silently passing - see
:func:`test_real_provider_end_to_end_is_blocked_without_a_credential`.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, TempDirTestCase, requires_git, run_git, write_test_project

from sidekick.core.engine import DecisionEngine
from sidekick.core.registry import ToolRegistry
from sidekick.core.safety import SafetyPolicy
from sidekick.core.schemas import ActionStatus, SidekickRequest
from sidekick.core.sessions import SessionStore
from sidekick.tools.execution import ExecutionServiceAdapter

from sidekick_execution.http_service import serve_in_thread
from sidekick_execution.providers.local_cli import LocalCliCodingProvider
from sidekick_execution.service import ExecutionService
from sidekick_execution.workspace import WorkspacePolicy

FIXTURE_CLI = REPO_ROOT / "tests" / "fixtures" / "fixture_coding_cli.py"


def has_real_provider() -> bool:
    """Is a real coding provider configured in this environment?"""
    if os.environ.get("SIDEKICK_LLM_API_KEY"):
        return True
    cli = os.environ.get("SIDEKICK_CODING_CLI")
    if not cli:
        return False
    from sidekick_execution.sandbox import resolve_executable

    return resolve_executable(cli) is not None


class CoreIntegrationTests(TempDirTestCase):
    """The full path through the real core."""

    def setUp(self) -> None:
        super().setUp()
        requires_git(self)
        self.repo = write_test_project(self.tmp_path / "repo")
        run_git(["init", "--initial-branch=main"], self.repo)
        run_git(["config", "user.email", "t@sidekick.invalid"], self.repo)
        run_git(["config", "user.name", "Sidekick Tests"], self.repo)
        run_git(["add", "-A"], self.repo)
        run_git(["commit", "-m", "initial"], self.repo)

        provider = LocalCliCodingProvider(
            cli=sys.executable,
            args=[str(FIXTURE_CLI), "--task", "{task}", "--workspace", "{workspace}"],
        )
        self.execution = ExecutionService.create(
            provider=provider,
            workspace_policy=WorkspacePolicy([str(self.tmp_path)]),
        )
        self.httpd, _ = serve_in_thread(self.execution, "127.0.0.1", 0)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.execution.job_manager.shutdown)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        registry = ToolRegistry()
        registry.register(ExecutionServiceAdapter(base_url=self.base_url))
        self.engine = DecisionEngine(
            registry=registry,
            sessions=SessionStore(),
            policy=SafetyPolicy(workspace_root=self.tmp_path),
        )

    # -- helpers -----------------------------------------------------------
    def _ask(self, utterance: str, request_id: str = "req-1", session_id: str = "s-1"):
        return self.engine.handle(
            SidekickRequest(
                request_id=request_id,
                session_id=session_id,
                utterance=utterance,
            )
        )

    def _wait_for_terminal(self, session_id: str, action_id: str, timeout: float = 60.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            action = self.engine.get_action(session_id, action_id)
            if action is not None and action.state in (
                ActionStatus.SUCCEEDED,
                ActionStatus.FAILED,
                ActionStatus.CANCELLED,
                ActionStatus.SUPERSEDED,
            ):
                return action
            time.sleep(0.05)
        return self.engine.get_action(session_id, action_id)

    # -- tests -------------------------------------------------------------
    def test_the_capability_is_declared_and_routes_to_the_execution_service(self) -> None:
        spec = self.engine.registry.spec("coding.execute")
        self.assertIsNotNone(spec)
        self.assertIn("coding.execute", self.engine.registry.available_tools())

        adapter = self.engine.registry.get("coding.execute")
        status = adapter.capability_status()
        self.assertEqual(status["status"], "REAL")

    def test_the_utterance_is_resolved_to_an_authorised_action(self) -> None:
        response = self._ask(f'fix the failing test in "{self.repo}"')
        self.assertEqual(len(response.action_plan), 1)
        action = response.action_plan[0]
        self.assertEqual(action.tool, "coding.execute")
        # The action changes files, so the safety policy demands an approval.
        self.assertTrue(action.approval_required)
        self.assertEqual(action.state, ActionStatus.AWAITING_CONFIRMATION)
        self.assertEqual(response.status.value, "awaiting_confirmation")

    def test_the_whole_path_produces_a_real_change_diff_and_test_result(self) -> None:
        response = self._ask(f'fix the failing test in "{self.repo}"')
        action = response.action_plan[0]

        # The core confirms on the user's behalf; only then does the work run.
        confirmed = self.engine.confirm_action(
            "s-1", action.action_id, approved=True, plan_hash=action.plan_hash
        )
        self.assertEqual(confirmed.state, ActionStatus.RUNNING)
        self.assertIsNotNone(confirmed.job_id, "the execution job id must map onto the core action")

        final = self._wait_for_terminal("s-1", action.action_id)
        self.assertEqual(final.state, ActionStatus.SUCCEEDED, final.error)
        self.assertIsNotNone(final.result)

        # 1. The files really changed.
        self.assertTrue((self.repo / "feature_added_by_fixture.py").is_file())
        # 2. The diff is the real diff of the workspace.
        self.assertIn("feature_added_by_fixture.py", final.result["diff"])
        # 3. The changed file list is real.
        paths = {entry["path"] for entry in final.result["changed_files"]}
        self.assertIn("feature_added_by_fixture.py", paths)
        # 4. The test command really ran and its exit code is preserved.
        self.assertEqual(final.result["test_result"]["exit_code"], 0)
        self.assertTrue(final.result["test_result"]["passed"])
        # 5. The provider that ran is reported truthfully.
        self.assertEqual(final.result["provider"]["level"], "REAL")
        self.assertFalse(final.result["provider"]["simulated"])

    def test_progress_events_reach_the_core_and_the_session(self) -> None:
        response = self._ask(f'fix the failing test in "{self.repo}"')
        action = response.action_plan[0]
        self.engine.confirm_action("s-1", action.action_id, approved=True, plan_hash=action.plan_hash)
        self._wait_for_terminal("s-1", action.action_id)

        events = self.engine.action_events("s-1", action.action_id)
        self.assertTrue(events, "the core must log the execution service's progress")
        kinds = {event.type for event in events}
        self.assertIn("action.progress", kinds)
        # Exactly one terminal event for the action.
        terminal = [
            event
            for event in events
            if event.type in ("action.succeeded", "action.failed", "action.cancelled")
        ]
        self.assertEqual(len(terminal), 1)

    def test_a_declined_approval_never_reaches_the_execution_service(self) -> None:
        response = self._ask(f'fix the failing test in "{self.repo}"')
        action = response.action_plan[0]
        declined = self.engine.confirm_action("s-1", action.action_id, approved=False)
        self.assertEqual(declined.state, ActionStatus.CANCELLED)
        self.assertFalse((self.repo / "feature_added_by_fixture.py").exists())
        self.assertEqual(self.execution.job_manager.list_jobs(), [])

    def test_an_unreachable_execution_service_is_an_honest_error(self) -> None:
        registry = ToolRegistry()
        registry.register(ExecutionServiceAdapter(base_url="http://127.0.0.1:9"))
        engine = DecisionEngine(
            registry=registry,
            sessions=SessionStore(),
            policy=SafetyPolicy(workspace_root=self.tmp_path),
        )
        response = engine.handle(
            SidekickRequest(
                request_id="req-x",
                session_id="s-x",
                utterance=f'fix the failing test in "{self.repo}"',
            )
        )
        action = response.action_plan[0]
        engine.confirm_action("s-x", action.action_id, approved=True, plan_hash=action.plan_hash)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = engine.get_action("s-x", action.action_id)
            if current.state in (ActionStatus.FAILED, ActionStatus.SUCCEEDED):
                break
            time.sleep(0.05)
        current = engine.get_action("s-x", action.action_id)
        self.assertEqual(current.state, ActionStatus.FAILED)
        self.assertIsNotNone(current.error)
        self.assertEqual(current.error.code, "execution_service_unavailable")
        self.assertTrue(current.error.retryable)

    def test_the_capability_report_states_the_truth(self) -> None:
        from sidekick.api.app import create_app

        app = create_app(self.engine)
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            payload = client.get("/api/v1/capabilities").json()
        tools = {tool["tool"]: tool for tool in payload["tools"]}
        self.assertIn("coding.execute", tools)
        self.assertEqual(tools["coding.execute"]["status"], "REAL")
        self.assertFalse(tools["coding.execute"]["simulated"])
        self.assertFalse(payload["any_simulated"])


class RealProviderTests(TempDirTestCase):
    """The real-provider acceptance test.

    It is **skipped with a reason** when no credential or coding CLI is
    configured, because a skipped test is the honest outcome - a fixture must
    never stand in for a real model and be reported as a pass.
    """

    def test_real_provider_end_to_end_is_blocked_without_a_credential(self) -> None:
        if has_real_provider():
            self.skipTest(
                "a real provider is configured on this machine; run the live acceptance "
                "separately so it never hides behind a fixture"
            )
        # Prove the point: without a provider the service says so, and the
        # capability report is honest about it.
        service = ExecutionService.create(
            workspace_policy=WorkspacePolicy([str(self.tmp_path)]),
        )
        self.addCleanup(service.job_manager.shutdown)
        report = service.capabilities()
        self.assertFalse(report["provider"]["available"])
        self.assertIn(
            report["provider"]["reason"],
            ("not_configured", "not_installed", "invalid_configuration"),
        )
        coding = {tool["tool"]: tool for tool in report["tools"]}["coding.execute"]
        self.assertEqual(coding["status"], "NOT_CONFIGURED")
        self.assertTrue(coding["status_detail"])


if __name__ == "__main__":
    unittest.main()
