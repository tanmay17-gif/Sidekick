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
from datetime import datetime, timedelta
from typing import Iterable

from .catalog import content_words, tokenize

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
    # A full stop followed by a space is a sentence boundary. A full stop in
    # the middle of a number ("5.5 minutes") is not, because it is not
    # followed by whitespace.
    r"|\.\s+"
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

    ``is_trailing`` marks the case where the marker ends the sentence
    ("echo hello instead"): the new instruction is what came *before* the
    marker and the correction refers to the previous request, not to another
    part of this turn.
    """

    is_correction: bool
    is_replacement: bool = False
    marker: str | None = None
    preceding: str = ""
    residue: str = ""
    is_trailing: bool = False

    @property
    def removes_previous(self) -> bool:
        return self.is_correction and self.is_replacement


def detect_correction(text: str) -> CorrectionSignal:
    """Detect a correction signal and split the text around the marker.

    The marker is usually in the middle ("open YouTube, no wait, open
    Spotify"): the part before it is superseded, the part after it is the new
    instruction. A trailing marker ("echo hello instead") is handled too: the
    instruction is what comes before it.
    """
    lowered = text.lower()
    for marker in _CORRECTION_MARKERS:
        idx = lowered.find(marker)
        if idx == -1:
            continue
        preceding = text[:idx].strip(" ,;:-.")
        residue = text[idx + len(marker) :].strip(" ,;:-")
        trailing = False
        if not residue and preceding:
            # A trailing marker: the instruction is the part before it.
            residue, preceding = preceding, ""
            trailing = True
        return CorrectionSignal(
            is_correction=True,
            is_replacement=marker in _REPLACEMENT_MARKERS,
            marker=marker,
            preceding=preceding,
            residue=residue,
            is_trailing=trailing,
        )
    return CorrectionSignal(is_correction=False, preceding="", residue=text.strip())


def bare_marker_is_control(text: str) -> bool:
    """Is the utterance only a correction marker that means "drop it"?"""
    signal = detect_correction(text)
    return signal.is_correction and not signal.residue and (
        signal.marker in _BARE_MARKER_IS_CONTROL
    )


#: "What can you actually do?" - a question about the product, not a task.
_CAPABILITY_QUESTION_RE = re.compile(
    r"\bwhat\s+(?:can|could|will)\s+you\s+(?:actually\s+|else\s+|really\s+)?do\b"
    r"|\bwhat\s+are\s+you\s+(?:capable|able)\s+(?:of|to do)\b"
    r"|\bwhat\s+do\s+you\s+do\b"
    r"|\b(?:list|show|tell)\s+(?:me\s+)?(?:about\s+)?(?:your\s+)?"
    r"(?:capabilities|abilities|features|skills|tools)\b"
    r"|\bwhat\s+can\s+you\s+help\s+me\s+with\b"
    r"|\bhelp\s+me\s+use\s+you\b",
    re.IGNORECASE,
)


def is_capability_question(text: str) -> bool:
    """Is the user asking what the product can do?"""
    return bool(_CAPABILITY_QUESTION_RE.search(text))


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
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "my", "your", "our", "some", "of", "for", "to",
        "please", "can", "you", "i", "me", "it", "that", "this", "and",
        "then", "now", "just",
    }
)

_LEADING_FILLER_RE = re.compile(
    r"^(?:that\s+says|that\s+is|that|to|about|for|with|saying|which\s+says|:\s*|-\s*)",
    re.IGNORECASE,
)

_PURE_NUMBER_RE = re.compile(r"^[\d\s.:]+$")


def extract_remainder(text: str, aliases: "Iterable[str]") -> str | None:
    """Return the part of ``text`` that follows the matching alias.

    This is how a free-text argument ("write a note that the milk is out")
    is captured without hard coding the sentence: the alias decides where
    the value starts.

    The alias does not have to appear word for word. "can you write me a
    note about the release" contains the alias "write a note" only in its
    content words, and the value still starts after it.
    """
    lowered = text.lower()
    best_index: int | None = None
    best_alias = ""
    best_length = 0
    for alias in aliases:
        alias = alias.strip().lower()
        if not alias:
            continue
        match = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", lowered)
        if match is None:
            continue
        # The longest alias wins, so "search for" beats "search" and the
        # remainder does not swallow the alias.
        length = len(alias)
        if best_index is None or length > best_length or (
            length == best_length and match.start() < best_index
        ):
            best_index = match.start()
            best_alias = alias
            best_length = length
    if best_index is None:
        # The alias only appears in its content words.
        end_of_alias = _alias_content_end(text, aliases)
        if end_of_alias is None:
            return None
        best_index = end_of_alias
        best_alias = ""

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


def _alias_content_end(text: str, aliases: "Iterable[str]") -> int | None:
    """Where the alias ends, when only its content words appear.

    "can you write me a note about x" contains "write a note" in its content
    words; the value starts after the last of them. The most specific alias
    (the one with the most content words) wins.
    """
    tokens = tokenize(text)
    if not tokens:
        return None
    best: tuple[int, int] | None = None  # (number of words, end offset)
    for alias in aliases:
        words = content_words(alias)
        if len(words) < 2:
            continue
        positions: list[int] = []
        cursor = 0
        for word in words:
            try:
                index = tokens.index(word, cursor)
            except ValueError:
                positions = []
                break
            positions.append(index)
            cursor = index + 1
        if len(positions) < 2:
            continue
        span = _word_span(text, positions[-1])
        if span is None:
            continue
        if best is None or len(positions) > best[0]:
            best = (len(positions), span[1])
    return best[1] if best else None


def _word_span(text: str, token_index: int) -> tuple[int, int] | None:
    """The character span of the n-th content word in the original text.

    The span is taken from the original word, not from the token: the token
    is stemmed ("notes" -> "note"), so its length is not the word's length.
    """
    seen = 0
    for match in re.finditer(r"[A-Za-z0-9']+", text):
        if match.group(0).lower() in _STOPWORDS:
            continue
        if seen == token_index:
            return match.start(), match.end()
        seen += 1
    return None


@dataclass
class ControlIntent:
    """A detected control verb (cancel / pause / resume / confirm / ...)."""

    name: str
    confidence: float = 0.0
    target: str | None = None


# --------------------------------------------------------------------------
# When
# --------------------------------------------------------------------------

_CLOCK_RE = re.compile(
    r"(?<![\d:])(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?(?![\d:])",
    re.IGNORECASE,
)
_RELATIVE_RE = re.compile(
    r"\bin\s+(?P<amount>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?|seconds?|secs?)\b",
    re.IGNORECASE,
)
_DAY_WORDS = {
    "today": 0,
    "tonight": 0,
    "tomorrow": 1,
    "tomorrow morning": 1,
    "tomorrow afternoon": 1,
    "tomorrow evening": 1,
    "tomorrow night": 1,
    "morning": 0,
    "afternoon": 0,
    "evening": 0,
    "night": 0,
}


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    """Parse the moment a reminder is meant for.

    Supported forms:

    - a relative one: "in 20 minutes", "in 2 hours"
    - a clock time: "at 6 pm", "at 6:30", "at 18:00"
    - a clock time with a day: "tomorrow at 9", "tonight at 8"

    A bare hour without am/pm is read the way people usually mean it: 1-6 is
    in the afternoon, 7-11 in the morning. The resolved time is always spoken
    back, so the assumption is visible and can be corrected.
    """
    moment = now or datetime.now().astimezone()
    lowered = text.lower()

    relative = _RELATIVE_RE.search(lowered)
    if relative:
        amount = int(relative.group("amount"))
        unit = relative.group("unit").lower()
        seconds = amount * 3600 if unit.startswith(("hour", "hr")) else (
            amount * 60 if unit.startswith(("min",)) else amount
        )
        return moment + timedelta(seconds=seconds)

    day_offset: int | None = None
    evening = False
    for word, offset in _DAY_WORDS.items():
        if word in lowered:
            day_offset = offset
            if word in ("tonight", "evening", "night", "afternoon"):
                evening = True
            break

    clock = _CLOCK_RE.search(lowered)
    if clock is None:
        if day_offset is not None:
            target = (moment + timedelta(days=day_offset)).replace(
                hour=9 if "morning" in lowered else 20,
                minute=0,
                second=0,
                microsecond=0,
            )
            return target
        return None

    hour = int(clock.group("hour"))
    minute = int(clock.group("minute") or 0)
    meridiem = (clock.group("meridiem") or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    elif not meridiem:
        if evening and hour < 12:
            hour += 12
        elif 1 <= hour <= 6:
            hour += 12
    if hour > 23 or minute > 59:
        return None

    target = (moment + timedelta(days=day_offset or 0)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if day_offset is None and target <= moment:
        # The time has passed today, so it means the next one.
        target += timedelta(days=1)
    return target


def format_when(moment: datetime) -> str:
    """A spoken time: '6:30 PM'."""
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


_WHEN_EXPR_RE = re.compile(
    r"\bin\s+\d+\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?)\b"
    r"|\b(?:today|tonight|tomorrow|morning|afternoon|evening|night)\b(?:\s+\w+)?"
    r"(?:\s+at)?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
    r"|\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
    r"|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    re.IGNORECASE,
)


def find_when_expression(text: str) -> str | None:
    """The part of a text that says *when* something should happen."""
    match = _WHEN_EXPR_RE.search(text)
    return match.group(0).strip() if match else None
