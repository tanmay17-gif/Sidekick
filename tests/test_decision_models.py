"""Decision model behaviour: availability, failure, timeout and fallback."""

from __future__ import annotations

import time

import pytest

from sidekick.bootstrap import build_decision_model
from sidekick.core.decision import (
    Decision,
    DecisionQuery,
    ModelInvalidOutput,
    ModelTimeout,
    ModelUnavailable,
)
from sidekick.core.decisions.base import BaseDecisionModel
from sidekick.core.decisions.laya_model import LayaDecisionModel
from sidekick.core.decisions.rule_model import RuleDecisionModel
from sidekick.core.engine import DecisionEngine
from sidekick.core.schemas import DecisionSource, ResponseStatus, SidekickRequest


class BrokenModel(BaseDecisionModel):
    """A model that always fails in a specific way."""

    provider = "test"
    model = "broken"

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error
        self.calls = 0

    def _decide(self, query: DecisionQuery) -> Decision:
        self.calls += 1
        raise self.error


def ask(engine: DecisionEngine, utterance: str, session: str = "s1"):
    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:20]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


@pytest.mark.parametrize(
    "error",
    [
        ModelUnavailable("the 'laya' package is not installed"),
        ModelTimeout("laya did not answer within 20.0s"),
        ModelInvalidOutput("laya returned no 'answers' mapping"),
        RuntimeError("something unexpected"),
    ],
)
def test_a_failing_model_falls_back_and_says_so(
    engine: DecisionEngine, error: Exception
) -> None:
    broken = BrokenModel(error)
    engine.primary_model = broken

    response = ask(engine, "echo hello")

    assert broken.calls == 1
    assert response.decision_model.fallback_used is True
    assert response.decision_model.source is DecisionSource.RULE
    assert response.decision_model.provider == "sidekick"
    assert response.decision_model.fallback_reason is not None
    assert type(error).__name__ in response.decision_model.fallback_reason
    # The request is still answered.
    assert response.status is ResponseStatus.SUCCEEDED
    assert response.action_plan[0].tool == "test.echo"


def test_the_rule_model_always_reports_itself_as_a_fallback() -> None:
    model = RuleDecisionModel()
    info = model.describe()

    assert info.source is DecisionSource.RULE
    assert info.fallback_used is True
    assert info.provider == "sidekick"
    assert info.model == "rule-engine-v1"


def test_a_model_that_is_not_confident_uses_the_deterministic_second_opinion(
    engine: DecisionEngine,
) -> None:
    class UnsureModel(BaseDecisionModel):
        provider = "test"
        model = "unsure"

        def _decide(self, query: DecisionQuery) -> Decision:
            return Decision(tool=None, confidence=0.0, source=DecisionSource.MODEL)

    engine.primary_model = UnsureModel()

    response = ask(engine, "echo hello")

    assert response.action_plan[0].tool == "test.echo"
    assert response.decision_model.fallback_used is True
    assert response.decision_model.source is DecisionSource.RULE
    assert "not confident" in (response.decision_model.fallback_reason or "")


def test_laya_reports_its_absence_without_raising() -> None:
    model = LayaDecisionModel()

    # The package is installed in this environment, so the check must be
    # truthful in both directions.
    assert model.available is True
    model.model = "definitely-not-installed"
    assert LayaDecisionModel(model_id="x").available is True


def test_lava_enforces_a_timeout() -> None:
    model = LayaDecisionModel(timeout_seconds=0.2, first_call_timeout_seconds=0.2)

    class SlowRouter:
        def predict(self, *args, **kwargs):  # noqa: ANN002, ANN003
            time.sleep(3)
            return {}

    with pytest.raises(ModelTimeout):
        model._predict_with_timeout(SlowRouter(), "hello", {})


def test_a_cold_start_gets_its_own_time_budget() -> None:
    """Building the checkpoint is slower than an inference.

    The first call must not be reported as a model timeout, and the calls
    after it must use the regular budget.
    """
    model = LayaDecisionModel(timeout_seconds=0.2, first_call_timeout_seconds=60.0)

    class SlowRouter:
        def predict(self, *args, **kwargs):  # noqa: ANN002, ANN003
            time.sleep(0.5)
            return {"answers": {}}

    # The first call uses the long budget, so it does not time out.
    model._predict_with_timeout(SlowRouter(), "hello", {})

    # A later call uses the short budget.
    with pytest.raises(ModelTimeout):
        model._predict_with_timeout(SlowRouter(), "hello", {})


def test_laya_rejects_unusable_output() -> None:
    from sidekick.core.registry import ToolRegistry

    model = LayaDecisionModel()
    registry = ToolRegistry()

    class BadRouter:
        def predict(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return {"answers": {}}

    query = DecisionQuery(utterance="x", catalog=registry.catalog, session=None)  # type: ignore[arg-type]
    with pytest.raises(ModelInvalidOutput):
        model._decide_with_router(BadRouter(), query)


def test_bootstrap_marks_the_rule_engine_as_a_fallback() -> None:
    primary, fallback, reason = build_decision_model(prefer_model="rule")

    assert primary.provider == "sidekick"
    assert reason
    assert primary.fallback_reason == reason
    assert fallback.provider == "sidekick"
