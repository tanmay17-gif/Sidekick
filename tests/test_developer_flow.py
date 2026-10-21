"""The voice-first developer flow.

The target: a user says "fix the failing tests in my project" and the core
routes it to the coding capability, supplies the workspace, asks for the
approval, follows the real progress and can cancel the right task.

These tests use a stand-in coding adapter with the *same shape* as Agent 2's
``coding.execute`` (a ``task`` and a ``workspace`` argument, an adapter that
describes itself with ``capability_status()`` and a background job that is
reported through ``ToolContext.complete``). The real adapter lives in the
execution service; the contract between the core and an adapter is what is
tested here.
"""

from __future__ import annotations

import threading
import time

import pytest

from sidekick.core.catalog import ARG_STRING, CAPTURE_QUOTED, ArgumentSpec, ToolSpec
from sidekick.core.engine import DecisionEngine
from sidekick.core.registry import ToolContext, ToolResult
from sidekick.core.safety import SafetyPolicy
from sidekick.core.schemas import Action, ActionStatus, ResponseStatus, RiskLevel
from sidekick.core.sessions import SessionStore


class FakeCodingAdapter:
    """A stand-in for the execution service adapter.

    It has the same shape: a ``task`` and a ``workspace`` argument, a
    self-report, a background job and a cancellation.
    """

    spec = ToolSpec(
        name="coding.execute",
        description="Run a real coding task in an authorized workspace",
        aliases=(
            "fix the failing test",
            "fix the bug",
            "write code",
            "change the code",
        ),
        risk=RiskLevel.HIGH,
        requires_approval=True,
        arguments=(
            ArgumentSpec(
                name="task",
                type=ARG_STRING,
                required=True,
                description="what the change should do",
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
    )

    def __init__(self, status: str = "NOT_CONFIGURED") -> None:
        self.status = status
        self.calls: list[dict] = []
        self.cancelled: list[str] = []
        self.finished = threading.Event()

    def capability_status(self) -> dict:
        return {
            "status": self.status,
            "detail": "no live coding provider is configured",
        }

    def execute(self, action: Action, arguments: dict, context: ToolContext) -> ToolResult:
        self.calls.append(dict(arguments))
        job_id = f"job-{action.action_id[:8]}"

        def work() -> None:
            context.progress("the provider is thinking", {"job_id": job_id})
            time.sleep(0.05)
            context.complete(
                ToolResult(
                    ok=True,
                    data={
                        "outcome": "succeeded",
                        "job_id": job_id,
                        "changed_files": [{"path": "a.py", "status": "modified"}],
                        "test_result": {"exit_code": 0, "passed": True},
                    },
                )
            )
            self.finished.set()

        threading.Thread(target=work, daemon=True).start()
        return ToolResult(ok=True, ongoing=True, data={"job_id": job_id})

    def cancel(self, action_id: str) -> bool:
        self.cancelled.append(action_id)
        return True


@pytest.fixture
def coding_engine(tmp_path):
    registry_holder = {}

    from sidekick.core.registry import ToolRegistry

    registry = ToolRegistry()
    adapter = FakeCodingAdapter()
    registry.register(adapter)
    registry_holder["adapter"] = adapter
    engine = DecisionEngine(
        registry=registry,
        sessions=SessionStore(),
        policy=SafetyPolicy(workspace_root=tmp_path),
    )
    engine.registry = registry
    return engine, adapter


def ask(engine: DecisionEngine, utterance: str, session: str = "dev"):
    from sidekick.core.schemas import SidekickRequest

    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:20]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_a_developer_request_reaches_the_coding_capability(coding_engine) -> None:
    engine, _adapter = coding_engine

    response = ask(
        engine,
        'fix the failing tests in "C:/work/my project"',
        session="dev1",
    )

    assert response.action_plan[0].tool == "coding.execute"
    assert response.status is ResponseStatus.AWAITING_CONFIRMATION
    assert response.action_plan[0].approval_required is True
    # The task is the whole instruction, the workspace is the quoted path.
    assert response.action_plan[0].arguments["task"] == "fix the failing tests"
    assert response.action_plan[0].arguments["workspace"] == "C:/work/my project"


def test_the_workspace_comes_from_the_project_the_session_is_in(coding_engine) -> None:
    """A voice user should not have to spell out a path for every task."""
    engine, _adapter = coding_engine

    ask(engine, 'fix the failing tests in "C:/work/my project"', session="dev2")
    response = ask(engine, "fix the failing tests in my project", session="dev2")

    action = response.action_plan[0]
    assert action.arguments["workspace"] == "C:/work/my project"
    assert action.arguments["task"]


def test_the_workspace_argument_is_still_required_without_a_project(coding_engine) -> None:
    """Without a project the core asks - it does not invent a path."""
    engine, _adapter = coding_engine

    response = ask(engine, "fix the failing tests in my project", session="dev3")

    action = response.action_plan[0]
    assert action.tool == "coding.execute"
    assert action.arguments.get("workspace") is None
    assert action.error is not None
    assert action.error.code == "missing_argument"
    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert "workspace" in response.clarification.question


def test_the_approval_is_required_before_anything_runs(coding_engine) -> None:
    engine, adapter = coding_engine

    asked = ask(
        engine, 'fix the failing tests in "C:/work/my project"', session="dev4"
    )
    assert adapter.calls == []

    action_id = asked.action_plan[0].action_id
    plan_hash = asked.action_plan[0].plan_hash
    approved = engine.confirm_action("dev4", action_id, approved=True, plan_hash=plan_hash)

    assert approved.state is ActionStatus.RUNNING
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["task"]


def test_the_real_progress_and_result_reach_the_session(coding_engine) -> None:
    engine, adapter = coding_engine
    asked = ask(
        engine, 'fix the failing tests in "C:/work/my project"', session="dev5"
    )
    action_id = asked.action_plan[0].action_id
    engine.confirm_action("dev5", action_id, approved=True)

    assert adapter.finished.wait(5)
    deadline = time.time() + 5
    state = engine.sessions.peek("dev5")
    while time.time() < deadline:
        assert state is not None
        action = state.get_action(action_id)
        if action is not None and action.state is ActionStatus.SUCCEEDED:
            break
        time.sleep(0.05)

    assert state is not None
    action = state.get_action(action_id)
    assert action is not None
    assert action.state is ActionStatus.SUCCEEDED
    assert action.result is not None
    assert action.result["test_result"]["exit_code"] == 0
    # The progress events are the real ones.
    kinds = {event.type for event in state.events}
    assert "action.progress" in kinds


def test_cancelling_reaches_the_right_action(coding_engine) -> None:
    engine, adapter = coding_engine
    asked = ask(
        engine, 'fix the failing tests in "C:/work/my project"', session="dev6"
    )
    action_id = asked.action_plan[0].action_id
    engine.confirm_action("dev6", action_id, approved=True)

    cancelled = engine.cancel_action("dev6", action_id)

    assert cancelled.state is ActionStatus.CANCELLED
    assert adapter.cancelled == [action_id]


def test_a_configured_project_is_used_when_the_user_does_not_name_one(
    coding_engine, monkeypatch
) -> None:
    """A deployment can set the project once; the user need not repeat it."""
    engine, _adapter = coding_engine
    monkeypatch.setenv("SIDEKICK_PROJECT_DIR", "C:/work/configured")

    response = ask(engine, "fix the failing tests", session="dev7")

    action = response.action_plan[0]
    assert action.tool == "coding.execute"
    assert action.arguments["workspace"] == "C:/work/configured"
    assert action.arguments["task"] == "fix the failing tests"


def test_the_capability_report_is_honest_about_the_provider(coding_engine) -> None:
    """An adapter that says it is not configured is not reported as live."""
    engine, _adapter = coding_engine
    from fastapi.testclient import TestClient

    from sidekick.api.app import create_app

    client = TestClient(create_app(engine))
    body = client.get("/api/v1/capabilities").json()

    capabilities = {item["id"]: item for item in body["capabilities"]}
    tools = {item["tool"]: item for item in body["tools"]}

    assert capabilities["coding.execute"]["state"] == "unconfigured"
    assert tools["coding.execute"]["status"] == "NOT_CONFIGURED"
    assert tools["coding.execute"]["simulated"] is False
    assert body["any_simulated"] is False


def test_a_live_provider_is_reported_as_live(coding_engine) -> None:
    engine, adapter = coding_engine
    adapter.status = "REAL"
    from fastapi.testclient import TestClient

    from sidekick.api.app import create_app

    client = TestClient(create_app(engine))
    body = client.get("/api/v1/capabilities").json()

    capabilities = {item["id"]: item for item in body["capabilities"]}
    assert capabilities["coding.execute"]["state"] == "live"
