"""Amazon Bedrock coding provider.

Proposes workspace change plans using foundation models hosted on Amazon Bedrock
(e.g., Anthropic Claude 3 Sonnet or Amazon Titan).

Authentication:
Uses standard AWS authentication (IAM role, environment variables AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, AWS_REGION, or AWS profile). Does NOT require an LLM API key.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from .. import errors
from ..errors import SidekickError
from .base import (
    ChangePlan,
    ClaimLevel,
    CodingProvider,
    CodingRequest,
    ProviderResult,
    ProviderStatus,
    validate_change_plan,
)
from .config import ProviderConfig

DEFAULT_BEDROCK_CODING_MODEL = "anthropic.claude-3-sonnet-20240229-v1:0"
DEFAULT_AWS_REGION = "us-east-1"

SYSTEM_PROMPT = """You are Sidekick's Coding Agent.
Your job is to propose precise file edits for the requested task in the authorized workspace.
You MUST output ONLY a valid JSON object with the following schema:
{
  "summary": "Short description of changes",
  "edits": [
    {
      "path": "relative/path/to/file",
      "content": "full new content of the file"
    }
  ]
}
Rules:
1. Every path must be relative to the workspace root.
2. Provide the full content for any file being created or modified.
3. Do NOT include markdown formatting or commentary outside the JSON object.
"""


class BedrockCodingProvider(CodingProvider):
    """Coding provider backed by Amazon Bedrock."""

    name: str = "bedrock"
    level: str = ClaimLevel.REAL

    def __init__(
        self,
        *,
        model_id: Optional[str] = None,
        region_name: Optional[str] = None,
        timeout_seconds: float = 60.0,
        config: Optional[ProviderConfig] = None,
        boto3_client: Any = None,
    ) -> None:
        self.config = config or ProviderConfig.from_env()
        self.model = (
            model_id
            or os.environ.get("BEDROCK_MODEL_ID")
            or DEFAULT_BEDROCK_CODING_MODEL
        )
        self.region = (
            region_name
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or DEFAULT_AWS_REGION
        )
        self.timeout = float(timeout_seconds)
        self._client = boto3_client
        self._client_init_error: Optional[str] = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
            session = boto3.Session(region_name=self.region)
            creds = session.get_credentials()
            if creds is None and not os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
                self._client_init_error = "AWS credentials not configured"
                return None
            self._client = session.client("bedrock-runtime", region_name=self.region)
            return self._client
        except Exception as exc:  # noqa: BLE001
            self._client_init_error = str(exc)
            return None

    def status(self) -> ProviderStatus:
        client = self._get_client()
        if client is None:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.UNAVAILABLE,
                reason="not_configured",
                detail={
                    "provider": self.name,
                    "hint": "Configure AWS credentials (e.g. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or IAM role) to enable Bedrock.",
                },
            )
        return ProviderStatus(
            available=True,
            level=ClaimLevel.REAL,
            reason="configured",
            detail={
                "provider": self.name,
                "region": self.region,
                "model": self.model,
                "timeout_seconds": self.timeout,
            },
        )

    def plan(self, request: CodingRequest) -> ProviderResult:
        status = self.status()
        if not status.available:
            return ProviderResult(
                plan=None,
                status=status,
                error=SidekickError(
                    errors.PROVIDER_NOT_CONFIGURED,
                    "Amazon Bedrock is not configured in this deployment (requires AWS credentials).",
                    details={"provider": self.name, "reason": status.reason, **status.detail},
                ),
            )

        client = self._get_client()
        prompt = self._build_prompt(request)
        started = time.monotonic()

        try:
            if "claude" in self.model.lower():
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                })
                response = client.invoke_model(
                    modelId=self.model,
                    body=body,
                )
                response_body = json.loads(response["body"].read())
                output_text = response_body["content"][0]["text"].strip()
            else:
                body = json.dumps({
                    "inputText": f"{SYSTEM_PROMPT}\n\n{prompt}",
                    "textGenerationConfig": {
                        "maxTokenCount": 4096,
                        "temperature": 0.0,
                    },
                })
                response = client.invoke_model(
                    modelId=self.model,
                    body=body,
                )
                response_body = json.loads(response["body"].read())
                output_text = response_body.get("results", [{}])[0].get("outputText", "").strip()
        except Exception as exc:  # noqa: BLE001
            latency = int((time.monotonic() - started) * 1000)
            return ProviderResult(
                plan=None,
                status=ProviderStatus(False, ClaimLevel.REAL, "error", {"provider": self.name}),
                error=SidekickError(
                    errors.PROVIDER_ERROR,
                    f"Amazon Bedrock invocation failed: {exc}",
                    details={"provider": self.name},
                ),
                latency_ms=latency,
            )

        latency = int((time.monotonic() - started) * 1000)

        # Extract JSON
        try:
            cleaned = output_text
            fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output_text, re.DOTALL)
            if fence_match:
                cleaned = fence_match.group(1)
            else:
                brace_start = output_text.find("{")
                brace_end = output_text.rfind("}")
                if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                    cleaned = output_text[brace_start : brace_end + 1]

            data = json.loads(cleaned)
            plan = ChangePlan.from_dict(data)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                plan=None,
                status=ProviderStatus(True, ClaimLevel.REAL, "invalid_output", {"provider": self.name}),
                error=SidekickError(
                    errors.PROVIDER_OUTPUT_INVALID,
                    f"The Bedrock provider returned output that could not be parsed: {exc}",
                    details={"provider": self.name},
                ),
                latency_ms=latency,
                raw_output=output_text[:8000],
            )

        plan.provider = self.name
        plan.model = self.model
        try:
            validate_change_plan(
                plan,
                max_edits=self.config.max_edits,
                max_file_bytes=self.config.max_file_bytes,
            )
        except SidekickError as exc:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(True, ClaimLevel.REAL, "invalid_output", {"provider": self.name}),
                error=exc,
                latency_ms=latency,
                raw_output=output_text[:8000],
            )

        return ProviderResult(
            plan=plan,
            status=ProviderStatus(True, ClaimLevel.REAL, "ok", {"provider": self.name, "model": self.model}),
            latency_ms=latency,
        )

    def _build_prompt(self, request: CodingRequest) -> str:
        parts: List[str] = [f"Task: {request.task}", f"Workspace: {request.workspace}"]
        if request.context_files:
            parts.append("Relevant files:")
            for path, content in request.context_files.items():
                parts.append(f"--- {path} ---\n{content}")
        if request.test_command:
            parts.append(f"Tests are run with: {' '.join(request.test_command)}")
        for constraint in request.constraints:
            parts.append(f"Constraint: {constraint}")
        parts.append("Return ONLY the JSON change plan object.")
        return "\n\n".join(parts)
