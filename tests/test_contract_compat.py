"""Contract compatibility with the other agents.

The expectations below are frozen copies of what the other agents publish:

- Agent 2, ``sidekick_execution/contracts.py`` (``origin/agent2/execution-foundation``)
- Agent 3, ``web/src/lib/api/types.ts`` (``origin/agent3/voice-experience``)

``scripts/check_contract_compat.py`` verifies the same thing against the live
branches; this module is the version that runs in CI, where the other branches
are not available.
"""

from __future__ import annotations

from sidekick.core.schemas import (
    Action,
    ActionError,
    ActionStatus,
    Clarification,
    DecisionModelInfo,
    Event,
    IntentInfo,
    SidekickRequest,
    SidekickResponse,
)

#: The action state vocabulary of contract v1. Agent 2 defines the same list in
#: ``sidekick_execution/contracts.py`` and Agent 3 as the ``ActionState`` union.
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

#: The fields Agent 2's ``Action.from_dict`` reads.
EXECUTION_ACTION_FIELDS = {
    "tool",
    "arguments",
    "action_id",
    "job_id",
    "approval_required",
    "state",
    "superseded_by",
    "result",
    "error",
    "progress",
    "timestamps",
}

#: The fields Agent 2's ``ActionError.from_dict`` reads.
EXECUTION_ERROR_FIELDS = {"code", "message", "retryable", "timeout", "details"}

#: The fields Agent 3's ``SidekickRequest`` sends.
BROWSER_REQUEST_FIELDS = {
    "request_id",
    "session_id",
    "utterance",
    "input_source",
    "utterance_finalized",
    "correction_context",
    "continuation_context",
}

#: The fields Agent 3's ``SidekickResponse`` reads.
BROWSER_RESPONSE_FIELDS = {
    "request_id",
    "session_id",
    "intent",
    "action_plan",
    "risk_level",
    "decision_model",
    "status",
    "clarification",
    "events",
    "speech",
}

#: The fields Agent 3's ``Action`` reads.
BROWSER_ACTION_FIELDS = {
    "action_id",
    "tool",
    "arguments",
    "approval_required",
    "state",
    "superseded_by",
    "result",
    "error",
    "timestamps",
}

#: The fields Agent 3's ``Intent`` reads.
BROWSER_INTENT_FIELDS = {"normalized", "confidence", "ambiguous", "entities"}

#: The fields Agent 3's ``DecisionModel`` reads.
BROWSER_DECISION_MODEL_FIELDS = {"provider", "model", "fallback_used"}

#: The fields Agent 3's ``Clarification`` reads.
BROWSER_CLARIFICATION_FIELDS = {"question", "options"}

#: The fields Agent 3's ``ProgressEvent`` reads.
BROWSER_EVENT_FIELDS = {"seq", "kind", "message", "action_id", "tool", "data", "at", "ts"}


def _field_names(model) -> set[str]:
    """The fields a pydantic model exposes, computed ones included."""
    names = set(model.model_fields)
    computed = getattr(model, "model_computed_fields", None)
    if computed:
        names |= set(computed)
    return names


def test_the_action_state_vocabulary_is_the_contract_v1_one() -> None:
    assert {state.value for state in ActionStatus} == CONTRACT_V1_STATES


def test_the_core_provides_every_field_the_execution_service_reads() -> None:
    assert EXECUTION_ACTION_FIELDS <= _field_names(Action)
    assert EXECUTION_ERROR_FIELDS <= _field_names(ActionError)


def test_the_core_provides_every_field_the_browser_client_reads() -> None:
    assert BROWSER_REQUEST_FIELDS <= _field_names(SidekickRequest)
    assert BROWSER_RESPONSE_FIELDS <= _field_names(SidekickResponse)
    assert BROWSER_ACTION_FIELDS <= _field_names(Action)
    assert BROWSER_INTENT_FIELDS <= _field_names(IntentInfo)
    assert BROWSER_DECISION_MODEL_FIELDS <= _field_names(DecisionModelInfo)
    assert BROWSER_CLARIFICATION_FIELDS <= _field_names(Clarification)
    assert BROWSER_EVENT_FIELDS <= _field_names(Event)


def test_the_core_accepts_the_correction_and_continuation_fields_the_browser_sends() -> None:
    request = SidekickRequest(
        request_id="r",
        session_id="s",
        utterance="echo hello",
        correction_context={"signal": "no wait", "supersedes": "action-1"},
        continuation_context={"previous_request_id": "req-0"},
    )

    assert request.correction_context is not None
    assert request.correction_context.signal == "no wait"
    assert request.correction_context.resolved_action_id() == "action-1"
    assert request.continuation_context is not None
    assert request.continuation_context.previous_request_id == "req-0"


def test_an_action_round_trips_through_the_execution_service_reader() -> None:
    """A faithful copy of Agent 2's ``Action.from_dict`` must parse our JSON."""

    def from_dict(raw: dict) -> dict:
        stamps = raw.get("timestamps") or {}
        error = raw.get("error")
        return {
            "tool": raw.get("tool", ""),
            "arguments": raw.get("arguments") or {},
            "action_id": raw.get("action_id"),
            "job_id": raw.get("job_id"),
            "approval_required": bool(raw.get("approval_required", False)),
            "state": raw.get("state", "pending"),
            "superseded_by": raw.get("superseded_by"),
            "result": raw.get("result"),
            "error": (
                {
                    "code": error.get("code", "internal_error"),
                    "message": error.get("msg", "Unknown error."),
                    "retryable": bool(error.get("retryable", False)),
                    "timeout": bool(error.get("timeout", False)),
                    "details": error.get("details"),
                }
                if isinstance(error, dict)
                else None
            ),
            "progress": raw.get("progress"),
            "timestamps": {
                "created": stamps.get("created"),
                "updated": stamps.get("updated"),
            },
        }

    action = Action(
        tool="coding.execute",
        arguments={"task": "do it"},
        approval_required=True,
        state=ActionStatus.AWAITING_CONFIRMATION,
        job_id="job-1",
        progress=0.5,
        error=ActionError(code="approval_required", message="needs approval"),
    )
    action.job_id = action.action_id

    parsed = from_dict(action.model_dump(mode="json"))

    assert parsed["tool"] == "coding.execute"
    assert parsed["arguments"] == {"task": "do it"}
    assert parsed["state"] == "awaiting_confirmation"
    assert parsed["approval_required"] is True
    assert parsed["job_id"] == action.action_id
    assert parsed["progress"] == 0.5
    assert parsed["error"] is not None
    assert parsed["error"]["code"] == "approval_required"
    assert parsed["timestamps"]["created"]
    assert parsed["timestamps"]["updated"]
