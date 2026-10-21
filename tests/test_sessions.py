"""Session isolation and bounded retention."""

from __future__ import annotations

from sidekick.core.engine import DecisionEngine
from sidekick.core.sessions import SessionStore
from sidekick.core.schemas import ActionStatus, ResponseStatus, SidekickRequest


def ask(engine: DecisionEngine, utterance: str, session: str, request_id: str):
    return engine.handle(
        SidekickRequest(request_id=request_id, session_id=session, utterance=utterance)
    )


def test_two_sessions_do_not_see_each_others_work(engine: DecisionEngine) -> None:
    first = ask(engine, "set a timer for 5 minutes", "session-a", "a-1")
    second = ask(engine, "what is pending?", "session-b", "b-1")

    assert first.status is ResponseStatus.RUNNING
    assert second.action_plan[0].tool == "control.status"
    assert "timer.set" not in (second.action_plan[0].result or {}).get("message", "")
    assert second.session is not None
    assert second.session.pending_action_ids == []

    # The first session still owns its running action.
    assert first.session is not None
    assert first.session.active_task_id is not None


def test_sessions_do_not_share_the_last_tool(engine: DecisionEngine) -> None:
    ask(engine, "echo hello", "session-a", "a-1")
    response = ask(engine, "echo again", "session-b", "b-1")

    assert response.action_plan[0].arguments == {"text": "again"}


def test_session_state_is_isolated_between_two_live_sessions(engine: DecisionEngine) -> None:
    ask(engine, "echo alpha", "left", "l-1")
    ask(engine, "echo beta", "right", "r-1")

    left = engine.sessions.peek("left")
    right = engine.sessions.peek("right")

    assert left is not None and right is not None
    assert left is not right
    assert [a.arguments["text"] for a in left.actions.values()] == ["alpha"]
    assert [a.arguments["text"] for a in right.actions.values()] == ["beta"]


def test_store_drops_idle_sessions() -> None:
    store = SessionStore(ttl_seconds=0)
    store.get("gone")
    store.get("also-gone")

    # ttl 0 means every session is immediately stale.
    assert store.get("gone") is not None
    assert store.session_count <= 1


def test_store_is_bounded() -> None:
    store = SessionStore(max_sessions=3)
    for index in range(10):
        store.get(f"session-{index}")

    assert store.session_count == 3


def test_repeated_request_id_replays_the_same_answer(engine: DecisionEngine) -> None:
    first = ask(engine, "echo hello", "s1", "same-id")
    second = ask(engine, "echo something else", "s1", "same-id")

    assert second.action_plan[0].arguments == first.action_plan[0].arguments
    assert any(event.type == "request.replayed" for event in second.events)


def test_session_view_exposes_pending_actions(engine: DecisionEngine) -> None:
    response = ask(engine, "set a timer for 30 seconds", "s1", "r-1")

    assert response.session is not None
    assert len(response.session.pending_action_ids) == 0
    state = engine.sessions.peek("s1")
    assert state is not None
    running = [a for a in state.actions.values() if a.state is ActionStatus.RUNNING]
    assert len(running) == 1
