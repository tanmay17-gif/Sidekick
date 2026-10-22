"""Real decision model: ``convaiinnovations/laya``.

Laya is a non-autoregressive, Apache-2.0 decision model that answers *typed*
questions (choice / score / noul) with calibrated probabilities in a single
forward pass. It never generates text, so there is nothing to parse and no
hallucination risk - which is exactly what a safety-critical intent layer
wants.

The answer space is built at request time from the capability catalog, so new
capabilities need no retraining.

This adapter is defensive by design:

- the ``laya`` package is imported lazily (``find_spec`` only), so the core
  starts instantly even though ``torch`` is heavy;
- the router is created once and cached behind a lock;
- every call has a hard timeout - a slow model must never hang a request;
- unusable output raises :class:`ModelInvalidOutput` instead of being
  interpreted as "no intent";
- any failure is surfaced to the engine, which then falls back to the
  deterministic rule model *and reports that it did so*.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from typing import Any

from ..catalog import CapabilityCatalog
from ..decision import Decision, DecisionQuery, ModelInvalidOutput, ModelTimeout, ModelUnavailable
from ..parsing import CONTROL_INTENT_DESCRIPTIONS
from ..schemas import DecisionSource
from .base import BaseDecisionModel

DEFAULT_MODEL_ID = "convaiinnovations/laya"

#: The checkpoint the adapter uses by default.
#:
#: Measured on this task with ``scripts/eval_laya.py``:
#:
#: ============  ==============  ==============  ==========
#: checkpoint    tool accuracy   with fallback   destination
#: ============  ==============  ==============  ==========
#: english       25%             67%             100%
#: multilingual  50%             92%             100%
#: typed-decisions 50%          100%             100%
#: ============  ==============  ==============  ==========
#:
#: ``typed-decisions`` is the checkpoint that was fine-tuned for typed
#: decisions, which is exactly what this layer asks for.
DEFAULT_CHECKPOINT = "typed-decisions"


class LayaDecisionModel(BaseDecisionModel):
    """Adapter around the real Laya checkpoint."""

    provider = "convaiinnovations"

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        device: str | None = None,
        timeout_seconds: float = 20.0,
        first_call_timeout_seconds: float = 300.0,
        confidence_floor: float = 0.35,
        preload: bool = False,
        checkpoint: str | None = None,
        max_loaded: int = 2,
    ) -> None:
        super().__init__()
        self.model = model_id
        self._device = device
        self._timeout = timeout_seconds
        #: The very first call also builds the checkpoint, which takes far
        #: longer than an inference (tens of seconds on a CPU). It gets its
        #: own budget so a cold start is not reported as a timeout.
        self._first_call_timeout = first_call_timeout_seconds
        self._first_call = True
        self._confidence_floor = confidence_floor
        self._preload = preload or os.environ.get("LAYA_PRELOAD", "").lower() in {"1", "true", "yes"}
        self._checkpoint = (
            checkpoint
            or os.environ.get("SIDEKICK_LAYA_CHECKPOINT")
            or DEFAULT_CHECKPOINT
        )
        self._max_loaded = max_loaded
        self._router: Any | None = None
        self._router_lock = threading.Lock()
        self._last_routing: dict[str, Any] = {}

    # -- availability -----------------------------------------------------

    @property
    def available(self) -> bool:
        """True when the ``laya`` package is importable.

        This is a *cheap* check (no torch import). Whether the weights can
        actually be loaded is discovered at call time and reported through
        ``load_error``.
        """
        try:
            return importlib.util.find_spec("laya") is not None
        except (ImportError, ValueError):
            return False

    # -- router lifecycle -------------------------------------------------

    def _ensure_router(self) -> Any:
        if self._router is not None:
            return self._router
        with self._router_lock:
            if self._router is not None:
                return self._router
            if not self.available:
                raise ModelUnavailable(
                    "the 'laya' package is not installed (pip install 'sidekick[laya]')"
                )
            # transformers probes for TensorFlow at import time; the absl
            # runtime can deadlock model construction when TF is present.
            os.environ.setdefault("USE_TF", "0")
            try:
                from laya import Router  # type: ignore import-not-found
            except Exception as exc:  # noqa: BLE001 - import can fail in many ways
                self._load_error = f"importing laya failed: {exc}"
                raise ModelUnavailable(self._load_error) from exc

            device = self._device or self._detect_device()
            try:
                router = Router(device=device, max_loaded=self._max_loaded, default=self._checkpoint)
                if self._preload:
                    router.preload([self._checkpoint])
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"loading the laya router failed: {exc}"
                raise ModelUnavailable(self._load_error) from exc
            self._router = router
            return router

    def _detect_device(self) -> str:
        try:
            import torch  # type: ignore import-not-found

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - torch is optional at this point
            return "cpu"

    def warmup(self) -> bool:
        """Try to load the model ahead of the first request."""
        try:
            self._ensure_router()
            return True
        except ModelUnavailable:
            return False

    # -- question construction --------------------------------------------

    def build_questions(self, catalog: CapabilityCatalog) -> dict[str, dict[str, Any]]:
        """Build the typed questions from the capability catalog.

        The answer space of the ``action`` question is the *capability*
        catalog only. Control verbs (cancel, pause, resume, ...) are core
        orchestration vocabulary and are resolved by the deterministic
        grammar: measured on this task the model picked control intents
        more often than the right capability, so the model is not asked
        about them at all.
        """
        questions: dict[str, dict[str, Any]] = {}

        criteria: dict[str, str] = {}
        for spec in catalog:
            aliases = ", ".join(spec.aliases[:4])
            criteria[spec.name] = (
                f"{spec.description}. Trigger words: {aliases}." if aliases else spec.description
            )
        if len(criteria) >= 2:
            questions["action"] = {
                "type": "choice",
                "instructions": (
                    "Which capability does the user want to use? "
                    "Pick the capability whose trigger words appear in the request."
                ),
                "criteria": criteria,
            }

        destinations = catalog.all_destinations()
        if len(destinations) >= 2:
            questions["destination"] = {
                "type": "choice",
                "instructions": "Which service, app or file is the user talking about?",
                "criteria": {dest: f"the {dest} service or app" for dest in sorted(destinations)},
            }

        questions["is_correction"] = {
            "type": "noul",
            "instructions": (
                "Is the user correcting, replacing or changing an earlier request "
                "(for example 'no wait', 'actually', 'instead')?"
            ),
        }
        questions["confidence"] = {
            "type": "score",
            "instructions": "How certain is it that the request is clear and complete?",
            "criteria": ["uncertain and possibly incomplete", "mostly clear", "clear and complete"],
        }
        return questions

    # -- inference --------------------------------------------------------

    def _decide(self, query: DecisionQuery) -> Decision:
        router = self._ensure_router()
        return self._decide_with_router(router, query)

    def _decide_with_router(self, router: Any, query: DecisionQuery) -> Decision:
        """Interpret one segment with an already loaded router."""
        questions = self.build_questions(query.catalog)
        if "action" not in questions:
            raise ModelInvalidOutput("the capability catalog has no actionable tools")

        started = time.perf_counter()
        result = self._predict_with_timeout(router, query.utterance, questions)
        latency = (time.perf_counter() - started) * 1000.0
        if not isinstance(result, dict):
            raise ModelInvalidOutput(f"laya returned {type(result).__name__}, expected a mapping")
        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise ModelInvalidOutput("laya returned no 'answers' mapping")
        if "action" not in answers:
            raise ModelInvalidOutput("laya did not answer the 'action' question")

        routing = result.get("routing") if isinstance(result.get("routing"), dict) else {}
        self._last_routing = routing

        action_answer = answers.get("action") or {}
        tool = _as_choice(action_answer)
        tool_confidence = _as_confidence(action_answer)

        destination = None
        destination_confidence = 0.0
        if "destination" in answers:
            destination_answer = answers.get("destination") or {}
            destination = _as_choice(destination_answer)
            destination_confidence = _as_confidence(destination_answer)

        is_correction = _as_noul(answers.get("is_correction"))
        confidence = _as_confidence(answers.get("confidence")) if "confidence" in answers else 0.5

        # Blend the model's own confidence with the score of the chosen action.
        combined = max(confidence, tool_confidence)
        if tool is not None and tool not in query.catalog:
            raise ModelInvalidOutput(f"laya chose an unknown tool '{tool}'")
        if tool is not None and combined < self._confidence_floor:
            tool = None

        return Decision(
            tool=tool,
            tool_scores={tool: tool_confidence} if tool else {},
            destination=destination,
            destination_scores={destination: destination_confidence} if destination else {},
            destination_confidence=destination_confidence,
            is_correction=is_correction,
            is_multi_action=False,
            confidence=round(min(1.0, combined), 4),
            source=DecisionSource.MODEL,
            details={
                "routing": routing,
                "model_latency_ms": round(latency, 3),
                "answers": answers,
            },
        )

    def _predict_with_timeout(self, router: Any, utterance: str, questions: dict[str, Any]) -> Any:
        """Run the model with a hard timeout.

        The call is blocking, so it runs in a daemon thread. A timeout leaves
        the worker thread running (we cannot kill it safely) but the request
        is answered immediately with a fallback.

        The first call also builds the checkpoint, which is much slower than
        an inference, so it gets its own (longer) budget.
        """
        box: dict[str, Any] = {}
        budget = self._first_call_timeout if self._first_call else self._timeout

        def runner() -> None:
            try:
                if self._checkpoint:
                    box["result"] = router.predict(
                        utterance, questions, model=self._checkpoint
                    )
                else:
                    box["result"] = router.predict(utterance, questions)
            except BaseException as exc:  # noqa: BLE001 - forwarded to the caller
                box["error"] = exc

        worker = threading.Thread(target=runner, name="laya-predict", daemon=True)
        worker.start()
        worker.join(budget)
        if worker.is_alive():
            raise ModelTimeout(f"laya did not answer within {budget:.1f}s")
        self._first_call = False
        if "error" in box:
            error = box["error"]
            if isinstance(error, (ModelInvalidOutput, ModelTimeout, ModelUnavailable)):
                raise error
            self._load_error = f"laya inference failed: {type(error).__name__}: {error}"
            raise ModelUnavailable(self._load_error)
        return box.get("result")

    # -- provenance -------------------------------------------------------

    def _provenance(self, decision: Decision | None, latency_ms: float) -> Any:
        info = super()._provenance(decision, latency_ms)
        info.device = self._device or self._detect_device()
        return info

    def describe_extra(self) -> dict[str, Any]:
        return {
            "model_id": self.model,
            "router_loaded": self._router is not None,
            "routing": self._last_routing,
            "timeout_seconds": self._timeout,
        }


def _as_choice(answer: Any) -> str | None:
    if not isinstance(answer, dict):
        return None
    value = answer.get("choice")
    return value if isinstance(value, str) else None


def _as_confidence(answer: Any) -> float:
    """The calibrated probability of the answer that was chosen."""
    if not isinstance(answer, dict):
        return 0.0
    for key in ("answer_confidence", "probability", "prob", "confidence"):
        value = answer.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict) and answer.get("choice") in probabilities:
        value = probabilities[answer["choice"]]
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _as_noul(answer: Any) -> bool:
    if not isinstance(answer, dict):
        return False
    value = answer.get("noul")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) >= 0.5
    return False
