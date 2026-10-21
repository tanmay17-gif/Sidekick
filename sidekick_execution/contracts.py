"""Action contract for Sidekick execution.

Implements the ``Action`` object and the status vocabulary defined in
`.sidekick/API_CONTRACTS.md` v1. Field names and state values are identical
so that the core (Agent 1) can pass actions through unchanged.

Only additive fields are introduced here (``job_id``, ``progress``). A consumer
that implements contract v1 exactly will ignore them; a consumer that does not
know about them still finds every v1 field present.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Contract v1 action states.
PENDING = "pending"
AWAITING_CONFIRMATION = "awaiting_confirmation"
RUNNING = "running"
PAUSED = "paused"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
SUPERSEDED = "superseded"

ACTION_STATES: List[str] = [
    PENDING,
    AWAITING_CONFIRMATION,
    RUNNING,
    PAUSED,
    SUCCEEDED,
    FAILED,
    CANCELLED,
    SUPERSEDED,
]

TERMINAL_STATES: List[str] = [SUCCEEDED, FAILED, CANCELLED, SUPERSEDED]

#: Legal transitions. The manager in :mod:`sidekick_execution.jobs` enforces
#: these so a job can never jump from ``pending`` straight to ``succeeded``
#: without passing through the states in between.
ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
    PENDING: [AWAITING_CONFIRMATION, RUNNING, CANCELLED, SUPERSEDED, FAILED],
    AWAITING_CONFIRMATION: [RUNNING, CANCELLED, SUPERSEDED, FAILED],
    RUNNING: [PAUSED, SUCCEEDED, FAILED, CANCELLED, SUPERSEDED],
    PAUSED: [RUNNING, CANCELLED, SUPERSEDED, FAILED],
    SUCCEEDED: [],
    FAILED: [],
    CANCELLED: [],
    SUPERSEDED: [],
}


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    """Return a fresh stable UUID4 string."""
    return str(uuid.uuid4())


@dataclass
class ActionError:
    """The contract v1 error object."""

    code: str
    message: str
    retryable: bool = False
    timeout: bool = False
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "timeout": self.timeout,
        }
        if self.details:
            payload["details"] = self.details
        return payload

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ActionError":
        return cls(
            code=raw.get("code", "internal_error"),
            message=raw.get("message", "Unknown error."),
            retryable=bool(raw.get("retryable", False)),
            timeout=bool(raw.get("timeout", False)),
            details=raw.get("details"),
        )


@dataclass
class Timestamps:
    """Creation/update stamps for an action."""

    created: str = field(default_factory=utc_now_iso)
    updated: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, str]:
        return {"created": self.created, "updated": self.updated}

    def touch(self) -> None:
        self.updated = utc_now_iso()


@dataclass
class Action:
    """A single executable action.

    Mirrors contract v1 ``Action`` exactly and adds two optional fields:
    ``job_id`` (the execution-side identifier, useful when the core issues
    several actions for one job) and ``progress`` (0.0-1.0 when known).
    """

    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=new_id)
    job_id: Optional[str] = None
    approval_required: bool = False
    state: str = PENDING
    superseded_by: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[ActionError] = None
    progress: Optional[float] = None
    timestamps: Timestamps = field(default_factory=Timestamps)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the contract v1 action shape."""
        payload: Dict[str, Any] = {
            "action_id": self.action_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "approval_required": self.approval_required,
            "state": self.state,
            "superseded_by": self.superseded_by,
            "result": self.result,
            "error": self.error.to_dict() if self.error else None,
            "timestamps": self.timestamps.to_dict(),
        }
        if self.job_id is not None:
            payload["job_id"] = self.job_id
        if self.progress is not None:
            payload["progress"] = self.progress
        return payload

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Action":
        stamps = raw.get("timestamps") or {}
        error = raw.get("error")
        return cls(
            tool=raw.get("tool", ""),
            arguments=raw.get("arguments") or {},
            action_id=raw.get("action_id") or new_id(),
            job_id=raw.get("job_id"),
            approval_required=bool(raw.get("approval_required", False)),
            state=raw.get("state", PENDING),
            superseded_by=raw.get("superseded_by"),
            result=raw.get("result"),
            error=ActionError.from_dict(error) if isinstance(error, dict) else None,
            progress=raw.get("progress"),
            timestamps=Timestamps(
                created=stamps.get("created", utc_now_iso()),
                updated=stamps.get("updated", utc_now_iso()),
            ),
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
