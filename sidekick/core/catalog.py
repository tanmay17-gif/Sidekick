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
#: The part of the text that says *when* something should happen.
CAPTURE_WHEN = "when"
#: The text without the part that says *when*.
CAPTURE_EXCEPT_WHEN = "except_when"


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
    #: Whether the value may be carried over from the previous turn of the
    #: same session. A time like "6 pm" must not be: the user did not say it
    #: again.
    remember: bool = True

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
            "remember": self.remember,
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
    #: How a destination is spelled when it is spoken, e.g. "youtube" -> "YouTube".
    destination_labels: dict[str, str] = field(default_factory=dict)
    #: A short spoken line for the voice interface, e.g. ``"Opening {destination}."``.
    #: Placeholders are filled from the action's arguments; a placeholder
    #: without a value is dropped.
    speech_template: str | None = None
    #: A short human name for the capability inventory, e.g. "open a service".
    label: str | None = None
    #: Who owns the capability: "core" or the team that implemented it.
    owner: str = "core"
    #: Where the work happens: "server" (an adapter) or "client" (the browser).
    execution_target: str = "server"
    #: A longer explanation shown when the user asks what the product can do.
    detail: str | None = None

    @property
    def human_label(self) -> str:
        """A short name a person can read."""
        if self.label:
            return self.label
        return self.name.split(".")[-1].replace("_", " ")

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
            "destination_labels": dict(self.destination_labels),
            "speech_template": self.speech_template,
            "label": self.human_label,
            "owner": self.owner,
            "execution_target": self.execution_target,
            "detail": self.detail or self.description,
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

        The match is catalog driven: an alias matches when its *content words*
        appear in the utterance, allowing a filler word in between. The score
        grows with the number of content words, so a specific alias beats a
        generic one.

        That is what keeps "show me my notes" away from the generic
        "show me" of a browser launcher, and what makes "list my timers"
        match the alias "list timers".

        Ties are broken by the tool name, so the result does not depend on the
        order the adapters happened to be registered in.
        """
        tokens = tokenize(text)
        if not tokens:
            return None, 0.0
        best: tuple[str, float] | None = None
        for spec in self.tools.values():
            score = 0.0
            for alias in spec.aliases:
                matched = _alias_score(tokens, alias)
                if matched > score:
                    score = matched
            if score <= 0:
                continue
            if best is None or score > best[1] or (score == best[1] and spec.name < best[0]):
                best = (spec.name, score)
        return (best[0], best[1]) if best else (None, 0.0)

    def tool_support(self, text: str, tool: str) -> float:
        """How much the utterance supports a *particular* tool.

        Zero means the utterance does not mention the tool at all. The
        decision model is only allowed to pick a tool the utterance supports,
        so this is the check that stops the model from answering "order
        dinner for me" with a note reader.
        """
        spec = self.tools.get(tool)
        if spec is None:
            return 0.0
        tokens = tokenize(text)
        if not tokens:
            return 0.0
        best = 0.0
        for alias in spec.aliases:
            score = _alias_score(tokens, alias)
            if score > best:
                best = score
        return best

    def fuzzy_destination(self, text: str) -> str | None:
        """A destination the user almost typed ("open spotfy" -> spotify).

        Only a single typo in a single word counts, and only when the match
        is unambiguous. A wrong destination is worse than none.

        Short words are excluded: "at" is one edit away from "yt", but that
        is not a typo, it is a different word.
        """
        tokens = tokenize(text)
        if not tokens:
            return None
        candidates: list[str] = []
        for spec in self.tools.values():
            for destination in spec.destinations:
                if destination in tokens:
                    continue
                for alias in (destination, *spec.destination_aliases.get(destination, ())):
                    alias_words = alias.lower().split()
                    if len(alias_words) != 1:
                        continue
                    if len(alias_words[0]) < MIN_TYPO_LENGTH:
                        continue
                    for token in tokens:
                        if len(token) < MIN_TYPO_LENGTH:
                            continue
                        if _edit_distance(token, alias_words[0]) == 1:
                            candidates.append(destination)
                            break
        unique = sorted(set(candidates))
        return unique[0] if len(unique) == 1 else None

    def destination_owners(self, destination: str) -> list[str]:
        """The capabilities that declare a destination."""
        return [
            spec.name
            for spec in self.tools.values()
            if destination in spec.destinations
        ]

    def near_misses(self, text: str) -> list[tuple[str, str]]:
        """Capabilities the utterance almost named.

        An alias is a near miss when it has at least two content words and
        exactly one of them is missing from the utterance.

        This is deliberately narrow. It is only used where the *missing*
        word is a name the catalog already knows (a service), because a loose
        comparison cannot tell "find a restaurant" from "find a movie" - a
        suggestion that is wrong is worse than no suggestion.
        """
        tokens = tokenize(text)
        if not tokens:
            return []
        found: list[tuple[str, str, int]] = []
        for spec in self.tools.values():
            best: tuple[str, int] | None = None
            for alias in spec.aliases:
                words = content_words(alias)
                if len(words) < 2:
                    continue
                missing = [word for word in words if word not in tokens]
                if len(missing) != 1:
                    continue
                matched = len(words) - 1
                if best is None or matched > best[1]:
                    best = (alias, matched)
            if best is not None:
                found.append((spec.name, best[0], best[1]))
        found.sort(key=lambda item: (-item[2], item[0]))
        return [(name, alias) for name, alias, _ in found]

    def match_destination(self, text: str) -> tuple[str | None, float]:
        """Best (destination, score) match across the catalog destinations.

        A single typo counts ("open spotfy"), as long as the match is
        unambiguous.
        """
        tokens = tokenize(text)
        best: tuple[str, float] | None = None
        for spec in self.tools.values():
            for dest in spec.destinations:
                aliases = (dest, *spec.destination_aliases.get(dest, ()))
                for alias in aliases:
                    score = _alias_score(tokens, alias, base=0.75, per_word=0.1)
                    if score <= 0:
                        continue
                    if best is None or score > best[1]:
                        best = (dest, score)
        if best is not None:
            return best
        fuzzy = self.fuzzy_destination(text)
        return (fuzzy, 0.7) if fuzzy else (None, 0.0)

    def capability_summary(self) -> list[dict[str, Any]]:
        """A human readable inventory of everything the catalog can do."""
        summary: list[dict[str, Any]] = []
        for spec in self.tools.values():
            summary.append(
                {
                    "id": spec.name,
                    "label": spec.human_label,
                    "detail": spec.detail or spec.description,
                    "owner": spec.owner,
                    "execution_target": spec.execution_target,
                    "risk": spec.risk.value,
                    "requires_approval": spec.requires_approval,
                }
            )
        return summary


#: Words that carry no meaning in an alias or an utterance.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "my",
        "your",
        "our",
        "some",
        "of",
        "for",
        "to",
        "please",
        "can",
        "you",
        "i",
        "me",
        "it",
        "that",
        "this",
        "and",
        "then",
        "now",
        "just",
    }
)


#: A typo is only recognised in words of at least this length.
MIN_TYPO_LENGTH = 4


def _edit_distance(left: str, right: str) -> int:
    """The Levenshtein distance of two short words."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _singular(word: str) -> str:
    """A light stem, so "test" matches "tests" and "song" matches "songs"."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """The content words of a text, in order."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [_singular(word) for word in words if word not in _STOPWORDS]


def content_words(text: str) -> list[str]:
    """The words of a text that carry meaning."""
    return [
        _singular(word)
        for word in re.findall(r"[a-z0-9']+", text.lower())
        if word not in _STOPWORDS
    ]


def _alias_score(
    tokens: list[str],
    alias: str,
    base: float = 0.55,
    per_word: float = 0.1,
) -> float:
    """How well an alias matches a token list.

    The alias matches when all of its content words appear in the utterance,
    in order, with at most one filler word in between. The score grows with
    the number of content words, so a specific alias beats a generic one.
    """
    alias_tokens = content_words(alias)
    if not alias_tokens:
        return 0.0

    if len(alias_tokens) == 1:
        if alias_tokens[0] not in tokens:
            return 0.0
        return base

    positions: list[int] = []
    cursor = 0
    for word in alias_tokens:
        try:
            index = tokens.index(word, cursor)
        except ValueError:
            return 0.0
        positions.append(index)
        cursor = index + 1

    # The words must be close together: at most one filler word between them.
    span = positions[-1] - positions[0] + 1
    if span > len(alias_tokens) + 1:
        return 0.0
    return base + per_word * (len(alias_tokens) - 1)


def contains_phrase(haystack: str, needle: str) -> bool:
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
