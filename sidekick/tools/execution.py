"""The remote adapter for the Sidekick execution service.

Agent 1 owns the core; Agent 2 owns the execution layer. This module is the
seam between them: it implements the core's :class:`~sidekick.core.registry.
ToolAdapter` protocol and forwards ``coding.execute`` to a **real** execution
service over HTTP.

What it does
------------
* submits the action to the execution service and remembers the mapping
  between the core's action id and the execution service's job id;
* reports the execution job id in ``action.job_id`` (a ratified contract
  field), so both sides agree on one identifier;
* forwards every progress event of the job into the core, which in turn
  exposes it to the browser;
* reports the final outcome through ``ToolContext.complete`` - success,
  partial success, failure and cancellation are all distinguished;
* forwards a cancellation to the real job and reports honestly whether the
  job actually stopped.

Approval
--------
``coding.execute`` changes files, so the core's safety policy requires an
explicit confirmation and the execution service has its own approval gate.
The two are chained, not bypassed: the core asks the human, and only then
does this adapter hand the execution service the confirmation token it issued.
The execution service still refuses to run an unapproved action on its own.

Unavailability
--------------
When the execution service cannot be reached the adapter reports a
structured, retryable error. It never pretends the work happened.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..core.catalog import ARG_STRING, CAPTURE_QUOTED, ArgumentSpec, ToolSpec
from ..core.registry import ToolContext, ToolResult
from ..core.schemas import Action, ActionError, RiskLevel

DEFAULT_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_HEALTH_TIMEOUT_SECONDS = 2.0

#: Status values the execution service reports for its tools.
STATUS_REAL = "REAL"
STATUS_SIMULATED = "SIMULATED"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
STATUS_UNAVAILABLE = "UNAVAILABLE"


class ExecutionServiceError(RuntimeError):
    """The execution service could not be reached or refused the request."""

    def __init__(self, code: str, message: str, *, retryable: bool = True, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


class ExecutionServiceAdapter:
    """Routes ``coding.execute`` to a real execution service."""

    spec = ToolSpec(
        name="coding.execute",
        description=(
            "Run a real coding task in an authorized workspace: change the files, "
            "run the project's tests and report the real diff and test result."
        ),
        aliases=(
            "write code",
            "fix the bug",
            "fix the failing test",
            "code this",
            "make the change",
            "implement this",
            "change the code",
            "refactor",
        ),
        risk=RiskLevel.HIGH,
        requires_approval=True,
        reversible=True,
        cancellable=True,
        arguments=(
            ArgumentSpec(
                name="task",
                type=ARG_STRING,
                required=True,
                description="what the change should do",
                aliases=("request", "instruction", "goal", "change"),
            ),
            ArgumentSpec(
                name="workspace",
                type=ARG_STRING,
                required=True,
                description="the authorized directory the change is made in",
                aliases=("directory", "path", "repo", "project"),
                capture=CAPTURE_QUOTED,
            ),
        ),
        result_fields=(
            "outcome",
            "summary",
            "changed_files",
            "diff",
            "test_result",
            "provider",
        ),
    )

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        health_timeout: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    ) -> None:
        configured = base_url if base_url is not None else os.environ.get("SIDEKICK_EXECUTION_URL")
        self.base_url = (configured or "").rstrip("/")
        self.timeout = float(timeout)
        self.health_timeout = float(health_timeout)
        self._jobs: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- capability reporting ---------------------------------------------
    @property
    def configured(self) -> bool:
        """True when an execution service address is known."""
        return bool(self.base_url)

    def capability_status(self) -> Dict[str, str]:
        """Describe what this adapter can really do right now.

        The values use the execution service's vocabulary (``REAL``,
        ``SIMULATED``, ``NOT_CONFIGURED``, ``NOT_IMPLEMENTED``) so that the
        core can report the truth without guessing.
        """
        if not self.configured:
            return {
                "status": STATUS_NOT_CONFIGURED,
                "detail": (
                    "no execution service is configured; set SIDEKICK_EXECUTION_URL "
                    "to the address of the execution service"
                ),
            }
        try:
            health = self._request("GET", "/v1/health", timeout=self.health_timeout)
        except ExecutionServiceError as exc:
            return {
                "status": STATUS_UNAVAILABLE,
                "detail": f"the execution service at {self.base_url} is not reachable: {exc.message}",
            }
        try:
            capabilities = self._request("GET", "/v1/capabilities", timeout=self.health_timeout)
        except ExecutionServiceError as exc:
            return {
                "status": STATUS_UNAVAILABLE,
                "detail": f"the execution service at {self.base_url} did not report its capabilities: {exc.message}",
            }
        provider = capabilities.get("provider") or {}
        status = provider.get("status") or provider.get("level") or STATUS_REAL
        detail = provider.get("reason") or provider.get("detail") or ""
        if status == STATUS_SIMULATED:
            return {
                "status": STATUS_SIMULATED,
                "detail": "the execution service is configured with a simulated coding provider",
            }
        if status in (STATUS_REAL,):
            return {"status": STATUS_REAL, "detail": detail or "a real coding provider is configured"}
        return {"status": status, "detail": detail or "the coding provider is not configured"}

    # -- execution ---------------------------------------------------------
    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Start the real coding job and report progress through the core."""
        if not self.configured:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="execution_service_not_configured",
                    message=(
                        "no execution service is configured; set SIDEKICK_EXECUTION_URL "
                        "to the address of the execution service"
                    ),
                    retryable=False,
                ),
            )
        task = arguments.get("task")
        workspace = arguments.get("workspace")
        if not isinstance(task, str) or not task.strip():
            return ToolResult(
                ok=False,
                error=ActionError(code="invalid_task", message="the coding task needs a description"),
            )
        if not isinstance(workspace, str) or not workspace.strip():
            return ToolResult(
                ok=False,
                error=ActionError(code="invalid_workspace", message="the coding task needs a workspace"),
            )

        payload = {
            "tool": "coding.execute",
            # The core's safety policy has already validated these arguments,
            # so they are forwarded as they are. Optional keys such as
            # ``test_command`` or ``context_files`` therefore reach the
            # execution service unchanged when the capability declares them.
            "arguments": {k: v for k, v in arguments.items() if k not in ("task", "workspace")}
            | {"task": task, "workspace": workspace},
            "session_id": context.session_id,
        }
        try:
            response = self._request("POST", "/v1/actions", body=payload)
        except ExecutionServiceError as exc:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                    details=exc.details,
                ),
            )

        remote_action = response.get("action") or {}
        job_id = remote_action.get("action_id")
        if not job_id:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="execution_service_error",
                    message="the execution service did not return an action id",
                ),
            )

        confirmation = response.get("confirmation")
        if confirmation:
            # The execution service has its own approval gate. The core has
            # already collected the human's confirmation (the action only
            # reaches this point after the core's policy approved it), so the
            # approval is forwarded to the service with the token the service
            # itself issued. The service is never asked to run an unapproved
            # action on its own.
            token = confirmation.get("confirmation_token")
            if not token:
                return ToolResult(
                    ok=False,
                    error=ActionError(
                        code="approval_required",
                        message=(
                            "the execution service requires an approval confirmation that the "
                            "core did not collect"
                        ),
                    ),
                )
            try:
                self._request(
                    "POST",
                    f"/v1/actions/{job_id}/approve",
                    body={"confirmation_token": token, "approved_by": "core"},
                )
            except ExecutionServiceError as exc:
                return ToolResult(
                    ok=False,
                    error=ActionError(
                        code=exc.code,
                        message=exc.message,
                        retryable=exc.retryable,
                        details=exc.details,
                    ),
                )

        with self._lock:
            self._jobs[action.action_id] = job_id
        # The job id is a ratified contract field, so the core, the browser
        # and the execution service all refer to the same job.
        try:
            action.job_id = job_id
        except Exception:  # pragma: no cover - the field exists in contract v1
            pass

        worker = threading.Thread(
            target=self._follow,
            args=(job_id, context),
            name=f"sidekick-execution-{job_id[:8]}",
            daemon=True,
        )
        worker.start()

        return ToolResult(
            ok=True,
            ongoing=True,
            data={
                "job_id": job_id,
                "tool": "coding.execute",
                "state": remote_action.get("state", "running"),
                "message": "the coding task is running in the execution service",
            },
        )

    def cancel(self, action_id: str) -> bool:
        """Ask the execution service to stop the job behind ``action_id``."""
        with self._lock:
            job_id = self._jobs.get(action_id)
        if not job_id:
            return False
        try:
            response = self._request("POST", f"/v1/actions/{job_id}/cancel", body={})
        except ExecutionServiceError:
            return False
        remote_action = response.get("action") or response
        return remote_action.get("state") == "cancelled"

    # -- progress ----------------------------------------------------------
    def _follow(self, job_id: str, context: ToolContext) -> None:
        """Stream the job's events into the core until the job finishes."""
        try:
            for event in self._stream_events(job_id):
                message = event.get("message") or event.get("type") or ""
                data = dict(event.get("data") or {})
                data["execution_event_type"] = event.get("type")
                data["execution_seq"] = event.get("seq")
                context.progress(str(message), data)
                if event.get("type") in ("job.result", "job.error"):
                    break
        except Exception:  # noqa: BLE001 - a broken stream must not crash the core
            context.progress(
                "the execution event stream ended unexpectedly",
                {"execution_job_id": job_id},
            )
        finally:
            context.complete(self._final_result(job_id))

    def _final_result(self, job_id: str) -> ToolResult:
        """Read the real final state of the job from the execution service."""
        try:
            action = self._request("GET", f"/v1/actions/{job_id}")
        except ExecutionServiceError as exc:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )
        state = action.get("state")
        error = action.get("error")
        result = action.get("result") or {}
        if state == "succeeded":
            return ToolResult(ok=True, data=result)
        if state == "cancelled":
            return ToolResult(
                ok=False,
                cancelled=True,
                error=ActionError(
                    code=error.get("code", "cancelled") if isinstance(error, dict) else "cancelled",
                    message=(
                        error.get("message", "the action was cancelled")
                        if isinstance(error, dict)
                        else "the action was cancelled"
                    ),
                ),
                data=result,
            )
        return ToolResult(
            ok=False,
            error=ActionError(
                code=error.get("code", "tool_execution_error") if isinstance(error, dict) else "tool_execution_error",
                message=(
                    error.get("message", "the execution service reported a failure")
                    if isinstance(error, dict)
                    else "the execution service reported a failure"
                ),
                retryable=bool(error.get("retryable", False)) if isinstance(error, dict) else False,
                timeout=bool(error.get("timeout", False)) if isinstance(error, dict) else False,
                details=error.get("details", {}) if isinstance(error, dict) else {},
            ),
            # A failed action still carries the real outcome: the diff, the
            # changed files and the test result. The UI needs them to show
            # what actually happened.
            data=(
                error.get("details", {}).get("outcome", result)
                if isinstance(error, dict)
                else result
            ),
        )

    # -- HTTP --------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "sidekick-core-adapter"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            payload = _parse_json(raw)
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise ExecutionServiceError(
                code or "execution_service_error",
                message or f"the execution service returned HTTP {exc.code}",
                retryable=exc.code >= 500,
                details={"status": exc.code},
            ) from exc
        except urllib.error.URLError as exc:
            raise ExecutionServiceError(
                "execution_service_unavailable",
                f"the execution service at {self.base_url} could not be reached: {getattr(exc, 'reason', exc)}",
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise ExecutionServiceError(
                "execution_service_timeout",
                f"the execution service at {self.base_url} did not answer in time",
                retryable=True,
            ) from exc
        payload = _parse_json(raw)
        if not isinstance(payload, dict):
            raise ExecutionServiceError(
                "execution_service_error",
                "the execution service returned a response that is not a JSON object",
            )
        return payload

    def _stream_events(self, job_id: str):
        """Yield the execution service's events for ``job_id``."""
        url = f"{self.base_url}/v1/actions/{job_id}/events"
        request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = _parse_json(line[len("data:"):].strip())
                if isinstance(payload, dict):
                    yield payload


def _parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
