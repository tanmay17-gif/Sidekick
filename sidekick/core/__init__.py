"""Core brain: intent resolution, safety policy, sessions and orchestration."""

from __future__ import annotations

from .catalog import ARG_BOOLEAN, ARG_DURATION, ARG_ENUM, ARG_INTEGER, ARG_STRING, ArgumentSpec, CapabilityCatalog, ToolSpec, build_catalog
from .decision import Decision, DecisionModel, DecisionQuery, ModelInvalidOutput, ModelTimeout, ModelUnavailable
from .engine import DecisionEngine, ResolvedSegment
from .errors import (
    ConflictError,
    NotFoundError,
    SidekickError,
    UnprocessableEntityError,
)
from .registry import ToolAdapter, ToolRegistry, ToolResult, ToolUnavailableError
from .safety import PolicyDecision, PolicyViolation, SafetyPolicy, ViolationKind, plan_hash
from .schemas import (
    Action,
    ActionError,
    ActionStatus,
    Clarification,
    DecisionModelInfo,
    DecisionSource,
    Entity,
    Event,
    InputSource,
    IntentInfo,
    ResponseStatus,
    RiskLevel,
    SidekickRequest,
    SidekickResponse,
    SessionView,
)
from .sessions import SessionState, SessionStore, TaskState

__all__ = [
    "Action",
    "ActionError",
    "ActionStatus",
    "ARG_BOOLEAN",
    "ARG_DURATION",
    "ARG_ENUM",
    "ARG_INTEGER",
    "ARG_STRING",
    "ArgumentSpec",
    "CapabilityCatalog",
    "Clarification",
    "ConflictError",
    "Decision",
    "DecisionEngine",
    "DecisionModel",
    "DecisionModelInfo",
    "DecisionQuery",
    "DecisionSource",
    "Entity",
    "Event",
    "InputSource",
    "IntentInfo",
    "ModelInvalidOutput",
    "ModelTimeout",
    "ModelUnavailable",
    "NotFoundError",
    "PolicyDecision",
    "PolicyViolation",
    "ResolvedSegment",
    "ResponseStatus",
    "RiskLevel",
    "SafetyPolicy",
    "SessionState",
    "SessionStore",
    "SessionView",
    "SidekickError",
    "SidekickRequest",
    "SidekickResponse",
    "TaskState",
    "ToolAdapter",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolUnavailableError",
    "UnprocessableEntityError",
    "ViolationKind",
    "build_catalog",
    "plan_hash",
]
