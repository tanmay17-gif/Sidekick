"""The decision engine.

One public entry point: :meth:`DecisionEngine.handle`. It turns a validated
:class:`~sidekick.core.schemas.SidekickRequest` into a
:class:`~sidekick.core.schemas.SidekickResponse`.

Order of operations (this order *is* the product behaviour):

1. **Idempotency** - a repeated ``request_id`` replays the stored answer.
2. **Transcript gate** - an unfinalized transcript is never executed.
3. **Continuation / resume** - "continue what I was doing" resumes the
   suspended task instead of re-interpreting the sentence.
4. **Segmentation** - multi-action utterances become ordered segments.
5. **Interpretation** - every segment is interpreted by the decision model
   (real model first, deterministic fallback only on failure).
6. **Argument binding** - required arguments come from the segment, the
   session context or a clarification question.
7. **Safety policy** - deterministic gate; the model cannot skip it.
8. **Superseding** - a correction supersedes not-yet-executed actions and
   tries to stop in-flight ones.
9. **Execution** - actions run through the tool registry unless they wait
   for an explicit confirmation.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .catalog import (
    ARG_DURATION,
    ARG_ENUM,
    ARG_INTEGER,
    ARG_STRING,
    CAPTURE_AUTO,
    CAPTURE_EXCEPT_WHEN,
    CAPTURE_NONE,
    CAPTURE_QUOTED,
    CAPTURE_WHEN,
    ToolSpec,
    contains_phrase,
)
from .decision import (
    Decision,
    DecisionModel,
    DecisionQuery,
    ModelInvalidOutput,
    ModelTimeout,
    ModelUnavailable,
)
from .decisions.base import BaseDecisionModel
from .decisions.laya_model import LayaDecisionModel
from .decisions.rule_model import RuleDecisionModel
from .parsing import (
    ArgumentHints,
    ControlIntent,
    CorrectionSignal,
    Segment,
    bare_marker_is_control,
    detect_correction,
    extract_argument_hints,
    extract_remainder,
    find_when_expression,
    is_capability_question,
    is_resume_request,
    match_control,
    normalize,
    split_segments,
)
from .registry import ToolContext, ToolRegistry
from .safety import SafetyPolicy, plan_hash
from .schemas import (
    Action,
    ActionError,
    ActionStatus,
    Clarification,
    DecisionModelInfo,
    DecisionSource,
    Entity,
    Event,
    IntentInfo,
    ResponseStatus,
    RiskLevel,
    SidekickRequest,
    SidekickResponse,
    SessionView,
    new_id,
    utcnow,
)
from .sessions import SessionState, SessionStore, TaskState, TurnRecord

# A plain "and" is only treated as a separator when both sides resolve to
# different capabilities (see DecisionEngine._segment).
_AND_SPLIT_RE = re.compile(r"\s+and\s+")

#: How long a capability the browser client runs may stay ``pending`` before
#: the core gives up on it and reports the failure.
CLIENT_ACTION_TIMEOUT_SECONDS = 120.0

#: How often the background sweep looks for expired client actions.
CLIENT_SWEEP_INTERVAL_SECONDS = 15.0


@dataclass
class ResolvedSegment:
    """The outcome of interpreting one segment."""

    text: str
    tool: str | None = None
    destination: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    source: DecisionSource = DecisionSource.RULE
    entities: list[Entity] = field(default_factory=list)
    is_correction: bool = False
    correction: CorrectionSignal | None = None
    decision: Decision | None = None
    model_info: DecisionModelInfo | None = None
    error: str | None = None


class DecisionEngine:
    """Stateless-per-call orchestrator over session state, catalog and tools."""

    def __init__(
        self,
        registry: ToolRegistry,
        sessions: SessionStore,
        decision_model: DecisionModel | None = None,
        *,
        fallback_model: DecisionModel | None = None,
        policy: SafetyPolicy | None = None,
        primary_is_fallback: bool = False,
    ) -> None:
        self.registry = registry
        self.sessions = sessions
        self.primary_model = decision_model or RuleDecisionModel()
        self.fallback_model = fallback_model or RuleDecisionModel()
        self.policy = policy or SafetyPolicy()
        #: ``True`` when the primary model *is* the deterministic fallback
        #: (for example because the real model is not installed).
        self._primary_is_fallback = primary_is_fallback
        self._sweeper: threading.Thread | None = None
        self._sweeper_lock = threading.Lock()
        self._stop_sweeper = threading.Event()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def handle(self, request: SidekickRequest) -> SidekickResponse:
        session = self.sessions.get(request.session_id)

        cached = session.cached_response(request.request_id)
        if cached is not None:
            replay = cached.model_copy(deep=True)
            replay.events.append(
                Event(type="request.replayed", message="the request id was already processed")
            )
            return replay

        if not request.utterance_finalized:
            return self._defer(request, session)

        events: list[Event] = []
        response = self._run(request, session, events)
        for event in events:
            session.log_event(event)
        session.turn_count += 1
        session.last_request_id = request.request_id
        session.record_turn(
            TurnRecord(
                request_id=request.request_id,
                utterance=request.utterance,
                intent=response.intent.normalized,
                tool=response.action_plan[0].tool if response.action_plan else None,
            )
        )
        session.cache_response(request.request_id, response.model_copy(deep=True))
        return response

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    def _run(self, request: SidekickRequest, session: SessionState, events: list[Event]) -> SidekickResponse:
        events.append(Event(type="turn.received", message=request.utterance[:200]))

        # 1. Continuation / resume -------------------------------------
        resume_task_id = self._resume_task_id(request, session)
        if resume_task_id is not None:
            return self._resume(request, session, resume_task_id, events)

        # 2. Segmentation ------------------------------------------------
        segments = self._segment(request, session)
        multi_action = len(segments) > 1

        # 3. Interpretation ---------------------------------------------
        resolved = [self._resolve(segment, session, request) for segment in segments]

        model_info = self._aggregate_model_info(resolved)
        events.append(
            Event(
                type="model.decided",
                message=f"interpreted with {model_info.provider}/{model_info.model}",
                data={
                    "provider": model_info.provider,
                    "model": model_info.model,
                    "source": model_info.source.value,
                    "fallback_used": model_info.fallback_used,
                    "latency_ms": model_info.latency_ms,
                    "load_error": model_info.load_error,
                },
            )
        )

        # 4. Plan ---------------------------------------------------------
        actions, clarification = self._build_plan(request, session, resolved, events)
        risk = self._max_risk(actions)

        # 5. Execute -------------------------------------------------------
        actions = self._execute_plan(request, session, actions, events)

        status = self._overall_status(actions, clarification)
        entities = [entity for seg in resolved for entity in seg.entities]
        intent = IntentInfo(
            normalized=normalize(request.utterance),
            confidence=min([seg.confidence for seg in resolved], default=0.0),
            ambiguous=clarification is not None,
            entities=entities,
            multi_action=multi_action,
            source=model_info.source,
        )

        return SidekickResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            intent=intent,
            action_plan=actions,
            risk_level=risk,
            decision_model=model_info,
            status=status,
            clarification=clarification,
            events=events,
            session=self._session_view(session),
            message=self._summarise(actions, clarification),
            speech=self._speech(
                actions,
                clarification,
                corrected=any(segment.is_correction for segment in resolved),
            ),
        )

    # ------------------------------------------------------------------
    # Interpretation
    # ------------------------------------------------------------------

    def _segment(self, request: SidekickRequest, session: SessionState) -> list[Segment]:
        """Split the utterance into independently resolvable segments.

        The strong separators ("and then", "then", ...) are applied first. A
        plain "and" is only a separator when *both* sides clearly resolve to
        different capabilities - "echo hello and goodbye" stays one request.
        """
        segments = split_segments(request.utterance)
        if len(segments) != 1:
            return segments

        parts = _AND_SPLIT_RE.split(segments[0].text)
        if len(parts) < 2:
            return segments

        tools: list[str | None] = []
        for part in parts:
            decision, _ = self._decide(self._query(part.strip(), session))
            tools.append(decision.tool)
        if any(tool is None for tool in tools) or len(set(tools)) != len(tools):
            return segments
        return [
            Segment(text=part.strip(), index=index)
            for index, part in enumerate(parts)
            if part.strip()
        ]

    def _resolve(self, segment: Segment, session: SessionState, request: SidekickRequest) -> ResolvedSegment:
        """Interpret one segment, falling back to the rule model on failure."""
        correction = detect_correction(segment.text)

        # "What can you actually do?" is a question about the product, not a
        # task. It is answered from the catalog, so it never reaches a model
        # and it is never mistaken for a correction (the word "actually" is
        # a correction marker).
        if is_capability_question(segment.text):
            decision = Decision(
                tool="control.capabilities",
                confidence=1.0,
                source=DecisionSource.RULE,
                details={"capability_question": True},
            )
            info = DecisionModelInfo(
                provider="sidekick",
                model="capability-catalog",
                source=DecisionSource.RULE,
                fallback_used=False,
                fallback_reason=None,
                latency_ms=0.0,
                model_available=getattr(self.primary_model, "available", True),
            )
            return self._finish_segment(
                segment, session, request, decision, info, correction, segment.text
            )

        if correction.is_correction and not correction.residue:
            if bare_marker_is_control(segment.text):
                # "never mind" and friends mean "drop the pending work".
                text = segment.text
            else:
                # A bare correction marker carries no action of its own.
                text = ""
        elif correction.is_correction:
            text = correction.residue
        else:
            text = segment.text

        # Control verbs are core orchestration vocabulary and are resolved by
        # the deterministic grammar. Measured against the real model, the
        # model picked control intents more often than the right capability,
        # so it is not asked about them at all.
        control, control_score = match_control(text)
        if control and not self._control_is_ambiguous(control, text):
            decision = Decision(
                tool=control,
                confidence=control_score,
                source=DecisionSource.RULE,
                details={"control_grammar": True},
            )
            info = DecisionModelInfo(
                provider="sidekick",
                model="rule-engine-v1",
                source=DecisionSource.RULE,
                fallback_used=True,
                fallback_reason=(
                    "the request was resolved by the deterministic control grammar"
                ),
                latency_ms=0.0,
                model_available=getattr(self.primary_model, "available", True),
            )
            return self._finish_segment(
                segment, session, request, decision, info, correction, text
            )

        decision, model_info = self._decide(self._query(text, session))

        # A correction that does not name an action on its own ("actually,
        # tomorrow") keeps the capability of the instruction it corrects. The
        # inherited capability is checked against the *preceding* text, which
        # is the text that mentioned it.
        support_text = text
        if decision.tool is None and correction.is_correction and correction.preceding:
            previous, _ = self._decide(self._query(correction.preceding, session))
            if previous.tool and not self._is_control(previous.tool):
                decision.tool = previous.tool
                decision.confidence = max(decision.confidence, previous.confidence * 0.9)
                support_text = correction.preceding

        decision = self._anchor_to_utterance(decision, support_text, session)
        return self._finish_segment(
            segment, session, request, decision, model_info, correction, text
        )

    def _anchor_to_utterance(
        self, decision: Decision, text: str, session: SessionState
    ) -> Decision:
        """Keep the decision model inside what the utterance actually says.

        Measured with the real model: on a *new* answer space the checkpoint
        answers confidently but arbitrarily - "order dinner for me" and
        "xyzzy plugh" both came back as "read my notes". Its confidence is
        not calibrated for an answer space it was not trained on (the library
        says so itself), so it is never allowed to introduce a capability the
        utterance does not mention.

        The model may still choose *between* the capabilities the utterance
        supports, and that is where it earns its place.
        """
        if decision.source is not DecisionSource.MODEL:
            return decision
        tool = decision.tool
        if not tool or self._is_control(tool):
            return decision

        catalog = self.registry.catalog
        support = catalog.tool_support(text, tool)
        if support > 0:
            # The utterance mentions this capability. Keep the model's choice.
            return decision

        # The model named a capability the utterance never mentions.
        candidate, score = catalog.match_tool(text)
        if candidate is None:
            # A destination that only one capability owns identifies that
            # capability on its own: "no, I meant Spotify" is an "open".
            candidate, score = self._capability_from_destination(text)
        if candidate and candidate != tool and not self._is_control(candidate):
            decision.details["anchor"] = {
                "rejected_tool": tool,
                "reason": "the utterance does not mention that capability",
                "chosen": candidate,
            }
            decision.tool = candidate
            decision.confidence = max(decision.confidence, score)
            return decision

        decision.details["anchor"] = {
            "rejected_tool": tool,
            "reason": "the utterance does not mention that capability",
            "chosen": None,
        }
        decision.tool = None
        decision.confidence = 0.0
        return decision

    def _finish_segment(
        self,
        segment: Segment,
        session: SessionState,
        request: SidekickRequest,
        decision: Decision,
        model_info: DecisionModelInfo,
        correction: CorrectionSignal,
        text: str,
    ) -> ResolvedSegment:
        """Bind arguments and assemble the resolved segment."""
        tool = decision.tool
        destination = decision.destination
        confidence = decision.confidence

        # An elided tool ("continue what I was doing") reuses the last tool.
        if tool is None and session.last_tool:
            if request.continuation_context and request.continuation_context.elide_tool:
                tool = session.last_tool
                confidence = max(confidence, 0.5)

        spec = self.registry.spec(tool) if tool else None
        arguments: dict[str, Any] = {}
        entities: list[Entity] = []

        if spec is not None:
            arguments, entities = self._bind_arguments(spec, text, decision, session)

        if decision.is_correction or correction.is_correction:
            decision.is_correction = True

        return ResolvedSegment(
            text=segment.text,
            tool=tool,
            destination=destination,
            arguments=arguments,
            confidence=confidence,
            source=model_info.source,
            entities=entities,
            is_correction=decision.is_correction or correction.is_correction,
            correction=correction,
            decision=decision,
            model_info=model_info,
        )

    @staticmethod
    def _control_is_ambiguous(control: str, text: str) -> bool:
        """A short "yes"/"no" is a reply; a long one is part of a request."""
        if control in ("control.confirm", "control.reject"):
            return len(text.split()) > 3
        return False

    def _query(self, text: str, session: SessionState) -> DecisionQuery:
        return DecisionQuery(
            utterance=text,
            catalog=self.registry.catalog,
            session=session,
            pending_actions=session.pending_actions() + session.awaiting_confirmation_actions(),
            last_tool=session.last_tool,
            last_arguments=dict(session.last_arguments),
        )

    @staticmethod
    def _is_control(tool: str | None) -> bool:
        return bool(tool) and tool.startswith("control.")

    @staticmethod
    def _is_trailing(segment: ResolvedSegment) -> bool:
        """Is the correction marker at the end of the segment?"""
        return bool(segment.correction and segment.correction.is_trailing)

    def _decide(self, query: DecisionQuery) -> tuple[Decision, DecisionModelInfo]:
        """Run the primary model, fall back deterministically on failure."""
        started = time.perf_counter()
        try:
            decision = self.primary_model.decide(query)
            info = self.primary_model.describe()
            info.latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        except (ModelUnavailable, ModelTimeout, ModelInvalidOutput, Exception) as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
            decision = self.fallback_model.decide(query)
            info = self.fallback_model.describe()
            info.provider = getattr(self.fallback_model, "provider", "sidekick")
            info.model = getattr(self.fallback_model, "model", "rule-engine-v1")
            info.source = DecisionSource.RULE
            info.fallback_used = True
            info.fallback_reason = reason
            info.load_error = reason
            info.latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            info.model_available = False
            return decision, info

        # Second opinion: when the model was not able to pick a capability,
        # the deterministic matcher may still resolve it. That is a fallback
        # and is reported as one.
        if decision.tool is None and not self._primary_is_fallback:
            alternative = self.fallback_model.decide(query)
            if alternative.tool:
                info = self.fallback_model.describe()
                info.fallback_used = True
                info.source = DecisionSource.RULE
                info.fallback_reason = (
                    "the decision model was not confident enough to pick a capability"
                )
                info.latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                decision = alternative
        return decision, info

    def _last_model_info(self) -> DecisionModelInfo:
        info = self.primary_model.describe()
        if info.fallback_used:
            return info
        return info

    def _aggregate_model_info(self, resolved: list[ResolvedSegment]) -> DecisionModelInfo:
        """Describe what actually produced the interpretation of this turn.

        When at least one segment was interpreted by the real model, that is
        what is reported. Otherwise the deterministic layer is reported as
        the source, with the reason why.
        """
        infos = [seg.model_info for seg in resolved if seg.model_info is not None]
        if not infos:
            return self._last_model_info()
        model_infos = [info for info in infos if info.source is DecisionSource.MODEL]
        base = model_infos[0] if model_infos else infos[0]
        # A copy: the model's own provenance object is shared, and the sum of
        # the latencies belongs to this turn only.
        base = base.model_copy(deep=True)
        base.latency_ms = round(sum(info.latency_ms for info in infos), 3)
        return base

    # ------------------------------------------------------------------
    # Argument binding
    # ------------------------------------------------------------------

    def _bind_arguments(
        self,
        spec: ToolSpec,
        text: str,
        decision: Decision,
        session: SessionState,
    ) -> tuple[dict[str, Any], list[Entity]]:
        """Fill the tool's arguments from the segment, the model and the session."""
        arguments: dict[str, Any] = {}
        entities: list[Entity] = []
        hints = extract_argument_hints(text)

        # The destinations the utterance actually mentions. The model may
        # choose *between* them, but it may not introduce one that is not
        # there - a model that is confident enough to invent a destination
        # would otherwise turn "xyzzy plugh" into "Opening Google".
        mentioned = self._mentioned_destinations(spec, text)
        model_destination = (
            decision.destination
            if decision.destination and decision.destination in mentioned
            else None
        )

        for arg in spec.arguments:
            if arg.type == ARG_ENUM:
                value = _match_enum(arg.enum, text)
                if model_destination and model_destination in arg.enum:
                    value = model_destination
                if value is None:
                    # A single typo in a service name ("open spotfy").
                    fuzzy, _score = self.registry.catalog.match_destination(text)
                    if fuzzy and fuzzy in arg.enum:
                        value = fuzzy
                if value is not None:
                    arguments[arg.name] = value
                    entities.append(
                        Entity(
                            name=arg.name,
                            value=value,
                            source="model" if value == model_destination else "parser",
                        )
                    )
            elif arg.type == ARG_DURATION:
                if hints.duration_seconds is not None:
                    arguments[arg.name] = hints.duration_seconds
                    entities.append(
                        Entity(
                            name=arg.name,
                            value=str(hints.duration_seconds),
                            source="parser",
                        )
                    )
            elif arg.type == ARG_INTEGER:
                if hints.count is not None:
                    arguments[arg.name] = hints.count.count
                    entities.append(
                        Entity(name=arg.name, value=str(hints.count.count), source="parser")
                    )
            elif arg.type == ARG_STRING:
                value = self._capture_text(arg, spec, text, hints)
                if value is not None:
                    arguments[arg.name] = value
                    entities.append(
                        Entity(name=arg.name, value=value, source="parser")
                    )

        # The destination the model picked was already applied above, when it
        # was one of the destinations the utterance mentions.

        # Session context fills arguments the utterance left out, but only for
        # the same tool - that is what makes "play that again" work. An
        # argument that must not be carried over (a time) is left alone.
        if session.last_tool == spec.name:
            for key, value in session.last_arguments.items():
                argument = spec.argument(key)
                if argument is not None and not argument.remember:
                    continue
                arguments.setdefault(key, value)

        return arguments, entities

    def _ensure_client_sweeper(self) -> None:
        """Start the background sweep that expires unanswered client actions.

        It is a daemon thread, so it never keeps the process alive.
        """
        with self._sweeper_lock:
            if self._sweeper is not None and self._sweeper.is_alive():
                return
            thread = threading.Thread(
                target=self._sweep_client_actions,
                name="sidekick-client-sweeper",
                daemon=True,
            )
            self._sweeper = thread
            thread.start()

    def _sweep_client_actions(self) -> None:
        while not self._stop_sweeper.is_set():
            try:
                self.expire_client_actions()
            except Exception:  # noqa: BLE001 - a sweep must never kill the process
                pass
            self._stop_sweeper.wait(CLIENT_SWEEP_INTERVAL_SECONDS)

    def _capability_from_destination(self, text: str) -> tuple[str | None, float]:
        """The capability a mentioned destination identifies on its own.

        "No, I meant Spotify" names no action, but Spotify belongs to exactly
        one capability, so that capability is what the user means.
        """
        catalog = self.registry.catalog
        for spec in catalog:
            for destination in spec.destinations:
                aliases = (destination, *spec.destination_aliases.get(destination, ()))
                lowered = text.lower()
                mentioned = any(contains_phrase(lowered, alias) for alias in aliases)
                if not mentioned:
                    continue
                owners = catalog.destination_owners(destination)
                if len(owners) == 1:
                    return owners[0], 0.5
        return None, 0.0

    @staticmethod
    def _mentioned_destinations(spec: ToolSpec, text: str) -> set[str]:
        """The destinations of a tool that the utterance actually mentions."""
        found: set[str] = set()
        lowered = text.lower()
        for destination in spec.destinations:
            aliases = (destination, *spec.destination_aliases.get(destination, ()))
            for alias in aliases:
                if contains_phrase(lowered, alias):
                    found.add(destination)
                    break
        return found

    @staticmethod
    def _capture_text(
        arg: Any,
        spec: ToolSpec,
        text: str,
        hints: ArgumentHints,
    ) -> str | None:
        """Capture a free-text argument according to its capture mode."""
        if arg.capture == CAPTURE_NONE:
            return None
        if arg.capture == CAPTURE_WHEN:
            expression = find_when_expression(text)
            if expression is None:
                return None
            return re.sub(r"^at\s+", "", expression, flags=re.IGNORECASE).strip()
        if arg.capture == CAPTURE_EXCEPT_WHEN:
            expression = find_when_expression(text)
            if expression is None:
                return extract_remainder(text, spec.aliases)
            without = text.replace(expression, " ")
            return extract_remainder(without, spec.aliases) or _clean_remainder(without)
        if arg.capture in (CAPTURE_QUOTED, CAPTURE_AUTO):
            if hints.text_value:
                return hints.text_value
            if arg.capture == CAPTURE_QUOTED:
                return None
        remainder = extract_remainder(text, spec.aliases)
        if remainder:
            remainder = remainder.strip(" ,.;:!?-")
        return remainder

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _build_plan(
        self,
        request: SidekickRequest,
        session: SessionState,
        resolved: list[ResolvedSegment],
        events: list[Event],
    ) -> tuple[list[Action], Clarification | None]:
        actions: list[Action] = []
        clarification: Clarification | None = None

        for segment in resolved:
            if segment.tool is None:
                actions.append(
                    Action(
                        action_id=new_id(),
                        tool="unresolved",
                        description=segment.text,
                        state=ActionStatus.FAILED,
                        error=ActionError(
                            code="intent_not_resolved",
                            message="the request could not be mapped to a known capability",
                        ),
                    )
                )
                if clarification is None:
                    clarification = self._unsupported_clarification(segment.text)
                continue

            # Control intents are core orchestration, not capabilities.
            if self._is_control(segment.tool):
                action = Action(
                    action_id=new_id(),
                    tool=segment.tool,
                    arguments={},
                    state=ActionStatus.PENDING,
                    description=segment.text,
                )
                action.job_id = action.action_id
                actions.append(action)
                if segment.is_correction:
                    self._supersede_plan_actions(actions[:-1], action, events)
                continue

            spec = self.registry.spec(segment.tool)
            if spec is None:
                actions.append(
                    Action(
                        action_id=new_id(),
                        tool=segment.tool,
                        description=segment.text,
                        state=ActionStatus.FAILED,
                        error=ActionError(
                            code="tool_unavailable",
                            message=f"'{segment.tool}' is not available in this deployment",
                        ),
                    )
                )
                continue

            arguments = dict(segment.arguments)
            available = self.registry.is_available(spec.name)
            if not available and spec.execution_target == "client":
                # The browser client runs this capability. It is not "missing":
                # the core plans it and the client executes it.
                available = True
            decision = self.policy.evaluate(spec, arguments, tool_available=available)

            action = Action(
                action_id=new_id(),
                tool=spec.name,
                arguments=dict(arguments),
                approval_required=decision.approval_required,
                state=ActionStatus.PENDING,
                description=segment.text,
                plan_hash=plan_hash(spec.name, arguments),
            )
            action.job_id = action.action_id
            actions.append(action)

            if segment.is_correction and not self._is_trailing(segment):
                # A correction replaces the actions planned before it in the
                # same turn, before any of them can execute. A trailing
                # marker ("echo hello instead") refers to the previous
                # request instead, so it leaves this turn's plan alone.
                self._supersede_plan_actions(actions[:-1], action, events)

            if not available:
                action.state = ActionStatus.FAILED
                action.error = ActionError(
                    code="tool_unavailable",
                    message=(
                        f"'{spec.name}' is declared but no adapter is wired up "
                        "in this deployment"
                    ),
                )
                continue

            if not decision.ok:
                action.state = ActionStatus.FAILED
                action.error = ActionError(
                    code=decision.violations[0].kind.value,
                    message="; ".join(v.message for v in decision.violations),
                )
                if clarification is None and decision.violations:
                    first = decision.violations[0]
                    clarification = Clarification(
                        question=_clarification_question(spec, first.kind.value, first.argument),
                        options=list(first.options),
                        action_id=action.action_id,
                        missing_arguments=decision.missing_arguments,
                    )
                continue

            if decision.approval_required:
                action.state = ActionStatus.AWAITING_CONFIRMATION
                events.append(
                    Event(
                        type="action.awaiting_confirmation",
                        action_id=action.action_id,
                        message=f"{spec.name} needs an explicit confirmation",
                        data={"risk": spec.risk.value, "plan_hash": action.plan_hash},
                    )
                )

        # A correction supersedes everything that has not started yet.
        correction_target = (
            request.correction_context.resolved_action_id()
            if request.correction_context
            else None
        )
        if any(seg.is_correction for seg in resolved) or correction_target:
            self._supersede_pending(session, actions, events, target=correction_target)

        events.append(
            Event(
                type="plan.created",
                message=f"{len(actions)} action(s) planned",
                data={"tools": [a.tool for a in actions]},
            )
        )
        return actions, clarification

    def _supersede_plan_actions(
        self,
        previous: list[Action],
        replacement: Action,
        events: list[Event],
    ) -> None:
        """Supersede the actions of the same turn that a correction replaces."""
        for action in previous:
            if action.state in (ActionStatus.PENDING, ActionStatus.AWAITING_CONFIRMATION):
                action.state = ActionStatus.SUPERSEDED
                action.superseded_by = replacement.action_id
                action.touch()
                events.append(
                    Event(
                        type="action.superseded",
                        action_id=action.action_id,
                        message=f"{action.tool} was superseded by the corrected request",
                        data={"superseded_by": replacement.action_id},
                    )
                )

    def _supersede_pending(
        self,
        session: SessionState,
        new_actions: list[Action],
        events: list[Event],
        target: str | None = None,
    ) -> None:
        """Mark not-yet-executed actions as superseded by the new plan.

        ``target`` is the action id the caller named explicitly (the browser
        sends it when it recognises a correction). When it is given, only that
        action is superseded.
        """
        new_ids = {a.action_id for a in new_actions}
        for action in list(session.actions.values()):
            if action.action_id in new_ids:
                continue
            if target is not None and action.action_id != target:
                continue
            if action.state in (ActionStatus.PENDING, ActionStatus.AWAITING_CONFIRMATION):
                action.state = ActionStatus.SUPERSEDED
                action.superseded_by = new_actions[0].action_id if new_actions else None
                action.touch()
                events.append(
                    Event(
                        type="action.superseded",
                        action_id=action.action_id,
                        message=f"{action.tool} was superseded by the corrected request",
                        data={"superseded_by": action.superseded_by},
                    )
                )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_plan(
        self,
        request: SidekickRequest,
        session: SessionState,
        actions: list[Action],
        events: list[Event],
    ) -> list[Action]:
        affected: list[Action] = []
        for action in actions:
            if action.state is ActionStatus.SUPERSEDED:
                # A superseded action never runs.
                session.add_action(action)
                continue
            if action.state is ActionStatus.AWAITING_CONFIRMATION:
                session.add_action(action)
                continue
            if action.state is ActionStatus.FAILED:
                session.add_action(action)
                continue
            if self._is_control(action.tool):
                affected.extend(self._run_control_action(action, session, events))
                session.add_action(action)
                continue
            spec = self.registry.spec(action.tool)
            if spec is not None and spec.execution_target == "client":
                # The browser client runs this one. The core plans it and
                # waits for the client to report the real outcome - with a
                # deadline, so it cannot stay pending forever.
                action.state = ActionStatus.PENDING
                action.result = {
                    "execution_target": "client",
                    "status": "awaiting_client",
                    "capability": spec.name,
                    "client_deadline": time.time() + CLIENT_ACTION_TIMEOUT_SECONDS,
                }
                action.touch()
                events.append(
                    Event(
                        type="action.awaiting_client",
                        action_id=action.action_id,
                        message=f"{spec.name} is executed by the app",
                        data={
                            "capability": spec.name,
                            "deadline_seconds": CLIENT_ACTION_TIMEOUT_SECONDS,
                        },
                    )
                )
                session.add_action(action)
                self._ensure_client_sweeper()
                continue
            self._execute_action(action, session, events)
            session.add_action(action)
        return actions + affected

    def _run_control_action(
        self, action: Action, session: SessionState, events: list[Event]
    ) -> list[Action]:
        """Execute a control intent (cancel / pause / resume / status / ...).

        Returns the actions the control affected, so the caller can show them
        in the plan instead of hiding what happened.
        """
        name = action.tool
        affected: list[Action] = []
        message = ""
        try:
            if name == "control.capabilities":
                inventory = self.capability_inventory()
                message = self._capability_message(inventory)
                action.result = {"capabilities": inventory, "message": message}
            elif name == "control.cancel":
                affected, message = self._do_cancel(session, events)
            elif name == "control.pause":
                affected, message = self._do_pause(session, events)
            elif name == "control.resume":
                task_id = self._resume_task_id_for_control(session)
                if task_id is None:
                    message = "there is nothing to resume"
                else:
                    response = self._resume(
                        SidekickRequest(
                            request_id=action.action_id,
                            session_id=session.session_id,
                            utterance="continue",
                        ),
                        session,
                        task_id,
                        events,
                    )
                    message = response.message
                    affected = list(response.action_plan)
            elif name == "control.switch":
                affected, message = self._do_cancel(session, events)
                message = "the previous task was superseded"
            elif name == "control.status":
                message = self._describe_pending(session)
            elif name == "control.confirm":
                affected, message = self._do_confirm(session, events, approved=True)
            elif name == "control.reject":
                affected, message = self._do_confirm(session, events, approved=False)
            else:
                message = "that control is not supported"
        except Exception as exc:  # noqa: BLE001 - controls must never crash a turn
            message = f"the control could not be applied: {exc}"
        action.state = ActionStatus.SUCCEEDED
        if action.result is None:
            action.result = {"message": message}
        action.touch()
        events.append(
            Event(type="action.succeeded", action_id=action.action_id, message=message)
        )
        return affected

    # ------------------------------------------------------------------
    # Capability inventory
    # ------------------------------------------------------------------

    def capability_inventory(self) -> list[dict[str, Any]]:
        """Everything the product can do, with the truth about each one."""
        inventory: list[dict[str, Any]] = []
        for spec in self.registry.catalog:
            available = self.registry.is_available(spec.name)
            if spec.execution_target == "client":
                state = "client"
                detail = spec.detail or spec.description
            elif available:
                state = "live"
                detail = spec.detail or spec.description
            else:
                state = "unavailable"
                detail = "declared, but no adapter is wired up in this deployment"
            inventory.append(
                {
                    "id": spec.name,
                    "label": spec.human_label,
                    "detail": detail,
                    "state": state,
                    "owner": spec.owner,
                    "execution_target": spec.execution_target,
                }
            )
        return inventory

    def _capability_message(self, inventory: list[dict[str, Any]]) -> str:
        """What the product can do, told honestly.

        A capability the browser client runs is not something the *core* did,
        so it is named separately instead of being mixed in with the things
        the server can do.
        """
        server = [item["label"] for item in inventory if item["state"] == "live"]
        client = [item["label"] for item in inventory if item["state"] == "client"]
        parts: list[str] = []
        if server:
            parts.append("I can " + ", ".join(server))
        if client:
            parts.append("in the app I can " + ", ".join(client))
        if not parts:
            return "I do not have any working capabilities in this deployment yet."
        return ". ".join(parts) + "."

    def _resume_task_id_for_control(self, session: SessionState) -> str | None:
        suspended = session.suspended_tasks()
        if suspended:
            return suspended[-1].task_id
        task = session.active_task()
        return task.task_id if task else None

    def _execute_action(self, action: Action, session: SessionState, events: list[Event]) -> Action:
        """Run one action through the tool registry and record the real result."""
        spec = self.registry.spec(action.tool)
        if spec is None:
            action.state = ActionStatus.FAILED
            action.error = ActionError(
                code="tool_unavailable",
                message=f"'{action.tool}' is not available in this deployment",
            )
            action.touch()
            return action

        action.state = ActionStatus.RUNNING
        action.touch()
        events.append(
            Event(type="action.started", action_id=action.action_id, message=f"{action.tool} started")
        )

        task = session.get_task_for_action(action.action_id)
        if task is None:
            task = TaskState(
                task_id=new_id(),
                tool=action.tool,
                description=action.description,
                action_ids=[action.action_id],
                state=ActionStatus.RUNNING,
                resumable=True,
            )
            session.add_task(task)
            session.active_task_id = task.task_id

        context = self._make_context(session, action)
        result = self.registry.execute(action, action.arguments, context)

        if result.ongoing:
            # The work continues in the background: the action stays running
            # until the adapter reports the final outcome. What is already
            # known (the due time, the job id) is recorded now.
            action.state = ActionStatus.RUNNING
            action.result = dict(result.data)
            action.touch()
            task.state = ActionStatus.RUNNING
            task.touch()
            events.append(
                Event(
                    type="action.ongoing",
                    action_id=action.action_id,
                    message=f"{action.tool} is running in the background",
                    data=dict(result.data),
                )
            )
            return action

        self._apply_result(action, result, events)
        task.state = action.state
        task.touch()
        if action.state in (ActionStatus.SUCCEEDED, ActionStatus.FAILED):
            if session.active_task_id == task.task_id:
                session.active_task_id = None

        if action.state is ActionStatus.SUCCEEDED:
            session.last_tool = action.tool
            session.last_arguments = dict(action.arguments)
            session.last_intent = action.tool
        return action

    def _apply_result(self, action: Action, result: Any, events: list[Event]) -> None:
        """Write a tool result into the action and emit the matching event."""
        if result.ok:
            action.state = ActionStatus.SUCCEEDED
            action.result = result.data
        elif result.cancelled:
            action.state = ActionStatus.CANCELLED
            action.error = result.error
        else:
            action.state = ActionStatus.FAILED
            action.error = result.error
        action.touch()
        events.append(
            Event(
                type=f"action.{action.state.value}",
                action_id=action.action_id,
                message=action.error.message if action.error else f"{action.tool} {action.state.value}",
                data={"result": action.result} if action.result is not None else {},
            )
        )

    def _make_context(self, session: SessionState, action: Action) -> ToolContext:
        """Build the context handed to the adapter.

        The completion callback lets an adapter finish an ongoing action
        later (for example when a timer fires) without the engine having to
        poll.
        """

        def complete(result: Any) -> None:
            self._apply_result(action, result, [])
            session.log_event(
                Event(
                    type=f"action.{action.state.value}",
                    action_id=action.action_id,
                    message=action.error.message if action.error else f"{action.tool} {action.state.value}",
                    data={"result": action.result} if action.result is not None else {},
                )
            )
            task = session.get_task_for_action(action.action_id)
            if task is not None:
                task.state = action.state
                task.touch()
                if action.state in (ActionStatus.SUCCEEDED, ActionStatus.CANCELLED):
                    if session.active_task_id == task.task_id:
                        session.active_task_id = None

        def progress(message: str, data: dict[str, Any]) -> None:
            session.log_event(
                Event(
                    type="action.progress",
                    action_id=action.action_id,
                    message=message,
                    data=data,
                )
            )

        return ToolContext(
            session_id=session.session_id,
            action_id=action.action_id,
            _complete=complete,
            _progress=progress,
        )

    # ------------------------------------------------------------------
    # Control intents
    # ------------------------------------------------------------------

    def _do_cancel(self, session: SessionState, events: list[Event]) -> tuple[list[Action], str]:
        """Cancel the most recent actionable action, or all of them on request."""
        candidates = [
            action
            for action in session.actions.values()
            if action.state
            in (
                ActionStatus.RUNNING,
                ActionStatus.AWAITING_CONFIRMATION,
                ActionStatus.PENDING,
            )
        ]
        if not candidates:
            return [], "there was nothing to cancel"

        target = candidates[-1]
        actions: list[Action] = []
        stopped = False

        if target.state is ActionStatus.RUNNING:
            stopped = self.registry.cancel(target.action_id, target.tool)
            if stopped:
                target.state = ActionStatus.CANCELLED
                target.touch()
                events.append(
                    Event(type="action.cancelled", action_id=target.action_id, message="cancelled")
                )
            else:
                # Honest reporting: the work may still be running.
                target.state = ActionStatus.PAUSED
                target.error = ActionError(
                    code="cancellation_unsupported",
                    message=(
                        f"'{target.tool}' cannot be interrupted; it may still be running"
                    ),
                )
                target.touch()
                events.append(
                    Event(
                        type="action.paused",
                        action_id=target.action_id,
                        message=target.error.message,
                    )
                )
            actions.append(target)
        else:
            target.state = ActionStatus.CANCELLED
            target.touch()
            actions.append(target)
            events.append(
                Event(type="action.cancelled", action_id=target.action_id, message="cancelled")
            )

        task = session.get_task_for_action(target.action_id)
        if task is not None:
            task.state = target.state
            task.touch()
            if session.active_task_id == task.task_id and target.state is ActionStatus.CANCELLED:
                session.active_task_id = None

        if not stopped and target.state is ActionStatus.PAUSED:
            return actions, target.error.message if target.error else "the action could not be stopped"
        return actions, "the pending work was cancelled"

    def _do_pause(self, session: SessionState, events: list[Event]) -> tuple[list[Action], str]:
        task = session.active_task()
        actions: list[Action] = []
        if task is None:
            return actions, "there is no active task to pause"
        for action_id in task.action_ids:
            action = session.get_action(action_id)
            if action is None:
                continue
            if action.state is ActionStatus.RUNNING:
                stopped = self.registry.cancel(action.action_id, action.tool)
                action.state = ActionStatus.PAUSED if stopped else ActionStatus.RUNNING
                if not stopped:
                    action.error = ActionError(
                        code="cancellation_unsupported",
                        message=f"'{action.tool}' cannot be interrupted; it may still be running",
                    )
                action.touch()
                actions.append(action)
        task.state = ActionStatus.PAUSED
        task.touch()
        session.active_task_id = None
        if task.task_id not in session.suspended_task_ids:
            session.suspended_task_ids.append(task.task_id)
        events.append(
            Event(type="task.paused", message="the task was suspended", data={"task_id": task.task_id})
        )
        return actions, "the task is paused - say continue to pick it up"

    def _do_confirm(
        self, session: SessionState, events: list[Event], *, approved: bool
    ) -> tuple[list[Action], str]:
        pending = session.awaiting_confirmation_actions()
        if not pending:
            return [], "there is nothing waiting for confirmation"
        action = pending[-1]
        if not approved:
            action.state = ActionStatus.CANCELLED
            action.touch()
            events.append(
                Event(type="action.cancelled", action_id=action.action_id, message="declined by the user")
            )
            return [action], "the action was declined"
        self._execute_action(action, session, events)
        return [action], f"{action.tool} {action.state.value}"

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    def _resume_task_id(self, request: SidekickRequest, session: SessionState) -> str | None:
        if request.continuation_context and request.continuation_context.resume_task_id:
            return request.continuation_context.resume_task_id
        if request.continuation_context and request.continuation_context.elide_tool:
            task = session.active_task()
            if task is not None:
                return task.task_id
            suspended = session.suspended_tasks()
            if suspended:
                return suspended[-1].task_id
            return None
        if is_resume_request(request.utterance):
            suspended = session.suspended_tasks()
            if suspended:
                return suspended[-1].task_id
            task = session.active_task()
            if task is not None:
                return task.task_id
            recent = session.most_recent_task()
            if recent is not None:
                return recent.task_id
        return None

    def _resume(
        self,
        request: SidekickRequest,
        session: SessionState,
        task_id: str,
        events: list[Event],
    ) -> SidekickResponse:
        """Resume a task: only the unfinished part is replayed."""
        task = session.get_task(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")

        pending_actions = [
            session.get_action(aid)
            for aid in task.action_ids
            if session.get_action(aid) is not None
            and session.get_action(aid).state
            not in (ActionStatus.SUCCEEDED, ActionStatus.CANCELLED, ActionStatus.SUPERSEDED)
        ]
        source = next((a for a in pending_actions if a is not None), None)

        if source is None:
            task.state = ActionStatus.SUCCEEDED
            task.touch()
            if task.task_id in session.suspended_task_ids:
                session.suspended_task_ids.remove(task.task_id)
            message = "that task was already finished"
            return SidekickResponse(
                request_id=request.request_id,
                session_id=request.session_id,
                intent=IntentInfo(normalized=normalize(request.utterance), confidence=0.6),
                action_plan=[],
                risk_level=RiskLevel.LOW,
                decision_model=self._last_model_info(),
                status=ResponseStatus.SUCCEEDED,
                events=events,
                session=self._session_view(session),
                message=message,
            )

        spec = self.registry.spec(source.tool)
        new_action: Action | None = None
        if spec is None:
            message = f"'{source.tool}' is no longer available"
        else:
            new_action = Action(
                action_id=new_id(),
                tool=source.tool,
                arguments=dict(source.arguments),
                approval_required=source.approval_required,
                state=ActionStatus.PENDING,
                description=source.description or task.description,
                plan_hash=plan_hash(source.tool, source.arguments),
            )
            new_action.job_id = new_action.action_id
            if source.approval_required:
                new_action.state = ActionStatus.AWAITING_CONFIRMATION
            else:
                self._execute_action(new_action, session, events)
            session.add_action(new_action)
            task.action_ids.append(new_action.action_id)
            task.state = new_action.state
            task.touch()
            session.active_task_id = task.task_id
            if task.task_id in session.suspended_task_ids:
                session.suspended_task_ids.remove(task.task_id)
            events.append(
                Event(
                    type="task.resumed",
                    message="the task was resumed",
                    data={"task_id": task.task_id, "action_id": new_action.action_id},
                )
            )
            message = f"resumed {source.tool}"

        return SidekickResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            intent=IntentInfo(normalized=normalize(request.utterance), confidence=0.6),
            action_plan=[new_action] if new_action is not None else [],
            risk_level=self._max_risk([source]),
            decision_model=self._last_model_info(),
            status=self._overall_status([new_action] if new_action is not None else [], None),
            events=events,
            session=self._session_view(session),
            message=message,
            speech=self._speech([new_action] if new_action is not None else [], None),
        )

    # ------------------------------------------------------------------
    # Out of band action control (used by the HTTP API)
    # ------------------------------------------------------------------

    def confirm_action(
        self,
        session_id: str,
        action_id: str,
        *,
        approved: bool,
        plan_hash: str | None = None,
    ) -> Action:
        """Approve or refuse a pending action.

        The confirmation binds to the exact action: when the caller sends a
        ``plan_hash`` that no longer matches, the confirmation has expired
        and a conflict is reported.
        """
        from .errors import ConflictError, NotFoundError

        session = self.sessions.get(session_id)
        action = session.get_action(action_id)
        if action is None:
            raise NotFoundError(f"unknown action: {action_id}")
        if action.state is not ActionStatus.AWAITING_CONFIRMATION:
            raise ConflictError(
                "the action is no longer waiting for a confirmation",
                details={"state": action.state.value},
            )
        if plan_hash is not None and plan_hash != action.plan_hash:
            raise ConflictError(
                "the plan changed, so the confirmation expired",
                details={"expected_plan_hash": action.plan_hash},
            )

        events: list[Event] = []
        if not approved:
            action.state = ActionStatus.CANCELLED
            action.touch()
            events.append(
                Event(type="action.cancelled", action_id=action.action_id, message="declined")
            )
            session.log_event(events[-1])
            return action

        self._execute_action(action, session, events)
        for event in events:
            session.log_event(event)
        return action

    def cancel_action(self, session_id: str, action_id: str) -> Action:
        """Cancel one pending or running action by id."""
        from .errors import ConflictError, NotFoundError

        session = self.sessions.get(session_id)
        action = session.get_action(action_id)
        if action is None:
            raise NotFoundError(f"unknown action: {action_id}")
        if action.state in (ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.CANCELLED):
            raise ConflictError(
                "the action already finished",
                details={"state": action.state.value},
            )
        if action.state is ActionStatus.RUNNING:
            stopped = self.registry.cancel(action.action_id, action.tool)
            action.state = ActionStatus.CANCELLED if stopped else ActionStatus.PAUSED
            if not stopped:
                action.error = ActionError(
                    code="cancellation_unsupported",
                    message=f"'{action.tool}' cannot be interrupted; it may still be running",
                )
        else:
            action.state = ActionStatus.CANCELLED
        action.touch()
        session.log_event(
            Event(
                type=f"action.{action.state.value}",
                action_id=action.action_id,
                message=action.error.message if action.error else "cancelled",
            )
        )
        return action

    def complete_action(
        self,
        session_id: str,
        action_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: ActionError | None = None,
    ) -> Action:
        """Record the outcome a *client* reported for one of its actions.

        The browser client executes the capabilities the core planned for it
        (``execution_target == "client"``) and reports back here. The core
        never claims the client did something it did not report.

        Only a client-executed action can be completed this way: completing a
        server action would let a client claim work the server did.
        """
        from .errors import ConflictError, NotFoundError

        session = self.sessions.get(session_id)
        action = session.get_action(action_id)
        if action is None:
            raise NotFoundError(f"unknown action: {action_id}")
        spec = self.registry.spec(action.tool)
        if spec is None or spec.execution_target != "client":
            raise ConflictError(
                "only a capability the client executes can be completed by the client",
                details={"tool": action.tool, "execution_target": spec.execution_target if spec else None},
            )
        if action.state not in (
            ActionStatus.PENDING,
            ActionStatus.RUNNING,
        ):
            raise ConflictError(
                "the action already finished",
                details={"state": action.state.value},
            )

        state = {
            "succeeded": ActionStatus.SUCCEEDED,
            "failed": ActionStatus.FAILED,
            "cancelled": ActionStatus.CANCELLED,
            "pending": ActionStatus.PENDING,
            "running": ActionStatus.RUNNING,
        }.get(status.lower())
        if state is None:
            raise ConflictError(f"unknown status: {status}")

        action.state = state
        if result is not None:
            action.result = result
        if error is not None:
            action.error = error
        action.touch()
        session.log_event(
            Event(
                type=f"action.{action.state.value}",
                action_id=action.action_id,
                message=action.error.message if action.error else f"{action.tool} {action.state.value}",
                data={"result": action.result} if action.result is not None else {},
            )
        )
        return action

    def expire_client_actions(self, now: float | None = None) -> list[Action]:
        """Fail the client actions the client never reported on.

        A capability the browser was supposed to run must not stay ``pending``
        forever: after the deadline the action fails with a clear reason
        instead of hanging.
        """
        expired: list[Action] = []
        moment = now if now is not None else time.time()
        for session_id in self.sessions.session_ids():
            session = self.sessions.peek(session_id)
            if session is None:
                continue
            for action in session.actions.values():
                if action.state is not ActionStatus.PENDING:
                    continue
                spec = self.registry.spec(action.tool)
                if spec is None or spec.execution_target != "client":
                    continue
                deadline = (action.result or {}).get("client_deadline")
                if not isinstance(deadline, (int, float)) or moment < deadline:
                    continue
                action.state = ActionStatus.FAILED
                action.error = ActionError(
                    code="client_timeout",
                    message=(
                        f"the app did not report a result for '{action.tool}' "
                        "in time"
                    ),
                    retryable=True,
                    timeout=True,
                )
                action.touch()
                session.log_event(
                    Event(
                        type="action.failed",
                        action_id=action.action_id,
                        message=action.error.message,
                    )
                )
                expired.append(action)
        return expired

    # ------------------------------------------------------------------
    # Event streaming
    # ------------------------------------------------------------------

    def action_events(
        self, session_id: str, action_id: str, after_seq: int = 0
    ) -> list[Event]:
        """The events already logged for one action."""
        session = self.sessions.peek(session_id)
        if session is None:
            return []
        return session.events_after(after_seq, action_id=action_id)

    def wait_for_action_events(
        self,
        session_id: str,
        action_id: str,
        after_seq: int = 0,
        timeout: float = 1.0,
    ) -> list[Event]:
        """Wait for new events of one action and return them."""
        session = self.sessions.peek(session_id)
        if session is None:
            return []
        return session.wait_for_events(after_seq, action_id=action_id, timeout=timeout)

    def get_action(self, session_id: str, action_id: str) -> Action | None:
        session = self.sessions.peek(session_id)
        if session is None:
            return None
        return session.get_action(action_id)

    # ------------------------------------------------------------------
    # Spoken summary
    # ------------------------------------------------------------------

    def _speech(
        self,
        actions: list[Action],
        clarification: Clarification | None,
        corrected: bool = False,
    ) -> str | None:
        """A short line the client may speak verbatim.

        It describes what is *about to happen* or what is needed from the
        user. It never claims that something finished unless it did.
        """
        if clarification is not None:
            return clarification.question

        if not actions:
            return None

        for action in actions:
            if action.state is ActionStatus.AWAITING_CONFIRMATION:
                phrase = self._action_phrase(action)
                if phrase:
                    return f"Can you confirm: {phrase[0].lower()}{phrase[1:]}"
                return "Can you confirm that action?"

        for action in actions:
            if action.state in (
                ActionStatus.PENDING,
                ActionStatus.RUNNING,
                ActionStatus.SUCCEEDED,
            ):
                result = action.result if isinstance(action.result, dict) else {}
                message = result.get("message")
                if isinstance(message, str) and message:
                    return message
                phrase = self._action_phrase(action)
                if phrase:
                    if corrected:
                        return f"{phrase.rstrip('.')} instead."
                    return phrase
        return None

    def _action_phrase(self, action: Action) -> str | None:
        """Render the tool's spoken template with the action's arguments."""
        spec = self.registry.spec(action.tool)
        if spec is None or not spec.speech_template:
            return None
        values: dict[str, Any] = {}
        for arg in spec.arguments:
            if arg.name not in action.arguments:
                continue
            value = action.arguments[arg.name]
            if arg.type == "duration" and isinstance(value, (int, float)):
                values[arg.name] = _humanize_duration(int(value))
            else:
                values[arg.name] = value
        # A destination is spoken with its brand name when the tool knows one.
        for key, value in list(values.items()):
            if isinstance(value, str):
                label = spec.destination_labels.get(value)
                if label:
                    values[key] = label
        try:
            rendered = spec.speech_template.format_map(_MissingAsEmpty(values))
        except (KeyError, IndexError, ValueError):
            return None
        rendered = re.sub(r"\s{2,}", " ", rendered).strip()
        rendered = re.sub(r"\s+([.,!?])", r"\1", rendered)
        return rendered or None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _defer(self, request: SidekickRequest, session: SessionState) -> SidekickResponse:
        """A non-final transcript is never executed."""
        response = SidekickResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            intent=IntentInfo(normalized=normalize(request.utterance), confidence=0.0),
            action_plan=[],
            risk_level=RiskLevel.LOW,
            decision_model=self._last_model_info(),
            status=ResponseStatus.AWAITING_TRANSCRIPT,
            events=[Event(type="turn.deferred", message="waiting for the final transcript")],
            session=self._session_view(session),
            message="waiting for the transcript to settle",
        )
        session.cache_response(request.request_id, response.model_copy(deep=True))
        return response

    def _max_risk(self, actions: list[Action]) -> RiskLevel:
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.IRREVERSIBLE]
        worst = RiskLevel.LOW
        for action in actions:
            spec = self.registry.spec(action.tool)
            if spec is None:
                continue
            if order.index(spec.risk) > order.index(worst):
                worst = spec.risk
        return worst

    def _overall_status(self, actions: list[Action], clarification: Clarification | None) -> ResponseStatus:
        if clarification is not None:
            return ResponseStatus.NEEDS_CLARIFICATION
        if not actions:
            return ResponseStatus.SUCCEEDED
        states = [a.state for a in actions]
        if ActionStatus.AWAITING_CONFIRMATION in states:
            return ResponseStatus.AWAITING_CONFIRMATION
        if ActionStatus.RUNNING in states:
            return ResponseStatus.RUNNING
        if ActionStatus.FAILED in states:
            return ResponseStatus.FAILED
        if ActionStatus.CANCELLED in states:
            return ResponseStatus.CANCELLED
        if ActionStatus.SUPERSEDED in states:
            return ResponseStatus.SUPERSEDED
        if ActionStatus.PAUSED in states:
            return ResponseStatus.PAUSED
        if all(state is ActionStatus.SUCCEEDED for state in states):
            return ResponseStatus.SUCCEEDED
        return ResponseStatus.PENDING

    def _tool_options(self) -> list[str]:
        return sorted(spec.name for spec in self.registry.catalog)

    def _unsupported_clarification(self, text: str = "") -> Clarification:
        """An honest answer for a request the product cannot fulfil.

        Saying "I did not catch which action you want" is not the same as
        "I do not have a capability for that". The options are the human
        readable names of what the product *can* do, and a near miss is
        offered when the utterance was one word away from a real capability.
        """
        inventory = self.capability_inventory()
        options = [
            item["label"]
            for item in inventory
            if item["state"] in ("live", "client")
        ]
        if not options:
            return Clarification(
                question=(
                    "I do not have a working capability for that yet. "
                    "There is nothing I can do yet in this deployment."
                ),
                options=[],
                missing_arguments=[],
            )

        question = (
            "I do not have a capability for that yet. "
            "What I can do: " + ", ".join(options) + "."
        )
        # A "did you mean" is only offered where it can be reliable. A loose
        # comparison cannot tell "find a restaurant" from "find a movie", so
        # the answer lists what the product can do instead of guessing.
        return Clarification(
            question=question,
            options=options,
            missing_arguments=[],
        )

    def _describe_pending(self, session: SessionState) -> str:
        parts: list[str] = []
        for action in session.actions.values():
            if action.state in (
                ActionStatus.PENDING,
                ActionStatus.AWAITING_CONFIRMATION,
                ActionStatus.RUNNING,
            ):
                parts.append(f"{action.tool} ({action.state.value})")
        if not parts:
            return "nothing is pending"
        return "pending: " + ", ".join(parts)

    def _session_view(self, session: SessionState) -> SessionView:
        return SessionView(
            session_id=session.session_id,
            active_task_id=session.active_task_id,
            suspended_task_ids=list(session.suspended_task_ids),
            pending_action_ids=[a.action_id for a in session.pending_actions()],
            awaiting_confirmation_action_ids=[
                a.action_id for a in session.awaiting_confirmation_actions()
            ],
            last_intent=session.last_intent,
            last_entities=list(session.last_entities),
            turn_count=session.turn_count,
            updated_at=session.updated_at,
        )

    def _summarise(self, actions: list[Action], clarification: Clarification | None) -> str:
        if clarification is not None:
            return clarification.question
        if not actions:
            return "nothing to do"
        for action in actions:
            if self._is_control(action.tool):
                result = action.result or {}
                message = result.get("message")
                if message:
                    return str(message)
        done = [a for a in actions if a.state is ActionStatus.SUCCEEDED]
        if len(done) == len(actions):
            return "; ".join(f"{a.tool} succeeded" for a in done)
        waiting = [a for a in actions if a.state is ActionStatus.AWAITING_CONFIRMATION]
        if waiting:
            return f"{waiting[0].tool} is waiting for confirmation"
        failed = [a for a in actions if a.state is ActionStatus.FAILED]
        if failed:
            return failed[0].error.message if failed[0].error else "an action failed"
        return "; ".join(f"{a.tool} {a.state.value}" for a in actions)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _clean_remainder(text: str) -> str | None:
    """Strip the filler words from a leftover text."""
    value = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    value = re.sub(r"^(?:that|to|for|about|with|and|me|my|i)\s+", "", value, flags=re.I)
    return value or None


class _MissingAsEmpty(dict):
    """A format mapping that leaves unknown placeholders empty."""

    def __missing__(self, key: str) -> str:
        return ""


def _humanize_duration(seconds: int) -> str:
    """'300' -> '5 minutes'."""
    if seconds < 60:
        return f"{seconds} second" if seconds == 1 else f"{seconds} seconds"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60 and rest == 0:
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    if minutes:
        parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
    if rest:
        parts.append(f"{rest} second" if rest == 1 else f"{rest} seconds")
    return " ".join(parts)


def _match_enum(values: tuple[str, ...] | list[str], text: str) -> str | None:
    """Find an enumeration value mentioned in the text (longest match wins)."""
    lowered = text.lower()
    best: str | None = None
    for value in values:
        if value.lower() in lowered:
            if best is None or len(value) > len(best):
                best = value
    return best


def _clarification_question(spec: ToolSpec, kind: str, argument: str | None) -> str:
    if kind == "missing_argument":
        return f"Which {argument or 'value'} should I use for {spec.name}?"
    if kind == "ambiguous_argument":
        return f"Which value should I use for {argument or 'the parameter'}?"
    if kind == "unknown_argument":
        return f"I did not understand the value for {argument or 'that parameter'}."
    return "Could you clarify that?"
