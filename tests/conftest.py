"""Shared fixtures.

The tests run against the *real* engine and the *real* local adapters (notes
and timers really write files and really fire). Only the browser is stubbed,
because opening a real browser during a test run would be a side effect on the
developer machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sidekick.core.catalog import ARG_ENUM, ARG_STRING, ArgumentSpec, ToolSpec
from sidekick.core.decisions.rule_model import RuleDecisionModel
from sidekick.core.engine import DecisionEngine
from sidekick.core.registry import ToolContext, ToolRegistry, ToolResult
from sidekick.core.safety import SafetyPolicy
from sidekick.core.schemas import Action, RiskLevel
from sidekick.core.sessions import SessionStore
from sidekick.tools.local import MediaOpenTool, NoteReadTool, NoteWriteTool, TimerListTool, TimerSetTool


class EchoTool:
    """Records what it was asked to do."""

    spec = ToolSpec(
        name="test.echo",
        description="Repeat a message back to the user",
        aliases=("echo", "repeat back", "say back"),
        risk=RiskLevel.LOW,
        arguments=(
            ArgumentSpec(name="text", type=ARG_STRING, required=True, description="the message"),
        ),
        result_fields=("echoed",),
    )

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(ok=True, data={"echoed": arguments.get("text", "")})

    def cancel(self, action_id: str) -> bool:
        return True


class DangerTool:
    """Irreversible and therefore always requires an explicit approval."""

    spec = ToolSpec(
        name="test.danger",
        description="Delete all of the user's data",
        aliases=("delete everything", "wipe everything"),
        risk=RiskLevel.IRREVERSIBLE,
        requires_approval=True,
        reversible=False,
        cancellable=False,
        arguments=(),
    )

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls += 1
        return ToolResult(ok=True, data={"deleted": True})

    def cancel(self, action_id: str) -> bool:
        return False


class FailingTool:
    """Always raises, to exercise the structured error path."""

    spec = ToolSpec(
        name="test.failing",
        description="Always fails on purpose",
        aliases=("explode", "fail on purpose"),
        risk=RiskLevel.LOW,
    )

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raise RuntimeError("the tool exploded")

    def cancel(self, action_id: str) -> bool:
        return True


class UncancellableTool:
    """Runs forever and cannot be interrupted."""

    spec = ToolSpec(
        name="test.uncancellable",
        description="A job that cannot be interrupted",
        aliases=("start the long job",),
        risk=RiskLevel.LOW,
        cancellable=False,
    )

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, ongoing=True, data={"job": "long"})

    def cancel(self, action_id: str) -> bool:
        return False


class ModeTool:
    """Has a closed enumeration argument."""

    spec = ToolSpec(
        name="test.mode",
        description="Run something in a specific mode",
        aliases=("run the job",),
        risk=RiskLevel.LOW,
        arguments=(
            ArgumentSpec(
                name="mode",
                type=ARG_ENUM,
                required=True,
                description="how to run",
                enum=("fast", "slow"),
            ),
        ),
    )

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, data={"mode": arguments.get("mode")})

    def cancel(self, action_id: str) -> bool:
        return True


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def browser(monkeypatch) -> list[str]:
    """Stub the system browser and record the URLs that were opened."""
    opened: list[str] = []

    def fake_open(url: str, *args: Any, **kwargs: Any) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr("sidekick.tools.local.webbrowser.open", fake_open)
    return opened


@pytest.fixture
def registry(workspace: Path) -> ToolRegistry:
    reg = ToolRegistry()
    timer = TimerSetTool()
    reg.register(NoteWriteTool(workspace))
    reg.register(NoteReadTool(workspace))
    reg.register(timer)
    reg.register(TimerListTool(timer))
    reg.register(MediaOpenTool())
    reg.register(EchoTool())
    reg.register(DangerTool())
    reg.register(FailingTool())
    reg.register(UncancellableTool())
    reg.register(ModeTool())
    return reg


@pytest.fixture
def engine(registry: ToolRegistry, workspace: Path) -> DecisionEngine:
    return DecisionEngine(
        registry=registry,
        sessions=SessionStore(),
        decision_model=RuleDecisionModel(),
        fallback_model=RuleDecisionModel(),
        policy=SafetyPolicy(workspace_root=workspace),
    )


@pytest.fixture
def client(engine: DecisionEngine):
    from fastapi.testclient import TestClient

    from sidekick.api.app import create_app

    return TestClient(create_app(engine))
