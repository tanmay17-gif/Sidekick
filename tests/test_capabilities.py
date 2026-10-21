"""Capability selection, discovery and the honest answers.

Every test in this module is a regression test for a failure that was
*reproduced against the running application* - see
``docs/DECISION_FAILURES.md``.
"""

from __future__ import annotations

import time

import pytest

from sidekick.core.decision import Decision, DecisionQuery
from sidekick.core.decisions.base import BaseDecisionModel
from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import (
    ActionStatus,
    DecisionSource,
    ResponseStatus,
    SidekickRequest,
)
from sidekick.tools.local import MEDIA_DESTINATIONS


def ask(engine: DecisionEngine, utterance: str, session: str = "cap"):
    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:24]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


# --------------------------------------------------------------------------
# Capability discovery
# --------------------------------------------------------------------------


def test_asking_what_the_product_can_do_returns_the_inventory(
    engine: DecisionEngine,
) -> None:
    """Reproduced failure: "What can you actually do?" was unresolvable."""
    response = ask(engine, "What can you actually do?")

    assert response.status is ResponseStatus.SUCCEEDED
    action = response.action_plan[0]
    assert action.tool == "control.capabilities"
    assert action.result is not None

    inventory = action.result["capabilities"]
    labels = {item["label"] for item in inventory}
    assert "write a note" in labels
    assert "search the web" in labels
    assert "set a reminder" in labels
    # The client side is named separately: the core did not run those.
    client_items = [item for item in inventory if item["state"] == "client"]
    assert {item["id"] for item in client_items} >= {"media.play", "movie.play", "game.start"}


def test_the_capability_question_is_not_mistaken_for_a_correction(
    engine: DecisionEngine,
) -> None:
    """The word "actually" is a correction marker - the question must still win."""
    response = ask(engine, "what can you actually do")

    assert response.action_plan[0].tool == "control.capabilities"


def test_the_capability_answer_names_what_the_server_and_the_client_do(
    engine: DecisionEngine,
) -> None:
    response = ask(engine, "What can you do?")

    assert response.speech is not None
    assert "write a note" in response.speech
    assert "in the app" in response.speech


# --------------------------------------------------------------------------
# The honest answer for a request the product cannot fulfil
# --------------------------------------------------------------------------


def test_an_unsupported_request_says_so_instead_of_guessing(engine: DecisionEngine) -> None:
    """Reproduced failure: every unsupported request produced the same
    "I did not catch which action you want" with a list of raw tool names."""
    response = ask(engine, "Order dinner for me")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert "do not have a capability" in response.clarification.question
    # The options are things a person can read, not internal names.
    assert "media.open" not in response.clarification.options
    assert "write a note" in response.clarification.options


def test_nonsense_gets_the_same_honest_answer(engine: DecisionEngine) -> None:
    response = ask(engine, "xyzzy plugh")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification is not None
    assert "do not have a capability" in response.clarification.question


# --------------------------------------------------------------------------
# Capability selection
# --------------------------------------------------------------------------


def test_a_generic_verb_does_not_hijack_a_specific_capability(
    engine: DecisionEngine,
) -> None:
    """Reproduced failure: "show me my notes" opened a browser."""
    response = ask(engine, "show me my notes")

    action = response.action_plan[0]
    assert action.tool == "note.read"
    assert action.state is ActionStatus.SUCCEEDED


def test_an_alias_matches_across_a_filler_word(engine: DecisionEngine) -> None:
    """Reproduced failure: "list my timers" did not match "list timers"."""
    response = ask(engine, "list my timers")

    assert response.action_plan[0].tool == "timer.list"


def test_a_plural_in_the_utterance_matches_a_singular_alias(
    engine: DecisionEngine,
) -> None:
    response = ask(engine, "read my notes")

    assert response.action_plan[0].tool == "note.read"


def test_the_model_may_not_introduce_a_capability_the_utterance_does_not_mention(
    engine: DecisionEngine,
) -> None:
    """Reproduced failure with the real model: "order dinner for me" and
    "xyzzy plugh" were both answered with a note reader, and they *succeeded*.

    The model is never allowed to name a capability the utterance does not
    mention, because its confidence is not calibrated for this answer space.
    """

    class ConfidentModel(BaseDecisionModel):
        provider = "test"
        model = "confident-but-wrong"

        def _decide(self, query: DecisionQuery) -> Decision:
            return Decision(
                tool="note.read",
                confidence=0.99,
                source=DecisionSource.MODEL,
            )

    engine.primary_model = ConfidentModel()

    for utterance in ("Order dinner for me", "xyzzy plugh"):
        response = ask(engine, utterance, session=f"anchor-{utterance[:6]}")
        assert response.action_plan[0].tool == "unresolved"
        assert response.action_plan[0].error is not None
        assert response.action_plan[0].error.code == "intent_not_resolved"


def test_the_model_may_choose_between_the_capabilities_the_utterance_supports(
    engine: DecisionEngine,
) -> None:
    """The model is anchored, not ignored: when the utterance supports the
    capability it names, its choice stands."""

    class NoteModel(BaseDecisionModel):
        provider = "test"
        model = "agrees"

        def _decide(self, query: DecisionQuery) -> Decision:
            return Decision(
                tool="note.read",
                confidence=0.9,
                source=DecisionSource.MODEL,
            )

    engine.primary_model = NoteModel()

    response = ask(engine, "read my notes")

    assert response.action_plan[0].tool == "note.read"
    assert response.decision_model.source is DecisionSource.MODEL


def test_a_destination_must_be_mentioned_in_the_utterance(
    engine: DecisionEngine, browser: list[str]
) -> None:
    """Reproduced failure with the real model: a nonsense utterance was
    answered with "Opening Google"."""

    class InventingModel(BaseDecisionModel):
        provider = "test"
        model = "invents-destinations"

        def _decide(self, query: DecisionQuery) -> Decision:
            return Decision(
                tool="media.open",
                destination="google",
                destination_confidence=0.99,
                confidence=0.95,
                source=DecisionSource.MODEL,
            )

    engine.primary_model = InventingModel()

    response = ask(engine, "xyzzy plugh")

    # The model named a capability the utterance never mentions, so it is
    # rejected: nothing is opened and nothing is claimed.
    assert browser == []
    assert response.action_plan[0].tool == "unresolved"
    assert response.action_plan[0].error is not None
    assert response.action_plan[0].error.code == "intent_not_resolved"


# --------------------------------------------------------------------------
# The capabilities that were missing
# --------------------------------------------------------------------------


def test_a_web_search_opens_a_real_search(engine: DecisionEngine, browser: list[str]) -> None:
    response = ask(engine, "search the web for python tutorials")

    action = response.action_plan[0]
    assert action.tool == "web.search"
    assert action.state is ActionStatus.SUCCEEDED
    assert action.result is not None
    assert action.result["query"] == "python tutorials"
    assert browser == ["https://www.google.com/search?q=python+tutorials"]


def test_a_search_is_not_a_booking(engine: DecisionEngine, browser: list[str]) -> None:
    """Searching for flights is a search - the core does not book anything."""
    response = ask(engine, "search for flights to Delhi next Friday")

    action = response.action_plan[0]
    assert action.tool == "web.search"
    assert "flights to Delhi next Friday" in action.result["query"]
    assert len(browser) == 1
    assert browser[0].startswith("https://www.google.com/search?q=")


def test_a_reminder_is_scheduled_for_the_requested_moment(engine: DecisionEngine) -> None:
    response = ask(engine, "Remind me to call my friend at 6 PM")

    action = response.action_plan[0]
    assert action.tool == "reminder.set"
    assert action.state is ActionStatus.RUNNING
    assert action.arguments["text"] == "call my friend"
    assert "6" in action.arguments["at"]
    assert action.result is not None
    assert action.result["reminder"] == "call my friend"
    assert action.result["due_at"]


def test_a_reminder_does_not_inherit_the_previous_reminders_time(
    engine: DecisionEngine,
) -> None:
    """A time the user did not say again must not be carried over."""
    ask(engine, "remind me to call mom at 6 pm")
    response = ask(engine, "remind me to take the bread out in 20 minutes")

    action = response.action_plan[0]
    assert action.arguments["text"] == "take the bread out"
    assert "20 minutes" in action.arguments["at"]


def test_the_spoken_reminder_repeats_the_moment_it_understood(
    engine: DecisionEngine,
) -> None:
    response = ask(engine, "remind me to call mom at 6 pm")

    # The spoken line repeats the moment the way the user said it.
    assert response.speech == "Reminder set for 6 pm."


# --------------------------------------------------------------------------
# Capabilities the browser client executes
# --------------------------------------------------------------------------


def test_a_client_capability_is_planned_for_the_client_and_not_executed(
    engine: DecisionEngine,
) -> None:
    """Reproduced failure: the core claimed it could play music and movies
    while having no adapter for either."""
    response = ask(engine, "Play some relaxing music")

    action = response.action_plan[0]
    assert action.tool == "media.play"
    assert action.state is ActionStatus.PENDING
    assert action.result is not None
    assert action.result["execution_target"] == "client"
    assert action.result["status"] == "awaiting_client"


def test_the_client_reports_the_real_outcome(engine: DecisionEngine) -> None:
    response = ask(engine, "find a good movie for tonight")
    action = response.action_plan[0]
    assert action.tool == "movie.play"

    completed = engine.complete_action(
        "cap",
        action.action_id,
        status="succeeded",
        result={"playing": "tears-of-steel"},
    )

    assert completed.state is ActionStatus.SUCCEEDED
    assert completed.result == {"playing": "tears-of-steel"}


def test_a_client_failure_is_recorded_as_a_failure(engine: DecisionEngine) -> None:
    from sidekick.core.schemas import ActionError

    response = ask(engine, "start chess")
    action = response.action_plan[0]

    completed = engine.complete_action(
        "cap",
        action.action_id,
        status="failed",
        error=ActionError(code="client_failed", message="the game could not start"),
    )

    assert completed.state is ActionStatus.FAILED
    assert completed.error is not None
    assert completed.error.code == "client_failed"


def test_the_capability_report_separates_the_server_the_client_and_the_missing(
    client,
) -> None:
    """The server side keeps the state vocabulary the browser already renders.

    The browser client has a fixed map of states, so a capability the *client*
    runs is reported in its own list instead of inventing a new state value.
    """
    body = client.get("/api/v1/capabilities").json()

    by_id = {item["id"]: item for item in body["capabilities"]}
    assert by_id["note.write"]["state"] == "live"
    # The server side only reports what the server runs.
    assert "media.play" not in by_id

    client_side = {item["id"]: item for item in body["client_capabilities"]}
    assert client_side["media.play"]["state"] == "client"
    assert client_side["media.play"]["execution_target"] == "client"
    assert client_side["media.play"]["owner"] == "agent3"

    tools = {item["tool"]: item for item in body["tools"]}
    assert tools["note.write"]["status"] == "REAL"
    # A client capability is not in the server's tool report.
    assert "media.play" not in tools


def test_the_server_states_stay_inside_the_vocabulary_the_browser_renders(
    client,
) -> None:
    """Agent 3's UI maps a fixed set of states; the core must not exceed it."""
    body = client.get("/api/v1/capabilities").json()
    known = {"live", "simulated", "unavailable", "unconfigured", "disconnected"}

    assert {item["state"] for item in body["capabilities"]} <= known


def test_every_destination_opens_a_real_url(engine: DecisionEngine, browser: list[str]) -> None:
    for destination in MEDIA_DESTINATIONS:
        ask(engine, f"open {destination}", session=f"dest-{destination}")
    assert len(browser) == len(MEDIA_DESTINATIONS)
    assert all(url.startswith("https://") for url in browser)
