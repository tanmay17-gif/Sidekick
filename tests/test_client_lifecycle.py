"""The complete client-action lifecycle, including approval.

The trust boundary, stated plainly:

- the **core** plans the action, applies the safety policy and asks for the
  approval. It never runs a client capability and never claims it ran it;
- the **client** runs the capability in the browser and reports what really
  happened;
- the **core** records the report. It cannot independently verify that a
  browser really played a track or really started a game - it can only record
  what the client said. That is why the capability report says the client
  side is ``client`` and not ``live``.
"""

from __future__ import annotations

import time

import pytest

from sidekick.core.catalog import ToolSpec
from sidekick.core.engine import DecisionEngine
from sidekick.core.errors import ConflictError
from sidekick.core.registry import ToolRegistry
from sidekick.core.safety import SafetyPolicy
from sidekick.core.schemas import (
    ActionStatus,
    ResponseStatus,
    RiskLevel,
    SidekickRequest,
)
from sidekick.core.sessions import SessionStore


def ask(engine: DecisionEngine, utterance: str, session: str = "lifecycle"):
    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:20]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


@pytest.fixture
def approval_engine(workspace) -> DecisionEngine:
    """A client capability that needs an approval, like a destructive action."""
    registry = ToolRegistry()
    registry.declare(
        ToolSpec(
            name="client.reset",
            label="reset the app",
            description="Reset the app state in the browser",
            aliases=("reset the app",),
            owner="agent3",
            execution_target="client",
            requires_approval=True,
            risk=RiskLevel.HIGH,
        )
    )
    return DecisionEngine(
        registry=registry,
        sessions=SessionStore(),
        policy=SafetyPolicy(workspace_root=workspace),
    )


def test_the_full_client_lifecycle(approval_engine: DecisionEngine) -> None:
    """1. plan -> 2. pending -> 3. approved -> 4. client -> 5. report -> 6. final."""
    # 1. The core plans the action.
    planned = ask(approval_engine, "reset the app", session="life")
    assert planned.status is ResponseStatus.AWAITING_CONFIRMATION
    action = planned.action_plan[0]
    action_id = action.action_id
    plan_hash = action.plan_hash
    assert action.state is ActionStatus.AWAITING_CONFIRMATION
    assert action.approval_required is True

    # 2. It is not executed before the approval.
    assert action.result is None

    # 3. The approval is bound to the exact action.
    approved = approval_engine.confirm_action("life", action_id, approved=True, plan_hash=plan_hash)
    assert approved.state is ActionStatus.PENDING
    assert approved.result is not None
    assert approved.result["execution_target"] == "client"
    assert approved.result["status"] == "awaiting_client"

    # 4./5. The client runs it and reports.
    completed = approval_engine.complete_action(
        "life", action_id, status="succeeded", result={"reset": True}
    )

    # 6. The final state is the real one.
    assert completed.state is ActionStatus.SUCCEEDED
    assert completed.result == {"reset": True}


def test_an_approval_cannot_authorize_a_changed_action(
    approval_engine: DecisionEngine,
) -> None:
    planned = ask(approval_engine, "reset the app", session="stale")
    action_id = planned.action_plan[0].action_id

    with pytest.raises(ConflictError) as excinfo:
        approval_engine.confirm_action(
            "stale", action_id, approved=True, plan_hash="not-the-plan"
        )

    assert "expired" in str(excinfo.value)
    # The action is untouched.
    state = approval_engine.sessions.peek("stale")
    assert state is not None
    action = state.get_action(action_id)
    assert action is not None
    assert action.state is ActionStatus.AWAITING_CONFIRMATION


def test_a_failed_client_action_is_never_announced_as_successful(
    approval_engine: DecisionEngine,
) -> None:
    from sidekick.core.schemas import ActionError

    planned = ask(approval_engine, "reset the app", session="failed")
    action_id = planned.action_plan[0].action_id
    approval_engine.confirm_action("failed", action_id, approved=True)

    failed = approval_engine.complete_action(
        "failed",
        action_id,
        status="failed",
        error=ActionError(code="client_failed", message="the app could not reset"),
    )

    assert failed.state is ActionStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "client_failed"
    assert failed.result is not None
    assert failed.result.get("execution_target") == "client"


def test_a_cancelled_client_action_is_not_successful(
    approval_engine: DecisionEngine,
) -> None:
    planned = ask(approval_engine, "reset the app", session="cancelled")
    action_id = planned.action_plan[0].action_id
    approval_engine.confirm_action("cancelled", action_id, approved=True)

    cancelled = approval_engine.complete_action("cancelled", action_id, status="cancelled")

    assert cancelled.state is ActionStatus.CANCELLED


def test_the_spoken_line_asks_for_the_approval_without_claiming_success(
    approval_engine: DecisionEngine,
) -> None:
    """The core did not run it and does not know whether it worked."""
    planned = ask(approval_engine, "reset the app", session="speech")

    assert planned.speech is not None
    assert "confirm" in planned.speech.lower()
    assert "done" not in planned.speech.lower()


def test_the_spoken_line_names_who_runs_a_client_capability(
    engine: DecisionEngine,
) -> None:
    """A pending client action is announced as the app's work, not as done."""
    planned = ask(engine, "play some relaxing music", session="speech2")

    assert planned.status is ResponseStatus.PENDING
    assert planned.speech is not None
    assert planned.speech.startswith("The app will ")
    assert "done" not in planned.speech.lower()


def test_the_session_and_action_identifiers_are_validated(
    approval_engine: DecisionEngine,
) -> None:
    from sidekick.core.errors import NotFoundError

    planned = ask(approval_engine, "reset the app", session="ids")
    action_id = planned.action_plan[0].action_id

    # The right action id in the wrong session is not found.
    with pytest.raises(NotFoundError):
        approval_engine.complete_action("other-session", action_id, status="succeeded")


def test_the_client_capability_is_reported_as_client_not_live(client) -> None:
    """It is never reported as something the server runs."""
    body = client.get("/api/v1/capabilities").json()
    server_side = {item["id"]: item for item in body["capabilities"]}
    client_side = {item["id"]: item for item in body["client_capabilities"]}

    assert "media.play" not in server_side
    assert client_side["media.play"]["state"] == "client"
    assert client_side["media.play"]["execution_target"] == "client"
