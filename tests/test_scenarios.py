"""The product scenarios, end to end.

These are the flows the product vision names. They are written as behaviour
tests, not as a script of recognised sentences: the assertions check the
*state transitions* and the *effects*, so an implementation that only
recognised these exact strings would still fail them.
"""

from __future__ import annotations

import time

from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import ActionStatus, ResponseStatus, SidekickRequest


def ask(
    engine: DecisionEngine,
    utterance: str,
    *,
    session: str = "s1",
    request_id: str | None = None,
):
    return engine.handle(
        SidekickRequest(
            request_id=request_id or f"req-{utterance[:24]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_open_youtube_no_wait_open_spotify(engine: DecisionEngine, browser: list[str]) -> None:
    """The first destination is never opened."""
    response = ask(engine, "Open YouTube, no wait, open Spotify")

    assert response.status is ResponseStatus.SUCCEEDED
    assert browser == ["https://open.spotify.com"]
    assert [a.arguments.get("destination") for a in response.action_plan] == ["spotify"]


def test_the_stale_destination_is_superseded_not_just_ignored(
    engine: DecisionEngine, browser: list[str]
) -> None:
    """The superseded action stays visible - nothing is silently dropped."""
    response = ask(engine, "Open YouTube and then no wait open Spotify")

    assert len(response.action_plan) == 2
    first, second = response.action_plan
    assert first.state is ActionStatus.SUPERSEDED
    assert second.state is ActionStatus.SUCCEEDED
    assert first.superseded_by == second.action_id
    assert browser == ["https://open.spotify.com"]


def test_a_correction_can_switch_to_a_different_kind_of_action(
    engine: DecisionEngine,
) -> None:
    """A correction may replace an action with a control intent."""
    response = ask(engine, "Set a timer for 5 minutes, no wait pause it")

    tools = [action.tool for action in response.action_plan]
    assert "control.pause" in tools
    assert "timer.set" not in tools


def test_continue_what_i_was_doing_resumes_the_suspended_task(
    engine: DecisionEngine,
) -> None:
    started = ask(engine, "Set a timer for 5 minutes")
    assert started.status is ResponseStatus.RUNNING

    paused = ask(engine, "pause")
    assert paused.session is not None
    assert len(paused.session.suspended_task_ids) == 1

    resumed = ask(engine, "Continue what I was doing before")

    assert resumed.session is not None
    assert resumed.session.active_task_id is not None
    assert resumed.session.suspended_task_ids == []
    assert any(event.type == "task.resumed" for event in resumed.events)


def test_cancel_that_and_do_this_instead(engine: DecisionEngine) -> None:
    """The cancel happens *and* the new action happens."""
    ask(engine, "Set a timer for 5 minutes")

    response = ask(engine, "Cancel that and echo hello instead")

    tools = [action.tool for action in response.action_plan]
    assert "control.cancel" in tools
    assert "test.echo" in tools

    state = engine.sessions.peek("s1")
    assert state is not None
    timer_actions = [
        action for action in state.actions.values() if action.tool == "timer.set"
    ]
    assert timer_actions
    assert timer_actions[-1].state is ActionStatus.CANCELLED


def test_a_voice_yes_approves_the_exact_pending_action(engine: DecisionEngine) -> None:
    pending = ask(engine, "Delete everything")
    assert pending.status is ResponseStatus.AWAITING_CONFIRMATION
    action_id = pending.action_plan[0].action_id

    approved = ask(engine, "yes")

    target = next(a for a in approved.action_plan if a.action_id == action_id)
    assert target.state is ActionStatus.SUCCEEDED


def test_a_voice_no_refuses_the_pending_action(engine: DecisionEngine) -> None:
    pending = ask(engine, "Delete everything")
    action_id = pending.action_plan[0].action_id

    refused = ask(engine, "no")

    target = next(a for a in refused.action_plan if a.action_id == action_id)
    assert target.state is ActionStatus.CANCELLED


def test_approving_without_a_pending_action_says_so(engine: DecisionEngine) -> None:
    response = ask(engine, "yes")

    assert response.status is ResponseStatus.SUCCEEDED
    assert "nothing waiting for confirmation" in response.message


def test_a_confirmation_binds_to_the_action_that_is_still_pending(
    engine: DecisionEngine,
) -> None:
    """A second, different pending action is not approved by accident."""
    first = ask(engine, "Delete everything")
    first_id = first.action_plan[0].action_id

    second = ask(engine, "Wipe everything")
    second_id = next(
        action.action_id for action in second.action_plan if action.tool == "test.danger"
    )
    assert second_id != first_id

    approved = ask(engine, "yes")

    target = next(a for a in approved.action_plan if a.action_id == second_id)
    assert target.state is ActionStatus.SUCCEEDED

    state = engine.sessions.peek("s1")
    assert state is not None
    other = state.get_action(first_id)
    assert other is not None
    assert other.state is ActionStatus.AWAITING_CONFIRMATION
