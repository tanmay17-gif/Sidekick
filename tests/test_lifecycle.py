"""Interruption, suspension, resumption, cancellation and superseding."""

from __future__ import annotations

import time

from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import ActionStatus, ResponseStatus, SidekickRequest


def ask(engine: DecisionEngine, utterance: str, *, session: str = "s1", request_id: str | None = None):
    return engine.handle(
        SidekickRequest(
            request_id=request_id or f"req-{utterance[:24]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_running_action_can_be_cancelled(engine: DecisionEngine) -> None:
    started = ask(engine, "set a timer for 5 minutes")
    assert started.status is ResponseStatus.RUNNING

    cancelled = ask(engine, "cancel that")

    assert cancelled.status is ResponseStatus.CANCELLED
    target = next(a for a in cancelled.action_plan if a.tool == "timer.set")
    assert target.state is ActionStatus.CANCELLED
    # The control itself is reported as well, so the UI can show what happened.
    assert any(a.tool == "control.cancel" for a in cancelled.action_plan)


def test_cancellation_of_an_uncancellable_action_is_reported_honestly(
    engine: DecisionEngine,
) -> None:
    started = ask(engine, "start the long job")
    assert started.status is ResponseStatus.RUNNING

    cancelled = ask(engine, "cancel that")

    action = next(a for a in cancelled.action_plan if a.tool == "test.uncancellable")
    assert action.state is ActionStatus.PAUSED
    assert action.error is not None
    assert action.error.code == "cancellation_unsupported"
    assert "may still be running" in action.error.message


def test_task_can_be_paused_and_resumed(engine: DecisionEngine) -> None:
    started = ask(engine, "set a timer for 5 minutes")
    assert started.status is ResponseStatus.RUNNING

    paused = ask(engine, "pause")
    assert paused.session is not None
    assert paused.session.active_task_id is None
    assert len(paused.session.suspended_task_ids) == 1

    resumed = ask(engine, "continue")
    assert resumed.session is not None
    assert resumed.session.active_task_id is not None
    assert resumed.session.suspended_task_ids == []
    assert resumed.action_plan[0].tool == "timer.set"
    assert resumed.action_plan[0].state is ActionStatus.RUNNING
    assert any(event.type == "task.resumed" for event in resumed.events)


def test_resume_does_not_replay_completed_steps(engine: DecisionEngine) -> None:
    done = ask(engine, "echo hello")
    assert done.status is ResponseStatus.SUCCEEDED

    resumed = ask(engine, "continue")

    assert resumed.action_plan == []
    assert "already finished" in resumed.message


def test_pending_confirmation_is_superseded_by_a_correction(engine: DecisionEngine) -> None:
    pending = ask(engine, "delete everything")
    assert pending.status is ResponseStatus.AWAITING_CONFIRMATION
    pending_id = pending.action_plan[0].action_id

    corrected = ask(engine, "no wait, echo hello")

    assert corrected.status is ResponseStatus.SUCCEEDED
    state = engine.sessions.peek("s1")
    assert state is not None
    old = state.get_action(pending_id)
    assert old is not None
    assert old.state is ActionStatus.SUPERSEDED
    assert old.superseded_by == corrected.action_plan[0].action_id


def test_pending_actions_are_visible_and_individually_cancellable(engine: DecisionEngine) -> None:
    pending = ask(engine, "delete everything")
    action_id = pending.action_plan[0].action_id

    state = engine.sessions.peek("s1")
    assert state is not None
    assert action_id in [a.action_id for a in state.awaiting_confirmation_actions()]

    cancelled = engine.cancel_action("s1", action_id)
    assert cancelled.state is ActionStatus.CANCELLED


def test_background_work_reports_its_outcome(engine: DecisionEngine) -> None:
    started = ask(engine, "set a timer for 1 second")
    assert started.status is ResponseStatus.RUNNING
    action_id = started.action_plan[0].action_id

    deadline = time.time() + 5
    state = engine.sessions.peek("s1")
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
    assert action.result["fired"] is True
    assert any(event.type == "action.succeeded" for event in state.events)
