"""Alexa Skills Kit (ASK) request and response adapter for Sidekick.

Converts standard Alexa JSON requests (LaunchRequest, IntentRequest, SessionEndedRequest)
into Sidekick DecisionEngine requests, and formats the result into compliant Alexa
response JSON with SSML/speech output and cards.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
import uuid

from ..core.engine import DecisionEngine
from ..core.schemas import SidekickRequest


class AlexaAdapter:
    """Handles Alexa Skills Kit requests and drives the Sidekick DecisionEngine."""

    def __init__(self, engine: DecisionEngine, skill_id: Optional[str] = None) -> None:
        self.engine = engine
        self.skill_id = skill_id or os.environ.get("ALEXA_SKILL_ID")

    def handle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process an Alexa JSON payload and return an Alexa JSON response."""
        request = payload.get("request", {})
        session = payload.get("session", {})
        request_type = request.get("type")

        # Validate Application ID if configured
        if self.skill_id:
            app_id = session.get("application", {}).get("applicationId")
            if app_id != self.skill_id:
                return self._build_response(
                    speech="Unauthorized Alexa skill ID.",
                    should_end_session=True,
                )

        session_id = session.get("sessionId") or f"alexa-{uuid.uuid4().hex[:12]}"

        if request_type == "LaunchRequest":
            return self._handle_launch()

        if request_type == "IntentRequest":
            return self._handle_intent(request, session_id)

        if request_type == "SessionEndedRequest":
            return self._handle_session_ended(request)

        return self._build_response(
            speech="Sidekick did not recognize that request type.",
            should_end_session=True,
        )

    def _handle_launch(self) -> Dict[str, Any]:
        welcome = (
            "Welcome to Sidekick, your intelligent task and movie companion. "
            "You can ask me to run tasks, manage notes and timers, search the web, "
            "or start Movie Buddy. What would you like to do?"
        )
        return self._build_response(
            speech=welcome,
            reprompt="What task can I help you with?",
            should_end_session=False,
        )

    def _handle_intent(self, request: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        intent = request.get("intent", {})
        intent_name = intent.get("name", "")

        if intent_name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
            return self._build_response(
                speech="Goodbye from Sidekick.",
                should_end_session=True,
            )

        if intent_name == "AMAZON.HelpIntent":
            help_text = (
                "You can say things like: take a note to buy coffee, set a timer for five minutes, "
                "open Spotify, or what can you do. How can I assist you?"
            )
            return self._build_response(
                speech=help_text,
                reprompt="What would you like me to do?",
                should_end_session=False,
            )

        # Extract utterance from slots or intent
        utterance = self._extract_utterance(intent)
        if not utterance:
            return self._build_response(
                speech="I didn't catch that. Could you please repeat your request?",
                reprompt="Please tell me what you would like to do.",
                should_end_session=False,
            )

        # Dispatch to Sidekick DecisionEngine
        req = SidekickRequest(
            request_id=f"alexa-{uuid.uuid4().hex[:12]}",
            utterance=utterance,
            input_source="voice",
            session_id=session_id,
        )
        response = self.engine.handle(req)

        # Build spoken text
        speech = response.speech
        if not speech and response.clarification:
            speech = response.clarification.question
        if not speech:
            speech = "I processed your request."

        should_end = True
        if response.clarification is not None:
            should_end = False
        elif any(action.state.value in ("pending", "running", "awaiting_confirmation") for action in response.action_plan):
            should_end = False

        card_title = "Sidekick"
        if response.action_plan:
            card_title = f"Sidekick: {response.action_plan[0].tool}"

        return self._build_response(
            speech=speech,
            card_title=card_title,
            card_content=speech,
            reprompt="Is there anything else I can do for you?" if not should_end else None,
            should_end_session=should_end,
            session_attributes={"last_request_id": response.request_id},
        )

    def _handle_session_ended(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self._build_response(speech="", should_end_session=True)

    def _extract_utterance(self, intent: Dict[str, Any]) -> str:
        slots = intent.get("slots", {})
        # Look for custom slot names commonly used
        for slot_name in ("Utterance", "Query", "Task", "Text", "Command"):
            if slot_name in slots and slots[slot_name].get("value"):
                return str(slots[slot_name]["value"])

        # Concatenate any available non-empty slot values
        values = [
            str(s.get("value"))
            for s in slots.values()
            if isinstance(s, dict) and s.get("value")
        ]
        if values:
            return " ".join(values)

        # Fallback to intent name if readable
        raw_name = intent.get("name", "")
        if raw_name.startswith("Sidekick"):
            return raw_name.replace("Sidekick", "").strip() or ""
        return ""

    def _build_response(
        self,
        *,
        speech: str,
        reprompt: Optional[str] = None,
        card_title: Optional[str] = None,
        card_content: Optional[str] = None,
        should_end_session: bool = True,
        session_attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "version": "1.0",
            "response": {
                "outputSpeech": {
                    "type": "PlainText",
                    "text": speech,
                },
                "shouldEndSession": should_end_session,
            },
            "sessionAttributes": session_attributes or {},
        }

        if reprompt:
            response["response"]["reprompt"] = {
                "outputSpeech": {
                    "type": "PlainText",
                    "text": reprompt,
                }
            }

        if card_title and card_content:
            response["response"]["card"] = {
                "type": "Simple",
                "title": card_title,
                "content": card_content,
            }

        return response
