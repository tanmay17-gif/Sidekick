"""Structured error model for Sidekick execution.

Mirrors the error object in `.sidekick/API_CONTRACTS.md` v1::

    {
      "error": {
        "code": "<string>",
        "message": "<string>",
        "retryable": false,
        "timeout": false
      }
    }

Every failure that leaves the execution service is expressed as a
:class:`SidekickError` so that callers never receive a bare string or a
generic exception.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# --- Error codes -----------------------------------------------------------
# Stable, machine-readable identifiers. The UI (Agent 3) may branch on these;
# the wording of ``message`` is free-form and human-facing.

WORKSPACE_INVALID = "workspace_invalid"
WORKSPACE_UNAUTHORIZED = "workspace_unauthorized"
WORKSPACE_NOT_FOUND = "workspace_not_found"
WORKSPACE_NOT_A_DIRECTORY = "workspace_not_a_directory"

COMMAND_NOT_ALLOWED = "command_not_allowed"
COMMAND_TIMEOUT = "command_timeout"
COMMAND_FAILED = "command_failed"
COMMAND_CANCELLED = "command_cancelled"
OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"

APPROVAL_REQUIRED = "approval_required"
APPROVAL_INVALID = "approval_invalid"
APPROVAL_EXPIRED = "approval_expired"
DESTRUCTIVE_ACTION_BLOCKED = "destructive_action_blocked"

PROVIDER_NOT_CONFIGURED = "provider_not_configured"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_ERROR = "provider_error"
PROVIDER_OUTPUT_INVALID = "provider_output_invalid"
PROVIDER_AUTH_FAILED = "provider_auth_failed"
PROVIDER_RATE_LIMITED = "provider_rate_limited"
PROVIDER_CONFIG_INVALID = "provider_config_invalid"

JOB_NOT_FOUND = "job_not_found"
JOB_NOT_CANCELLABLE = "job_not_cancellable"
JOB_INTERRUPTED = "job_interrupted"

TEST_FAILED = "test_failed"
TESTS_NOT_RUN = "tests_not_run"

VCS_NOT_A_REPOSITORY = "vcs_not_a_repository"
VCS_ERROR = "vcs_error"
DIFF_TOO_LARGE = "diff_too_large"

EDIT_APPLY_FAILED = "edit_apply_failed"
EDIT_OUTSIDE_WORKSPACE = "edit_outside_workspace"
NO_CHANGES_PRODUCED = "no_changes_produced"

INVALID_REQUEST = "invalid_request"
NOT_IMPLEMENTED = "not_implemented"
INTERNAL_ERROR = "internal_error"

ERROR_CODES: Dict[str, str] = {
    WORKSPACE_INVALID: "The requested workspace path is missing, relative, or otherwise ambiguous.",
    WORKSPACE_UNAUTHORIZED: "The requested workspace is outside every authorized root.",
    WORKSPACE_NOT_FOUND: "The requested workspace does not exist.",
    WORKSPACE_NOT_A_DIRECTORY: "The requested workspace exists but is not a directory.",
    COMMAND_NOT_ALLOWED: "The requested command is not on the execution allowlist.",
    COMMAND_TIMEOUT: "The command exceeded its time limit and was terminated.",
    COMMAND_FAILED: "The command exited with a non-zero status.",
    COMMAND_CANCELLED: "The command was cancelled before it finished.",
    OUTPUT_LIMIT_EXCEEDED: "The command produced more output than the configured limit.",
    APPROVAL_REQUIRED: "This action requires explicit approval before it can run.",
    APPROVAL_INVALID: "The supplied approval does not match the pending action.",
    APPROVAL_EXPIRED: "The approval for this action has expired.",
    DESTRUCTIVE_ACTION_BLOCKED: "The action is destructive and was blocked.",
    PROVIDER_NOT_CONFIGURED: "No coding provider is configured for this deployment.",
    PROVIDER_UNAVAILABLE: "The configured coding provider is not reachable.",
    PROVIDER_ERROR: "The coding provider failed while producing a change plan.",
    PROVIDER_OUTPUT_INVALID: "The coding provider returned output that could not be parsed.",
    PROVIDER_AUTH_FAILED: "The coding provider rejected the credentials.",
    PROVIDER_RATE_LIMITED: "The coding provider is rate limiting this deployment.",
    PROVIDER_CONFIG_INVALID: "The coding provider configuration is not valid.",
    JOB_NOT_FOUND: "No job exists with that identifier.",
    JOB_NOT_CANCELLABLE: "The job is not in a cancellable state.",
    JOB_INTERRUPTED: "The job was interrupted by a service restart.",
    TEST_FAILED: "The requested tests failed.",
    TESTS_NOT_RUN: "The requested tests were not executed.",
    VCS_NOT_A_REPOSITORY: "The workspace is not a version-controlled repository.",
    VCS_ERROR: "A version-control command failed.",
    DIFF_TOO_LARGE: "The diff exceeded the configured maximum size.",
    EDIT_APPLY_FAILED: "The change plan could not be applied to the workspace.",
    EDIT_OUTSIDE_WORKSPACE: "The change plan tried to modify a file outside the workspace.",
    NO_CHANGES_PRODUCED: "The coding provider produced no changes.",
    INVALID_REQUEST: "The request payload is invalid.",
    NOT_IMPLEMENTED: "This capability is not implemented in this deployment.",
    INTERNAL_ERROR: "An unexpected internal error occurred.",
}


class SidekickError(Exception):
    """A structured, serializable failure.

    Attributes:
        code: One of :data:`ERROR_CODES`.
        message: Human-readable explanation.
        retryable: Whether retrying the same request could succeed.
        timeout: Whether the failure was specifically a timeout.
        details: Optional structured context (never contains secrets).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        timeout: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.timeout = timeout
        self.details: Dict[str, Any] = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return error_payload(
            self.code,
            self.message,
            retryable=self.retryable,
            timeout=self.timeout,
            details=self.details or None,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SidekickError(code={self.code!r}, message={self.message!r})"


def error_payload(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    timeout: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the contract-shaped error object.

    ``details`` is an additive field; contract v1 consumers that ignore unknown
    keys keep working.
    """
    payload: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "timeout": timeout,
        }
    }
    if details:
        payload["error"]["details"] = details
    return payload
