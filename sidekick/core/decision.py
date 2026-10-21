"""Decision model abstraction.

The core never talks to a model implementation directly. It talks to the
:class:`DecisionModel` protocol, which returns a :class:`Decision` plus a
truthful :class:`~sidekick.core.schemas.DecisionModelInfo` describing *what
actually ran*.

Two implementations ship with the project:

- :class:`sidekick.core.decisions.laya_model.LayaDecisionModel` - the real
  ``convaiinnovations/laya`` decision model (Apache-2.0, self hosted).
- :class:`sidekick.core.decisions.rule_model.RuleDecisionModel` - the
  deterministic fallback that keeps the product usable (and testable) without
  model weights.

The fallback is always reported as such. ``DecisionSource.MODEL`` is only
ever set when the real model produced the interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .catalog import CapabilityCatalog
from .schemas import Action, DecisionModelInfo, DecisionSource
from .sessions import SessionState


class ModelUnavailable(RuntimeError):
    """Raised when a decision model cannot be used (missing package, no weights)."""


class ModelTimeout(RuntimeError):
    """Raised when a decision model exceeded its time budget."""


class ModelInvalidOutput(RuntimeError):
    """Raised when a decision model returned something unusable."""


@dataclass
class DecisionQuery:
    """Everything a decision model is allowed to look at.

    Deliberately narrow: the model sees the utterance, the capability catalog
    and the *relevant* session context. It never sees secrets and it never
    executes anything.
    """

    utterance: str
    catalog: CapabilityCatalog
    session: SessionState
    pending_actions: list[Action] = field(default_factory=list)
    last_tool: str | None = None
    last_arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """Structured interpretation of one utterance segment."""

    tool: str | None = None
    tool_scores: dict[str, float] = field(default_factory=dict)
    destination: str | None = None
    destination_scores: dict[str, float] = field(default_factory=dict)
    #: Calibrated probability of the chosen destination (0..1).
    destination_confidence: float = 0.0
    is_correction: bool = False
    is_multi_action: bool = False
    confidence: float = 0.0
    source: DecisionSource = DecisionSource.RULE
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return bool(self.tool) and self.confidence > 0.0


@runtime_checkable
class DecisionModel(Protocol):
    """Protocol every decision model implements."""

    provider: str
    model: str

    @property
    def available(self) -> bool:
        """Whether the model can be used right now."""
        ...

    def decide(self, query: DecisionQuery) -> Decision:
        """Interpret one utterance segment."""
        ...

    def describe(self) -> DecisionModelInfo:
        """Truthful provenance of the last decision."""
        ...
