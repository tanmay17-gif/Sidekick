"""Contract v1 schemas.

These models are the stable boundary between the core brain and the rest of
the product. They are intentionally strict: the core validates everything that
enters the engine and emits everything that leaves it.

Versioning rules (see ``.sidekick/API_CONTRACTS.md``):

- Additive changes (new optional field, new enum member) are backward
  compatible and bump the *minor* contract version.
- Removing or retyping a field bumps the *major* contract version and needs a
  reviewed pull request.

Every model forbids unknown fields so that a typo in a client payload is an
error instead of a silently ignored value.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

CONTRACT_VERSION = "v1"


def utcnow() -> datetime:
    """Return an aware UTC timestamp (single source of truth for time)."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Return a fresh stable identifier."""
    return str(uuid.uuid4())


class StrictModel(BaseModel):
    """Base model: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class InputSource(str, Enum):
    VOICE = "voice"
    TEXT = "text"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IRREVERSIBLE = "irreversible"


class ActionStatus(str, Enum):
    """Lifecycle state of a single action."""

    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class ResponseStatus(str, Enum):
    """Overall status of one engine turn.

    Extends :class:`ActionStatus` with the two states that describe a turn
    rather than a single action: the engine is waiting for a clarification, or
    it deferred because the transcript was not final yet.
    """

    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    NEEDS_CLARIFICATION = "needs_clarification"
    AWAITING_TRANSCRIPT = "awaiting_transcript"


class DecisionSource(str, Enum):
    """Where the interpretation came from.

    ``MODEL`` means the real decision model produced the interpretation.
    ``RULE`` means the deterministic fallback handled it. It is never valid to
    report ``MODEL`` when the fallback ran.
    """

    MODEL = "model"
    RULE = "rule"


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


class CorrectionContext(StrictModel):
    """Explicit correction signal supplied by the caller.

    A voice front-end may know that the final transcript replaced an earlier
    one. The engine trusts it but still runs the same safety policy.

    ``signal`` and ``supersedes`` are the names the browser client uses; they
    are aliases of ``target_action_id`` and a free-form marker respectively.
    """

    replaces_request_id: str | None = None
    target_action_id: str | None = None
    kind: Literal["replace_destination", "replace_parameters", "cancel", "add", "unspecified"] = "unspecified"
    note: str | None = None
    #: Free-form marker, e.g. the correction word the client recognised.
    signal: str | None = None
    #: The action id this correction replaces (browser alias).
    supersedes: str | None = None

    def resolved_action_id(self) -> str | None:
        return self.target_action_id or self.supersedes


class ContinuationContext(StrictModel):
    """Explicit continuation signal supplied by the caller.

    ``resume_task_id`` continues an existing task; ``elide_tool`` marks the
    previous tool as implied ("continue what I was doing before").
    ``previous_request_id`` is sent by the browser on every follow-up.
    """

    resume_task_id: str | None = None
    elide_tool: bool = False
    note: str | None = None
    previous_request_id: str | None = None


class SidekickRequest(StrictModel):
    """A single user turn.

    ``request_id`` and ``session_id`` are required and stable. The session id
    may also be supplied through the ``X-Sidekick-Session`` header, in which
    case the header wins (see :func:`sidekick.api.routes.resolve_session_id`).
    """

    request_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    utterance: str = Field(default="", max_length=4000)
    input_source: InputSource = InputSource.TEXT
    utterance_finalized: bool = True
    correction_context: CorrectionContext | None = None
    continuation_context: ContinuationContext | None = None

    @field_validator("utterance")
    @classmethod
    def _strip_utterance(cls, value: str) -> str:
        return value.strip()

    @field_validator("session_id", "request_id")
    @classmethod
    def _no_control_chars(cls, value: str) -> str:
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("identifier must not contain control characters")
        return value


# --------------------------------------------------------------------------
# Response
# --------------------------------------------------------------------------


class Entity(BaseModel):
    """A typed slot extracted for an action."""

    name: str
    value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Literal["model", "parser", "session", "user"] = "parser"

    model_config = ConfigDict(extra="forbid")


class IntentInfo(BaseModel):
    """The interpreted intent of the turn."""

    normalized: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ambiguous: bool = False
    entities: list[Entity] = Field(default_factory=list)
    multi_action: bool = False
    source: DecisionSource = DecisionSource.RULE

    model_config = ConfigDict(extra="forbid")


class ActionError(BaseModel):
    """Structured, actionable error. Never a bare string."""

    code: str
    message: str
    retryable: bool = False
    timeout: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class Timestamps(BaseModel):
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(default_factory=utcnow)

    model_config = ConfigDict(extra="forbid")


class Action(StrictModel):
    """One planned or executed action."""

    action_id: str = Field(default_factory=new_id)
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = False
    state: ActionStatus = ActionStatus.PENDING
    superseded_by: str | None = None
    result: Any | None = None
    error: ActionError | None = None
    timestamps: Timestamps = Field(default_factory=Timestamps)
    description: str = ""
    plan_hash: str = ""
    #: The execution-side job that carries this action (equal to
    #: ``action_id`` in the core). Optional, additive.
    job_id: str | None = None
    #: Progress fraction between 0.0 and 1.0 when the action reports one.
    progress: float | None = Field(default=None, ge=0.0, le=1.0)

    def touch(self) -> None:
        self.timestamps.updated = utcnow()


class Clarification(StrictModel):
    """A question the engine asks instead of guessing."""

    question: str
    options: list[str] = Field(default_factory=list)
    action_id: str | None = None
    missing_arguments: list[str] = Field(default_factory=list)


class DecisionModelInfo(BaseModel):
    """Truthful provenance of the interpretation.

    ``fallback_used`` is ``True`` exactly when the deterministic rule engine
    produced the interpretation instead of the real decision model. The
    ``provider``/``model`` pair always describes what actually ran.
    """

    provider: str
    model: str
    source: DecisionSource
    fallback_used: bool
    fallback_reason: str | None = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    device: str | None = None
    load_error: str | None = None
    model_available: bool = True

    model_config = ConfigDict(extra="forbid")


class Event(StrictModel):
    """A progress/decision event for the UI.

    The field set is the union of what the browser client and the execution
    service need: ``type`` is the precise event name, ``kind`` is the coarse
    category the UI switches on, ``seq`` is a monotonic sequence number and
    ``ts`` mirrors ``at`` for the execution event schema.
    """

    type: str
    at: datetime = Field(default_factory=utcnow)
    action_id: str | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    #: Coarse category for the UI: progress | log | action_update | diff |
    #: result | error.
    kind: str = "progress"
    #: Monotonic sequence number within the session.
    seq: int = 0
    #: The tool this event belongs to.
    tool: str | None = None
    #: The action state at the time of the event.
    status: str | None = None
    #: The execution job that carries the action.
    job_id: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ts(self) -> str:
        """UTC timestamp in the execution event format (millisecond, ``Z``)."""
        moment = self.at.astimezone(timezone.utc)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"

    def serialise(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SessionView(StrictModel):
    """Read-only projection of a session, safe for any client to render."""

    session_id: str
    active_task_id: str | None = None
    suspended_task_ids: list[str] = Field(default_factory=list)
    pending_action_ids: list[str] = Field(default_factory=list)
    awaiting_confirmation_action_ids: list[str] = Field(default_factory=list)
    last_intent: str | None = None
    last_entities: list[Entity] = Field(default_factory=list)
    turn_count: int = 0
    updated_at: datetime = Field(default_factory=utcnow)


class SidekickResponse(StrictModel):
    """The engine's answer for one turn."""

    contract_version: str = CONTRACT_VERSION
    request_id: str
    session_id: str
    intent: IntentInfo
    action_plan: list[Action] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    decision_model: DecisionModelInfo
    status: ResponseStatus = ResponseStatus.PENDING
    clarification: Clarification | None = None
    events: list[Event] = Field(default_factory=list)
    session: SessionView | None = None
    message: str = ""
    #: Optional text the client may speak verbatim. When it is absent the
    #: client reads a short summary of the real action plan.
    speech: str | None = None
