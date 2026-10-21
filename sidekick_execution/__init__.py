"""Sidekick execution service.

Real task execution for Sidekick: a coding agent that edits files inside an
authorized workspace, runs real commands and tests, captures real diffs, and
reports honest outcomes.

This package owns the *execution* side of `.sidekick/API_CONTRACTS.md` v1. It
never interprets user intent (Agent 1) and never renders UI (Agent 3); it
exposes a stable action/job/event contract for both to build on.

Public surface:

- :class:`~sidekick_execution.contracts.Action` -- action record (contract v1)
- :class:`~sidekick_execution.errors.SidekickError` -- structured error model
- :class:`~sidekick_execution.jobs.JobManager` -- job lifecycle
- :class:`~sidekick_execution.workspace.WorkspacePolicy` -- workspace authorization
- :class:`~sidekick_execution.sandbox.CommandPolicy` -- command execution policy
- :func:`~sidekick_execution.adapters.registry.default_registry` -- tool registry
"""

from .contracts import (
    ACTION_STATES,
    TERMINAL_STATES,
    Action,
    ActionError,
    Timestamps,
)
from .errors import (
    ERROR_CODES,
    SidekickError,
    error_payload,
)
from .events import EVENT_TYPES, Event, EventType

__all__ = [
    "ACTION_STATES",
    "TERMINAL_STATES",
    "Action",
    "ActionError",
    "Timestamps",
    "ERROR_CODES",
    "SidekickError",
    "error_payload",
    "Event",
    "EventType",
    "EVENT_TYPES",
]

__version__ = "0.1.0"
