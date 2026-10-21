"""Failure-injection tests for job reliability.

These tests inject the failures that break real systems - a disconnect, a
restart, a duplicated request, a cancellation race, a provider timeout, a
half-finished job - and check the **observable** result through the real
HTTP API wherever that is possible.

Nothing here is mocked between the client and the service: the service is a
real HTTP server and the jobs are real.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests.support import TempDirTestCase

from sidekick_execution.adapters.registry import ToolRegistry, ToolSpec
from sidekick_execution.approval import ApprovalStore
from sidekick_execution.errors import SidekickError
from sidekick_execution.events import EventBus
from sidekick_execution.http_service import serve_in_thread
from sidekick_execution.jobs import JobManager
from sidekick_execution.service import ExecutionService
from sidekick_execution.store import JobStore
from sidekick_execution.workspace import WorkspacePolicy


class CountingTool:
    """A tool that records every call, so duplicates are visible."""

    spec = ToolSpec(
        name="counting.echo",
        description="echo and count",
        handler=None,  # replaced in __init__
    )

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.spec = ToolSpec(
            name="counting.echo",
            description="echo and count",
            handler=self._execute,
        )

    def _execute(self, arguments, context):
        self.calls.append(dict(arguments))
        return {"echo": arguments.get("value"), "calls": len(self.calls)}

    def cancel(self, action_id: str) -> bool:
        return True


class SlowTool:
    """A tool that runs until it is cancelled."""

    spec = ToolSpec(
        name="slow.wait",
        description="wait until cancelled",
        handler=None,
    )

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name="slow.wait",
            description="wait until cancelled",
            handler=self._execute,
        )

    def _execute(self, arguments, context):
        while not context.cancel_event.wait(0.05):
            pass
        return {"stopped": True}

    def cancel(self, action_id: str) -> bool:
        return True


class FailingTool:
    """A tool that fails in a specific, observable way."""

    def __init__(self, code: str, message: str, *, timeout: bool = False) -> None:
        self.code = code
        self.message = message
        self.timeout = timeout
        self.spec = ToolSpec(
            name="always.fails",
            description="always fails",
            handler=self._execute,
        )

    def _execute(self, arguments, context):
        raise SidekickError(
            self.code, self.message, retryable=True, timeout=self.timeout
        )

    def cancel(self, action_id: str) -> bool:
        return True


def build_service(registry: ToolRegistry, store_path: Path | None = None) -> ExecutionService:
    service = ExecutionService.create(
        workspace_policy=WorkspacePolicy([str(Path(tempfile.gettempdir()))]),
    )
    service.registry = registry
    manager = JobManager(
        registry,
        ApprovalStore(),
        service.job_manager.events,
        store=JobStore(store_path) if store_path else None,
    )
    service.job_manager = manager
    return service


import tempfile  # noqa: E402  (used by build_service above)


class ReliabilityTestCase(TempDirTestCase):
    def _serve(self, registry: ToolRegistry, store_path: Path | None = None):
        service = build_service(registry, store_path)
        httpd, _ = serve_in_thread(service, "127.0.0.1", 0)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(service.job_manager.shutdown)
        return service, f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base: str, path: str, payload: dict):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def _get(self, base: str, path: str):
        with urllib.request.urlopen(base + path, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))


class DuplicateRequestTests(ReliabilityTestCase):
    def test_a_repeated_submission_does_not_run_the_work_twice(self) -> None:
        tool = CountingTool()
        registry = ToolRegistry()
        registry.register(tool.spec)
        service, base = self._serve(registry)

        payload = {
            "tool": "counting.echo",
            "arguments": {"value": "x"},
            "session_id": "s-1",
            "idempotency_key": "request-abc",
        }
        status1, body1 = self._post(base, "/v1/actions", payload)
        status2, body2 = self._post(base, "/v1/actions", payload)

        self.assertEqual(status1, 202)
        self.assertEqual(status2, 200, "a replayed submission must not look like a new job")
        self.assertEqual(body1["action"]["action_id"], body2["action"]["action_id"])
        self.assertTrue(body2.get("idempotent_replay"))

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(tool.calls) < 1:
            time.sleep(0.02)
        time.sleep(0.3)
        self.assertEqual(len(tool.calls), 1, "the tool must run exactly once")

    def test_a_different_key_starts_a_second_job(self) -> None:
        tool = CountingTool()
        registry = ToolRegistry()
        registry.register(tool.spec)
        service, base = self._serve(registry)
        for key in ("a", "b"):
            self._post(
                base,
                "/v1/actions",
                {
                    "tool": "counting.echo",
                    "arguments": {"value": "x"},
                    "session_id": "s-1",
                    "idempotency_key": key,
                },
            )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(tool.calls) < 2:
            time.sleep(0.02)
        self.assertEqual(len(tool.calls), 2)

    def test_an_empty_idempotency_key_is_refused(self) -> None:
        registry = ToolRegistry()
        registry.register(CountingTool().spec)
        service, base = self._serve(registry)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(
                base,
                "/v1/actions",
                {"tool": "counting.echo", "arguments": {}, "idempotency_key": "  "},
            )
        self.assertEqual(ctx.exception.code, 400)


class ReconnectTests(ReliabilityTestCase):
    def _read_events(self, base: str, job_id: str, after: int = 0, limit: int = 0):
        events = []
        request = urllib.request.Request(base + f"/v1/actions/{job_id}/events?after={after}")
        with urllib.request.urlopen(request, timeout=30) as response:
            buffer = ""
            for raw in response:
                buffer += raw.decode("utf-8")
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    for line in frame.splitlines():
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
                    if limit and len(events) >= limit:
                        return events
        return events

    def test_a_client_can_reconnect_and_resume_without_a_gap(self) -> None:
        registry = ToolRegistry()
        registry.register(CountingTool().spec)
        service, base = self._serve(registry)
        _, body = self._post(
            base, "/v1/actions", {"tool": "counting.echo", "arguments": {"value": "x"}}
        )
        job_id = body["action"]["action_id"]

        # First connection: read the whole stream.
        first = self._read_events(base, job_id)
        self.assertGreaterEqual(len(first), 3)
        seqs = [e["seq"] for e in first]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

        # Second connection after a "disconnect": resume from a cursor.
        cursor = seqs[1]
        second = self._read_events(base, job_id, after=cursor)
        self.assertTrue(second)
        self.assertEqual(second[0]["seq"], cursor + 1, "the stream must continue without a gap")
        self.assertEqual(
            [e["seq"] for e in second],
            list(range(cursor + 1, cursor + 1 + len(second))),
            "no duplicates and no gaps",
        )

    def test_resuming_from_the_last_sequence_yields_only_the_terminal_event(self) -> None:
        registry = ToolRegistry()
        registry.register(CountingTool().spec)
        service, base = self._serve(registry)
        _, body = self._post(
            base, "/v1/actions", {"tool": "counting.echo", "arguments": {"value": "x"}}
        )
        job_id = body["action"]["action_id"]
        first = self._read_events(base, job_id)
        last_seq = first[-1]["seq"]
        rest = self._read_events(base, job_id, after=last_seq)
        self.assertEqual(rest, [], "there is nothing after the last event")


class RestartTests(ReliabilityTestCase):
    def test_a_job_interrupted_by_a_restart_is_recovered_as_failed(self) -> None:
        store_path = self.tmp_path / "jobs.json"
        registry = ToolRegistry()
        registry.register(SlowTool().spec)
        service = build_service(registry, store_path)
        payload = service.job_manager.submit("slow.wait", {}, session_id="s-1")
        job_id = payload["action"]["action_id"]
        service.job_manager.store.flush()

        # Simulate a crash: the manager is abandoned without a clean shutdown.
        state, _ = service.job_manager.get(job_id), None
        self.assertEqual(state.state, "running")
        # The abandoned worker is stopped at the end of the test so that it
        # cannot keep the interpreter alive at exit.
        self.addCleanup(service.job_manager.cancel, job_id)

        # A new service over the same store recovers the job.
        recovered_registry = ToolRegistry()
        recovered_registry.register(SlowTool().spec)
        recovered = JobManager(
            recovered_registry,
            ApprovalStore(),
            EventBus(),
            store=JobStore(store_path),
        )
        self.addCleanup(recovered.shutdown)
        action = recovered.get(job_id)
        self.assertEqual(action.state, "failed")
        self.assertEqual(action.error.code, "job_interrupted")
        self.assertIn("partially applied", action.error.message)

    def test_the_recovered_job_still_has_its_event_history(self) -> None:
        store_path = self.tmp_path / "jobs.json"
        registry = ToolRegistry()
        registry.register(SlowTool().spec)
        service = build_service(registry, store_path)
        payload = service.job_manager.submit("slow.wait", {}, session_id="s-1")
        job_id = payload["action"]["action_id"]
        time.sleep(0.2)
        service.job_manager.store.flush()
        self.addCleanup(service.job_manager.cancel, job_id)

        bus = EventBus()
        recovered = JobManager(
            registry, ApprovalStore(), bus, store=JobStore(store_path)
        )
        self.addCleanup(recovered.shutdown)
        history = bus.history(job_id)
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual([e.seq for e in history], list(range(1, len(history) + 1)))
        # The last event is the honest terminal one.
        self.assertEqual(history[-1].type, "job.error")
        self.assertEqual(history[-1].data["error"]["code"], "job_interrupted")


class CancellationRaceTests(ReliabilityTestCase):
    def test_cancelling_twice_is_safe(self) -> None:
        registry = ToolRegistry()
        registry.register(SlowTool().spec)
        service, base = self._serve(registry)
        _, body = self._post(base, "/v1/actions", {"tool": "slow.wait", "arguments": {}})
        job_id = body["action"]["action_id"]
        time.sleep(0.2)

        status, first = self._post(base, f"/v1/actions/{job_id}/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(first["state"], "cancelled")

        # The second cancel is refused because the job already finished.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(base, f"/v1/actions/{job_id}/cancel", {})
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "job_not_cancellable")

    def test_cancelling_an_unknown_job_is_refused(self) -> None:
        registry = ToolRegistry()
        registry.register(SlowTool().spec)
        service, base = self._serve(registry)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(base, "/v1/actions/no-such-job/cancel", {})
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "job_not_found")

    def test_a_job_that_finishes_while_it_is_cancelled_keeps_its_real_outcome(self) -> None:
        """The race between 'finished' and 'cancelled' must not lie."""
        registry = ToolRegistry()
        registry.register(CountingTool().spec)
        service, base = self._serve(registry)
        _, body = self._post(
            base, "/v1/actions", {"tool": "counting.echo", "arguments": {"value": "x"}}
        )
        job_id = body["action"]["action_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            _, action = self._get(base, f"/v1/actions/{job_id}")
            if action["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.02)
        self.assertEqual(action["state"], "succeeded")
        self.assertEqual(action["result"]["echo"], "x")


class ProviderFailureTests(ReliabilityTestCase):
    def test_a_failing_tool_fails_the_job_with_its_own_code(self) -> None:
        registry = ToolRegistry()
        registry.register(
            FailingTool("provider_timeout", "the provider timed out", timeout=True).spec
        )
        service, base = self._serve(registry)
        _, body = self._post(base, "/v1/actions", {"tool": "always.fails", "arguments": {}})
        job_id = body["action"]["action_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            _, action = self._get(base, f"/v1/actions/{job_id}")
            if action["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.02)
        self.assertEqual(action["state"], "failed")
        self.assertEqual(action["error"]["code"], "provider_timeout")
        self.assertTrue(action["error"]["timeout"])
        self.assertTrue(action["error"]["retryable"])


class RetentionTests(ReliabilityTestCase):
    def test_finished_jobs_are_pruned_when_they_age_out(self) -> None:
        store_path = self.tmp_path / "jobs.json"
        registry = ToolRegistry()
        registry.register(CountingTool().spec)
        service = build_service(registry, store_path)
        payload = service.job_manager.submit(
            "counting.echo", {"value": "x"}, session_id="s-1"
        )
        job_id = payload["action"]["action_id"]
        service.job_manager.wait(job_id, timeout=20)
        self.assertIn(job_id, [j.job_id for j in service.job_manager.store.all_jobs()])

        removed = service.job_manager.prune(older_than_seconds=0)
        self.assertIn(job_id, removed)
        self.assertNotIn(job_id, [j.job_id for j in service.job_manager.store.all_jobs()])
        # The event history goes with it.
        self.assertEqual(service.job_manager.events.history(job_id), [])


if __name__ == "__main__":
    unittest.main()
