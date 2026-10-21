"""Session scoped state.

Requirements implemented here:

- **Isolation** - every piece of conversational state lives under an explicit
  ``session_id``. Two concurrent sessions never see each other's tasks,
  pending actions or entities. There is no global singleton.
- **Bounded retention** - per session limits on stored actions, tasks and
  cached responses; a global limit on the number of live sessions (LRU
  eviction of the least recently used session).
- **Thread safety** - a re-entrant lock guards the store.
- **Expiry** - idle sessions are dropped after ``ttl_seconds``.

Actions are stored exactly once (in ``SessionState.actions``); tasks reference
them by id. That keeps a single source of truth for the action lifecycle.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .schemas import Action, ActionStatus, Entity, Event, SidekickResponse, utcnow

DEFAULT_TTL_SECONDS = 60 * 60  # one hour of inactivity
DEFAULT_MAX_SESSIONS = 500
DEFAULT_MAX_ACTIONS_PER_SESSION = 200
DEFAULT_MAX_TASKS_PER_SESSION = 50
DEFAULT_MAX_CACHED_RESPONSES = 50


@dataclass
class TaskState:
    """One user-visible unit of work (usually one tool invocation)."""

    task_id: str
    tool: str
    description: str = ""
    action_ids: list[str] = field(default_factory=list)
    state: ActionStatus = ActionStatus.PENDING
    resumable: bool = True
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def touch(self) -> None:
        self.updated_at = utcnow()


@dataclass
class TurnRecord:
    """Minimal transcript entry, kept for context and debugging."""

    request_id: str
    utterance: str
    intent: str
    tool: str | None
    at: datetime = field(default_factory=utcnow)


@dataclass
class SessionState:
    """All state for exactly one session."""

    session_id: str
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    turn_count: int = 0
    last_request_id: str | None = None
    last_intent: str | None = None
    last_tool: str | None = None
    last_arguments: dict[str, Any] = field(default_factory=dict)
    last_entities: list[Entity] = field(default_factory=list)
    #: The project the user is working in. A voice user should not have to
    #: spell out a path for every task; the core remembers it.
    project: str | None = None
    active_task_id: str | None = None
    suspended_task_ids: list[str] = field(default_factory=list)
    actions: "OrderedDict[str, Action]" = field(default_factory=OrderedDict)
    tasks: dict[str, TaskState] = field(default_factory=dict)
    request_cache: "OrderedDict[str, SidekickResponse]" = field(default_factory=OrderedDict)
    transcript: list[TurnRecord] = field(default_factory=list)
    #: Bounded log of events, including events emitted by background work.
    events: list[Event] = field(default_factory=list)
    #: Signalled whenever a new event is logged, so a streaming client can
    #: wait for it instead of polling.
    event_signal: threading.Condition = field(default_factory=threading.Condition)

    # -- action helpers ---------------------------------------------------

    def add_action(self, action: Action) -> Action:
        self.actions[action.action_id] = action
        self._trim(self.actions, DEFAULT_MAX_ACTIONS_PER_SESSION)
        return action

    def get_action(self, action_id: str) -> Action | None:
        return self.actions.get(action_id)

    def pending_actions(self) -> list[Action]:
        return [a for a in self.actions.values() if a.state is ActionStatus.PENDING]

    def awaiting_confirmation_actions(self) -> list[Action]:
        return [a for a in self.actions.values() if a.state is ActionStatus.AWAITING_CONFIRMATION]

    def running_actions(self) -> list[Action]:
        return [a for a in self.actions.values() if a.state is ActionStatus.RUNNING]

    # -- task helpers -----------------------------------------------------

    def add_task(self, task: TaskState) -> TaskState:
        self.tasks[task.task_id] = task
        if len(self.tasks) > DEFAULT_MAX_TASKS_PER_SESSION:
            oldest = min(self.tasks.values(), key=lambda t: t.updated_at)
            self.tasks.pop(oldest.task_id, None)
            if self.active_task_id == oldest.task_id:
                self.active_task_id = None
        return task

    def get_task(self, task_id: str) -> TaskState | None:
        return self.tasks.get(task_id)

    def active_task(self) -> TaskState | None:
        if self.active_task_id is None:
            return None
        return self.tasks.get(self.active_task_id)

    def suspended_tasks(self) -> list[TaskState]:
        return [self.tasks[t] for t in self.suspended_task_ids if t in self.tasks]

    def get_task_for_action(self, action_id: str) -> TaskState | None:
        """Find the task that owns an action."""
        for task in self.tasks.values():
            if action_id in task.action_ids:
                return task
        return None

    def most_recent_task(self) -> TaskState | None:
        """The task that was touched most recently."""
        if not self.tasks:
            return None
        return max(self.tasks.values(), key=lambda task: task.updated_at)

    def cache_response(self, request_id: str, response: SidekickResponse) -> None:
        self.request_cache[request_id] = response
        self.request_cache.move_to_end(request_id)
        while len(self.request_cache) > DEFAULT_MAX_CACHED_RESPONSES:
            self.request_cache.popitem(last=False)

    def cached_response(self, request_id: str) -> SidekickResponse | None:
        return self.request_cache.get(request_id)

    def record_turn(self, record: TurnRecord) -> None:
        self.transcript.append(record)
        if len(self.transcript) > 50:
            del self.transcript[:-50]

    def log_event(self, event: Event) -> None:
        """Append an event to the session log (bounded).

        The sequence number is assigned here so that it is monotonic per
        session, including for events produced by background work. Waiters
        are woken up so a streaming client sees the event immediately.
        """
        with self.event_signal:
            event.seq = len(self.events) + 1
            self.events.append(event)
            if len(self.events) > 200:
                del self.events[:-200]
            self.event_signal.notify_all()

    def events_after(self, seq: int = 0, action_id: str | None = None) -> list[Event]:
        """The events logged after ``seq`` (optionally only for one action)."""
        with self.event_signal:
            events = [event for event in self.events if event.seq > seq]
        if action_id is not None:
            events = [event for event in events if event.action_id == action_id]
        return events

    def wait_for_events(
        self,
        seq: int = 0,
        action_id: str | None = None,
        timeout: float = 1.0,
    ) -> list[Event]:
        """Wait until at least one new event exists, then return the new ones."""
        with self.event_signal:
            self.event_signal.wait_for(
                lambda: any(event.seq > seq for event in self.events),
                timeout=timeout,
            )
            events = [event for event in self.events if event.seq > seq]
        if action_id is not None:
            events = [event for event in events if event.action_id == action_id]
        return events

    def touch(self) -> None:
        self.updated_at = utcnow()

    @staticmethod
    def _trim(mapping: "OrderedDict[str, Any]", limit: int) -> None:
        while len(mapping) > limit:
            mapping.popitem(last=False)


class SessionStore:
    """Thread safe, bounded, session scoped store."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._sessions: "OrderedDict[str, SessionState]" = OrderedDict()
        self._lock = threading.RLock()
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_sessions = max_sessions

    # -- lifecycle --------------------------------------------------------

    def get(self, session_id: str) -> SessionState:
        """Return (creating if needed) the state of one session."""
        with self._lock:
            self._expire()
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState(session_id=session_id)
                self._sessions[session_id] = state
                self._sessions.move_to_end(session_id)
                self._evict()
            else:
                self._sessions.move_to_end(session_id)
                state.touch()
            return state

    def peek(self, session_id: str) -> SessionState | None:
        """Return the state without creating it."""
        with self._lock:
            return self._sessions.get(session_id)

    def drop(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    # -- internals --------------------------------------------------------

    def _expire(self) -> None:
        now = utcnow()
        stale = [sid for sid, state in self._sessions.items() if now - state.updated_at > self._ttl]
        for sid in stale:
            self._sessions.pop(sid, None)

    def _evict(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)

    # -- introspection ----------------------------------------------------

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def session_ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def find_action(self, action_id: str) -> tuple[SessionState, Action] | None:
        """Locate an action in any session."""
        with self._lock:
            for state in self._sessions.values():
                action = state.get_action(action_id)
                if action is not None:
                    return state, action
        return None
