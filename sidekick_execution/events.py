"""Job progress events for Sidekick execution.

Agent 3 renders these in the browser UI, so the shape is stable and
documented in `docs/execution-service-contract.md`.

Guarantees
----------
* ``seq`` is strictly increasing **per job**, starting at 1, with no gaps.
* Events for one job are delivered in ``seq`` order.
* Exactly one terminal event (``job.result`` or ``job.error``) is emitted per
  job, and it is the last event for that job.
* ``ts`` is UTC ISO-8601 with millisecond precision and a ``Z`` suffix.
* ``action_id`` is present whenever the event relates to a contract-v1 action.

Event types
-----------
``job.created``     A job was accepted. ``data.status`` is ``pending``.
``job.status``      The job changed state. ``data.status`` is the new state.
``job.progress``    Incremental progress. ``data.progress`` is 0.0-1.0.
``job.log``         A line of output from a real command. ``data.stream`` is
                    ``stdout`` or ``stderr``.
``job.result``      Terminal success (or partial success). ``data.status`` is
                    the final state, ``data.result`` carries the tool payload.
``job.error``       Terminal failure. ``data.error`` carries the contract-v1
                    error object.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .contracts import new_id, utc_now_iso

JOB_CREATED = "job.created"
JOB_STATUS = "job.status"
JOB_PROGRESS = "job.progress"
JOB_LOG = "job.log"
JOB_RESULT = "job.result"
JOB_ERROR = "job.error"

EVENT_TYPES: List[str] = [JOB_CREATED, JOB_STATUS, JOB_PROGRESS, JOB_LOG, JOB_RESULT, JOB_ERROR]

TERMINAL_EVENT_TYPES: List[str] = [JOB_RESULT, JOB_ERROR]


class EventType:
    """Namespace of the job event types."""

    CREATED = JOB_CREATED
    STATUS = JOB_STATUS
    PROGRESS = JOB_PROGRESS
    LOG = JOB_LOG
    RESULT = JOB_RESULT
    ERROR = JOB_ERROR


@dataclass
class Event:
    """A single job event."""

    job_id: str
    type: str
    status: Optional[str] = None
    message: Optional[str] = None
    action_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    event_id: str = field(default_factory=new_id)
    ts: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type,
            "status": self.status,
            "message": self.message,
            "data": self.data,
        }
        if self.action_id is not None:
            payload["action_id"] = self.action_id
        return payload


class EventBus:
    """Thread-safe fan-out of job events to subscribers.

    Each subscriber gets its own bounded queue. A slow consumer drops its
    oldest events rather than blocking the worker; the dropped count is
    reported in the ``data.dropped`` field of the next delivered event so the
    UI can tell that it missed something instead of silently showing a gap.
    """

    def __init__(self, queue_size: int = 512) -> None:
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List["queue.Queue[Event]"]] = {}
        self._history: Dict[str, List[Event]] = {}
        self._seq: Dict[str, int] = {}
        self._queue_size = queue_size

    # -- publishing --------------------------------------------------------
    def publish(self, event: Event) -> Event:
        """Assign a sequence number, record history, and fan out."""
        with self._lock:
            nxt = self._seq.get(event.job_id, 0) + 1
            self._seq[event.job_id] = nxt
            event.seq = nxt
            history = self._history.setdefault(event.job_id, [])
            history.append(event)
            subscribers = list(self._subscribers.get(event.job_id, ()))
        for sub in subscribers:
            self._offer(sub, event)
        return event

    @staticmethod
    def _offer(sub: "queue.Queue[Event]", event: Event) -> None:
        try:
            sub.put_nowait(event)
        except queue.Full:
            try:
                dropped = sub.get_nowait()
            except queue.Empty:  # pragma: no cover - race with a consumer
                dropped = None
            if dropped is not None:
                event.data.setdefault("dropped", 0)
                event.data["dropped"] += 1
            try:
                sub.put_nowait(event)
            except queue.Full:  # pragma: no cover - consumer lost the race
                pass

    # -- subscribing -------------------------------------------------------
    def subscribe(self, job_id: str) -> "queue.Queue[Event]":
        """Return a queue that receives future events for ``job_id``."""
        sub: "queue.Queue[Event]" = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(sub)
        return sub

    def unsubscribe(self, job_id: str, sub: "queue.Queue[Event]") -> None:
        with self._lock:
            subs = self._subscribers.get(job_id)
            if not subs:
                return
            try:
                subs.remove(sub)
            except ValueError:
                pass

    # -- history -----------------------------------------------------------
    def history(self, job_id: str) -> List[Event]:
        """Return every event published for ``job_id`` so far, in order."""
        with self._lock:
            return list(self._history.get(job_id, ()))

    def replay(self, job_id: str, after_seq: int = 0) -> List[Event]:
        """Return events with ``seq > after_seq`` (used to resume an SSE stream)."""
        with self._lock:
            return [e for e in self._history.get(job_id, ()) if e.seq > after_seq]

    def drop(self, job_id: str) -> None:
        """Forget history and sequence state for ``job_id``."""
        with self._lock:
            self._history.pop(job_id, None)
            self._seq.pop(job_id, None)

    def known_jobs(self) -> Iterable[str]:
        with self._lock:
            return tuple(self._history.keys())

    # -- durability --------------------------------------------------------
    def restore(self, events: Iterable[Event]) -> int:
        """Rehydrate the bus with events that were persisted before a restart.

        The sequence numbers are restored with the events, so a client that
        reconnects with ``?after=<seq>`` continues exactly where it left off
        instead of seeing a gap or an empty stream.

        Returns the number of restored events.
        """
        restored = 0
        with self._lock:
            for event in events:
                history = self._history.setdefault(event.job_id, [])
                if any(existing.seq == event.seq for existing in history):
                    continue
                history.append(event)
                if event.seq > self._seq.get(event.job_id, 0):
                    self._seq[event.job_id] = event.seq
                restored += 1
            for job_id, history in self._history.items():
                history.sort(key=lambda e: e.seq)
        return restored

    def prune(self, job_ids: Iterable[str]) -> int:
        """Forget the history of the given jobs. Returns how many were removed."""
        removed = 0
        with self._lock:
            for job_id in job_ids:
                if self._history.pop(job_id, None) is not None:
                    removed += 1
                self._seq.pop(job_id, None)
        return removed
