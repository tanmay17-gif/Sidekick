"""Deterministic text analysis.

Everything in this module is generic language handling, not a script of
recognised demo sentences. It provides:

- normalisation (case, punctuation, filler words),
- segmentation of multi-action utterances,
- detection of correction / continuation / control signals,
- extraction of common argument shapes (durations, counts, quoted or named
  text).

The catalog supplies the vocabulary (tool aliases, destination aliases); this
module supplies the grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

_FILLER_RE = re.compile(
    r"\b(?:please|kindly|could you|can you|would you|hey|ok|okay|so|um|uh|now)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s'\"\-]+")
_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, drop filler words and punctuation, collapse whitespace."""
    lowered = text.lower().strip()
    without_filler = _FILLER_RE.sub(" ", lowered)
    without_punct = _PUNCT_RE.sub(" ", without_filler)
    return _SPACE_RE.sub(" ", without_punct).strip()


# --------------------------------------------------------------------------
# Segmentation
# --------------------------------------------------------------------------

# Ordered from the strongest separator to the weakest. A single regex is used
# so that the *leftmost* separator wins and longer separators are preferred
# over the shorter ones they contain ("and then" before "then").
_SPLIT_RE = re.compile(
    r"\s*;\s*"
    r"|\s+and\s+then\s+"
    r"|\s+and\s+after\s+that\s+"
    r"|\s+after\s+that\s+"
    r"|\s+and\s+also\s+"
    r"|\s+then\s+"
    r"|\s+followed\s+by\s+"
    r"|\s+plus\s+"
    r"|\s*,\s+and\s+"
)

_MIN_SEGMENT_CHARS = 3


@dataclass
class Segment:
    """One independently resolvable part of an utterance."""

    text: str
    index: int
    is_correction: bool = False
    correction_of: int | None = None

    @property
    def normalized(self) -> str:
        return normalize(self.text)


def split_segments(text: str) -> list[Segment]:
    """Split a multi-action utterance into independently resolvable parts.

    The split is deliberately conservative: a separator only creates a new
    segment when the remainder still carries a recognisable amount of text.
    Segments are never dropped - if the utterance cannot be split safely the
    whole utterance stays a single segment.
    """
    working = text.strip()
    if not working:
        return []

    parts: list[str] = []
    for raw in _SPLIT_RE.split(working):
        part = raw.strip()
        if not part:
            continue
        if parts and len(part) < _MIN_SEGMENT_CHARS:
            # Too short to stand alone -> keep it attached to the previous.
            parts[-1] = f"{parts[-1]} {part}"
            continue
        parts.append(part)

    if not parts:
        return [Segment(text=working, index=0)]
    return [Segment(text=part, index=index) for index, part in enumerate(parts)]


# --------------------------------------------------------------------------
# Correction / continuation signals
# --------------------------------------------------------------------------

# Linguistic markers of a correction. These are general discourse markers,
# not recognised demo sentences.
_CORRECTION_MARKERS: tuple[str, ...] = (
    "no wait",
    "no no",
    "wait",
    "actually",
    "instead",
    "rather",
    "i meant",
    "i mean",
    "not that",
    "scratch that",
    "never mind",
    "nevermind",
    "forget that",
    "make it",
    "change it to",
    "switch to",
    "instead of",
)

# Markers that introduce a *replacement* rather than a modification.
_REPLACEMENT_MARKERS: tuple[str, ...] = (
    "no wait",
    "actually",
    "instead",
    "rather",
    "i meant",
    "i mean",
    "scratch that",
    "never mind",
    "nevermind",
    "forget that",
    "switch to",
    "instead of",
)

# Markers that on their own mean "drop what you were doing" and therefore act
# as a control rather than as a correction.
_BARE_MARKER_IS_CONTROL: frozenset[str] = frozenset(
    {"never mind", "nevermind", "forget that"}
)


@dataclass
class CorrectionSignal:
    """Detected correction inside one segment.

    ``preceding`` holds the instruction that is being corrected and
    ``residue`` holds the *new* instruction. Splitting the two is what makes
    "open YouTube - no wait, open Spotify" resolve to Spotify only.
    """

    is_correction: bool
    is_replacement: bool = False
    marker: str | None = None
    preceding: str = ""
    residue: str = ""

    @property
    def removes_previous(self) -> bool:
        return self.is_correction and self.is_replacement


def detect_correction(text: str) -> CorrectionSignal:
    """Detect a correction signal and split the text around the marker."""
    lowered = text.lower()
    for marker in _CORRECTION_MARKERS:
        idx = lowered.find(marker)
        if idx == -1:
            continue
        preceding = text[:idx].strip(" ,;:-.")
        residue = text[idx + len(marker) :].strip(" ,;:-")
        return CorrectionSignal(
            is_correction=True,
            is_replacement=marker in _REPLACEMENT_MARKERS,
            marker=marker,
            preceding=preceding,
            residue=residue,
        )
    return CorrectionSignal(is_correction=False, preceding="", residue=text.strip())


def bare_marker_is_control(text: str) -> bool:
    """Is the utterance only a correction marker that means "drop it"?"""
    signal = detect_correction(text)
    return signal.is_correction and not signal.residue and (
        signal.marker in _BARE_MARKER_IS_CONTROL
    )


_CONTINUATION_MARKERS: tuple[str, ...] = (
    "continue",
    "resume",
    "carry on",
    "keep going",
    "go on",
    "pick up where",
    "what was i doing",
    "what were we doing",
    "as before",
    "again",
)

_RESUME_MARKERS: tuple[str, ...] = (
    "continue",
    "resume",
    "carry on",
    "keep going",
    "go on",
    "pick up where",
)


def is_continuation(text: str) -> bool:
    """Does the utterance ask to continue previous work?"""
    lowered = normalize(text)
    return any(marker in lowered for marker in _CONTINUATION_MARKERS)


def is_resume_request(text: str) -> bool:
    lowered = normalize(text)
    return any(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", lowered) for marker in _RESUME_MARKERS)


# --------------------------------------------------------------------------
# Control intents
# --------------------------------------------------------------------------

CONTROL_INTENT_DESCRIPTIONS: dict[str, str] = {
    "control.cancel": "The user wants to cancel, stop or abort the pending or running action.",
    "control.pause": "The user wants to pause or suspend the current task.",
    "control.resume": "The user wants to continue or resume the previous or suspended task.",
    "control.switch": "The user wants to switch to a different task or action.",
    "control.status": "The user asks what is pending, running or queued.",
    "control.confirm": "The user approves a pending confirmation.",
    "control.reject": "The user refuses a pending confirmation.",
}

CONTROL_NAMES: tuple[str, ...] = tuple(CONTROL_INTENT_DESCRIPTIONS)

_CONTROL_PATTERNS: dict[str, re.Pattern[str]] = {
    "control.cancel": re.compile(
        r"(?<!\w)(?:cancel|stop|abort|kill|drop|halt)(?!\w)"
        r"|(?<!\w)never mind(?!\w)"
        r"|(?<!\w)forget it(?!\w)",
    ),
    "control.pause": re.compile(
        r"(?<!\w)(?:pause|suspend|hold on|freeze|hold)(?!\w)",
    ),
    "control.resume": re.compile(
        r"(?<!\w)(?:resume|unpause|continue)(?!\w)",
    ),
    "control.switch": re.compile(
        r"(?<!\w)(?:switch|change)(?!\w)"
    ),
    "control.status": re.compile(
        r"(?<!\w)(?:status|what(?:'s| is) (?:pending|queued|next|running)|"
        r"what do you have|list (?:my )?(?:tasks|actions)|show (?:my )?(?:tasks|actions))(?!\w)",
    ),
    "control.confirm": re.compile(
        r"(?<!\w)(?:yes|yeah|yep|confirm|do it|go ahead|proceed|approved|approve)(?!\w)",
    ),
    "control.reject": re.compile(
        r"(?<!\w)(?:no|nope|don'?t|do not|reject|deny)(?!\w)",
    ),
}


def match_control(text: str) -> tuple[str | None, float]:
    """Detect a control intent (cancel/pause/resume/...) in the text.

    Returns the control name and a rough confidence. Control verbs are core
    orchestration vocabulary, so they live here rather than in the catalog.
    """
    lowered = normalize(text)
    best: tuple[str | None, float] = (None, 0.0)
    for name, pattern in _CONTROL_PATTERNS.items():
        match = pattern.search(lowered)
        if not match:
            continue
        # Multi word markers are more specific than single words such as
        # "stop" or "no", so they score higher.
        score = 0.62 if len(match.group(0).split()) > 1 else 0.55
        if score > best[1]:
            best = (name, score)
    return best


def control_is_targeted_at_action(text: str) -> bool:
    """Does the control phrase refer to a concrete action (``that``/``it``)?"""
    lowered = normalize(text)
    return bool(re.search(r"(?<!\w)(?:that|it|the last one|previous|previous one)(?!\w)", lowered))


# --------------------------------------------------------------------------
# Argument extraction helpers
# --------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>hours?|hrs?|minutes?|mins?|seconds?|secs?|h|m|s)\b",
    re.IGNORECASE,
)

_UNIT_SECONDS = {"h": 3600, "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600}
_UNIT_MINUTES = {"m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60}
_UNIT_SECONDS_ONLY = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}


def parse_duration_seconds(text: str) -> int | None:
    """Parse a duration such as ``5 minutes`` / ``1h30m`` / ``90 seconds``.

    All matching components are summed, so ``1h30m`` becomes 5400.
    """
    total = 0.0
    found = False
    for match in _DURATION_RE.finditer(text):
        found = True
        unit = match.group("unit").lower()
        amount = float(match.group("amount"))
        if unit in _UNIT_SECONDS:
            total += amount * 3600
        elif unit in _UNIT_MINUTES:
            total += amount * 60
        elif unit in _UNIT_SECONDS_ONLY:
            total += amount
    if not found or total <= 0:
        return None
    return int(round(total))


_COUNT_RE = re.compile(
    r"(?P<count>\d+)\s*(?P<label>song(?:s)?|track(?:s)?|item(?:s)?|note(?:s)?|times?|minutes?)",
    re.IGNORECASE,
)


@dataclass
class ExtractedCount:
    count: int
    label: str


def parse_count(text: str) -> ExtractedCount | None:
    """Parse ``3 songs`` style quantities."""
    match = _COUNT_RE.search(text)
    if not match:
        return None
    label = match.group("label").lower()
    singular = label[:-1] if label.endswith("s") else label
    return ExtractedCount(count=int(match.group("count")), label=singular)


_QUOTED_RE = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{1,200})[\"'“”‘’]")
_NAMED_RE = re.compile(
    r"\b(?:named|called|titled|entitled)\s+(?:it\s+)?[\"'“”]?([^\"'“”]{1,120}?)[\"'“”]?(?:\s*$|[,.;])",
    re.IGNORECASE,
)


def parse_quoted_text(text: str) -> str | None:
    """Extract a quoted or explicitly named piece of text."""
    quoted = _QUOTED_RE.search(text)
    if quoted:
        value = quoted.group(1).strip()
        if value:
            return value
    named = _NAMED_RE.search(text)
    if named:
        value = named.group(1).strip()
        if value:
            return value
    return None


@dataclass
class ArgumentHints:
    """Generic argument hints extracted from a segment."""

    duration_seconds: int | None = None
    count: ExtractedCount | None = None
    text_value: str | None = None
    values: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "duration_seconds": self.duration_seconds,
            "count": self.count.count if self.count else None,
            "count_label": self.count.label if self.count else None,
            "text_value": self.text_value,
            **self.values,
        }


def extract_argument_hints(text: str) -> ArgumentHints:
    """Extract the argument shapes that are independent of any tool."""
    return ArgumentHints(
        duration_seconds=parse_duration_seconds(text),
        count=parse_count(text),
        text_value=parse_quoted_text(text),
    )


# Leading words that introduce the value of an argument.
_LEADING_FILLER_RE = re.compile(
    r"^(?:that\s+says|that\s+is|that|to|about|for|with|saying|which\s+says|:\s*|-\s*)",
    re.IGNORECASE,
)

_PURE_NUMBER_RE = re.compile(r"^[\d\s.:]+$")


def extract_remainder(text: str, aliases: "Iterable[str]") -> str | None:
    """Return the part of ``text`` that follows the first matching alias.

    This is how a free-text argument ("write a note that the milk is out")
    is captured without hard coding the sentence: the alias decides where
    the value starts.
    """
    lowered = text.lower()
    best_index: int | None = None
    best_alias = ""
    for alias in aliases:
        alias = alias.strip().lower()
        if not alias:
            continue
        match = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", lowered)
        if match is None:
            continue
        if best_index is None or match.start() < best_index:
            best_index = match.start()
            best_alias = alias
    if best_index is None:
        return None

    remainder = text[best_index + len(best_alias) :].strip()
    previous = None
    while previous != remainder:
        previous = remainder
        remainder = _LEADING_FILLER_RE.sub("", remainder).strip()
    if not remainder or _PURE_NUMBER_RE.match(remainder):
        return None
    if parse_duration_seconds(remainder) is not None and len(remainder) < 16:
        # "set a timer for 5 minutes" - the remainder is only a duration.
        return None
    return remainder


@dataclass
class ControlIntent:
    """A detected control verb (cancel / pause / resume / confirm / ...)."""

    name: str
    confidence: float = 0.0
    target: str | None = None
