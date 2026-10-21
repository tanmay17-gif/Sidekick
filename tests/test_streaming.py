"""Live event streaming for long running actions."""

from __future__ import annotations

import json
import threading
import time

from fastapi.testclient import TestClient

from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import ActionStatus, SidekickRequest


def start_timer(engine: DecisionEngine, session: str = "stream-session", seconds: int = 1):
    request = SidekickRequest(
        request_id="stream-req",
        session_id=session,
        utterance=f"set a timer for {seconds} second",
    )
    return engine.handle(request)


def test_the_action_event_stream_follows_a_running_action(client: TestClient) -> None:
    """A client that subscribes sees the completion event as it happens."""
    engine = client.app.state.engine
    started = start_timer(engine, "live-session", 1)
    action_id = started.action_plan[0].action_id

    frames: list[dict] = []
    errors: list[Exception] = []

    def read_stream() -> None:
        try:
            with client.stream(
                "GET",
                f"/api/v1/actions/{action_id}/events?session_id=live-session&timeout=10",
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    frames.append(json.loads(line[len("data: ") :]))
        except Exception as exc:  # noqa: BLE001 - reported through `errors`
            errors.append(exc)

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    reader.join(timeout=20)

    assert not errors
    assert frames, "the stream produced no frames"
    types = [frame.get("type") for frame in frames if "type" in frame]
    assert "action.succeeded" in types
    seqs = [frame["seq"] for frame in frames if "seq" in frame]
    assert seqs == sorted(seqs)


def test_the_action_event_stream_can_resume_after_a_sequence_number(
    client: TestClient,
) -> None:
    engine = client.app.state.engine
    started = start_timer(engine, "resume-session", 1)
    action_id = started.action_plan[0].action_id

    # Let the action finish first.
    deadline = time.time() + 5
    state = engine.sessions.peek("resume-session")
    while time.time() < deadline:
        assert state is not None
        action = state.get_action(action_id)
        if action is not None and action.state is ActionStatus.SUCCEEDED:
            break
        time.sleep(0.05)

    assert state is not None
    events = state.events
    assert events
    last_seq = events[-1].seq

    response = client.get(
        f"/api/v1/actions/{action_id}/events?session_id=resume-session&after={last_seq}&timeout=0.2"
    )

    assert response.status_code == 200
    frames = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    # No new *event* was replayed, but the final action state is still sent.
    assert [frame for frame in frames if "type" in frame] == []
    assert frames[-1]["action"]["action_id"] == action_id
    assert frames[-1]["action"]["state"] == "succeeded"


def test_an_unknown_action_stream_is_a_404(client: TestClient) -> None:
    response = client.get("/api/v1/actions/nope/events?session_id=whatever")

    assert response.status_code == 404
