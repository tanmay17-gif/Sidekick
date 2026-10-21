"""Deterministic fallback decision model.

This model is *not* a script of recognised demo sentences. It is a
catalog-driven matcher: every tool and destination in the capability catalog
declares its aliases, and the matcher looks for those aliases as whole words
in the utterance. Adding a capability to the catalog immediately makes it
recognisable - no keyword list lives inside the brain.

It is used when the real model is unavailable, slow or returns unusable
output. Whenever it runs, the response reports
``decision_model.fallback_used = true``.
"""

from __future__ import annotations

from ..catalog import CapabilityCatalog
from ..decision import Decision, DecisionQuery
from ..parsing import detect_correction, match_control, normalize
from ..schemas import DecisionSource
from .base import BaseDecisionModel


class RuleDecisionModel(BaseDecisionModel):
    """Catalog driven, deterministic interpretation."""

    provider = "sidekick"
    model = "rule-engine-v1"

    #: Below this score the fallback refuses to guess and lets the engine ask.
    confidence_floor = 0.35

    def _decide(self, query: DecisionQuery) -> Decision:
        text = query.utterance or ""
        lowered = normalize(text)

        correction = detect_correction(text)
        control, control_score = match_control(text)

        tool, tool_score = query.catalog.match_tool(lowered)
        destination, destination_score = query.catalog.match_destination(lowered)

        # A control verb without a concrete target is still a control intent.
        if control and control_score >= tool_score:
            tool = control
            tool_score = control_score

        # The destination can identify the tool even when the verb is generic
        # ("play something on spotify" -> the media tool with destination).
        if destination and (tool is None or tool_score < 0.5):
            owner = query.catalog.all_destinations().get(destination)
            if owner:
                tool = owner
                tool_score = max(tool_score, 0.5)

        confidence = min(1.0, max(tool_score, destination_score * 0.9))
        if correction.is_correction:
            confidence = min(1.0, confidence + 0.1)

        resolved_tool = tool if confidence >= self.confidence_floor else None
        if resolved_tool is not None and not resolved_tool.startswith("control."):
            if resolved_tool not in query.catalog:
                resolved_tool = None

        return Decision(
            tool=resolved_tool,
            tool_scores={spec.name: 0.0 for spec in query.catalog},
            destination=destination,
            destination_scores={},
            destination_confidence=1.0 if destination else 0.0,
            is_correction=correction.is_correction,
            is_multi_action=False,
            confidence=round(confidence, 4),
            source=DecisionSource.RULE,
            details={
                "marker": correction.marker,
                "rule_matched": True,
                "catalog_size": len(query.catalog),
            },
        )

    def _provenance_extra(self) -> dict[str, object]:
        return {"kind": "catalog_matcher"}
