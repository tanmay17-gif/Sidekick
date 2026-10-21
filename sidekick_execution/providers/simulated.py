"""A development/test-only coding provider. **SIMULATED - NOT A REAL AGENT.**

This provider does not call a model, a service, or an agent. It fabricates a
deterministic change plan so that the surrounding *real* machinery -- file
writes, sandboxed command execution, real diffs, real test runs, job
lifecycle, event streaming -- can be exercised in tests and local demos.

Safety rails
------------
* It reports ``level = SIMULATED`` in every status and result.
* It refuses to run unless ``SIDEKICK_ALLOW_SIMULATED_PROVIDER=1``.
* It refuses to run when ``SIDEKICK_ENV=production``.
* The tool registry never selects it unless explicitly requested.

Never present output from this provider as the result of a real coding agent.
"""

from __future__ import annotations

import os
import time
from typing import List

from .. import errors
from ..errors import SidekickError
from .base import (
    ChangePlan,
    ClaimLevel,
    CodingProvider,
    CodingRequest,
    FileEdit,
    ProviderResult,
    ProviderStatus,
)

ENV_FLAG = "SIDEKICK_ALLOW_SIMULATED_PROVIDER"
ENV_NAME = "SIDEKICK_ENV"


class SimulatedCodingProvider(CodingProvider):
    """Produces a deterministic, obviously-synthetic change plan."""

    name = "simulated"
    level = ClaimLevel.SIMULATED

    def __init__(self, *, enabled: bool | None = None) -> None:
        self._explicitly_enabled = enabled

    # -- status ------------------------------------------------------------
    def status(self) -> ProviderStatus:
        if self._explicitly_enabled is False:
            return ProviderStatus(
                available=False,
                level=ClaimLevel.SIMULATED,
                reason="disabled",
                detail={"provider": self.name},
            )
        if os.environ.get(ENV_NAME, "").lower() == "production":
            return ProviderStatus(
                available=False,
                level=ClaimLevel.SIMULATED,
                reason="not_allowed_in_production",
                detail={"provider": self.name, "env": ENV_NAME},
            )
        if os.environ.get(ENV_FLAG, "") != "1":
            return ProviderStatus(
                available=False,
                level=ClaimLevel.SIMULATED,
                reason="not_enabled",
                detail={"provider": self.name, "hint": f"Set {ENV_FLAG}=1 to use the simulated provider."},
            )
        return ProviderStatus(
            available=True,
            level=ClaimLevel.SIMULATED,
            reason="enabled",
            detail={"provider": self.name, "simulated": True},
        )

    # -- planning ----------------------------------------------------------
    def plan(self, request: CodingRequest) -> ProviderResult:
        status = self.status()
        if not status.available:
            return ProviderResult(
                plan=None,
                status=status,
                error=SidekickError(
                    errors.PROVIDER_NOT_CONFIGURED,
                    "The simulated coding provider is not enabled in this environment.",
                    details={"provider": self.name, "reason": status.reason},
                ),
            )
        started = time.monotonic()
        marker = "sidekick-simulated-change"
        target = "sidekick_simulated_change.txt"
        content = (
            f"# SIMULATED OUTPUT - NOT A REAL CODING AGENT\n"
            f"# provider: {self.name}\n"
            f"# task: {request.task}\n"
            f"# marker: {marker}\n"
        )
        plan = ChangePlan(
            edits=[FileEdit(path=target, content=content)],
            summary=f"Simulated provider wrote {target}.",
            provider=self.name,
            model="simulated",
        )
        return ProviderResult(
            plan=plan,
            status=status,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def required_executables(self) -> List[str]:
        return []

    def secret_values(self) -> List[str]:
        return []
