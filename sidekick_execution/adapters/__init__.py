"""Adapters that turn a tool request into a real, reportable outcome."""

from .coding import CodingActionOutcome, CodingActionRequest, CodingAdapter
from .registry import (
    RISK_HIGH,
    RISK_IRREVERSIBLE,
    RISK_LOW,
    RISK_MEDIUM,
    STATUS_NOT_CONFIGURED,
    STATUS_NOT_IMPLEMENTED,
    STATUS_REAL,
    STATUS_SIMULATED,
    ToolContext,
    ToolRegistry,
    ToolSpec,
)

__all__ = [
    "CodingActionOutcome",
    "CodingActionRequest",
    "CodingAdapter",
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "STATUS_REAL",
    "STATUS_SIMULATED",
    "STATUS_NOT_CONFIGURED",
    "STATUS_NOT_IMPLEMENTED",
    "RISK_LOW",
    "RISK_MEDIUM",
    "RISK_HIGH",
    "RISK_IRREVERSIBLE",
]
