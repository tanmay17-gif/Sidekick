"""A real coding provider backed by an authorized local CLI.

Some coding agents are installed as command-line tools rather than reached
over HTTP. This provider drives such a CLI through the sandbox, so the CLI
runs with the same allowlist, environment scrubbing, timeout and output limits
as every other command.

Configuration (environment):

``SIDEKICK_CODING_CLI``       The CLI to run, e.g. ``aider`` or ``claude``.
``SIDEKICK_CODING_CLI_ARGS``  JSON array of argument templates. Placeholders:
                               ``{task}``, ``{workspace}``, ``{context}``.
``SIDEKICK_CODING_CLI_TIMEOUT`` Optional seconds. Defaults to 300.

The CLI is expected to print a JSON change plan on stdout, matching
:mod:`sidekick_execution.providers.base`. This is the documented contract for
an authorized local coding CLI.

If the CLI is not installed the provider reports ``available=False`` with the
reason ``not_installed`` -- it never silently degrades to a fake result.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import errors
from ..errors import SidekickError
from ..sandbox import CommandRunner, resolve_executable
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

DEFAULT_TIMEOUT = 300.0
DEFAULT_ARGS: List[str] = ["--json-plan", "--task", "{task}", "--workspace", "{workspace}"]


class LocalCliCodingProvider(CodingProvider):
    """Drives an authorized local coding CLI."""

    name = "local_cli"
    level = ClaimLevel.REAL

    def __init__(
        self,
        cli: Optional[str] = None,
        args: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        runner: Optional[CommandRunner] = None,
        *,
        config: Optional[ProviderConfig] = None,
    ) -> None:
        self.config = config or ProviderConfig.from_env()
        self.cli = cli if cli is not None else self.config.cli
        if args is not None:
            self.args = list(args)
        elif self.config.cli_args:
            self.args = list(self.config.cli_args)
        else:
            raw_args = os.environ.get("SIDEKICK_CODING_CLI_ARGS")
            self.args = list(DEFAULT_ARGS)
            if raw_args:
                try:
                    parsed = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    self.args = [str(part) for part in parsed]
        self.timeout = float(timeout if timeout is not None else self.config.cli_timeout_seconds or DEFAULT_TIMEOUT)
        self.runner = runner or CommandRunner()

    # -- status ------------------------------------------------------------
    def status(self) -> ProviderStatus:
        problems = [problem for problem in self.config.problems if "SIDEKICK_CODING_CLI" in problem]
        if problems:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.UNAVAILABLE,
                reason="invalid_configuration",
                detail={"provider": self.name, "problems": problems},
            )
        if not self.cli:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.UNAVAILABLE,
                reason="not_configured",
                detail={
                    "provider": self.name,
                    "hint": "Set SIDEKICK_CODING_CLI to an authorized local coding CLI.",
                },
            )
        resolved = resolve_executable(self.cli)
        if resolved is None:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.UNAVAILABLE,
                reason="not_installed",
                detail={"provider": self.name, "cli": self.cli},
            )
        return ProviderStatus(
            available=True,
            level=ClaimLevel.REAL,
            reason="installed",
            detail={"provider": self.name, "cli": self.cli, "path": resolved},
        )

    # -- planning ----------------------------------------------------------
    def plan(self, request: CodingRequest) -> ProviderResult:
        status = self.status()
        if not status.available:
            return ProviderResult(
                plan=None,
                status=status,
                error=SidekickError(
                    errors.PROVIDER_NOT_CONFIGURED
                    if status.reason == "not_configured"
                    else errors.PROVIDER_UNAVAILABLE,
                    "The configured local coding CLI is not available.",
                    details={"provider": self.name, "reason": status.reason},
                ),
            )
        argv = [self.cli] + [self._expand(arg, request) for arg in self.args]
        started = time.monotonic()
        try:
            result = self.runner.run(
                argv,
                cwd=Path(request.workspace),
                timeout=self.timeout,
            )
        except SidekickError as exc:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(False, ClaimLevel.REAL, "failed", {"provider": self.name}),
                error=exc,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        latency = int((time.monotonic() - started) * 1000)
        if result.timed_out:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(False, ClaimLevel.REAL, "timeout", {"provider": self.name}),
                error=SidekickError(
                    errors.PROVIDER_ERROR,
                    "The local coding CLI timed out.",
                    details={"provider": self.name},
                    timeout=True,
                    retryable=True,
                ),
                latency_ms=latency,
                raw_output=result.stdout[:8000],
            )
        if result.exit_code != 0:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(False, ClaimLevel.REAL, "failed", {"provider": self.name}),
                error=SidekickError(
                    errors.PROVIDER_ERROR,
                    f"The local coding CLI exited with code {result.exit_code}.",
                    details={"provider": self.name, "exit_code": result.exit_code},
                    retryable=True,
                ),
                latency_ms=latency,
                raw_output=(result.stdout + result.stderr)[:8000],
            )
        try:
            plan = ChangePlan.from_dict(json.loads(result.stdout))
        except (json.JSONDecodeError, SidekickError) as exc:
            return ProviderResult(
                plan=None,
                status=ProviderStatus(True, ClaimLevel.REAL, "invalid_output", {"provider": self.name}),
                error=SidekickError(
                    errors.PROVIDER_OUTPUT_INVALID,
                    f"The local coding CLI did not return a valid change plan: {exc}",
                    details={"provider": self.name},
                ),
                latency_ms=latency,
                raw_output=result.stdout[:8000],
            )
        plan.provider = self.name
        plan.model = self.cli
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
                raw_output=result.stdout[:8000],
            )
        return ProviderResult(
            plan=plan,
            status=ProviderStatus(True, ClaimLevel.REAL, "ok", {"provider": self.name}),
            latency_ms=latency,
        )

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _expand(template: str, request: CodingRequest) -> str:
        context = json.dumps(
            {"files": {k: v for k, v in list(request.context_files.items())[:20]}}
        )
        return (
            template.replace("{task}", request.task)
            .replace("{workspace}", request.workspace)
            .replace("{context}", context)
        )

    def required_executables(self) -> List[str]:
        return [self.cli] if self.cli else []

    def secret_values(self) -> List[str]:
        return []
