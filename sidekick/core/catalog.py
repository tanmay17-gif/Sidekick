"""Capability catalog.

The catalog is the single description of what Sidekick can do. It is *data*,
not code, and it is the shared vocabulary between:

- the real decision model (the choice space of a Laya question is generated
  from the catalog),
- the deterministic fallback (aliases are matched against the utterance),
- the safety policy (risk, approval and argument rules live here),
- the UI (Agent 3 renders the catalog, so it can never offer a capability the
  backend does not actually have).

Adding a capability to the catalog is therefore enough to make it
recognisable; no keyword list is hard coded inside the brain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .schemas import RiskLevel

# Argument value kinds understood by the core.
ARG_STRING = "string"
ARG_INTEGER = "integer"
ARG_BOOLEAN = "boolean"
ARG_ENUM = "enum"
ARG_DURATION = "duration"

# How a text argument takes its value out of the utterance.
CAPTURE_NONE = "none"
CAPTURE_QUOTED = "quoted"
CAPTURE_REMAINDER = "remainder"
CAPTURE_AUTO = "auto"


@dataclass(frozen=True)
class ArgumentSpec:
    """Description of one tool argument.

    ``aliases`` lists alternative names used when the same value can be given
    under a different key (used for argument *binding*, e.g. ``{"minutes": 5}``
    also satisfies ``{"duration_seconds": 300}`` when the tool declares it).

    ``capture`` says where a text value comes from:

    - ``quoted`` - only an explicitly quoted or named value is accepted,
    - ``remainder`` - the text that follows the tool alias,
    - ``auto`` - quoted when available, otherwise the remainder,
    - ``none`` - the value is only ever supplied by the caller.
    """

    name: str
    type: str = ARG_STRING
    required: bool = False
    description: str = ""
    enum: tuple[str, ...] = ()
    default: Any = None
    aliases: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    capture: str = CAPTURE_AUTO

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
            "enum": list(self.enum),
            "default": self.default,
            "aliases": list(self.aliases),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "capture": self.capture,
        }


@dataclass(frozen=True)
class ToolSpec:
    """Description of one capability exposed by the execution layer."""

    name: str
    description: str
    aliases: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    reversible: bool = True
    cancellable: bool = True
    arguments: tuple[ArgumentSpec, ...] = ()
    result_fields: tuple[str, ...] = ()
    # Free-form destination values this tool understands ("spotify", "youtube").
    destinations: tuple[str, ...] = ()
    # Destinations are matched against the utterance to resolve a target.
    destination_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def argument(self, name: str) -> ArgumentSpec | None:
        for spec in self.arguments:
            if spec.name == name or name in spec.aliases:
                return spec
        return None

    def required_arguments(self) -> list[ArgumentSpec]:
        return [a for a in self.arguments if a.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "aliases": list(self.aliases),
            "risk": self.risk.value,
            "requires_approval": self.requires_approval,
            "reversible": self.reversible,
            "cancellable": self.cancellable,
            "arguments": [a.to_dict() for a in self.arguments],
            "result_fields": list(self.result_fields),
            "destinations": list(self.destinations),
        }


@dataclass
class CapabilityCatalog:
    """The set of capabilities the engine may plan."""

    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def add(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self.tools:
            raise ValueError(f"duplicate tool spec: {spec.name}")
        self.tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self.tools.get(name)
        if spec is None:
            raise KeyError(f"unknown tool: {name}")
        return spec

    def __contains__(self, name: object) -> bool:
        return name in self.tools

    def __iter__(self):
        return iter(self.tools.values())

    def __len__(self) -> int:
        return len(self.tools)

    # -- destinations -----------------------------------------------------

    def all_destinations(self) -> dict[str, str]:
        """Map ``destination -> tool name`` across every tool."""
        mapping: dict[str, str] = {}
        for spec in self.tools.values():
            for dest in spec.destinations:
                mapping.setdefault(dest, spec.name)
        return mapping

    def destination_aliases(self) -> dict[str, tuple[str, ...]]:
        """All destination aliases across tools, merged."""
        merged: dict[str, list[str]] = {}
        for spec in self.tools.values():
            for dest, aliases in spec.destination_aliases.items():
                merged.setdefault(dest, []).extend(aliases)
        return {k: tuple(dict.fromkeys(v)) for k, v in merged.items()}

    def destinations_for(self, tool: str) -> tuple[str, ...]:
        spec = self.tools.get(tool)
        return spec.destinations if spec else ()

    # -- matching ---------------------------------------------------------

    def match_tool(self, text: str) -> tuple[str | None, float]:
        """Best (tool, score) match for a piece of text.

        The match is catalog driven: an alias counts when it appears as a whole
        word (or a whole phrase) in the text. Longer aliases win over shorter
        ones so that ``"open spotify"`` beats ``"open"``.
        """
        lowered = text.lower()
        best_name: str | None = None
        best_score = 0.0
        for spec in self.tools.values():
            score = 0.0
            for alias in spec.aliases:
                if _contains_phrase(lowered, alias):
                    weight = 0.55 + min(0.4, 0.05 * len(alias.split()))
                    score = max(score, weight)
            if score > best_score:
                best_name, best_score = spec.name, score
        return best_name, best_score

    def match_destination(self, text: str) -> tuple[str | None, float]:
        """Best (destination, score) match across the catalog destinations."""
        lowered = text.lower()
        best_dest: str | None = None
        best_score = 0.0
        for spec in self.tools.values():
            for dest in spec.destinations:
                aliases = (dest, *spec.destination_aliases.get(dest, ()))
                for alias in aliases:
                    if _contains_phrase(lowered, alias):
                        score = 0.6 + min(0.35, 0.05 * len(alias.split()))
                        if score > best_score:
                            best_dest, best_score = dest, score
        return best_dest, best_score


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Whole-word/phrase containment test that tolerates simple punctuation."""
    if not needle:
        return False
    pattern = r"(?<!\w)" + re.escape(needle.strip().lower()) + r"(?!\w)"
    return re.search(pattern, haystack) is not None


def build_catalog(specs: Iterable[ToolSpec]) -> CapabilityCatalog:
    catalog = CapabilityCatalog()
    for spec in specs:
        catalog.add(spec)
    return catalog
