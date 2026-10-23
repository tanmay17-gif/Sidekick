"""Local, real execution adapters.

These adapters perform actual work on the machine:

- :class:`NoteWriteTool` / :class:`NoteReadTool` - read and write real files
  inside the workspace directory;
- :class:`TimerSetTool` - schedules a real timer in the background and reports
  the outcome when it fires, so the action lifecycle is genuinely asynchronous;
- :class:`MediaOpenTool` - opens a real URL with the system browser.

They are deliberately dependency free so the product works offline and the
test suite stays fast.
"""

from __future__ import annotations

import os
import re
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from ..core.catalog import (
    ARG_DURATION,
    ARG_ENUM,
    ARG_STRING,
    CAPTURE_EXCEPT_WHEN,
    CAPTURE_QUOTED,
    CAPTURE_WHEN,
    ArgumentSpec,
    ToolSpec,
)
from ..core.parsing import format_when, parse_when
from ..core.registry import ToolContext, ToolResult
from ..core.schemas import Action, ActionError, RiskLevel

DEFAULT_WORKSPACE = Path(
    os.environ.get("SIDEKICK_WORKSPACE", Path.cwd() / "sidekick_runtime")
).resolve()

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 _.-]+")


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------


class _NoteToolBase:
    def __init__(self, workspace: Path | str | None = None) -> None:
        self.workspace = Path(workspace or DEFAULT_WORKSPACE).resolve()
        self.notes_dir = self.workspace / "notes"

    def _target_path(self, title: str | None) -> Path:
        name = (title or "note").strip() or "note"
        name = _SAFE_NAME_RE.sub("", name).strip() or "note"
        return self.notes_dir / f"{name}.txt"


class NoteWriteTool(_NoteToolBase):
    """Writes a note into the workspace (a real file on disk)."""

    spec = ToolSpec(
        name="note.write",
        description="Write a note for the user so it can be read back later",
        label="write a note",
        detail="Saves a real note that can be read back later.",
        aliases=("write a note", "take a note", "note this down", "save a note", "remember this"),
        risk=RiskLevel.LOW,
        requires_approval=False,
        reversible=True,
        cancellable=False,
        arguments=(
            ArgumentSpec(
                name="content",
                type=ARG_STRING,
                required=True,
                description="the text of the note",
                aliases=("text", "body", "note"),
            ),
            ArgumentSpec(
                name="title",
                type=ARG_STRING,
                required=False,
                description="a short title for the note",
                aliases=("name",),
                capture=CAPTURE_QUOTED,
            ),
        ),
        result_fields=("path", "bytes", "title"),
        speech_template="Saving your note.",
    )

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        content = arguments.get("content")
        if not isinstance(content, str) or not content.strip():
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="empty_note",
                    message="the note needs some content",
                ),
            )
        path = self._target_path(arguments.get("title"))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="note_write_failed",
                    message=f"could not write the note: {exc}",
                    retryable=True,
                ),
            )
        return ToolResult(
            ok=True,
            data={
                "path": str(path),
                "bytes": len(content.encode("utf-8")),
                "title": path.stem,
            },
        )

    def cancel(self, action_id: str) -> bool:
        return True


class NoteReadTool(_NoteToolBase):
    """Reads back the notes stored in the workspace."""

    spec = ToolSpec(
        name="note.read",
        description="Read notes the user asked to save earlier",
        label="read my notes",
        detail="Reads back the notes that were saved earlier.",
        aliases=("read my notes", "show my notes", "list notes", "open my notes"),
        risk=RiskLevel.LOW,
        requires_approval=False,
        reversible=True,
        cancellable=False,
        arguments=(
            ArgumentSpec(
                name="title",
                type=ARG_STRING,
                required=False,
                description="the title of a single note to read",
                aliases=("name",),
            ),
        ),
        result_fields=("notes",),
        speech_template="Reading your notes.",
    )

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        title = arguments.get("title")
        try:
            if title:
                path = self._target_path(title)
                if not path.exists():
                    return ToolResult(
                        ok=False,
                        error=ActionError(
                            code="note_not_found",
                            message=f"there is no note called '{title}'",
                        ),
                    )
                paths = [path]
            else:
                if not self.notes_dir.exists():
                    return ToolResult(ok=True, data={"notes": []})
                paths = sorted(self.notes_dir.glob("*.txt"))
        except OSError as exc:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="note_read_failed",
                    message=f"could not read the notes: {exc}",
                    retryable=True,
                ),
            )

        notes = []
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            notes.append({"title": path.stem, "path": str(path), "content": text})
        return ToolResult(ok=True, data={"notes": notes})

    def cancel(self, action_id: str) -> bool:
        return True


# --------------------------------------------------------------------------
# Timers
# --------------------------------------------------------------------------


@dataclass
class _TimerState:
    timer_id: str
    due_at: datetime
    duration_seconds: int
    label: str = ""
    fired: bool = False
    cancelled: bool = False
    handle: threading.Timer | None = field(default=None, repr=False)


class TimerSetTool:
    """Schedules a real timer.

    The timer runs on a background thread. The action therefore stays
    ``running`` until the timer fires or is cancelled - this is what makes
    interruption and cancellation genuinely observable.
    """

    spec = ToolSpec(
        name="timer.set",
        description="Start a countdown timer that notifies the user when it is done",
        label="set a timer",
        detail="Starts a real countdown and reports it when it is done.",
        aliases=("set a timer", "start a timer", "remind me in", "countdown"),
        risk=RiskLevel.LOW,
        requires_approval=False,
        reversible=True,
        cancellable=True,
        arguments=(
            ArgumentSpec(
                name="duration_seconds",
                type=ARG_DURATION,
                required=True,
                description="how long the timer should run",
                aliases=("duration", "seconds"),
                minimum=1,
                maximum=60 * 60 * 24,
            ),
            ArgumentSpec(
                name="label",
                type=ARG_STRING,
                required=False,
                description="what the timer is for",
                aliases=("name", "message"),
                capture=CAPTURE_QUOTED,
            ),
        ),
        result_fields=("timer_id", "due_at", "duration_seconds"),
        speech_template="Setting a timer for {duration_seconds}.",
    )

    def __init__(self) -> None:
        self._timers: dict[str, _TimerState] = {}
        self._lock = threading.Lock()

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        duration = arguments.get("duration_seconds")
        if not isinstance(duration, (int, float)) or duration <= 0:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="invalid_duration",
                    message="the timer needs a positive duration",
                ),
            )

        due_at = datetime.now(timezone.utc) + timedelta(seconds=float(duration))
        state = _TimerState(
            timer_id=action.action_id,
            due_at=due_at,
            duration_seconds=int(duration),
            label=str(arguments.get("label") or ""),
        )

        def fire() -> None:
            with self._lock:
                if state.cancelled:
                    return
                state.fired = True
            context.complete(
                ToolResult(
                    ok=True,
                    data={
                        "timer_id": state.timer_id,
                        "fired": True,
                        "label": state.label,
                        "duration_seconds": state.duration_seconds,
                    },
                )
            )

        timer = threading.Timer(float(duration), fire)
        timer.daemon = True
        state.handle = timer
        with self._lock:
            self._timers[action.action_id] = state
        timer.start()

        return ToolResult(
            ok=True,
            ongoing=True,
            data={
                "timer_id": state.timer_id,
                "due_at": due_at.isoformat(),
                "duration_seconds": state.duration_seconds,
                "label": state.label,
            },
        )

    def cancel(self, action_id: str) -> bool:
        with self._lock:
            state = self._timers.get(action_id)
            if state is None or state.fired:
                return False
            state.cancelled = True
            if state.handle is not None:
                state.handle.cancel()
            return True

    def list_timers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "timer_id": s.timer_id,
                    "due_at": s.due_at.isoformat(),
                    "duration_seconds": s.duration_seconds,
                    "label": s.label,
                    "fired": s.fired,
                    "cancelled": s.cancelled,
                }
                for s in self._timers.values()
            ]


class TimerListTool:
    """Lists the timers that are currently scheduled."""

    spec = ToolSpec(
        name="timer.list",
        description="List the timers that are currently running",
        label="list my timers",
        detail="Lists the timers that are currently scheduled.",
        aliases=("list timers", "show my timers", "what timers do i have"),
        risk=RiskLevel.LOW,
        arguments=(),
        result_fields=("timers",),
        speech_template="Checking your timers.",
    )

    def __init__(self, timer_tool: TimerSetTool) -> None:
        self._timer_tool = timer_tool

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, data={"timers": self._timer_tool.list_timers()})

    def cancel(self, action_id: str) -> bool:
        return True


# --------------------------------------------------------------------------
# Media
# --------------------------------------------------------------------------

MEDIA_DESTINATIONS: dict[str, str] = {
    "spotify": "https://open.spotify.com",
    "youtube": "https://www.youtube.com",
    "netflix": "https://www.netflix.com",
    "apple_music": "https://music.apple.com",
    "twitch": "https://www.twitch.tv",
    "vlc": "https://www.videolan.org/vlc",
    "wikipedia": "https://www.wikipedia.org",
    "google": "https://www.google.com",
}

#: How each destination is spelled when it is spoken.
MEDIA_LABELS: dict[str, str] = {
    "spotify": "Spotify",
    "youtube": "YouTube",
    "netflix": "Netflix",
    "apple_music": "Apple Music",
    "twitch": "Twitch",
    "vlc": "VLC",
    "wikipedia": "Wikipedia",
    "google": "Google",
}


class WebSearchTool:
    """Searches the web by opening a real search URL in the browser.

    This is *not* a booking, a purchase or a content fetch - it is the real
    search results page for the user's query. When Agent 2's ``web.fetch``
    adapter is registered it is preferred, because it returns the content
    instead of a page to look at.
    """

    spec = ToolSpec(
        name="web.search",
        description="Search the web and show the real results",
        aliases=(
            "search",
            "search for",
            "search the web for",
            "look up",
            "google",
            "find out",
            "research",
            "browse for",
            "what is",
            "who is",
            # Flight / travel searches
            "find flight",
            "find flights",
            "find a flight",
            "book flight",
            "search for flight",
            "search flights",
            "flight from",
            "flights from",
            "cheap flights",
            "find me a flight",
        ),
        risk=RiskLevel.LOW,
        requires_approval=False,
        reversible=True,
        cancellable=False,
        label="search the web",
        speech_template="Searching for {query}.",
        detail=(
            "Opens the real search results page for a query. It does not read, "
            "summarise or verify the results - that needs a content fetch."
        ),
        arguments=(
            ArgumentSpec(
                name="query",
                type=ARG_STRING,
                required=True,
                description="what to search for",
                aliases=("for", "text", "search"),
            ),
            ArgumentSpec(
                name="engine",
                type=ARG_ENUM,
                required=False,
                description="which search engine to use",
                enum=("google", "bing", "duckduckgo"),
                default="google",
            ),
        ),
        result_fields=("query", "engine", "url", "opened"),
    )

    ENGINES: dict[str, str] = {
        "google": "https://www.google.com/search?q=",
        "bing": "https://www.bing.com/search?q=",
        "duckduckgo": "https://duckduckgo.com/?q=",
    }

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(
                ok=False,
                error=ActionError(code="missing_query", message="the search needs something to look for"),
            )
        engine = str(arguments.get("engine") or "google")
        prefix = self.ENGINES.get(engine, self.ENGINES["google"])
        url = prefix + quote_plus(query)
        try:
            opened = bool(webbrowser.open(url))
        except Exception as exc:  # noqa: BLE001 - the browser is optional
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="browser_unavailable",
                    message=f"could not open the browser: {exc}",
                    retryable=True,
                ),
            )
        if not opened:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="browser_unavailable",
                    message="no browser is available on this machine",
                    retryable=True,
                ),
            )
        return ToolResult(
            ok=True,
            data={
                "query": query,
                "engine": engine,
                "url": url,
                "opened": True,
                "kind": "search_results_page",
                "note": "the results page is open; the content was not read",
            },
        )

    def cancel(self, action_id: str) -> bool:
        return True


class ReminderSetTool:
    """Schedules a real reminder that fires at the requested local time.

    The reminder is a real scheduled task: a background timer waits for the
    moment and then completes the action, so the browser learns about it
    through the action's event stream.
    """

    spec = ToolSpec(
        name="reminder.set",
        description="Set a reminder for a specific time",
        aliases=("remind me", "set a reminder", "reminder", "remind"),
        risk=RiskLevel.LOW,
        requires_approval=False,
        reversible=True,
        cancellable=True,
        label="set a reminder",
        speech_template="Reminder set for {at}.",
        detail=(
            "Schedules a reminder in the running process. It fires while the "
            "process runs; it is not delivered after a restart."
        ),
        arguments=(
            ArgumentSpec(
                name="text",
                type=ARG_STRING,
                required=True,
                description="what to be reminded of",
                aliases=("message", "note", "reminder"),
                capture=CAPTURE_EXCEPT_WHEN,
            ),
            ArgumentSpec(
                name="at",
                type=ARG_STRING,
                required=True,
                description="when the reminder is due, e.g. '6 pm' or 'in 20 minutes'",
                aliases=("when", "time"),
                capture=CAPTURE_WHEN,
                remember=False,
            ),
        ),
        result_fields=("reminder", "due_at", "when"),
    )

    def __init__(self) -> None:
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text") or "").strip()
        when_text = str(arguments.get("at") or "").strip()
        if not text:
            return ToolResult(
                ok=False,
                error=ActionError(code="empty_reminder", message="the reminder needs something to say"),
            )
        due = parse_when(when_text)
        if due is None:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="unparseable_time",
                    message=f"could not work out when '{when_text}' is",
                ),
            )

        delay = max(1.0, (due - datetime.now().astimezone()).total_seconds())

        def fire() -> None:
            context.complete(
                ToolResult(
                    ok=True,
                    data={
                        "reminder": text,
                        "due_at": due.isoformat(),
                        "when": format_when(due),
                        "fired": True,
                        "delivery": "in-process; a restart loses the reminder",
                    },
                )
            )

        timer = threading.Timer(delay, fire)
        timer.daemon = True
        with self._lock:
            self._timers[action.action_id] = timer
        timer.start()

        return ToolResult(
            ok=True,
            ongoing=True,
            data={
                "reminder": text,
                "due_at": due.isoformat(),
                "when": format_when(due),
                "in_seconds": round(delay),
                "delivery": "in-process; a restart loses the reminder",
            },
        )

    def cancel(self, action_id: str) -> bool:
        with self._lock:
            timer = self._timers.pop(action_id, None)
        if timer is None:
            return False
        timer.cancel()
        return True


class MediaOpenTool:
    """Opens a real URL with the system browser."""

    spec = ToolSpec(
        name="media.open",
        description="Open a service or app in the browser",
        aliases=("open", "launch", "go to", "open up"),
        label="open a service",
        speech_template="Opening {destination}.",
        detail="Opens the real service in the browser.",
        risk=RiskLevel.LOW,
        requires_approval=False,
        reversible=True,
        cancellable=False,
        destinations=tuple(MEDIA_DESTINATIONS),
        destination_aliases={
            "spotify": ("spotify",),
            "youtube": ("youtube", "yt", "you tube"),
            "netflix": ("netflix",),
            "apple_music": ("apple music", "itunes"),
            "twitch": ("twitch",),
            "vlc": ("vlc",),
            "wikipedia": ("wikipedia",),
            "google": ("google",),
        },
        destination_labels=MEDIA_LABELS,
        arguments=(
            ArgumentSpec(
                name="destination",
                type=ARG_ENUM,
                required=True,
                description="which service to open",
                enum=tuple(MEDIA_DESTINATIONS),
            ),
        ),
        result_fields=("destination", "url", "opened"),
    )

    @staticmethod
    def resolve_url(destination: str) -> str | None:
        """Pure helper: the URL a destination maps to."""
        return MEDIA_DESTINATIONS.get(destination)

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        destination = arguments.get("destination")
        url = self.resolve_url(str(destination))
        if url is None:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="unknown_destination",
                    message=f"'{destination}' is not a known destination",
                ),
            )
        try:
            opened = bool(webbrowser.open(url))
        except Exception as exc:  # noqa: BLE001 - the browser is optional
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="browser_unavailable",
                    message=f"could not open the browser: {exc}",
                    retryable=True,
                ),
            )
        if not opened:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="browser_unavailable",
                    message="no browser is available on this machine",
                    retryable=True,
                ),
            )
        return ToolResult(ok=True, data={"destination": destination, "url": url, "opened": True})

    def cancel(self, action_id: str) -> bool:
        return True


def default_tool_specs() -> list[ToolSpec]:
    """The specs of every tool the core ships with."""
    return [
        MediaOpenTool.spec,
        NoteWriteTool.spec,
        NoteReadTool.spec,
        TimerSetTool.spec,
        TimerListTool.spec,
    ]
