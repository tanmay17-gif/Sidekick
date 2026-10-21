"""Shared base for decision models."""

from __future__ import annotations

import time
from typing import Any

from ..decision import Decision, DecisionQuery, ModelUnavailable
from ..schemas import DecisionModelInfo, DecisionSource


class BaseDecisionModel:
    """Common bookkeeping for decision models.

    Subclasses implement :meth:`_decide`; the base class measures latency,
    keeps the last provenance and guarantees that a failure is reported as a
    failure instead of being silently swallowed.
    """

    provider: str = "unknown"
    model: str = "unknown"
    #: Why this model is used as a fallback (set by the bootstrap layer).
    fallback_reason: str | None = None

    def __init__(self) -> None:
        self._last_info: DecisionModelInfo | None = None
        self._load_error: str | None = None

    # -- public API -------------------------------------------------------

    @property
    def available(self) -> bool:
        return True

    def decide(self, query: DecisionQuery) -> Decision:
        started = time.perf_counter()
        try:
            decision = self._decide(query)
        except ModelUnavailable as exc:
            self._load_error = str(exc)
            raise
        latency_ms = (time.perf_counter() - started) * 1000.0
        decision.details.setdefault("latency_ms", round(latency_ms, 3))
        self._last_info = self._provenance(decision, latency_ms)
        return decision

    def describe(self) -> DecisionModelInfo:
        if self._last_info is not None:
            return self._last_info
        return self._provenance(None, 0.0)

    # -- hooks ------------------------------------------------------------

    def _decide(self, query: DecisionQuery) -> Decision:
        raise NotImplementedError

    def _provenance(self, decision: Decision | None, latency_ms: float) -> DecisionModelInfo:
        source = decision.source if decision else DecisionSource.RULE
        return DecisionModelInfo(
            provider=self.provider,
            model=self.model,
            source=source,
            fallback_used=source is DecisionSource.RULE,
            fallback_reason=(
                self.fallback_reason
                if source is DecisionSource.RULE
                else None
            ),
            latency_ms=round(latency_ms, 3),
            device=None,
            load_error=self._load_error,
            model_available=self.available,
        )

    def describe_extra(self) -> dict[str, Any]:
        """Model specific details for the /healthz and diagnostics output."""
        return {}
