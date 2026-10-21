"""Safety policy: approvals, refusals, argument validation, plan binding."""

from __future__ import annotations

import pytest

from sidekick.core.engine import DecisionEngine
from sidekick.core.errors import ConflictError
from sidekick.core.safety import SafetyPolicy, ViolationKind, plan_hash
from sidekick.core.schemas import ActionStatus, ResponseStatus, SidekickRequest
from sidekick.tools.local import NoteWriteTool


def ask(engine: DecisionEngine, utterance: str, *, session: str = "s1", request_id: str | None = None):
    return engine.handle(
        SidekickRequest(
            request_id=request_id or f"req-{utterance[:24]}-{session}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_irreversible_action_requires_an_explicit_confirmation(engine: DecisionEngine) -> None:
    response = ask(engine, "delete everything")

    assert response.status is ResponseStatus.AWAITING_CONFIRMATION
    action = response.action_plan[0]
    assert action.tool == "test.danger"
    assert action.approval_required is True
    assert action.state is ActionStatus.AWAITING_CONFIRMATION
    # The action must not have run yet.
    assert response.risk_level.value == "irreversible"


def test_confirming_runs_the_approved_action(engine: DecisionEngine) -> None:
    pending = ask(engine, "delete everything")
    action_id = pending.action_plan[0].action_id

    action = engine.confirm_action("s1", action_id, approved=True)

    assert action.state is ActionStatus.SUCCEEDED
    assert action.result == {"deleted": True}


def test_refusing_cancels_the_action_without_running_it(engine: DecisionEngine) -> None:
    pending = ask(engine, "delete everything")
    action_id = pending.action_plan[0].action_id

    action = engine.confirm_action("s1", action_id, approved=False)

    assert action.state is ActionStatus.CANCELLED


def test_a_confirmation_binds_to_the_exact_action(engine: DecisionEngine) -> None:
    pending = ask(engine, "delete everything")
    action = pending.action_plan[0]

    with pytest.raises(ConflictError) as excinfo:
        engine.confirm_action("s1", action.action_id, approved=True, plan_hash="not-the-plan")

    assert "expired" in str(excinfo.value)


def test_confirming_an_unknown_action_is_a_not_found(engine: DecisionEngine) -> None:
    from sidekick.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        engine.confirm_action("s1", "does-not-exist", approved=True)


def test_confirming_an_action_that_is_no_longer_pending_conflicts(engine: DecisionEngine) -> None:
    response = ask(engine, "echo hello")
    action_id = response.action_plan[0].action_id

    with pytest.raises(ConflictError):
        engine.confirm_action("s1", action_id, approved=True)


def test_policy_rejects_unknown_arguments() -> None:
    policy = SafetyPolicy()
    spec = NoteWriteTool.spec

    decision = policy.evaluate(spec, {"content": "x", "surprise": 1})

    assert not decision.ok
    assert decision.violations[0].kind is ViolationKind.UNKNOWN_ARGUMENT


def test_policy_requires_missing_arguments() -> None:
    policy = SafetyPolicy()
    decision = policy.evaluate(NoteWriteTool.spec, {})

    assert decision.missing_arguments == ["content"]
    assert decision.violations[0].kind is ViolationKind.MISSING_ARGUMENT


def test_policy_rejects_values_outside_a_closed_enumeration() -> None:
    from sidekick.core.catalog import ARG_ENUM, ArgumentSpec, ToolSpec

    policy = SafetyPolicy()
    spec = ToolSpec(
        name="x.y",
        description="demo",
        arguments=(ArgumentSpec(name="mode", type=ARG_ENUM, required=True, enum=("fast", "slow")),),
    )

    decision = policy.evaluate(spec, {"mode": "sideways"})

    assert not decision.ok
    assert decision.violations[0].kind is ViolationKind.AMBIGUOUS_ARGUMENT
    assert decision.violations[0].options == ["fast", "slow"]


def test_policy_rejects_values_outside_the_declared_range() -> None:
    from sidekick.core.catalog import ARG_DURATION, ArgumentSpec, ToolSpec

    policy = SafetyPolicy()
    spec = ToolSpec(
        name="x.d",
        description="demo",
        arguments=(
            ArgumentSpec(name="duration_seconds", type=ARG_DURATION, required=True, minimum=1, maximum=10),
        ),
    )

    decision = policy.evaluate(spec, {"duration_seconds": 99})

    assert not decision.ok
    assert decision.violations[0].kind is ViolationKind.OUT_OF_RANGE


def test_policy_keeps_values_inside_the_workspace() -> None:
    policy = SafetyPolicy(workspace_root="/tmp/sidekick")
    spec = NoteWriteTool.spec

    decision = policy.evaluate(spec, {"content": "x", "title": "../../etc/passwd"})

    # The title is not a path argument in this tool, but the containment check
    # must still refuse a value that escapes the workspace.
    assert not decision.ok
    assert decision.violations[0].kind is ViolationKind.UNSAFE_VALUE


def test_plan_hash_changes_when_the_plan_changes() -> None:
    first = plan_hash("note.write", {"content": "a"})
    second = plan_hash("note.write", {"content": "b"})

    assert first != second
    assert first == plan_hash("note.write", {"content": "a"})


def test_the_model_cannot_lower_the_risk_of_a_tool(engine: DecisionEngine) -> None:
    response = ask(engine, "delete everything")

    assert response.risk_level.value == "irreversible"
    assert response.action_plan[0].approval_required is True
