"""Coding provider interface.

A *coding provider* decides **what** should change in a workspace. It never
touches the filesystem itself: it returns a :class:`ChangePlan`, and the
executor in :mod:`sidekick_execution.adapters.coding` applies that plan with
real file writes, real command runs and real diffs.

Providers declare their own truth level via :class:`ClaimLevel`:

``REAL``       Talks to a real provider (an API or an authorized local CLI).
``SIMULATED`` A development/test substitute. Never reachable in production.
``UNAVAILABLE`` Not configured in this deployment.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import errors
from ..errors import SidekickError


class ClaimLevel:
    """Truth level of a provider (see ``.sidekick/DEMO_TRUTH_TABLE.md``)."""

    REAL = "REAL"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class FileEdit:
    """One intended file change.

    Exactly one of ``content`` or ``patch`` is used:

    * ``content`` -- the full new file content (the file is replaced).
    * ``patch`` -- a unified diff applied with ``git apply``.
    """

    path: str
    content: Optional[str] = None
    patch: Optional[str] = None
    delete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"path": self.path}
        if self.delete:
            payload["delete"] = True
        elif self.content is not None:
            payload["content"] = self.content
        elif self.patch is not None:
            payload["patch"] = self.patch
        return payload

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "FileEdit":
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise SidekickError(
                errors.PROVIDER_OUTPUT_INVALID,
                "A change-plan edit is missing a valid 'path'.",
            )
        return cls(
            path=path,
            content=raw.get("content"),
            patch=raw.get("patch"),
            delete=bool(raw.get("delete", False)),
        )


@dataclass
class ChangePlan:
    """The set of changes a provider proposes."""

    edits: List[FileEdit] = field(default_factory=list)
    summary: str = ""
    provider: str = ""
    model: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "provider": self.provider,
            "model": self.model,
            "edits": [e.to_dict() for e in self.edits],
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ChangePlan":
        if not isinstance(raw, dict):
            raise SidekickError(
                errors.PROVIDER_OUTPUT_INVALID,
                "The provider returned a change plan that is not a JSON object.",
            )
        edits_raw = raw.get("edits")
        if edits_raw is None:
            edits_raw = []
        if not isinstance(edits_raw, list):
            raise SidekickError(
                errors.PROVIDER_OUTPUT_INVALID,
                "The provider returned a change plan whose 'edits' is not a list.",
            )
        return cls(
            edits=[FileEdit.from_dict(e) for e in edits_raw],
            summary=str(raw.get("summary", "")),
            provider=str(raw.get("provider", "")),
            model=str(raw.get("model", "")),
        )


@dataclass
class CodingRequest:
    """What the provider is asked to do."""

    task: str
    workspace: str
    context_files: Dict[str, str] = field(default_factory=dict)
    test_command: Optional[List[str]] = None
    constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "workspace": self.workspace,
            "context_files": sorted(self.context_files),
            "test_command": list(self.test_command) if self.test_command else None,
            "constraints": list(self.constraints),
        }


@dataclass
class ProviderStatus:
    """Whether a provider can actually be used right now, and why."""

    available: bool
    level: str = ClaimLevel.UNAVAILABLE
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "level": self.level,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


@dataclass
class ProviderResult:
    """The outcome of asking a provider for a change plan."""

    plan: Optional[ChangePlan]
    status: ProviderStatus
    error: Optional[SidekickError] = None
    latency_ms: int = 0
    raw_output: str = ""

    @property
    def ok(self) -> bool:
        return self.plan is not None and self.error is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
            "error": self.error.to_dict() if self.error else None,
            "latency_ms": self.latency_ms,
        }


class CodingProvider(abc.ABC):
    """Base class for coding providers."""

    #: Stable provider identifier reported in action results.
    name: str = "provider"

    #: Truth level. Subclasses must set this honestly.
    level: str = ClaimLevel.UNAVAILABLE

    @abc.abstractmethod
    def status(self) -> ProviderStatus:
        """Report whether this provider can be used right now."""

    @abc.abstractmethod
    def plan(self, request: CodingRequest) -> ProviderResult:
        """Produce a change plan for ``request``."""

    def required_executables(self) -> List[str]:
        """Executables this provider needs on the sandbox allowlist."""
        return []

    def secret_values(self) -> List[str]:
        """Values that must be masked in captured output."""
        return []
