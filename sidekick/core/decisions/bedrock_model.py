"""Amazon Bedrock decision model.

This model routes natural-language requests using Amazon Bedrock foundation
models (e.g. Anthropic Claude 3 Sonnet or Amazon Titan).

When AWS credentials and region are configured (via environment variables
``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``, ``AWS_REGION``, or IAM
instance profile), requests are routed via Bedrock's converse API.

If AWS credentials are missing or the service is unreachable, the model
truthfully reports itself as unavailable, allowing the engine to fall back
deterministically to the catalog-driven ``RuleDecisionModel`` with transparent
provenance.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..decision import (
    Decision,
    DecisionQuery,
    ModelInvalidOutput,
    ModelTimeout,
    ModelUnavailable,
)
from ..schemas import DecisionSource
from .base import BaseDecisionModel

DEFAULT_BEDROCK_MODEL = "anthropic.claude-3-sonnet-20240229-v1:0"
DEFAULT_AWS_REGION = "us-east-1"


class BedrockDecisionModel(BaseDecisionModel):
    """Decision model backed by Amazon Bedrock."""

    provider = "aws-bedrock"

    def __init__(
        self,
        *,
        model_id: str | None = None,
        region_name: str | None = None,
        timeout_seconds: float = 15.0,
        boto3_client: Any | None = None,
    ) -> None:
        super().__init__()
        self.model = (
            model_id
            or os.environ.get("BEDROCK_MODEL_ID")
            or DEFAULT_BEDROCK_MODEL
        )
        self.region = (
            region_name
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or DEFAULT_AWS_REGION
        )
        self.timeout = timeout_seconds
        self._client = boto3_client
        self._client_init_error: str | None = None

    @property
    def available(self) -> bool:
        """True when boto3 is installed and credentials/client can be initialized."""
        try:
            import boto3  # noqa: F401
            client = self._get_client()
            return client is not None
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            return False

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
            # Check for minimal credentials or IAM config
            session = boto3.Session(region_name=self.region)
            creds = session.get_credentials()
            if creds is None and not os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
                # No credentials found
                self._client_init_error = "AWS credentials not configured"
                return None
            self._client = session.client("bedrock-runtime", region_name=self.region)
            return self._client
        except Exception as exc:  # noqa: BLE001
            self._client_init_error = str(exc)
            return None

    def _decide(self, query: DecisionQuery) -> Decision:
        client = self._get_client()
        if client is None:
            raise ModelUnavailable(
                self._client_init_error or "Amazon Bedrock client unavailable"
            )

        tools_desc = []
        for spec in query.catalog.tools.values():
            tools_desc.append({
                "name": spec.name,
                "description": spec.description,
                "aliases": spec.aliases[:5],
            })

        system_prompt = (
            "You are Sidekick's Intent Router. Match the user utterance to exactly one tool "
            "from the catalog or indicate if it is a control command.\n"
            "Return a JSON object only, with fields: 'tool' (string or null), "
            "'confidence' (float 0.0 to 1.0), 'destination' (string or null), "
            "'is_correction' (bool).\n\n"
            f"Available capabilities: {json.dumps(tools_desc)}"
        )

        user_content = f"User utterance: {query.utterance}"

        started = time.time()
        try:
            if "claude" in self.model.lower():
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 200,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}],
                    "temperature": 0.0,
                })
                response = client.invoke_model(
                    modelId=self.model,
                    body=body,
                )
                response_body = json.loads(response["body"].read())
                output_text = response_body["content"][0]["text"].strip()
            else:
                # Generic model invocation format
                body = json.dumps({
                    "inputText": f"{system_prompt}\n\n{user_content}",
                    "textGenerationConfig": {"maxTokenCount": 200, "temperature": 0.0},
                })
                response = client.invoke_model(
                    modelId=self.model,
                    body=body,
                )
                response_body = json.loads(response["body"].read())
                output_text = response_body.get("results", [{}])[0].get("outputText", "").strip()

            elapsed = time.time() - started
            if elapsed > self.timeout:
                raise ModelTimeout(f"Bedrock invocation timed out after {elapsed:.1f}s")

            # Extract JSON block
            if "{" in output_text and "}" in output_text:
                start = output_text.find("{")
                end = output_text.rfind("}") + 1
                parsed = json.loads(output_text[start:end])
            else:
                parsed = json.loads(output_text)

            tool = parsed.get("tool")
            confidence = float(parsed.get("confidence", 0.0))
            destination = parsed.get("destination")
            is_correction = bool(parsed.get("is_correction", False))

            return Decision(
                tool=tool,
                confidence=confidence,
                destination=destination,
                is_correction=is_correction,
                source=DecisionSource.MODEL,
                details={
                    "model": self.model,
                    "provider": self.provider,
                    "region": self.region,
                },
            )

        except ModelTimeout:
            raise
        except json.JSONDecodeError as exc:
            raise ModelInvalidOutput(f"Bedrock returned invalid JSON: {exc}") from exc
        except Exception as exc:
            raise ModelUnavailable(f"Bedrock call failed: {exc}") from exc

    def describe_extra(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "timeout_seconds": self.timeout,
            "boto3_initialized": self._client is not None,
        }
