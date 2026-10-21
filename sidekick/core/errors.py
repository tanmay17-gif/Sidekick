"""Typed errors with the documented error envelope.

The API never returns a bare string error. Every failure carries a stable
``code`` plus the ``retryable`` / ``timeout`` flags defined in the contract.
"""

from __future__ import annotations

from typing import Any


class SidekickError(Exception):
    """Base class for every error the API surfaces."""

    code = "internal_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        self.timeout = timeout

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "timeout": self.timeout,
                "details": self.details,
            }
        }


class NotFoundError(SidekickError):
    code = "not_found"
    status_code = 404


class ConflictError(SidekickError):
    code = "conflict"
    status_code = 409


class UnprocessableEntityError(SidekickError):
    code = "unprocessable_entity"
    status_code = 422


class ServiceUnavailableError(SidekickError):
    code = "service_unavailable"
    status_code = 503

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)
