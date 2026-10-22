"""Intent routing: explicit requests, paraphrases, typos, ambiguity, follow-ups.

Every test here is a behaviour test - it asserts what the user ends up with,
not which internal layer decided. The rules the product holds itself to:

- never execute an unrelated capability because a model was confident;
- never turn an uncertain request into a false success;
- do not force a capability match when the utterance lacks the evidence;
- ask a concise clarification when several interpretations are plausible,
  otherwise state the limitation honestly;
- the user does not have to say a capability's exact catalog alias.
"""

from __future__ import annotations

import time

import pytest

from sidekick.core.decision import Decision, DecisionQuery
from sidekick.core.decisions.base import BaseDecisionModel
from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import ActionStatus, DecisionSource, ResponseStatus, SidekickRequest


def ask(engine: DecisionEngine, utterance: str, session: str = "route"):
    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:24]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def tools_of(response) -> list[str]:
    return [action.tool for action in response.action_plan]


# --------------------------------------------------------------------------
# Explicit requests and paraphrases
# --------------------------------------------------------------------------


def test_an_explicit_request_is_executed(engine: DecisionEngine) -> None:
    response = ask(engine, "write a note about the release")

    assert tools_of(response) == ["note.write"]
    assert response.action_plan[0].state is ActionStatus.SUCCEEDED


@pytest.mark.parametrize(
    "utterance",
    [
        "can you write me a note about the release",
        "please write down a note about the release",
        "save a note about the release",
        "take a note about the release",
    ],
)
def test_a_paraphrase_reaches_the_same_capability(
    engine: DecisionEngine, utterance: str
) -> None:
    """The user must not have to say the exact catalog alias."""
    response = ask(engine, utterance, session=f"para-{utterance[:12]}")

    assert tools_of(response) == ["note.write"]
    assert response.action_plan[0].state is ActionStatus.SUCCEEDED


def test_a_typo_in_a_service_name_is_resolved(engine: DecisionEngine) -> None:
    response = ask(engine, "open spotfy", session="typo")

    assert tools_of(response) == ["media.open"]
    assert response.action_plan[0].arguments == {"destination": "spotify"}


def test_a_typo_outside_a_known_name_is_not_guessed(engine: DecisionEngine) -> None:
    response = ask(engine, "open spotflix", session="typo2")

    # "spotflix" is one edit away from two different services, so nothing is
    # guessed - the user is asked which one.
    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None


# --------------------------------------------------------------------------
# Corrections
# --------------------------------------------------------------------------


def test_a_destination_correction_keeps_the_corrected_intent(
    engine: DecisionEngine, browser: list[str]
) -> None:
    response = ask(engine, "No, I meant Spotify, not YouTube", session="corr1")

    assert tools_of(response) == ["media.open"]
    assert response.action_plan[0].arguments == {"destination": "spotify"}
    assert browser == ["https://open.spotify.com"]


def test_a_correction_after_a_fulfilled_request_supersedes_it(
    engine: DecisionEngine, browser: list[str]
) -> None:
    ask(engine, "open youtube", session="corr2")
    response = ask(engine, "no wait, open spotify", session="corr2")

    assert response.action_plan[0].arguments == {"destination": "spotify"}
    # The first request legitimately opened YouTube; the correction opened
    # Spotify and did not open YouTube a second time.
    assert browser == ["https://www.youtube.com", "https://open.spotify.com"]


def test_a_contextual_follow_up_keeps_the_capability_and_changes_the_time(
    engine: DecisionEngine,
) -> None:
    """"Actually, tomorrow at 9" after a reminder is the same reminder, later."""
    first = ask(engine, "remind me to call mom at 6 pm", session="follow")
    assert tools_of(first) == ["reminder.set"]

    second = ask(engine, "Actually, tomorrow at 9", session="follow")

    assert tools_of(second) == ["reminder.set"]
    action = second.action_plan[0]
    assert action.arguments["at"] == "tomorrow at 9"
    # The subject of the reminder is remembered.
    assert action.arguments["text"] == "call mom"


def test_a_correction_that_names_nothing_does_not_invent_a_capability(
    engine: DecisionEngine,
) -> None:
    """"never mind" drops the pending work; it does not start something else."""
    ask(engine, "set a timer for 5 minutes", session="corr3")
    response = ask(engine, "actually, never mind", session="corr3")

    assert "control.cancel" in tools_of(response)
    # The timer that was running is gone, and nothing else was started.
    state = engine.sessions.peek("corr3")
    assert state is not None
    timer_actions = [a for a in state.actions.values() if a.tool == "timer.set"]
    assert timer_actions
    assert timer_actions[-1].state is ActionStatus.CANCELLED


# --------------------------------------------------------------------------
# Unsupported requests
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utterance",
    [
        "book a flight to Delhi next Friday",
        "order me a pizza",
        "transfer 200 euros to my friend",
        "book a table for two tonight",
    ],
)
def test_a_request_without_a_real_capability_is_refused_honestly(
    engine: DecisionEngine, utterance: str
) -> None:
    """These need a provider, an account and a money policy. None exists."""
    response = ask(engine, utterance, session=f"unsup-{utterance[:10]}")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.action_plan[0].tool == "unresolved"
    assert response.action_plan[0].state is ActionStatus.FAILED
    assert response.clarification is not None
    assert "do not have a capability" in response.clarification.question


def test_nonsense_is_refused_honestly(engine: DecisionEngine) -> None:
    response = ask(engine, "xyzzy plugh", session="nonsense")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.action_plan[0].error is not None
    assert response.action_plan[0].error.code == "intent_not_resolved"


def test_a_refused_request_does_not_touch_any_adapter(
    engine: DecisionEngine, browser: list[str]
) -> None:
    ask(engine, "book a flight to Delhi", session="refuse")

    assert browser == []


# --------------------------------------------------------------------------
# Ambiguity
# --------------------------------------------------------------------------


def test_a_request_that_could_be_two_capabilities_asks_rather_than_guesses(
    engine: DecisionEngine,
) -> None:
    """Two capabilities match and the utterance does not say which."""
    response = ask(engine, "set the thing", session="ambig")

    # The honest answer: no capability, and a request for the missing piece.
    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None


def test_a_specific_capability_wins_over_a_generic_verb(engine: DecisionEngine) -> None:
    """"play chess" is the game, not the music player."""
    response = ask(engine, "play chess", session="ambig2")

    assert tools_of(response) == ["game.start"]
    assert response.action_plan[0].state is ActionStatus.PENDING


def test_a_missing_argument_asks_for_exactly_that(engine: DecisionEngine) -> None:
    response = ask(engine, "open", session="ambig3")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert "destination" in response.clarification.question


# --------------------------------------------------------------------------
# The model may not invent anything
# --------------------------------------------------------------------------


class _ConfidentInventor(BaseDecisionModel):
    """A model that is certain about everything, including nonsense."""

    provider = "test"
    model = "confident-inventor"

    def __init__(self, tool: str) -> None:
        super().__init__()
        self._tool = tool

    def _decide(self, query: DecisionQuery) -> Decision:
        return Decision(
            tool=self._tool,
            confidence=0.99,
            source=DecisionSource.MODEL,
        )


@pytest.mark.parametrize(
    "utterance",
    [
        "book a flight to Delhi",
        "order me a pizza",
        "xyzzy plugh",
        "transfer 200 euros",
    ],
)
def test_a_confident_model_cannot_execute_an_unrelated_capability(
    engine: DecisionEngine, utterance: str
) -> None:
    engine.primary_model = _ConfidentInventor("note.write")

    response = ask(engine, utterance, session=f"invent-{utterance[:10]}")

    assert response.action_plan[0].tool == "unresolved"
    assert response.action_plan[0].state is ActionStatus.FAILED
    assert response.action_plan[0].error is not None
    assert response.action_plan[0].error.code == "intent_not_resolved"


def test_a_confident_model_cannot_make_an_unsupported_request_succeed(
    engine: DecisionEngine,
) -> None:
    engine.primary_model = _ConfidentInventor("web.search")

    response = ask(engine, "order me a pizza", session="invent2")

    assert response.action_plan[0].tool == "unresolved"
    assert response.status is ResponseStatus.NEEDS_CLARIFICATION


def test_the_model_may_still_choose_between_supported_capabilities(
    engine: DecisionEngine,
) -> None:
    """The anchor must not turn the model into a no-op."""
    engine.primary_model = _ConfidentInventor("note.write")

    response = ask(engine, "write a note about the release", session="invent3")

    assert tools_of(response) == ["note.write"]
    assert response.action_plan[0].state is ActionStatus.SUCCEEDED


def test_the_provenance_says_when_the_model_was_not_believed(
    engine: DecisionEngine,
) -> None:
    engine.primary_model = _ConfidentInventor("note.write")

    response = ask(engine, "order me a pizza", session="invent4")

    info = response.decision_model
    assert info.source is DecisionSource.RULE
    assert info.fallback_used is True
    assert info.fallback_reason
