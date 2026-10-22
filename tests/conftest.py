"""Shared fixtures.

The tests run against the *real* engine and the *real* local adapters (notes
and timers really write files and really fire).

**No test may open a real browser window.** `webbrowser.open` is replaced
session wide by the `no_real_browser` fixture, so a test can never launch a
browser by accident. The URLs the code *would* have opened are recorded and
returned by the `browser` fixture.
"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Any

import pytest

from sidekick.bootstrap import build_registry
from sidekick.core.catalog import ARG_ENUM, ARG_STRING, ArgumentSpec, ToolSpec
from sidekick.core.decisions.rule_model import RuleDecisionModel
from sidekick.core.engine import DecisionEngine
from sidekick.core.registry import ToolContext, ToolRegistry, ToolResult
from sidekick.core.safety import SafetyPolicy
from sidekick.core.schemas import Action, RiskLevel
from sidekick.core.sessions import SessionStore


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


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make the real browser unreachable for the whole test session.

    `webbrowser.open` and `webbrowser.get` are both replaced, so a test
    cannot launch a window even by accident. A test that needs to know which
    URL the code *would* have opened uses the ``browser`` fixture.

    Set ``SIDECKICK_STRICT_BROWSER=1`` to turn every browser call into a
    failure - useful when hunting a test that opens a window.
    """
    opened: list[str] = []
    strict = os.environ.get("SIDECKICK_STRICT_BROWSER", "").lower() in {"1", "true", "yes"}

    def fake_open(url: str, *args: Any, **kwargs: Any) -> bool:
        if strict:
            raise AssertionError(f"a test tried to open a real browser: {url}")
        opened.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)

    # The real browser machinery is unreachable as well: `webbrowser.get()`
    # hands out a controller that would start the browser on Windows.
    class _NoBrowser:
        def open(self, *args: Any, **kwargs: Any) -> bool:
            raise AssertionError("a test tried to reach the real browser")

        def open_new(self, *args: Any, **kwargs: Any) -> bool:
            raise AssertionError("a test tried to reach the real browser")

        def open_new_tab(self, *args: Any, **kwargs: Any) -> bool:
            raise AssertionError("a test tried to reach the real browser")

    monkeypatch.setattr(webbrowser, "get", lambda *a, **k: _NoBrowser())
    return opened


@pytest.fixture
def browser(no_real_browser: list[str]) -> list[str]:
    """The URLs the code opened during the test (never a real window)."""
    return no_real_browser


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def registry(workspace: Path) -> ToolRegistry:
    """The real registry, plus the test-only adapters."""
    reg = build_registry(workspace)
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
