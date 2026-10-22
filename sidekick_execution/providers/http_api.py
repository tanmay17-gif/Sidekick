"""A real coding provider backed by an OpenAI-compatible HTTP API.

This provider performs a genuine network call to a configured chat-completions
endpoint. It is **not** connected unless the deployment supplies credentials.

Configuration (environment, all optional except the key):

``SIDEKICK_LLM_API_KEY``   Required for this provider. The bearer token.
``SIDEKICK_LLM_BASE_URL``  Defaults to ``https://api.openai.com/v1``.
``SIDEKICK_LLM_MODEL``     Defaults to ``gpt-4o-mini``.
``SIDEKICK_LLM_TIMEOUT``   Defaults to 120 seconds.

When the key is missing, or the configuration is invalid, the provider reports
``available=False`` with the exact reason. The execution service surfaces that
reason to the UI instead of pretending to be connected.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
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
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, ProviderConfig

SYSTEM_PROMPT = (
    "You are a careful coding agent operating inside an authorized workspace. "
    "You MUST reply with a single JSON object and nothing else. The object has "
    'the shape {"summary": "<short text>", "edits": [{"path": "<repo relative path>", '
    '"content": "<the complete new file content>"}]}. Use "content" for full file '
    "replacements. Only reference paths inside the workspace. Do not include "
    "explanations outside the JSON object."
)


class HttpApiCodingProvider(CodingProvider):
    """Calls a real OpenAI-compatible chat-completions endpoint."""

    name = "http_api"
    level = ClaimLevel.REAL

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        *,
        config: Optional[ProviderConfig] = None,
    ) -> None:
        self.config = config or ProviderConfig.from_env()
        self.api_key = api_key if api_key is not None else self.config.api_key
        self.base_url = (base_url or self.config.base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or self.config.model or DEFAULT_MODEL
        self.timeout = float(timeout if timeout is not None else self.config.timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    # -- status ------------------------------------------------------------
    def status(self) -> ProviderStatus:
        problems = [
            problem
            for problem in self.config.problems
            if "SIDEKICK_LLM" in problem or "provider" in problem
        ]
        if problems:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.UNAVAILABLE,
                reason="invalid_configuration",
                detail={
                    "provider": self.name,
                    "problems": problems,
                    "hint": "Fix the reported configuration problems.",
                },
            )
        if not self.api_key:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.UNAVAILABLE,
                reason="not_configured",
                detail={
                    "provider": self.name,
                    "hint": "Set SIDEKICK_LLM_API_KEY to enable this provider.",
                },
            )
        return ProviderStatus(
            available=True,
            level=ClaimLevel.REAL,
            reason="configured",
            detail={
                "provider": self.name,
                "base_url": self.base_url,
                "model": self.model,
                "timeout_seconds": self.timeout,
            },
        )

    # -- planning ----------------------------------------------------------
    def plan(self, request: CodingRequest) -> ProviderResult:
        status = self.status()
        if not status.available:
            code = (
                errors.PROVIDER_CONFIG_INVALID
                if status.reason == "invalid_configuration"
                else errors.PROVIDER_NOT_CONFIGURED
            )
            return ProviderResult(
                plan=None,
                status=status,
                error=SidekickError(
                    code,
                    "The coding provider is not usable in this deployment.",
                    details={"provider": self.name, "reason": status.reason, **status.detail},
                ),
            )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(request)},
            ],
        }
        started = time.monotonic()
        try:
            raw = self._post(payload)
        except SidekickError as exc:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(False, ClaimLevel.REAL, "unreachable", {"provider": self.name}),
                error=exc,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        latency = int((time.monotonic() - started) * 1000)
        try:
            content = self._extract_content(raw)
            plan = ChangePlan.from_dict(json.loads(content))
        except (SidekickError, json.JSONDecodeError, KeyError, TypeError) as exc:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(True, ClaimLevel.REAL, "invalid_output", {"provider": self.name}),
                error=SidekickError(
                    errors.PROVIDER_OUTPUT_INVALID,
                    f"The coding provider returned output that could not be parsed: {exc}",
                    details={"provider": self.name},
                ),
                latency_ms=latency,
                raw_output=raw[:8000],
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
                raw_output=raw[:8000],
            )
        return ProviderResult(
            plan=plan,
            status=ProviderStatus(True, ClaimLevel.REAL, "ok", {"provider": self.name, "model": self.model}),
            latency_ms=latency,
        )

    # -- internals ---------------------------------------------------------
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
        parts.append("Return only the JSON object describing the edits that fulfil the task.")
        return "\n\n".join(parts)

    def _post(self, payload: Dict[str, Any]) -> str:
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "sidekick-execution",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except TimeoutError as exc:
            raise SidekickError(
                errors.COMMAND_TIMEOUT,
                f"The coding provider did not answer within {self.timeout} seconds.",
                details={"provider": self.name, "timeout_seconds": self.timeout},
                timeout=True,
                retryable=True,
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise SidekickError(
                    errors.COMMAND_TIMEOUT,
                    f"The coding provider did not answer within {self.timeout} seconds.",
                    details={"provider": self.name, "timeout_seconds": self.timeout},
                    timeout=True,
                    retryable=True,
                ) from exc
            raise SidekickError(
                errors.PROVIDER_UNAVAILABLE,
                f"The coding provider could not be reached: {reason}",
                details={"provider": self.name},
                retryable=True,
            ) from exc

    def _http_error(self, exc: urllib.error.HTTPError) -> SidekickError:
        """Translate an HTTP status into a precise, actionable error."""
        code = exc.code
        detail = exc.read().decode("utf-8", "replace")[:500]
        if code in (401, 403):
            return SidekickError(
                errors.PROVIDER_AUTH_FAILED,
                f"The coding provider rejected the credentials (HTTP {code}).",
                details={"provider": self.name, "status": code},
                retryable=False,
            )
        if code == 429:
            retry_after = None
            try:
                retry_after = exc.headers.get("Retry-After")
            except Exception:  # pragma: no cover - header access is best effort
                retry_after = None
            return SidekickError(
                errors.PROVIDER_RATE_LIMITED,
                "The coding provider is rate limiting this deployment (HTTP 429).",
                details={
                    "provider": self.name,
                    "status": code,
                    "retry_after": retry_after,
                },
                retryable=True,
            )
        if code in (408, 504):
            return SidekickError(
                errors.COMMAND_TIMEOUT,
                f"The coding provider timed out (HTTP {code}).",
                details={"provider": self.name, "status": code},
                timeout=True,
                retryable=True,
            )
        return SidekickError(
            errors.PROVIDER_ERROR,
            f"The coding provider returned HTTP {code}.",
            details={"provider": self.name, "status": code, "body": detail},
            retryable=code >= 500,
        )

    @staticmethod
    def _extract_content(raw: str) -> str:
        parsed = json.loads(raw)
        choices = parsed.get("choices") or []
        if not choices:
            raise KeyError("choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise TypeError("message.content is not a string")
        content = content.strip()
        if content.startswith("```"):
            # Strip a markdown fence if the model added one.
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:]
            content = content.strip()
        return content

    def secret_values(self) -> List[str]:
        return [self.api_key] if self.api_key else []
