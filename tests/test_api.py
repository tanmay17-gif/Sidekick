"""HTTP contract tests - the surface Agent 2 and Agent 3 build against."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient


def decide(client: TestClient, utterance: str, session: str = "api-session", request_id: str | None = None):
    return client.post(
        "/v1/decide",
        json={
            "request_id": request_id or f"req-{time.time_ns()}",
            "session_id": session,
            "utterance": utterance,
            "input_source": "text",
            "utterance_finalized": True,
        },
    )


def test_decide_returns_the_documented_envelope(client: TestClient) -> None:
    response = decide(client, "echo hello")
    assert response.status_code == 200

    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["session_id"] == "api-session"
    assert body["status"] == "succeeded"
    assert body["intent"]["normalized"] == "echo hello"
    assert body["action_plan"][0]["tool"] == "test.echo"
    assert body["action_plan"][0]["state"] == "succeeded"
    assert body["decision_model"]["provider"]
    assert "fallback_used" in body["decision_model"]
    assert isinstance(body["events"], list)
    assert body["session"]["session_id"] == "api-session"


def test_the_session_header_wins_over_the_body_field(client: TestClient) -> None:
    response = client.post(
        "/v1/decide",
        headers={"X-Sidekick-Session": "header-session"},
        json={
            "request_id": "req-header",
            "session_id": "body-session",
            "utterance": "echo hello",
        },
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "header-session"


def test_an_invalid_payload_returns_the_error_envelope(client: TestClient) -> None:
    response = client.post("/v1/decide", json={"utterance": "echo hello"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["retryable"] is False
    assert body["error"]["timeout"] is False
    assert body["error"]["details"]["errors"]


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/decide",
        json={
            "request_id": "req-extra",
            "session_id": "s",
            "utterance": "echo hello",
            "surprise": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_healthz_reports_the_model_truthfully(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["contract_version"] == "v1"
    assert "provider" in body["model"]
    assert "fallback_used" in body["model"]
    assert "test.echo" in body["tools"]


def test_the_tool_catalog_is_published(client: TestClient) -> None:
    response = client.get("/v1/tools")

    assert response.status_code == 200
    body = response.json()
    names = {tool["name"] for tool in body["tools"]}
    assert "test.echo" in names
    assert "test.echo" in body["available"]
    echo = next(tool for tool in body["tools"] if tool["name"] == "test.echo")
    assert echo["risk"] == "low"
    assert echo["arguments"][0]["name"] == "text"


def test_session_state_is_readable(client: TestClient) -> None:
    decide(client, "set a timer for 5 minutes", session="state-session")

    response = client.get("/v1/sessions/state-session")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["session_id"] == "state-session"
    assert body["tasks"]
    assert body["actions"][0]["tool"] == "timer.set"


def test_an_unknown_session_is_a_404(client: TestClient) -> None:
    response = client.get("/v1/sessions/does-not-exist")

    assert response.status_code == 404


def test_the_confirmation_endpoint_runs_the_action(client: TestClient) -> None:
    pending = decide(client, "delete everything", session="confirm-session").json()
    action_id = pending["action_plan"][0]["action_id"]

    response = client.post(
        f"/v1/actions/{action_id}/confirm",
        json={"session_id": "confirm-session", "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["action"]["state"] == "succeeded"


def test_a_stale_confirmation_is_a_conflict(client: TestClient) -> None:
    pending = decide(client, "delete everything", session="stale-session").json()
    action_id = pending["action_plan"][0]["action_id"]

    response = client.post(
        f"/v1/actions/{action_id}/confirm",
        json={
            "session_id": "stale-session",
            "approved": True,
            "plan_hash": "00000000000000000000000000000000",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_the_cancel_endpoint_cancels_one_action(client: TestClient) -> None:
    pending = decide(client, "delete everything", session="cancel-session").json()
    action_id = pending["action_plan"][0]["action_id"]

    response = client.post(
        f"/v1/actions/{action_id}/cancel",
        json={"session_id": "cancel-session"},
    )

    assert response.status_code == 200
    assert response.json()["action"]["state"] == "cancelled"


def test_the_events_endpoint_returns_the_session_log(client: TestClient) -> None:
    decide(client, "echo hello", session="events-session")

    response = client.get("/v1/sessions/events-session/events")

    assert response.status_code == 200
    types = {event["type"] for event in response.json()["events"]}
    assert "turn.received" in types


def test_the_index_page_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Sidekick" in response.text


# --------------------------------------------------------------------------
# Compatibility with the browser client (Agent 3) and the execution service
# (Agent 2). These paths and field names are already implemented on their
# side, so the core has to speak them exactly.
# --------------------------------------------------------------------------

BROWSER_PATHS = {
    "interpret": "/api/v1/requests",
    "capabilities": "/api/v1/capabilities",
    "action": "/api/v1/actions/{id}",
}


def test_the_browser_request_path_works(client: TestClient) -> None:
    response = client.post(
        BROWSER_PATHS["interpret"],
        json={
            "request_id": "req-browser",
            "session_id": "browser-session",
            "utterance": "echo hello",
            "input_source": "voice",
            "utterance_finalized": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action_plan"][0]["tool"] == "test.echo"


def test_the_browser_session_header_is_accepted(client: TestClient) -> None:
    response = client.post(
        BROWSER_PATHS["interpret"],
        headers={"x-sidekick-session-id": "browser-header-session"},
        json={
            "request_id": "req-browser-header",
            "session_id": "body-session",
            "utterance": "echo hello",
        },
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "browser-header-session"


def test_the_browser_correction_and_continuation_fields_are_accepted(client: TestClient) -> None:
    response = client.post(
        BROWSER_PATHS["interpret"],
        json={
            "request_id": "req-browser-context",
            "session_id": "browser-context-session",
            "utterance": "echo hello",
            "correction_context": {"signal": "no wait", "supersedes": "some-action"},
            "continuation_context": {"previous_request_id": "req-earlier"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


def test_the_capability_inventory_uses_both_vocabularies(client: TestClient) -> None:
    response = client.get(BROWSER_PATHS["capabilities"])

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["mode"] == "live"

    # The browser vocabulary.
    capabilities = {item["id"]: item for item in body["capabilities"]}
    assert capabilities["test.echo"]["state"] == "live"

    # The execution service vocabulary.
    tools = {item["tool"]: item for item in body["tools"]}
    assert tools["test.echo"]["status"] == "REAL"
    assert tools["test.echo"]["risk_level"] == "low"
    assert body["any_simulated"] is False
    assert body["tool_count"] == len(body["tools"])


def test_a_declared_but_unimplemented_capability_is_not_reported_as_live(
    client: TestClient,
) -> None:
    client.app.state.engine.registry.declare(
        __import__("sidekick.core.catalog", fromlist=["ToolSpec"]).ToolSpec(
            name="future.thing",
            description="declared only",
            aliases=("do the future thing",),
        )
    )

    body = client.get(BROWSER_PATHS["capabilities"]).json()
    capabilities = {item["id"]: item for item in body["capabilities"]}
    tools = {item["tool"]: item for item in body["tools"]}

    assert capabilities["future.thing"]["state"] == "unavailable"
    assert tools["future.thing"]["status"] == "NOT_IMPLEMENTED"


def test_a_single_action_can_be_read_by_id(client: TestClient) -> None:
    pending = decide(client, "delete everything", session="action-session").json()
    action_id = pending["action_plan"][0]["action_id"]

    response = client.get(f"{BROWSER_PATHS['action'].format(id=action_id)}?session_id=action-session")

    assert response.status_code == 200
    body = response.json()
    assert body["action"]["action_id"] == action_id
    assert body["action"]["state"] == "awaiting_confirmation"


def test_the_approve_alias_works(client: TestClient) -> None:
    pending = decide(client, "delete everything", session="approve-session").json()
    action_id = pending["action_plan"][0]["action_id"]

    response = client.post(
        f"/api/v1/actions/{action_id}/approve",
        json={"session_id": "approve-session", "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["action"]["state"] == "succeeded"


def test_the_request_endpoint_can_answer_with_an_event_stream(client: TestClient) -> None:
    response = client.post(
        BROWSER_PATHS["interpret"],
        headers={"accept": "text/event-stream"},
        json={
            "request_id": "req-sse",
            "session_id": "sse-session",
            "utterance": "echo hello",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [
        line[len("data: ") :]
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert frames
    final = json.loads(frames[-1])
    assert final["request_id"] == "req-sse"
    assert final["action_plan"][0]["tool"] == "test.echo"


def test_events_carry_the_sequence_and_the_ui_friendly_kind(client: TestClient) -> None:
    decide(client, "echo hello", session="seq-session")

    events = client.get("/v1/sessions/seq-session/events").json()["events"]

    assert events
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["kind"] for event in events)
    assert all("ts" in event for event in events)
