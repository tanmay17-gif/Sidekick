"""Contract conformance tests.

`.sidekick/API_CONTRACTS.md` v1 is owned by Agent 1. These tests check that
the execution service emits exactly that shape, so the core (Agent 1) and the
UI (Agent 3) can rely on it.

If Agent 1 changes the contract, these tests are the signal that the
execution side needs to follow.
"""

from __future__ import annotations

import json
import unittest

from sidekick_execution.adapters.registry import ToolRegistry, ToolSpec
from sidekick_execution.approval import ApprovalStore
from sidekick_execution.contracts import (
    ACTION_STATES,
    ALLOWED_TRANSITIONS,
    AWAITING_CONFIRMATION,
    CANCELLED,
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    Action,
    ActionError,
    Timestamps,
)
from sidekick_execution.errors import SidekickError, error_payload
from sidekick_execution.events import (
    EVENT_TYPES,
    JOB_CREATED,
    JOB_RESULT,
    Event,
    EventBus,
)
from sidekick_execution.jobs import JobManager

#: The action states named in `.sidekick/API_CONTRACTS.md` v1.
CONTRACT_V1_STATES = {
    "pending",
    "awaiting_confirmation",
    "running",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
    "superseded",
}


class ActionContractTests(unittest.TestCase):
    def test_state_vocabulary_matches_contract_v1(self) -> None:
        self.assertEqual(set(ACTION_STATES), CONTRACT_V1_STATES)

    def test_action_serializes_every_contract_v1_field(self) -> None:
        action = Action(tool="coding.execute", arguments={"task": "x"})
        payload = action.to_dict()

        for field in (
            "action_id",
            "tool",
            "arguments",
            "approval_required",
            "state",
            "superseded_by",
            "result",
            "error",
            "timestamps",
        ):
            self.assertIn(field, payload, f"missing contract field: {field}")

        self.assertIsInstance(payload["action_id"], str)
        self.assertIsInstance(payload["tool"], str)
        self.assertIsInstance(payload["arguments"], dict)
        self.assertIsInstance(payload["approval_required"], bool)
        self.assertIsInstance(payload["state"], str)
        self.assertIn(payload["state"], CONTRACT_V1_STATES)
        self.assertIsNone(payload["superseded_by"])
        self.assertIsNone(payload["error"])
        self.assertIn("created", payload["timestamps"])
        self.assertIn("updated", payload["timestamps"])

    def test_action_round_trips(self) -> None:
        action = Action(tool="echo", arguments={"a": 1}, approval_required=True)
        action.error = ActionError(code="x", message="y", retryable=True)
        restored = Action.from_dict(action.to_dict())
        self.assertEqual(restored.to_dict(), action.to_dict())

    def test_legal_transitions_never_skip_the_running_state(self) -> None:
        self.assertEqual(set(ALLOWED_TRANSITIONS), CONTRACT_V1_STATES)
        self.assertIn(RUNNING, ALLOWED_TRANSITIONS[PENDING])
        self.assertIn(AWAITING_CONFIRMATION, ALLOWED_TRANSITIONS[PENDING])
        self.assertEqual(ALLOWED_TRANSITIONS[SUCCEEDED], [])
        self.assertEqual(ALLOWED_TRANSITIONS[FAILED], [])
        self.assertEqual(ALLOWED_TRANSITIONS[CANCELLED], [])


class ErrorContractTests(unittest.TestCase):
    def test_error_payload_matches_contract_v1(self) -> None:
        payload = error_payload("some_code", "a message")
        self.assertIn("error", payload)
        error = payload["error"]
        self.assertEqual(error["code"], "some_code")
        self.assertEqual(error["message"], "a message")
        self.assertFalse(error["retryable"])
        self.assertFalse(error["timeout"])

    def test_timeout_flag_is_preserved(self) -> None:
        payload = error_payload("command_timeout", "timed out", timeout=True, retryable=True)
        self.assertTrue(payload["error"]["timeout"])
        self.assertTrue(payload["error"]["retryable"])

    def test_sidekick_error_serializes_to_the_contract_shape(self) -> None:
        exc = SidekickError("command_failed", "boom", retryable=True)
        payload = exc.to_dict()
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["code"], "command_failed")


class EventContractTests(unittest.TestCase):
    def test_event_shape(self) -> None:
        event = Event(job_id="job-1", type=JOB_CREATED, status=PENDING, message="hi")
        payload = event.to_dict()
        for field in ("event_id", "job_id", "seq", "ts", "type", "status", "message", "data"):
            self.assertIn(field, payload)
        self.assertIn(payload["type"], EVENT_TYPES)
        self.assertTrue(payload["ts"].endswith("Z"))

    def test_sequence_numbers_are_monotonic_per_job(self) -> None:
        bus = EventBus()
        for i in range(5):
            bus.publish(Event(job_id="job-1", type="job.progress", message=str(i)))
        bus.publish(Event(job_id="job-2", type="job.progress", message="other"))

        seqs = [e.seq for e in bus.history("job-1")]
        self.assertEqual(seqs, [1, 2, 3, 4, 5])
        self.assertEqual(bus.history("job-2")[0].seq, 1)

    def test_exactly_one_terminal_event_ends_a_job(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(name="echo", description="e", handler=lambda a, c: {"ok": True})
        )
        bus = EventBus()
        manager = JobManager(registry, ApprovalStore(), bus)
        self.addCleanup(manager.shutdown)

        payload = manager.submit("echo", {})
        manager.wait(payload["action"]["action_id"], timeout=10)
        events = bus.history(payload["action"]["action_id"])

        terminal = [e for e in events if e.type in (JOB_RESULT, "job.error")]
        self.assertEqual(len(terminal), 1)
        self.assertIs(terminal[0], events[-1])

    def test_subscribers_receive_events_in_order(self) -> None:
        bus = EventBus()
        queue = bus.subscribe("job-1")
        for i in range(3):
            bus.publish(Event(job_id="job-1", type="job.progress", message=str(i)))
        received = []
        while not queue.empty():
            received.append(queue.get_nowait())
        self.assertEqual([e.seq for e in received], [1, 2, 3])

    def test_events_are_json_serializable(self) -> None:
        bus = EventBus()
        bus.publish(Event(job_id="job-1", type="job.progress", data={"n": 1}))
        payload = bus.history("job-1")[0].to_dict()
        json.dumps(payload)  # must not raise


if __name__ == "__main__":
    unittest.main()
