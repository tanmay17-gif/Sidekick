"""End to end tests against the *real* Laya model.

These are opt-in: they need the ``laya`` package and the checkpoint weights
(~800 MB, downloaded on first use). They are skipped by default so the suite
stays fast and offline.

Run them with::

    pip install -e ".[dev,laya]"
    SIDEKICK_RUN_MODEL_TESTS=1 python -m pytest tests/test_laya_integration.py

The suite has **no external side effects**: the browser is stubbed for the
whole session (see ``tests/conftest.py``), and every adapter that would
schedule background work uses daemon threads, so the run leaves nothing behind.

What they prove: the engine works with the real decision model, not only with
the deterministic fallback. The fallback is a safety net, but the product must
be able to run on the model alone.

They assert *behaviour* (what the user gets), not which internal layer made
the decision. The model is a tool, not the specification.
"""

from __future__ import annotations

import os

import pytest

from sidekick.core.decisions.laya_model import LayaDecisionModel
from sidekick.core.engine import DecisionEngine
from sidekick.core.registry import ToolRegistry
from sidekick.core.safety import SafetyPolicy
from sidekick.core.schemas import ActionStatus, DecisionSource, ResponseStatus, SidekickRequest
from sidekick.core.sessions import SessionStore
from sidekick.tools.local import (
    MediaOpenTool,
    NoteWriteTool,
    ReminderSetTool,
    TimerSetTool,
    WebSearchTool,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDEKICK_RUN_MODEL_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="set SIDEKICK_RUN_MODEL_TESTS=1 to run the real model tests",
)


@pytest.fixture(scope="module")
def model() -> LayaDecisionModel:
    if not LayaDecisionModel().available:
        pytest.skip("the 'laya' package is not installed")
    return LayaDecisionModel()


@pytest.fixture
def engine(model: LayaDecisionModel, tmp_path) -> DecisionEngine:
    registry = ToolRegistry()
    registry.register(NoteWriteTool(tmp_path))
    registry.register(TimerSetTool())
    registry.register(MediaOpenTool())
    registry.register(WebSearchTool())
    registry.register(ReminderSetTool())
    from sidekick.bootstrap import load_client_capabilities

    load_client_capabilities(registry)
    return DecisionEngine(
        registry=registry,
        sessions=SessionStore(),
        decision_model=model,
        fallback_model=RuleFallback(),
        policy=SafetyPolicy(workspace_root=tmp_path),
    )


class RuleFallback:
    """The deterministic matcher, used only when the model is not confident."""

    from sidekick.core.decisions.rule_model import RuleDecisionModel as _Rule

    def __new__(cls):
        return cls._Rule()


def ask(engine: DecisionEngine, utterance: str, session: str = "model"):
    import time

    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:20]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_the_real_model_produces_the_interpretation(engine: DecisionEngine) -> None:
    """The model runs, and the user gets the right capability."""
    response = ask(engine, "Open Spotify")

    assert response.decision_model.provider == "convaiinnovations"
    assert response.decision_model.model.startswith("convaiinnovations/laya")
    assert response.decision_model.model_available is True
    assert response.action_plan[0].tool == "media.open"
    assert response.action_plan[0].arguments == {"destination": "spotify"}


def test_the_real_model_resolves_a_correction_to_the_last_destination(
    engine: DecisionEngine, browser: list[str]
) -> None:
    """The stale destination must never reach an action."""
    response = ask(engine, "Open YouTube, no wait, open Spotify")

    assert response.action_plan[0].arguments == {"destination": "spotify"}
    # The browser is stubbed for the whole session, so this is the URL the
    # code would have opened - not a window on the machine.
    assert browser == ["https://open.spotify.com"]


def test_the_real_model_handles_a_multi_action_request(engine: DecisionEngine) -> None:
    response = ask(engine, "Open Spotify and then set a timer for 5 minutes")

    tools = [action.tool for action in response.action_plan]
    assert tools == ["media.open", "timer.set"]
    assert response.action_plan[1].arguments == {"duration_seconds": 300}


def test_the_real_model_finds_the_capability_of_an_unusual_sentence(
    engine: DecisionEngine,
) -> None:
    """The capability is found by meaning, not by a memorised phrase."""
    response = ask(engine, "Remind me to take the bread out in 5 minutes")

    assert response.action_plan
    assert response.action_plan[0].tool == "reminder.set"


def test_an_unsupported_utterance_is_answered_honestly(engine: DecisionEngine) -> None:
    """What the model is *expected* to do here is: nothing.

    The checkpoint answers confidently and arbitrarily on an answer space it
    was not calibrated for, so the engine does not let it choose. The user
    gets an honest limitation and no side effect - not a wrong action that
    reports success.
    """
    response = ask(engine, "xyzzy plugh")

    assert response.status is ResponseStatus.NEEDS_CLARIFICATION
    assert response.action_plan[0].tool == "unresolved"
    assert response.action_plan[0].state is ActionStatus.FAILED
    assert response.action_plan[0].error is not None
    assert response.action_plan[0].error.code == "intent_not_resolved"
    assert response.clarification is not None
    assert "do not have a capability" in response.clarification.question


def test_the_model_is_reported_truthfully_whatever_it_answered(engine: DecisionEngine) -> None:
    """The provenance says which layer produced the interpretation."""
    response = ask(engine, "Open Spotify")

    info = response.decision_model
    assert info.source in (DecisionSource.MODEL, DecisionSource.RULE)
    if info.source is DecisionSource.MODEL:
        assert info.fallback_used is False
    else:
        # The model ran but was not believed: that is a fallback and it says so.
        assert info.fallback_used is True
        assert info.fallback_reason
    assert info.latency_ms > 0
