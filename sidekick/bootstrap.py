"""Application bootstrap.

Builds the object graph: tool registry -> decision engine -> HTTP app.

The decision model selection is explicit and observable:

- if ``laya`` is installed the real model is primary and the deterministic
  rule engine is the fallback;
- if ``laya`` is *not* installed the rule engine becomes primary but every
  response still reports ``fallback_used = true`` and says why.
"""

from __future__ import annotations

import os
from pathlib import Path

from .core.decision import DecisionModel
from .core.decisions.laya_model import LayaDecisionModel
from .core.decisions.rule_model import RuleDecisionModel
from .core.engine import DecisionEngine
from .core.registry import ToolRegistry
from .core.safety import SafetyPolicy
from .core.sessions import SessionStore
from .tools.local import (
    MediaOpenTool,
    NoteReadTool,
    NoteWriteTool,
    TimerListTool,
    TimerSetTool,
)

DEFAULT_WORKSPACE = Path(
    os.environ.get("SIDEKICK_WORKSPACE", Path.cwd() / "sidekick_runtime")
).resolve()


def build_registry(workspace: Path | str | None = None) -> ToolRegistry:
    """Register the adapters that ship with the core."""
    root = Path(workspace or DEFAULT_WORKSPACE).resolve()
    registry = ToolRegistry()
    timer_tool = TimerSetTool()
    registry.register(NoteWriteTool(root))
    registry.register(NoteReadTool(root))
    registry.register(timer_tool)
    registry.register(TimerListTool(timer_tool))
    registry.register(MediaOpenTool())
    return registry


def build_decision_model(prefer_model: str | None = None) -> tuple[DecisionModel, DecisionModel, str]:
    """Return ``(primary, fallback, reason)``.

    ``prefer_model`` may force a specific provider (``"laya"`` or ``"rule"``);
    by default the real model is used when it is installed.
    """
    choice = (prefer_model or os.environ.get("SIDEKICK_DECISION_MODEL") or "auto").lower()

    if choice == "rule":
        rule = RuleDecisionModel()
        rule.fallback_reason = "the decision model was disabled by configuration"
        return rule, RuleDecisionModel(), rule.fallback_reason

    laya = LayaDecisionModel()
    if laya.available:
        return laya, RuleDecisionModel(), ""

    rule = RuleDecisionModel()
    reason = "the 'laya' decision model is not installed (pip install 'sidekick[laya]')"
    rule.fallback_reason = reason
    return rule, RuleDecisionModel(), reason


def build_engine(
    registry: ToolRegistry | None = None,
    sessions: SessionStore | None = None,
    *,
    prefer_model: str | None = None,
    workspace: Path | str | None = None,
) -> DecisionEngine:
    """Create a fully wired decision engine."""
    registry = registry or build_registry(workspace)
    sessions = sessions or SessionStore()
    primary, fallback, reason = build_decision_model(prefer_model)
    policy = SafetyPolicy(workspace_root=Path(workspace or DEFAULT_WORKSPACE).resolve())
    return DecisionEngine(
        registry=registry,
        sessions=sessions,
        decision_model=primary,
        fallback_model=fallback,
        policy=policy,
        primary_is_fallback=bool(reason),
    )
