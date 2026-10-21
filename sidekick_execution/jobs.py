"""Job lifecycle management for Sidekick execution.

A *job* is one execution of one tool. This module owns the state machine and
nothing else: the tool adapter decides what actually happens, the registry
decides what is allowed, and the event bus tells the UI what it did.

States follow `.sidekick/API_CONTRACTS.md` v1:
``pending -> awaiting_confirmation -> running -> succeeded | failed | cancelled``.

Rules enforced here:

* An action that requires approval never leaves ``awaiting_confirmation``
  until a confirmation token bound to that exact action and plan is supplied.
* A terminal action is never overwritten by a late worker result.
* Cancellation of a running action is honest: the worker is asked to stop, and
  if the underlying process does not stop promptly the action reports that the
  stop was *requested* rather than claiming the process is already gone.
* On restart, jobs that were running when the process died are recovered as
  ``failed`` with a ``job_interrupted`` error rather than being left dangling.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters.registry import (
    STATUS_NOT_CONFIGURED,
    STATUS_NOT_IMPLEMENTED,
    ToolContext,
    ToolRegistry,
    ToolSpec,
)
from .approval import ApprovalStore
from .contracts import (
    ACTION_STATES,
    ALLOWED_TRANSITIONS,
    AWAITING_CONFIRMATION,
    CANCELLED,
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    Action,
    ActionError,
    new_id,
    utc_now_iso,
)
from .errors import JOB_INTERRUPTED, JOB_NOT_CANCELLABLE, SidekickError
from .events import (
    JOB_CREATED,
    JOB_ERROR,
    JOB_PROGRESS,
    JOB_RESULT,
    JOB_STATUS,
    Event,
    EventBus,
)


class JobTransitionError(SidekickError):
    """Raised when an illegal state transition is attempted."""


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
    """A tiny JSON-file job store used for restart recovery."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> List[JobRecord]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = raw.get("jobs") if isinstance(raw, dict) else None
        if not isinstance(records, list):
            return []
        out: List[JobRecord] = []
        for item in records:
            if isinstance(item, dict):
                out.append(JobRecord.from_dict(item))
        return out

    def save(self, records: List[JobRecord]) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(
                    json.dumps(
                        {"jobs": [r.to_dict() for r in records]}, indent=2, default=str
                    ),
                    encoding="utf-8",
                )
                os.replace(tmp, self.path)
            except OSError:
                # Persistence is best-effort; a failure here must not break the
                # running action.
                pass


@dataclass
class ConfirmationRequest:
    """The confirmation payload handed back for an approval-gated action."""

    action_id: str
    token: str
    expires_at: float
    plan_hash: str
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "confirmation_token": self.token,
            "expires_at": self.expires_at,
            "plan_hash": self.plan_hash,
            "reason": self.reason,
        }


class JobManager:
    """Creates, runs, cancels and reports execution jobs."""

    def __init__(
        self,
        registry: ToolRegistry,
        approvals: ApprovalStore,
        event_bus: Optional[EventBus] = None,
        *,
        store: Optional[JobStore] = None,
        max_workers: int = 4,
        cancel_grace_seconds: float = 5.0,
    ) -> None:
        self.registry = registry
        self.approvals = approvals
        self.events = event_bus or EventBus()
        self.store = store
        self.cancel_grace_seconds = cancel_grace_seconds

        self._jobs: Dict[str, Action] = {}
        self._records: Dict[str, JobRecord] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._sessions: Dict[str, List[str]] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sidekick-job")

        if self.store is not None:
            self._recover()

    # -- recovery ----------------------------------------------------------
    def _recover(self) -> None:
        """Mark jobs that were in flight when the process stopped as failed."""
        for record in self.store.load() if self.store else []:
            action = Action.from_dict(record.action)
            if action.state in (SUCCEEDED, FAILED, CANCELLED, "superseded"):
                self._jobs[action.action_id] = action
                self._records[action.action_id] = record
                continue
            action.state = FAILED
            action.error = ActionError(
                code=JOB_INTERRUPTED,
                message="The job was interrupted by a service restart and did not complete.",
                retryable=True,
            )
            action.timestamps.touch()
            self._jobs[action.action_id] = action
            record.action = action.to_dict()
            record.updated_at = utc_now_iso()
            self._records[action.action_id] = record
        self._persist()

    # -- submission --------------------------------------------------------
    def submit(
        self,
        tool: str,
        arguments: Dict[str, Any],
        *,
        session_id: Optional[str] = None,
        confirmation_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a tool request.

        Returns a payload with the action and, when approval is required and
        not yet granted, a :class:`ConfirmationRequest`.
        """
        spec = self.registry.get(tool)
        self._assert_tool_usable(spec)
        if not isinstance(arguments, dict):
            raise SidekickError("invalid_request", "Tool arguments must be a JSON object.")

        action = Action(
            tool=tool,
            arguments=dict(arguments),
            action_id=new_id(),
            job_id=None,
            approval_required=spec.approval_required,
            state=PENDING,
        )
        action.job_id = action.action_id

        with self._lock:
            self._jobs[action.action_id] = action
            self._cancel_events[action.action_id] = threading.Event()
            if session_id:
                self._sessions.setdefault(session_id, []).append(action.action_id)
            self._records[action.action_id] = JobRecord(
                job_id=action.action_id,
                action=action.to_dict(),
                session_id=session_id,
            )

        self._emit(action, JOB_CREATED, "Job accepted.", {"tool": tool, "status": PENDING})
        self._emit(action, JOB_STATUS, f"Job is {PENDING}.", {"status": PENDING})

        needs_approval = spec.approval_required or bool(arguments.get("approval_required"))
        if needs_approval and confirmation_token is None:
            self._transition(action, AWAITING_CONFIRMATION)
            grant = self.approvals.issue(action.action_id, arguments, scope=tool)
            confirmation = ConfirmationRequest(
                action_id=action.action_id,
                token=grant.token,
                expires_at=grant.expires_at,
                plan_hash=grant.plan_hash,
                reason=f"{tool} requires explicit approval before it can run.",
            )
            self._persist()
            return {"action": action.to_dict(), "confirmation": confirmation.to_dict()}

        if spec.approval_required and confirmation_token is not None:
            self.approvals.consume(action.action_id, arguments, confirmation_token)

        self._start(action)
        self._persist()
        return {"action": action.to_dict(), "confirmation": None}

    @staticmethod
    def _assert_tool_usable(spec: ToolSpec) -> None:
        if spec.status == STATUS_NOT_IMPLEMENTED:
            raise SidekickError(
                "not_implemented",
                f"The tool {spec.name!r} is not implemented in this deployment.",
                details={"tool": spec.name},
            )
        if spec.status == STATUS_NOT_CONFIGURED:
            raise SidekickError(
                "provider_not_configured",
                spec.status_detail or f"The tool {spec.name!r} is not configured.",
                details={"tool": spec.name, "detail": spec.status_detail},
            )

    # -- approval ----------------------------------------------------------
    def approve(self, action_id: str, confirmation_token: str) -> Action:
        """Approve a pending action and start it."""
        action = self.get(action_id)
        if action.state != AWAITING_CONFIRMATION:
            raise SidekickError(
                "approval_invalid",
                f"The action is {action.state} and is not awaiting confirmation.",
                details={"action_id": action_id, "status": action.state},
            )
        self.approvals.consume(action_id, action.arguments, confirmation_token)
        self._start(action)
        self._persist()
        return action

    # -- execution ---------------------------------------------------------
    def _start(self, action: Action) -> None:
        self._transition(action, RUNNING)
        self._executor.submit(self._run, action.action_id)

    def _run(self, job_id: str) -> None:
        action = self._jobs.get(job_id)
        if action is None:  # pragma: no cover - defensive
            return
        spec = self.registry.get(action.tool)
        cancel_event = self._cancel_events[job_id]

        def progress(kind: str, message: str, data: Dict[str, Any]) -> None:
            if kind == "progress":
                self._emit(action, JOB_PROGRESS, message, data)
            elif kind == "error":
                self._emit(action, JOB_PROGRESS, message, data)
            else:
                self._emit(action, JOB_PROGRESS, message, data)

        ctx = ToolContext(
            progress=progress,
            cancel_event=cancel_event,
            session_id=None,
            action_id=job_id,
        )
        with self._lock:
            ctx.session_id = (self._records.get(job_id).session_id if self._records.get(job_id) else None)

        try:
            result = spec.handler(action.arguments, ctx)
        except SidekickError as exc:
            self._fail(action, exc)
            return
        except Exception as exc:  # noqa: BLE001 - convert to a structured error
            self._fail(
                action,
                SidekickError(
                    "internal_error",
                    f"The tool {spec.name!r} raised an unexpected error: {exc}",
                    details={"tool": spec.name},
                ),
            )
            return

        if cancel_event.is_set() and action.state == RUNNING:
            self._finish(
                action,
                CANCELLED,
                result={"cancelled": True, "note": "The action was cancelled before it finished."},
            )
            return
        self._finish(action, SUCCEEDED, result=result)

    def _fail(self, action: Action, exc: SidekickError) -> None:
        self._finish(action, FAILED, result=None, error=exc)

    def _finish(
        self,
        action: Action,
        state: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[SidekickError] = None,
    ) -> None:
        with self._lock:
            if action.state in (SUCCEEDED, FAILED, CANCELLED, "superseded"):
                # A late worker result must not overwrite a terminal state.
                return
            action.state = state
            action.result = result
            if error is not None:
                action.error = ActionError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                    timeout=error.timeout,
                    details=error.details or None,
                )
            action.timestamps.touch()
        self._emit(action, JOB_STATUS, f"Job is {state}.", {"status": state})
        if state in (SUCCEEDED, CANCELLED):
            # Success and cancellation are terminal *outcomes*, not failures.
            self._emit(action, JOB_RESULT, self._terminal_message(state, error), {"status": state, "result": result})
        else:
            payload: Dict[str, Any] = {"status": state}
            if error is not None:
                payload["error"] = error.to_dict()["error"]
            self._emit(action, JOB_ERROR, error.message if error else "Job failed.", payload)
        self._persist()

    @staticmethod
    def _terminal_message(state: str, error: Optional[SidekickError]) -> str:
        if state == SUCCEEDED:
            return "Job finished successfully."
        if state == CANCELLED:
            return "Job was cancelled."
        return error.message if error else "Job failed."

    # -- cancellation ------------------------------------------------------
    def cancel(self, action_id: str) -> Action:
        """Cancel a job.

        A job that is not yet running is cancelled immediately. A running job
        is asked to stop; if it does not stop within the grace period the
        action is still marked ``cancelled`` but says so in its result.
        """
        action = self.get(action_id)
        with self._lock:
            if action.state in (SUCCEEDED, FAILED, CANCELLED, "superseded"):
                raise SidekickError(
                    JOB_NOT_CANCELLABLE,
                    f"The job already finished with status {action.state}.",
                    details={"action_id": action_id, "status": action.state},
                )
            cancel_event = self._cancel_events.get(action_id)
            if cancel_event is not None:
                cancel_event.set()

        if action.state in (PENDING, AWAITING_CONFIRMATION):
            self._finish(
                action,
                CANCELLED,
                result={"cancelled": True, "note": "The action was cancelled before it started."},
            )
            return action

        deadline = time.monotonic() + self.cancel_grace_seconds
        while time.monotonic() < deadline:
            with self._lock:
                if action.state in (SUCCEEDED, FAILED, CANCELLED, "superseded"):
                    return action
            time.sleep(0.05)

        self._finish(
            action,
            CANCELLED,
            result={
                "cancelled": True,
                "stop_requested": True,
                "note": (
                    "Cancellation was requested. The underlying process did not stop "
                    "within the grace period and may still be terminating."
                ),
            },
        )
        return action

    # -- queries -----------------------------------------------------------
    def get(self, action_id: str) -> Action:
        with self._lock:
            action = self._jobs.get(action_id)
        if action is None:
            raise SidekickError(
                "job_not_found",
                f"No job exists with the identifier {action_id!r}.",
                details={"action_id": action_id},
            )
        return action

    def list_jobs(self, session_id: Optional[str] = None) -> List[Action]:
        with self._lock:
            if session_id is not None:
                ids = list(self._sessions.get(session_id, ()))
                return [self._jobs[i] for i in ids if i in self._jobs]
            return list(self._jobs.values())

    def wait(self, action_id: str, timeout: float = 30.0) -> Action:
        """Block until a job reaches a terminal state (or the timeout passes)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            action = self.get(action_id)
            if action.state in (SUCCEEDED, FAILED, CANCELLED, "superseded"):
                return action
            time.sleep(0.02)
        return self.get(action_id)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    # -- internals ---------------------------------------------------------
    def _transition(self, action: Action, new_state: str) -> None:
        if new_state not in ACTION_STATES:
            raise JobTransitionError(
                "invalid_request", f"Unknown action state {new_state!r}."
            )
        with self._lock:
            allowed = ALLOWED_TRANSITIONS.get(action.state, [])
            if new_state not in allowed:
                raise JobTransitionError(
                    "invalid_request",
                    f"Cannot move an action from {action.state!r} to {new_state!r}.",
                    details={"from": action.state, "to": new_state},
                )
            action.state = new_state
            action.timestamps.touch()
        self._emit(action, JOB_STATUS, f"Job is {new_state}.", {"status": new_state})

    def _emit(self, action: Action, event_type: str, message: Optional[str], data: Dict[str, Any]) -> Event:
        return self.events.publish(
            Event(
                job_id=action.action_id,
                action_id=action.action_id,
                type=event_type,
                status=action.state,
                message=message,
                data=data or {},
            )
        )

    def _persist(self) -> None:
        if self.store is None:
            return
        with self._lock:
            records = list(self._records.values())
            for action_id, action in self._jobs.items():
                record = self._records.get(action_id)
                if record is None:
                    continue
                record.action = action.to_dict()
                record.updated_at = utc_now_iso()
        self.store.save(records)
