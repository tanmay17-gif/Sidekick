"""Tests for Amazon Bedrock decision model."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

import pytest

from sidekick.core.catalog import CapabilityCatalog, ToolSpec
from sidekick.core.decision import (
    DecisionQuery,
    ModelInvalidOutput,
    ModelTimeout,
    ModelUnavailable,
)
from sidekick.core.decisions.bedrock_model import BedrockDecisionModel
from sidekick.core.schemas import DecisionSource, RiskLevel
from sidekick.core.sessions import SessionState


@pytest.fixture
def sample_catalog() -> CapabilityCatalog:
    cat = CapabilityCatalog()
    cat.add(
        ToolSpec(
            name="note.write",
            description="Write a note to a text file",
            aliases=("write a note", "take note", "save note"),
            risk=RiskLevel.LOW,
            arguments=(),
        )
    )
    cat.add(
        ToolSpec(
            name="media.open",
            description="Open a media service",
            aliases=("open youtube", "open spotify"),
            risk=RiskLevel.LOW,
            arguments=(),
        )
    )
    return cat


def test_bedrock_reports_availability_truthfully() -> None:
    # With no credentials provided, available should be False (or True only if environment has AWS credentials)
    model = BedrockDecisionModel(region_name="us-east-1")
    # Must not raise an exception
    assert isinstance(model.available, bool)
    info = model.describe()
    assert info.provider == "aws-bedrock"
    assert "claude" in info.model.lower()


def test_bedrock_decide_with_mocked_client(sample_catalog: CapabilityCatalog) -> None:
    mock_client = MagicMock()
    response_payload = {
        "content": [
            {
                "text": json.dumps({
                    "tool": "note.write",
                    "confidence": 0.95,
                    "destination": None,
                    "is_correction": False,
                })
            }
        ]
    }
    mock_client.invoke_model.return_value = {
        "body": io.BytesIO(json.dumps(response_payload).encode("utf-8"))
    }

    model = BedrockDecisionModel(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        boto3_client=mock_client,
    )
    assert model.available is True

    query = DecisionQuery(
        utterance="write a note to buy milk",
        catalog=sample_catalog,
        session=SessionState(session_id="test-session"),
    )

    decision = model.decide(query)
    assert decision.tool == "note.write"
    assert decision.confidence == 0.95
    assert decision.source == DecisionSource.MODEL
    assert decision.is_correction is False
    assert decision.details["provider"] == "aws-bedrock"


def test_bedrock_handles_invalid_json_output(sample_catalog: CapabilityCatalog) -> None:
    mock_client = MagicMock()
    response_payload = {
        "content": [{"text": "I am unable to parse this instruction."}]
    }
    mock_client.invoke_model.return_value = {
        "body": io.BytesIO(json.dumps(response_payload).encode("utf-8"))
    }

    model = BedrockDecisionModel(boto3_client=mock_client)
    query = DecisionQuery(
        utterance="do something random",
        catalog=sample_catalog,
        session=SessionState(session_id="test-session"),
    )

    with pytest.raises(ModelInvalidOutput):
        model.decide(query)


def test_bedrock_handles_api_exception(sample_catalog: CapabilityCatalog) -> None:
    mock_client = MagicMock()
    mock_client.invoke_model.side_effect = RuntimeError("ThrottlingException: rate limit exceeded")

    model = BedrockDecisionModel(boto3_client=mock_client)
    query = DecisionQuery(
        utterance="play some music",
        catalog=sample_catalog,
        session=SessionState(session_id="test-session"),
    )

    with pytest.raises(ModelUnavailable) as exc_info:
        model.decide(query)
    assert "rate limit exceeded" in str(exc_info.value)


def test_bootstrap_build_decision_model_bedrock() -> None:
    from sidekick.bootstrap import build_decision_model

    primary, fallback, reason = build_decision_model(prefer_model="bedrock")
    # If AWS credentials not configured, it gracefully returns fallback with reason
    if primary.provider == "aws-bedrock":
        assert primary.available is True
    else:
        assert primary.provider == "sidekick"
        assert "Bedrock" in reason or "configured" in reason
