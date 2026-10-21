"""Explicit approval gate for consequential actions.

Contract v1 requires that high-impact or irreversible actions carry an
explicit approval, and that "a confirmation binds to the exact pending action
and expires if the plan changes" (`.sidekick/ARCHITECTURE.md`).

This module implements that binding:

* A grant is issued for one ``action_id`` and one ``plan_hash``.
* The plan hash is computed from the *content* that would be executed. If the
  plan changes in any way, the hash changes and the old grant no longer
  applies.
* Grants expire after a configured TTL.
* Grants are single-use unless explicitly issued as reusable.

The grant token is an opaque random string. It is never logged and never
included in an action payload that reaches the UI.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import errors
from .errors import SidekickError

DEFAULT_TTL_SECONDS = 300.0


def compute_plan_hash(plan: Any) -> str:
    """Compute a stable hash of an execution plan.

    Accepts any JSON-serializable structure. The hash changes if any part of
    the plan changes, which is what makes an approval stale when the plan is
    edited.
    """
    import json

    payload = json.dumps(plan, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalGrant:
    """A single approval bound to one action and one plan."""

    action_id: str
    plan_hash: str
    token: str
    issued_at: float
    expires_at: float
    reusable: bool = False
    scope: str = "execute"

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialize *without* the token. Safe to send to the UI."""
        return {
            "action_id": self.action_id,
            "plan_hash": self.plan_hash,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "reusable": self.reusable,
            "scope": self.scope,
            "expired": self.expired,
        }


class ApprovalStore:
    """Issues and validates approval grants."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = float(ttl_seconds)
        self._grants: Dict[str, ApprovalGrant] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        action_id: str,
        plan: Any,
        *,
        scope: str = "execute",
        reusable: bool = False,
        ttl_seconds: Optional[float] = None,
    ) -> ApprovalGrant:
        """Issue an approval for ``action_id`` bound to ``plan``."""
        now = time.time()
        ttl = float(ttl_seconds if ttl_seconds is not None else self._ttl)
        grant = ApprovalGrant(
            action_id=action_id,
            plan_hash=compute_plan_hash(plan),
            token=secrets.token_urlsafe(24),
            issued_at=now,
            expires_at=now + ttl,
            reusable=reusable,
            scope=scope,
        )
        with self._lock:
            self._grants[action_id] = grant
        return grant

    def validate(self, action_id: str, plan: Any, token: Optional[str]) -> ApprovalGrant:
        """Validate ``token`` against the pending action and plan.

        Raises:
            SidekickError: ``approval_required`` when no token was supplied,
                ``approval_invalid`` when the token does not match the action
                or the plan, ``approval_expired`` when the grant has expired.
        """
        if not token:
            raise SidekickError(
                errors.APPROVAL_REQUIRED,
                "This action requires an explicit approval before it can run.",
            )
        with self._lock:
            grant = self._grants.get(action_id)
        if grant is None:
            raise SidekickError(
                errors.APPROVAL_INVALID,
                "No approval has been issued for this action.",
                details={"action_id": action_id},
            )
        if not hmac.compare_digest(grant.token, token):
            raise SidekickError(
                errors.APPROVAL_INVALID,
                "The supplied approval does not match the pending action.",
                details={"action_id": action_id},
            )
        if grant.expired:
            raise SidekickError(
                errors.APPROVAL_EXPIRED,
                "The approval for this action has expired; request a new one.",
                details={"action_id": action_id},
            )
        expected_hash = compute_plan_hash(plan)
        if not hmac.compare_digest(grant.plan_hash, expected_hash):
            raise SidekickError(
                errors.APPROVAL_INVALID,
                "The plan changed since it was approved; the approval no longer applies.",
                details={"action_id": action_id},
            )
        return grant

    def consume(self, action_id: str, plan: Any, token: Optional[str]) -> ApprovalGrant:
        """Validate and (for single-use grants) invalidate the approval."""
        grant = self.validate(action_id, plan, token)
        if not grant.reusable:
            with self._lock:
                self._grants.pop(action_id, None)
        return grant

    def revoke(self, action_id: str) -> None:
        with self._lock:
            self._grants.pop(action_id, None)

    def get(self, action_id: str) -> Optional[ApprovalGrant]:
        with self._lock:
            return self._grants.get(action_id)
