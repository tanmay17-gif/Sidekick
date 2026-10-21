"""Deterministic safety policy.

The safety layer is *not* model driven. A decision model may propose an action,
but this module decides whether that action is allowed, whether it needs an
explicit approval and whether its arguments are well formed. The model can
never bypass a rule here - the engine applies the outcome of this module after
the interpretation, always.

Rules implemented:

- **Risk**: the risk level comes from the tool spec and is only ever raised,
  never lowered, by the policy.
- **Approval**: anything with risk ``high``/``irreversible`` or
  ``requires_approval`` needs an explicit confirmation that binds to the exact
  action (via its ``plan_hash``).
- **Arguments**: required arguments must be present, values must match the
  declared type, enumerations are closed sets and numbers are range checked.
- **Workspace containment**: string arguments that name a location must stay
  inside the configured workspace root.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .catalog import (
    ARG_BOOLEAN,
    ARG_DURATION,
    ARG_ENUM,
    ARG_INTEGER,
    ARG_STRING,
    ArgumentSpec,
    ToolSpec,
)
from .schemas import RiskLevel

#: The argument names that name a *location* rather than a file the core
#: writes. They are outside the core's containment check, because the tool
#: that declares one owns that area and is responsible for authorising it.
_LOCATION_ARGUMENTS = frozenset(
    {"workspace", "path", "directory", "project", "repo", "root", "folder"}
)

_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.IRREVERSIBLE: 3,
}


class ViolationKind(str, Enum):
    MISSING_ARGUMENT = "missing_argument"
    INVALID_ARGUMENT = "invalid_argument"
    UNKNOWN_ARGUMENT = "unknown_argument"
    AMBIGUOUS_ARGUMENT = "ambiguous_argument"
    OUT_OF_RANGE = "out_of_range"
    UNSAFE_VALUE = "unsafe_value"
    TOOL_UNAVAILABLE = "tool_unavailable"


@dataclass
class PolicyViolation:
    kind: ViolationKind
    message: str
    argument: str | None = None
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "argument": self.argument,
            "options": list(self.options),
        }


@dataclass
class PolicyDecision:
    """Outcome of the policy for one action."""

    risk_level: RiskLevel = RiskLevel.LOW
    approval_required: bool = False
    violations: list[PolicyViolation] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def missing_arguments(self) -> list[str]:
        return [v.argument for v in self.violations if v.kind is ViolationKind.MISSING_ARGUMENT and v.argument]

    @property
    def ambiguous_arguments(self) -> list[str]:
        return [v.argument for v in self.violations if v.kind is ViolationKind.AMBIGUOUS_ARGUMENT and v.argument]


def plan_hash(tool: str, arguments: dict[str, Any]) -> str:
    """Stable fingerprint of the *exact* action a confirmation binds to.

    Any change to the tool or its arguments changes the hash, which expires
    the outstanding confirmation.
    """
    payload = json.dumps(
        {"tool": tool, "arguments": arguments},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class SafetyPolicy:
    """The deterministic gate every planned action passes through."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else None

    # -- public API -------------------------------------------------------

    def evaluate(self, spec: ToolSpec, arguments: dict[str, Any], *, tool_available: bool = True) -> PolicyDecision:
        decision = PolicyDecision()
        decision.risk_level = spec.risk

        if not tool_available:
            decision.violations.append(
                PolicyViolation(
                    kind=ViolationKind.TOOL_UNAVAILABLE,
                    message=f"'{spec.name}' is not available in this deployment",
                    argument=None,
                )
            )
            return decision

        self._check_arguments(spec, arguments, decision)
        self._check_approval(spec, decision)
        return decision

    # -- internals --------------------------------------------------------

    def _check_approval(self, spec: ToolSpec, decision: PolicyDecision) -> None:
        if spec.requires_approval:
            decision.approval_required = True
            decision.reasons.append(f"tool '{spec.name}' requires explicit approval")
        if _RISK_ORDER[spec.risk] >= _RISK_ORDER[RiskLevel.HIGH]:
            decision.approval_required = True
            decision.reasons.append(f"risk level '{spec.risk.value}' requires explicit approval")
        if not spec.reversible:
            decision.approval_required = True
            decision.reasons.append(f"tool '{spec.name}' is not reversible")

    def _check_arguments(self, spec: ToolSpec, arguments: dict[str, Any], decision: PolicyDecision) -> None:
        known = {a.name: a for a in spec.arguments}
        alias_map: dict[str, str] = {}
        for arg in spec.arguments:
            for alias in arg.aliases:
                alias_map[alias] = arg.name

        normalised: dict[str, Any] = {}
        for key, value in arguments.items():
            if key in known:
                normalised[key] = value
                continue
            target = alias_map.get(key)
            if target is not None and target not in normalised:
                normalised[target] = value
            else:
                decision.violations.append(
                    PolicyViolation(
                        kind=ViolationKind.UNKNOWN_ARGUMENT,
                        message=f"'{spec.name}' does not accept the argument '{key}'",
                        argument=key,
                    )
                )

        for arg in spec.arguments:
            if arg.name in normalised:
                value = normalised[arg.name]
                error = self._validate_value(spec, arg, value)
                if error is not None:
                    decision.violations.append(error)
                continue
            if arg.required:
                decision.violations.append(
                    PolicyViolation(
                        kind=ViolationKind.MISSING_ARGUMENT,
                        message=f"'{spec.name}' needs a value for '{arg.name}'",
                        argument=arg.name,
                        options=list(arg.enum) if arg.enum else [],
                    )
                )
            elif arg.default is not None:
                normalised[arg.name] = arg.default

        # Keep normalised values (aliases folded, defaults applied).
        arguments.clear()
        arguments.update(normalised)

    def _validate_value(self, spec: ToolSpec, arg: ArgumentSpec, value: Any) -> PolicyViolation | None:
        if value is None:
            return PolicyViolation(
                kind=ViolationKind.MISSING_ARGUMENT,
                message=f"'{spec.name}' needs a value for '{arg.name}'",
                argument=arg.name,
                options=list(arg.enum) if arg.enum else [],
            )

        if arg.type == ARG_ENUM:
            if not isinstance(value, str):
                return PolicyViolation(
                    kind=ViolationKind.INVALID_ARGUMENT,
                    message=f"'{arg.name}' must be one of {', '.join(arg.enum)}",
                    argument=arg.name,
                    options=list(arg.enum),
                )
            if value not in arg.enum:
                return PolicyViolation(
                    kind=ViolationKind.AMBIGUOUS_ARGUMENT,
                    message=f"'{arg.name}' must be one of {', '.join(arg.enum)}",
                    argument=arg.name,
                    options=list(arg.enum),
                )
            return None

        if arg.type in (ARG_INTEGER, ARG_DURATION):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return PolicyViolation(
                    kind=ViolationKind.INVALID_ARGUMENT,
                    message=f"'{arg.name}' must be a number",
                    argument=arg.name,
                )
            if arg.minimum is not None and value < arg.minimum:
                return PolicyViolation(
                    kind=ViolationKind.OUT_OF_RANGE,
                    message=f"'{arg.name}' must be at least {arg.minimum}",
                    argument=arg.name,
                )
            if arg.maximum is not None and value > arg.maximum:
                return PolicyViolation(
                    kind=ViolationKind.OUT_OF_RANGE,
                    message=f"'{arg.name}' must be at most {arg.maximum}",
                    argument=arg.name,
                )
            return None

        if arg.type == ARG_BOOLEAN:
            if not isinstance(value, bool):
                return PolicyViolation(
                    kind=ViolationKind.INVALID_ARGUMENT,
                    message=f"'{arg.name}' must be true or false",
                    argument=arg.name,
                )
            return None

        if arg.type == ARG_STRING:
            if not isinstance(value, str):
                return PolicyViolation(
                    kind=ViolationKind.INVALID_ARGUMENT,
                    message=f"'{arg.name}' must be text",
                    argument=arg.name,
                )
            if arg.name in _LOCATION_ARGUMENTS or set(arg.aliases) & _LOCATION_ARGUMENTS:
                # A location argument names the area the *tool* works in (a
                # project directory). The core does not own that area and
                # must not pretend to: the adapter is responsible for
                # authorising it, and the execution service enforces its own
                # allowed roots.
                return None
            unsafe = self._check_containment(value)
            if unsafe is not None:
                return PolicyViolation(
                    kind=ViolationKind.UNSAFE_VALUE,
                    message=unsafe,
                    argument=arg.name,
                )
            return None

        return None

    def _check_containment(self, value: str) -> str | None:
        """Reject values that escape the configured workspace root."""
        if self._workspace_root is None:
            return None
        if not re_path_like(value):
            return None
        candidate = (self._workspace_root / value).resolve()
        try:
            candidate.relative_to(self._workspace_root)
        except ValueError:
            return f"'{value}' points outside the allowed workspace"
        return None


def re_path_like(value: str) -> bool:
    """Heuristic: does this string look like a path? (used for containment)"""
    if os.path.isabs(value):
        return True
    return value.startswith(("./", "../", "~/")) or "/" in value or "\\" in value
