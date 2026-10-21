"""Application bootstrap.

Builds the object graph: tool registry -> decision engine -> HTTP app.

The decision model selection is explicit and observable:

- if ``laya`` is installed the real model is primary and the deterministic
  rule engine is the fallback;
- if ``laya`` is *not* installed the rule engine becomes primary but every
  response still reports ``fallback_used = true`` and says why.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core.catalog import (
    CAPTURE_AUTO,
    CAPTURE_REMAINDER,
    ArgumentSpec,
    ToolSpec,
)
from .core.decision import DecisionModel
from .core.decisions.laya_model import LayaDecisionModel
from .core.decisions.rule_model import RuleDecisionModel
from .core.engine import DecisionEngine
from .core.registry import ToolRegistry
from .core.safety import SafetyPolicy
from .core.schemas import RiskLevel
from .core.sessions import SessionStore
from .tools.local import (
    MediaOpenTool,
    NoteReadTool,
    NoteWriteTool,
    ReminderSetTool,
    TimerListTool,
    TimerSetTool,
    WebSearchTool,
)

DEFAULT_WORKSPACE = Path(
    os.environ.get("SIDEKICK_WORKSPACE", Path.cwd() / "sidekick_runtime")
).resolve()

#: The capabilities the browser client executes. Agent 3 owns the file.
CLIENT_CAPABILITIES_FILE = Path(__file__).parent / "client_capabilities.json"


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
    registry.register(WebSearchTool())
    registry.register(ReminderSetTool())
    load_client_capabilities(registry)
    return registry


def load_client_capabilities(
    registry: ToolRegistry, path: Path | str | None = None
) -> list[ToolSpec]:
    """Load the capabilities the *browser client* executes.

    Agent 3 owns the client side (media, movies, games). The core needs to
    know about them so it can route "find a good movie" to the right
    capability and so the capability inventory tells the truth about the
    whole product. The core never executes them: it plans the action and the
    client runs it.

    The manifest is optional. If it is missing the core simply has fewer
    capabilities - nothing breaks.
    """
    manifest = Path(path or CLIENT_CAPABILITIES_FILE)
    if not manifest.exists():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    owner = str(data.get("owner") or "client")
    loaded: list[ToolSpec] = []
    for entry in data.get("capabilities", []):
        try:
            spec = _client_spec(entry, owner)
        except (KeyError, TypeError, ValueError):
            continue
        if registry.spec(spec.name) is not None:
            continue
        registry.declare(spec)
        loaded.append(spec)
    return loaded


def _client_spec(entry: dict, owner: str) -> ToolSpec:
    arguments = tuple(
        ArgumentSpec(
            name=str(argument["name"]),
            type=str(argument.get("type", "string")),
            required=bool(argument.get("required", False)),
            description=str(argument.get("description", "")),
            enum=tuple(argument.get("enum", ())),
            capture=str(argument.get("capture", CAPTURE_REMAINDER)),
        )
        for argument in entry.get("arguments", [])
    )
    return ToolSpec(
        name=str(entry["id"]),
        description=str(entry.get("detail", "")),
        aliases=tuple(str(alias) for alias in entry.get("aliases", ())),
        risk=RiskLevel(str(entry.get("risk", "low"))),
        requires_approval=bool(entry.get("requires_approval", False)),
        arguments=arguments,
        label=str(entry.get("label", entry["id"])),
        owner=owner,
        execution_target="client",
        detail=str(entry.get("detail", "")),
        speech_template=entry.get("speech_template"),
    )


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
