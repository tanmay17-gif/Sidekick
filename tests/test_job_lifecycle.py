"""Tests for the job lifecycle: approval, progress events, cancellation,
failure and restart recovery.

The lifecycle rules under test come from `.sidekick/API_CONTRACTS.md` v1 and
`.sidekick/ARCHITECTURE.md`:

* an approval-gated action never runs before it is confirmed;
* a confirmation binds to the exact pending action and expires;
* events are ordered and exactly one terminal event ends a job;
* cancellation is reported honestly;
* a job that was in flight when the process died is recovered as failed.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path

from tests.support import TempDirTestCase

from sidekick_execution.adapters.registry import (
    STATUS_NOT_CONFIGURED,
    ToolRegistry,
    ToolSpec,
)
from sidekick_execution.approval import ApprovalStore, compute_plan_hash
from sidekick_execution.contracts import (
    AWAITING_CONFIRMATION,
    CANCELLED,
    FAILED,
    RUNNING,
    SUCCEEDED,
)
from sidekick_execution.errors import SidekickError
from sidekick_execution.events import (
    JOB_CREATED,
    JOB_ERROR,
    JOB_RESULT,
    JOB_STATUS,
    EventBus,
)
from sidekick_execution.jobs import JobManager, JobRecord, JobStore


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def echo(arguments, ctx):
        return {"echo": arguments.get("value")}

    def slow(arguments, ctx):
        while not ctx.cancel_event.wait(0.05):
            pass
        return {"stopped": True}

    def boom(arguments, ctx):
        raise SidekickError("command_failed", "the tool failed on purpose", retryable=True)

    def unexpected(arguments, ctx):
        raise RuntimeError("unexpected explosion")

    registry.register(
        ToolSpec(name="echo", description="echo", handler=echo, status="REAL")
    )
    registry.register(
        ToolSpec(name="slow", description="slow", handler=slow, status="REAL")
    )
    registry.register(
        ToolSpec(name="boom", description="boom", handler=boom, status="REAL")
    )
    registry.register(
        ToolSpec(name="unexpected", description="unexpected", handler=unexpected, status="REAL")
    )
    registry.register(
        ToolSpec(
            name="needs_approval",
            description="needs approval",
            handler=echo,
            status="REAL",
            approval_required=True,
            risk_level="high",
        )
    )
    registry.register(
        ToolSpec(
            name="unconfigured",
            description="not configured",
            handler=echo,
            status=STATUS_NOT_CONFIGURED,
            status_detail="Missing provider credential.",
        )
    )
    return registry


class JobLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = make_registry()
        self.bus = EventBus()
        self.manager = JobManager(self.registry, ApprovalStore(), self.bus)
        self.addCleanup(self.manager.shutdown)

    def test_successful_job_reports_success_and_a_terminal_result_event(self) -> None:
        payload = self.manager.submit("echo", {"value": "hello"})
        action_id = payload["action"]["action_id"]
        action = self.manager.wait(action_id, timeout=10)

        self.assertEqual(action.state, SUCCEEDED)
        self.assertEqual(action.result, {"echo": "hello"})

        events = self.bus.history(action_id)
        self.assertEqual(events[0].type, JOB_CREATED)
        self.assertEqual(events[-1].type, JOB_RESULT)
        self.assertEqual([e.seq for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1].data["status"], SUCCEEDED)

    def test_failed_tool_reports_a_structured_error(self) -> None:
        payload = self.manager.submit("boom", {})
        action = self.manager.wait(payload["action"]["action_id"], timeout=10)

        self.assertEqual(action.state, FAILED)
        self.assertIsNotNone(action.error)
        self.assertEqual(action.error.code, "command_failed")
        self.assertTrue(action.error.retryable)

        events = self.bus.history(payload["action"]["action_id"])
        self.assertEqual(events[-1].type, JOB_ERROR)
        self.assertEqual(events[-1].data["error"]["code"], "command_failed")

    def test_unexpected_exception_becomes_an_internal_error(self) -> None:
        payload = self.manager.submit("unexpected", {})
        action = self.manager.wait(payload["action"]["action_id"], timeout=10)

        self.assertEqual(action.state, FAILED)
        self.assertEqual(action.error.code, "internal_error")

    def test_unknown_tool_is_rejected(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.manager.submit("does-not-exist", {})
        self.assertEqual(ctx.exception.code, "not_implemented")

    def test_unconfigured_tool_is_rejected_with_a_reason(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.manager.submit("unconfigured", {})
        self.assertEqual(ctx.exception.code, "provider_not_configured")
        self.assertIn("credential", ctx.exception.message)

    def test_approval_gated_action_waits_for_confirmation(self) -> None:
        payload = self.manager.submit("needs_approval", {"value": 1})
        action = payload["action"]
        confirmation = payload["confirmation"]

        self.assertEqual(action["state"], AWAITING_CONFIRMATION)
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation["action_id"], action["action_id"])

        # It must not run until it is approved.
        time.sleep(0.2)
        self.assertEqual(self.manager.get(action["action_id"]).state, AWAITING_CONFIRMATION)

        approved = self.manager.approve(action["action_id"], confirmation["confirmation_token"])
        self.assertEqual(approved.state, SUCCEEDED)

    def test_approval_is_required_to_run(self) -> None:
        payload = self.manager.submit("needs_approval", {"value": 1})
        action_id = payload["action"]["action_id"]
        with self.assertRaises(SidekickError) as ctx:
            self.manager.approve(action_id, "not-the-right-token")
        self.assertEqual(ctx.exception.code, "approval_invalid")

    def test_cancellation_of_a_running_job_is_reported(self) -> None:
        payload = self.manager.submit("slow", {})
        action_id = payload["action"]["action_id"]
        time.sleep(0.2)
        action = self.manager.cancel(action_id)

        self.assertEqual(action.state, CANCELLED)
        events = self.bus.history(action_id)
        self.assertEqual(events[-1].type, JOB_RESULT)
        self.assertTrue(action.result.get("cancelled"))

    def test_cancelling_a_finished_job_is_refused(self) -> None:
        payload = self.manager.submit("echo", {"value": "x"})
        action_id = payload["action"]["action_id"]
        self.manager.wait(action_id, timeout=10)
        with self.assertRaises(SidekickError) as ctx:
            self.manager.cancel(action_id)
        self.assertEqual(ctx.exception.code, "job_not_cancellable")

    def test_status_events_are_emitted_for_each_transition(self) -> None:
        payload = self.manager.submit("echo", {"value": "x"})
        action_id = payload["action"]["action_id"]
        self.manager.wait(action_id, timeout=10)
        statuses = [
            e.data["status"] for e in self.bus.history(action_id) if e.type == JOB_STATUS
        ]
        self.assertEqual(statuses, ["pending", "running", "succeeded"])

    def test_unknown_job_lookup_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            self.manager.get("no-such-job")
        self.assertEqual(ctx.exception.code, "job_not_found")


class ApprovalBindingTests(unittest.TestCase):
    def test_approval_is_bound_to_the_exact_plan(self) -> None:
        store = ApprovalStore(ttl_seconds=60)
        grant = store.issue("action-1", {"task": "a"})
        store.validate("action-1", {"task": "a"}, grant.token)
        with self.assertRaises(SidekickError) as ctx:
            store.validate("action-1", {"task": "b"}, grant.token)
        self.assertEqual(ctx.exception.code, "approval_invalid")

    def test_expired_approval_is_refused(self) -> None:
        store = ApprovalStore(ttl_seconds=0)
        grant = store.issue("action-1", {"task": "a"})
        with self.assertRaises(SidekickError) as ctx:
            store.validate("action-1", {"task": "a"}, grant.token)
        self.assertEqual(ctx.exception.code, "approval_expired")

    def test_missing_approval_token_is_refused(self) -> None:
        store = ApprovalStore()
        store.issue("action-1", {"task": "a"})
        with self.assertRaises(SidekickError) as ctx:
            store.validate("action-1", {"task": "a"}, None)
        self.assertEqual(ctx.exception.code, "approval_required")

    def test_plan_hash_changes_when_the_plan_changes(self) -> None:
        first = compute_plan_hash({"task": "a", "files": ["x"]})
        second = compute_plan_hash({"task": "a", "files": ["y"]})
        self.assertNotEqual(first, second)

    def test_public_dict_does_not_leak_the_token(self) -> None:
        store = ApprovalStore()
        grant = store.issue("action-1", {"task": "a"})
        self.assertNotIn("token", grant.to_public_dict())


class RestartRecoveryTests(TempDirTestCase):
    def test_interrupted_jobs_are_recovered_as_failed(self) -> None:
        store_path = self.tmp_path / "jobs.json"
        store = JobStore(store_path)
        store.save(
            [
                JobRecord(
                    job_id="job-running",
                    action={
                        "action_id": "job-running",
                        "tool": "echo",
                        "arguments": {},
                        "approval_required": False,
                        "state": RUNNING,
                        "superseded_by": None,
                        "result": None,
                        "error": None,
                        "timestamps": {"created": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z"},
                    },
                ),
                JobRecord(
                    job_id="job-done",
                    action={
                        "action_id": "job-done",
                        "tool": "echo",
                        "arguments": {},
                        "approval_required": False,
                        "state": SUCCEEDED,
                        "superseded_by": None,
                        "result": {"ok": True},
                        "error": None,
                        "timestamps": {"created": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z"},
                    },
                ),
            ]
        )

        manager = JobManager(make_registry(), ApprovalStore(), EventBus(), store=JobStore(store_path))
        self.addCleanup(manager.shutdown)

        interrupted = manager.get("job-running")
        self.assertEqual(interrupted.state, FAILED)
        self.assertIsNotNone(interrupted.error)
        self.assertEqual(interrupted.error.code, "job_interrupted")

        finished = manager.get("job-done")
        self.assertEqual(finished.state, SUCCEEDED)
        self.assertEqual(finished.result, {"ok": True})


if __name__ == "__main__":
    unittest.main()
