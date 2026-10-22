"""The client-execution contract.

Agent 3's browser client runs the capabilities the core plans for it
(``execution_target == "client"``). These tests pin down the contract the two
sides agreed on:

- a client action waits for a genuine client result and never claims success
  on its own;
- only a client action can be completed by the client;
- a client action cannot stay pending forever;
- the action id and the session id are the ones the core handed out.
"""

from __future__ import annotations

import time

import pytest

from sidekick.core.engine import DecisionEngine
from sidekick.core.errors import ConflictError, NotFoundError
from sidekick.core.schemas import ActionStatus, SidekickRequest


def ask(engine: DecisionEngine, utterance: str, session: str = "client"):
    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:20]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_a_client_action_waits_for_the_client(engine: DecisionEngine) -> None:
    response = ask(engine, "Play some relaxing music")

    action = response.action_plan[0]
    assert action.tool == "media.play"
    assert action.state is ActionStatus.PENDING
    assert action.result is not None
    assert action.result["execution_target"] == "client"
    assert action.result["status"] == "awaiting_client"
    # The core has not run anything.
    assert action.result.get("fired") is None


def test_the_client_report_is_recorded_on_the_right_action(engine: DecisionEngine) -> None:
    response = ask(engine, "Start chess")
    action_id = response.action_plan[0].action_id

    completed = engine.complete_action(
        "client",
        action_id,
        status="succeeded",
        result={"game": "chess"},
    )

    assert completed.action_id == action_id
    assert completed.state is ActionStatus.SUCCEEDED
    assert completed.result == {"game": "chess"}

    # A different action in the same session is untouched.
    other = ask(engine, "Play a movie", session="client")
    other_action = other.action_plan[0]
    assert other_action.action_id != action_id
    assert other_action.state is ActionStatus.PENDING


def test_a_client_cannot_complete_a_server_action(engine: DecisionEngine) -> None:
    response = ask(engine, "Write a note about the release")
    action = response.action_plan[0]
    assert action.tool == "note.write"
    assert action.state is ActionStatus.SUCCEEDED

    with pytest.raises(ConflictError) as excinfo:
        engine.complete_action("client", action.action_id, status="succeeded")

    assert "only a capability the client executes" in str(excinfo.value)


def test_a_client_cannot_complete_an_unknown_action(engine: DecisionEngine) -> None:
    with pytest.raises(NotFoundError):
        engine.complete_action("client", "does-not-exist", status="succeeded")


def test_a_client_cannot_complete_an_action_twice(engine: DecisionEngine) -> None:
    response = ask(engine, "Play a movie")
    action_id = response.action_plan[0].action_id

    engine.complete_action("client", action_id, status="succeeded", result={"ok": True})

    with pytest.raises(ConflictError):
        engine.complete_action("client", action_id, status="failed")


def test_a_client_action_cannot_stay_pending_forever(engine: DecisionEngine) -> None:
    response = ask(engine, "Play a movie")
    action = response.action_plan[0]

    deadline = (action.result or {}).get("client_deadline")
    assert isinstance(deadline, (int, float))
    assert deadline > time.time()

    # Nothing reported yet, so the action is still pending.
    assert engine.expire_client_actions() == []

    # Pretend the deadline has passed.
    expired = engine.expire_client_actions(now=time.time() + 1000)

    assert len(expired) == 1
    assert expired[0].action_id == action.action_id
    assert expired[0].state is ActionStatus.FAILED
    assert expired[0].error is not None
    assert expired[0].error.code == "client_timeout"
    assert expired[0].error.timeout is True


def test_a_server_action_is_never_expired_by_the_sweeper(engine: DecisionEngine) -> None:
    response = ask(engine, "Write a note about the release")
    action = response.action_plan[0]
    assert action.state is ActionStatus.SUCCEEDED

    assert engine.expire_client_actions(now=time.time() + 1000) == []


def test_the_completion_endpoint_is_reachable_over_http(client) -> None:
    response = client.post(
        "/api/v1/requests",
        headers={"X-Sidekick-Session-Id": "http-client"},
        json={
            "request_id": "req-http-client",
            "session_id": "http-client",
            "utterance": "Start chess",
        },
    )
    action_id = response.json()["action_plan"][0]["action_id"]

    completed = client.post(
        f"/api/v1/actions/{action_id}/complete",
        json={
            "session_id": "http-client",
            "status": "succeeded",
            "result": {"game": "chess"},
        },
    )

    assert completed.status_code == 200
    assert completed.json()["action"]["state"] == "succeeded"
    assert completed.json()["action"]["result"] == {"game": "chess"}


def test_the_completion_endpoint_refuses_a_server_action(client) -> None:
    response = client.post(
        "/api/v1/requests",
        headers={"X-Sidekick-Session-Id": "http-server"},
        json={
            "request_id": "req-http-server",
            "session_id": "http-server",
            "utterance": "Write a note about the release",
        },
    )
    action_id = response.json()["action_plan"][0]["action_id"]

    refused = client.post(
        f"/api/v1/actions/{action_id}/complete",
        json={"session_id": "http-server", "status": "succeeded"},
    )

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "conflict"
