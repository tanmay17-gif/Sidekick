"""Durable state for the execution service.

What survives a process restart
-------------------------------
* **job records** - the identity, the tool, the arguments, the state, the
  result and the error of every job;
* **the event log** - every progress event, with its sequence number, so a
  client that reconnects with ``?after=<seq>`` continues exactly where it
  left off;
* **idempotency keys** - so a retried request does not run the work twice.

What does **not** survive
-------------------------
* the running process of an interrupted job. A job that was in flight when
  the process died is recovered as ``failed`` with the error code
  ``job_interrupted``. It is never reported as succeeded, and it is never
  silently resumed - the underlying command cannot be re-attached to.
* the contents of a disposable workspace, unless the caller kept it.

When no store is configured the service keeps everything in memory only, and
that limit is reported by ``GET /v1/health`` so nobody assumes durability.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .contracts import utc_now_iso

STORE_VERSION = 2

#: The default number of events kept per job. Older events are dropped from
#: the *persisted* log; the live bus keeps what it has.
DEFAULT_MAX_EVENTS_PER_JOB = 500
#: The default number of jobs kept in the store.
DEFAULT_MAX_JOBS = 500
#: How long an idempotency key is honoured.
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 3600.0


@dataclass
class JobRecord:
    """The persisted form of a job."""

    job_id: str
    action: Dict[str, Any]
    session_id: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "JobRecord":
        return cls(
            job_id=raw.get("job_id", ""),
            action=raw.get("action", {}),
            session_id=raw.get("session_id"),
            created_at=raw.get("created_at", utc_now_iso()),
            updated_at=raw.get("updated_at", utc_now_iso()),
        )


class JobStore:
    """A durable, bounded store for jobs, events and idempotency keys.

    Writes are debounced: the state is flushed to disk at most once per
    ``flush_interval`` seconds, and immediately when a job reaches a
    terminal state. That keeps a long-running job from rewriting the file on
    every progress event while still surviving a crash within a second of a
    terminal state.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        flush_interval: float = 1.0,
        max_events_per_job: int = DEFAULT_MAX_EVENTS_PER_JOB,
        max_jobs: int = DEFAULT_MAX_JOBS,
        idempotency_ttl: float = DEFAULT_IDEMPOTENCY_TTL_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.flush_interval = float(flush_interval)
        self.max_events_per_job = int(max_events_per_job)
        self.max_jobs = int(max_jobs)
        self.idempotency_ttl = float(idempotency_ttl)

        self._lock = threading.RLock()
        self._jobs: Dict[str, JobRecord] = {}
        self._events: Dict[str, List[Dict[str, Any]]] = {}
        self._idempotency: Dict[str, Dict[str, Any]] = {}
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._flusher: Optional[threading.Thread] = None
        self._closed = False

        self._restore()
        self._flusher = threading.Thread(
            target=self._flush_loop, name="sidekick-store-flush", daemon=True
        )
        self._flusher.start()

    # -- persistence -------------------------------------------------------
    def _restore(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for item in raw.get("jobs") or ():
            if isinstance(item, dict):
                record = JobRecord.from_dict(item)
                if record.job_id:
                    self._jobs[record.job_id] = record
        events = raw.get("events")
        if isinstance(events, dict):
            for job_id, items in events.items():
                if isinstance(items, list):
                    self._events[job_id] = [e for e in items if isinstance(e, dict)]
        idempotency = raw.get("idempotency")
        if isinstance(idempotency, dict):
            for key, value in idempotency.items():
                if isinstance(value, dict):
                    self._idempotency[key] = value

    def _snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": STORE_VERSION,
                "jobs": [record.to_dict() for record in self._jobs.values()],
                "events": {
                    job_id: list(items)[-self.max_events_per_job :]
                    for job_id, items in self._events.items()
                },
                "idempotency": dict(self._idempotency),
            }

    def _write(self) -> None:
        snapshot = self._snapshot()
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(
                    json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
                )
                os.replace(tmp, self.path)
            except OSError:
                # Persistence is best effort: a failure here must never break
                # the running job.
                pass

    def _flush_loop(self) -> None:
        while not self._stop.wait(self.flush_interval):
            if self._dirty.is_set():
                self._dirty.clear()
                self._write()

    def mark_dirty(self) -> None:
        """Schedule a flush. The write happens on the flusher thread."""
        self._dirty.set()

    def flush(self) -> None:
        """Write the state to disk now."""
        self._dirty.clear()
        self._write()

    def close(self) -> None:
        """Stop the flusher and write the final state."""
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._flusher is not None:
            self._flusher.join(timeout=5)
        self.flush()

    # -- jobs --------------------------------------------------------------
    def put_job(self, record: JobRecord) -> None:
        with self._lock:
            self._jobs[record.job_id] = record
        self.mark_dirty()

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def all_jobs(self) -> List[JobRecord]:
        with self._lock:
            return list(self._jobs.values())

    # -- events ------------------------------------------------------------
    def append_event(self, job_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            items = self._events.setdefault(job_id, [])
            items.append(event)
            if len(items) > self.max_events_per_job:
                del items[: len(items) - self.max_events_per_job]
        self.mark_dirty()

    def events_for(self, job_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events.get(job_id, ()))

    # -- idempotency -------------------------------------------------------
    @staticmethod
    def _idem_key(session_id: Optional[str], key: str) -> str:
        return f"{session_id or ''}\x00{key}"

    def put_idempotency(
        self, session_id: Optional[str], key: str, job_id: str
    ) -> None:
        with self._lock:
            self._idempotency[self._idem_key(session_id, key)] = {
                "job_id": job_id,
                "created_at": time.time(),
            }
        self.mark_dirty()

    def lookup_idempotency(
        self, session_id: Optional[str], key: str
    ) -> Optional[str]:
        """Return the job id an idempotency key already produced, if any."""
        with self._lock:
            entry = self._idempotency.get(self._idem_key(session_id, key))
            if not entry:
                return None
            created = float(entry.get("created_at", 0))
            if time.time() - created > self.idempotency_ttl:
                self._idempotency.pop(self._idem_key(session_id, key), None)
                return None
            job_id = entry.get("job_id")
            if job_id not in self._jobs:
                # The job it referred to is gone; the key may be reused.
                self._idempotency.pop(self._idem_key(session_id, key), None)
                return None
            return job_id

    # -- retention ---------------------------------------------------------
    def prune(self, *, older_than_seconds: float = 3600.0) -> List[str]:
        """Drop finished jobs (and their events) that are older than the TTL.

        Returns the ids of the removed jobs.
        """
        cutoff = time.time() - older_than_seconds
        removed: List[str] = []
        with self._lock:
            for job_id, record in list(self._jobs.items()):
                state = (record.action or {}).get("state")
                if state not in ("succeeded", "failed", "cancelled", "superseded"):
                    continue
                updated = record.updated_at or ""
                try:
                    stamp = time.mktime(time.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S"))
                except (ValueError, TypeError):
                    stamp = 0.0
                if stamp and stamp > cutoff:
                    continue
                self._jobs.pop(job_id, None)
                self._events.pop(job_id, None)
                removed.append(job_id)
            if len(self._jobs) > self.max_jobs:
                # Keep the newest jobs when the store grows past its bound.
                ordered = sorted(
                    self._jobs.values(), key=lambda r: r.updated_at, reverse=True
                )
                for record in ordered[self.max_jobs :]:
                    self._jobs.pop(record.job_id, None)
                    self._events.pop(record.job_id, None)
                    removed.append(record.job_id)
            for key, entry in list(self._idempotency.items()):
                if float(entry.get("created_at", 0)) < cutoff:
                    self._idempotency.pop(key, None)
        if removed:
            self.mark_dirty()
        return removed
