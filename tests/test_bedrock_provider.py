"""Tests for Bedrock coding provider and provider selection without LLM API keys."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock

from sidekick_execution import errors
from sidekick_execution.providers.base import ClaimLevel, CodingRequest
from sidekick_execution.providers.bedrock import BedrockCodingProvider
from sidekick_execution.service import select_provider


class BedrockCodingProviderTests(unittest.TestCase):
    def test_missing_aws_credentials_reports_not_configured(self) -> None:
        provider = BedrockCodingProvider()
        status = provider.status()
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "not_configured")
        self.assertEqual(status.level, ClaimLevel.UNAVAILABLE)
        self.assertIn("AWS credentials", status.detail.get("hint", ""))

    def test_configured_client_reports_real_provider(self) -> None:
        mock_client = MagicMock()
        provider = BedrockCodingProvider(boto3_client=mock_client)
        status = provider.status()
        self.assertTrue(status.available)
        self.assertEqual(status.level, ClaimLevel.REAL)
        self.assertEqual(status.detail.get("provider"), "bedrock")

    def test_planning_without_credentials_returns_structured_error(self) -> None:
        provider = BedrockCodingProvider()
        result = provider.plan(CodingRequest(task="fix bug", workspace="C:\\workspace"))
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, errors.PROVIDER_NOT_CONFIGURED)

    def test_successful_plan_with_mock_client(self) -> None:
        mock_client = MagicMock()
        mock_body = io.BytesIO(
            json.dumps({
                "content": [
                    {
                        "text": json.dumps({
                            "summary": "added fix",
                            "edits": [{"path": "fix.py", "content": "print('fixed')"}],
                        })
                    }
                ]
            }).encode("utf-8")
        )
        mock_client.invoke_model.return_value = {"body": mock_body}

        provider = BedrockCodingProvider(boto3_client=mock_client)
        result = provider.plan(CodingRequest(task="fix bug", workspace="C:\\workspace"))
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.summary, "added fix")
        self.assertEqual(len(result.plan.edits), 1)
        self.assertEqual(result.plan.edits[0].path, "fix.py")
        self.assertEqual(result.plan.edits[0].content, "print('fixed')")

    def test_select_provider_bedrock_explicit(self) -> None:
        provider = select_provider("bedrock")
        self.assertIsInstance(provider, BedrockCodingProvider)
        self.assertEqual(provider.name, "bedrock")

    def test_access_denied_reports_blocked_status(self) -> None:
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = Exception("AccessDeniedException: Account verification is pending.")
        mock_client.converse = None

        provider = BedrockCodingProvider(boto3_client=mock_client)
        result = provider.plan(CodingRequest(task="fix bug", workspace="C:\\workspace"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_AUTH_FAILED)
        self.assertEqual(result.status.reason, "blocked_by_aws")
        self.assertIn("BLOCKED", result.status.detail.get("hint", ""))


if __name__ == "__main__":
    unittest.main()
