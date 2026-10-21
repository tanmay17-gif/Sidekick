"""Contract level tests: the schemas are the public promise."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sidekick.core.schemas import (
    CONTRACT_VERSION,
    Action,
    ActionStatus,
    Clarification,
    DecisionModelInfo,
    DecisionSource,
    ResponseStatus,
    RiskLevel,
    SidekickRequest,
    SidekickResponse,
)


def test_request_requires_a_stable_identity() -> None:
    with pytest.raises(ValidationError):
        SidekickRequest(utterance="echo hello")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        SidekickRequest(request_id="r", session_id="", utterance="x")  # type: ignore[call-arg]


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SidekickRequest(request_id="r", session_id="s", utterance="x", surprise=1)  # type: ignore[call-arg]


def test_request_rejects_control_characters_in_identifiers() -> None:
    with pytest.raises(ValidationError):
        SidekickRequest(request_id="r\nx", session_id="s", utterance="x")


def test_request_defaults_are_safe() -> None:
    request = SidekickRequest(request_id="r", session_id="s", utterance="  echo hello  ")

    assert request.utterance == "echo hello"
    assert request.utterance_finalized is True
    assert request.input_source.value == "text"


def test_action_defaults() -> None:
    action = Action(tool="test.echo")

    assert action.state is ActionStatus.PENDING
    assert action.approval_required is False
    assert action.superseded_by is None
    assert action.arguments == {}
    assert action.plan_hash == ""


def test_decision_model_info_reports_the_source() -> None:
    info = DecisionModelInfo(
        provider="convaiinnovations",
        model="convaiinnovations/laya",
        source=DecisionSource.MODEL,
        fallback_used=False,
    )

    assert info.fallback_used is False
    assert info.source is DecisionSource.MODEL


def test_response_status_vocabulary() -> None:
    assert ResponseStatus.NEEDS_CLARIFICATION.value == "needs_clarification"
    assert ResponseStatus.AWAITING_TRANSCRIPT.value == "awaiting_transcript"
    assert set(ActionStatus) >= {
        ActionStatus.PENDING,
        ActionStatus.AWAITING_CONFIRMATION,
        ActionStatus.RUNNING,
        ActionStatus.PAUSED,
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.CANCELLED,
        ActionStatus.SUPERSEDED,
    }
    assert set(RiskLevel) == {
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.IRREVERSIBLE,
    }


def test_clarification_shape() -> None:
    clarification = Clarification(question="Which one?", options=["a", "b"])

    assert clarification.options == ["a", "b"]
    assert clarification.missing_arguments == []


def test_response_carries_the_contract_version() -> None:
    response = SidekickResponse(
        request_id="r",
        session_id="s",
        intent={"normalized": "echo hello"},
        decision_model=DecisionModelInfo(
            provider="sidekick",
            model="rule-engine-v1",
            source=DecisionSource.RULE,
            fallback_used=True,
        ),
    )

    assert response.contract_version == CONTRACT_VERSION
    assert response.status is ResponseStatus.PENDING
    assert response.action_plan == []


def test_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SidekickResponse(
            request_id="r",
            session_id="s",
            intent={"normalized": "x"},
            decision_model=DecisionModelInfo(
                provider="sidekick",
                model="rule-engine-v1",
                source=DecisionSource.RULE,
                fallback_used=True,
            ),
            surprise=True,  # type: ignore[call-arg]
        )
