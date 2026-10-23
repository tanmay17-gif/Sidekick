"""Amazon Bedrock coding provider.

Proposes workspace change plans using foundation models hosted on Amazon Bedrock
(e.g., Qwen 2.5/3 Coder, Anthropic Claude 3 Sonnet, or Amazon Nova/Titan).

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

DEFAULT_BEDROCK_CODING_MODEL = "qwen.qwen3-coder-30b-a3b-v1:0"
DEFAULT_AWS_REGION = "eu-north-1"

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
                    "region": self.region,
                    "model": self.model,
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

        output_text = ""
        try:
            # 1. Try Converse API if available and returns dict structure
            if hasattr(client, "converse") and callable(client.converse):
                try:
                    res = client.converse(
                        modelId=self.model,
                        messages=[{"role": "user", "content": [{"text": prompt}]}],
                        system=[{"text": SYSTEM_PROMPT}],
                        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
                    )
                    if isinstance(res, dict) and "output" in res and isinstance(res["output"], dict):
                        content_list = res["output"].get("message", {}).get("content", [])
                        if content_list and isinstance(content_list[0], dict) and "text" in content_list[0]:
                            output_text = str(content_list[0]["text"]).strip()
                except Exception:
                    output_text = ""

            # 2. Invoke model fallback
            if not output_text:
                if "claude" in self.model.lower():
                    body = json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 4096,
                        "system": SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                    })
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
                raw_body = response["body"].read() if hasattr(response.get("body"), "read") else response.get("body", "{}")
                response_body = json.loads(raw_body)
                if "content" in response_body and isinstance(response_body["content"], list):
                    output_text = str(response_body["content"][0]["text"]).strip()
                elif "results" in response_body:
                    output_text = str(response_body.get("results", [{}])[0].get("outputText", "")).strip()
                else:
                    output_text = str(response_body.get("generation", "")).strip()
        except Exception as exc:  # noqa: BLE001
            latency = int((time.monotonic() - started) * 1000)
            err_msg = str(exc)
            # Distinct classification for AWS Account Verification Pending / Access Denied
            if "AccessDeniedException" in err_msg or "pending verification" in err_msg.lower() or "is being verified" in err_msg.lower():
                return ProviderResult(
                    plan=None,
                    status=ProviderStatus(
                        False,
                        ClaimLevel.UNAVAILABLE,
                        "blocked_by_aws",
                        {
                            "provider": self.name,
                            "region": self.region,
                            "model": self.model,
                            "hint": "AWS account verification is pending or model access is waiting for AWS approval. Status: BLOCKED.",
                        },
                    ),
                    error=SidekickError(
                        errors.PROVIDER_AUTH_FAILED,
                        f"Amazon Bedrock access blocked: AWS account verification is pending ({err_msg}).",
                        details={"provider": self.name, "region": self.region, "model": self.model, "status": "BLOCKED"},
                    ),
                    latency_ms=latency,
                )

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
                parts.append(f"--- {path} ---\n{content}\n")
        return "\n\n".join(parts)
