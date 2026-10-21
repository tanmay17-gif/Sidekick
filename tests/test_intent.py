"""Intent classification, corrections, multi-action requests and parameters."""

from __future__ import annotations

from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import ActionStatus, ResponseStatus, SidekickRequest


def ask(engine: DecisionEngine, utterance: str, *, session: str = "s1", request_id: str | None = None):
    request = SidekickRequest(
        request_id=request_id or f"req-{utterance[:24]}-{session}",
        session_id=session,
        utterance=utterance,
    )
    return engine.handle(request)


def test_ordinary_request_is_classified(engine: DecisionEngine) -> None:
    response = ask(engine, "echo hello there")

    assert response.status is ResponseStatus.SUCCEEDED
    assert len(response.action_plan) == 1
    action = response.action_plan[0]
    assert action.tool == "test.echo"
    assert action.state is ActionStatus.SUCCEEDED
    assert action.arguments == {"text": "hello there"}
    assert action.result == {"echoed": "hello there"}


def test_request_is_not_executed_while_the_transcript_is_unstable(engine: DecisionEngine) -> None:
    response = engine.handle(
        SidekickRequest(
            request_id="req-partial",
            session_id="s1",
            utterance="echo hel",
            utterance_finalized=False,
        )
    )

    assert response.status is ResponseStatus.AWAITING_TRANSCRIPT
    assert response.action_plan == []
    assert any(event.type == "turn.deferred" for event in response.events)


def test_destination_is_resolved_from_the_catalog(engine: DecisionEngine) -> None:
    response = ask(engine, "open youtube")

    action = response.action_plan[0]
    assert action.tool == "media.open"
    assert action.arguments == {"destination": "youtube"}


def test_mid_request_correction_replaces_the_destination(
    engine: DecisionEngine, browser: list[str]
) -> None:
    response = ask(engine, "open spotify, no wait, open youtube")

    assert response.status is ResponseStatus.SUCCEEDED
    assert len(response.action_plan) == 1
    action = response.action_plan[0]
    assert action.tool == "media.open"
    assert action.arguments == {"destination": "youtube"}
    # The superseded destination was never opened.
    assert browser == ["https://www.youtube.com"]


def test_correction_inside_a_multi_action_request_supersedes_the_first_action(
    engine: DecisionEngine, browser: list[str]
) -> None:
    response = ask(engine, "open spotify and then no wait open youtube")

    tools = [action.tool for action in response.action_plan]
    assert tools == ["media.open", "media.open"]
    assert response.action_plan[0].state is ActionStatus.SUPERSEDED
    assert response.action_plan[1].state is ActionStatus.SUCCEEDED
    assert response.action_plan[0].superseded_by == response.action_plan[1].action_id
    assert browser == ["https://www.youtube.com"]


def test_multi_action_request_executes_every_segment_in_order(engine: DecisionEngine) -> None:
    response = ask(engine, "echo first and then echo second")

    assert response.intent.multi_action is True
    assert [a.arguments.get("text") for a in response.action_plan] == ["first", "second"]
    assert all(a.state is ActionStatus.SUCCEEDED for a in response.action_plan)


def test_multi_action_request_never_drops_a_segment(engine: DecisionEngine) -> None:
    response = ask(engine, "echo one, and echo two, and echo three")

    assert len(response.action_plan) == 3
    assert [a.arguments.get("text") for a in response.action_plan] == ["one", "two", "three"]


def test_missing_parameter_produces_a_clarification(engine: DecisionEngine) -> None:
    response = ask(engine, "echo")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert response.clarification.missing_arguments == ["text"]
    assert "text" in response.clarification.question


def test_unknown_request_produces_a_clarification_with_options(engine: DecisionEngine) -> None:
    response = ask(engine, "do something completely unrelated")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert response.clarification.options
    assert response.action_plan[0].error is not None
    assert response.action_plan[0].error.code == "intent_not_resolved"


def test_closed_enumeration_rejects_values_outside_the_set(engine: DecisionEngine) -> None:
    response = ask(engine, "run the job in a weird way")

    # "weird" is not part of the enum, so the value is missing, not guessed.
    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert response.clarification.missing_arguments == ["mode"]


def test_enumeration_value_is_bound_when_present(engine: DecisionEngine) -> None:
    response = ask(engine, "run the job fast")

    action = response.action_plan[0]
    assert action.tool == "test.mode"
    assert action.arguments == {"mode": "fast"}


def test_utterance_is_normalized_in_the_intent(engine: DecisionEngine) -> None:
    response = ask(engine, "Please, echo   HELLO!")

    assert response.intent.normalized == "echo hello"
    # The captured value keeps the user's own wording, without the trailing
    # punctuation that belongs to the sentence, not to the value.
    assert response.action_plan[0].arguments == {"text": "HELLO"}
