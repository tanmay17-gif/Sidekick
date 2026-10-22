"""Tool registry and truthful capability reporting.

The registry is the execution-side view of "what can Sidekick actually do".
Every entry states its truth level, so the UI can show the user what is real,
what is simulated, and what is not configured -- instead of presenting a
uniform list of buttons that may not work.

Statuses map onto the verified-claim vocabulary in
``.sidekick/DEMO_TRUTH_TABLE.md``:

``REAL``            Implemented and usable in this deployment.
``SIMULATED``       A development/test substitute. Labelled as such.
``NOT_CONFIGURED``  Implemented but missing a credential or dependency.
``NOT_IMPLEMENTED`` Not available.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .. import errors
from ..errors import SidekickError

STATUS_REAL = "REAL"
STATUS_SIMULATED = "SIMULATED"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_IRREVERSIBLE = "irreversible"


@dataclass
class ToolContext:
    """What a tool handler receives."""

    progress: Callable[[str, str, Dict[str, Any]], None]
    cancel_event: threading.Event
    session_id: Optional[str] = None
    action_id: Optional[str] = None


@dataclass
class ToolSpec:
    """One registered capability."""

    name: str
    description: str
    handler: Callable[[Dict[str, Any], ToolContext], Dict[str, Any]]
    arguments_schema: Dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False
    risk_level: str = RISK_LOW
    status: str = STATUS_REAL
    status_detail: str = ""
    simulated: bool = False
    destructive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.name,
            "description": self.description,
            "arguments_schema": dict(self.arguments_schema),
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "status": self.status,
            "status_detail": self.status_detail,
            "simulated": self.simulated,
        }


class ToolRegistry:
    """A thread-safe registry of executable tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._lock = threading.RLock()

    def register(self, spec: ToolSpec) -> ToolSpec:
        with self._lock:
            self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        with self._lock:
            spec = self._tools.get(name)
        if spec is None:
            raise SidekickError(
                errors.NOT_IMPLEMENTED,
                f"There is no tool named {name!r}.",
                details={"tool": name},
            )
        return spec

    def list_tools(self) -> List[ToolSpec]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools)]

    def capabilities(self) -> Dict[str, Any]:
        """Return a truthful capability report."""
        tools = [spec.to_dict() for spec in self.list_tools()]
        by_status: Dict[str, int] = {}
        for tool in tools:
            by_status[tool["status"]] = by_status.get(tool["status"], 0) + 1
        return {
            "tools": tools,
            "tool_count": len(tools),
            "status_counts": by_status,
            "any_simulated": any(t["simulated"] for t in tools),
        }
