"""Tests for Alexa Skills Kit adapter and HTTP endpoint."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest
from starlette.testclient import TestClient

from sidekick.api.alexa import AlexaAdapter
from sidekick.api.app import create_app
from sidekick.bootstrap import build_engine


@pytest.fixture
def temp_workspace() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def engine(temp_workspace: Path):
    return build_engine(prefer_model="rule", workspace=temp_workspace)


@pytest.fixture
def client(engine):
    app = create_app(engine)
    return TestClient(app)


def test_alexa_launch_request(engine) -> None:
    adapter = AlexaAdapter(engine)
    payload = {
        "version": "1.0",
        "session": {"sessionId": "amzn1.echo-api.session.test-01"},
        "request": {"type": "LaunchRequest"},
    }
    response = adapter.handle(payload)
    assert response["version"] == "1.0"
    speech = response["response"]["outputSpeech"]["text"]
    assert "Welcome to Sidekick" in speech
    assert response["response"]["shouldEndSession"] is False


def test_alexa_help_intent(engine) -> None:
    adapter = AlexaAdapter(engine)
    payload = {
        "version": "1.0",
        "session": {"sessionId": "amzn1.echo-api.session.test-02"},
        "request": {
            "type": "IntentRequest",
            "intent": {"name": "AMAZON.HelpIntent"},
        },
    }
    response = adapter.handle(payload)
    speech = response["response"]["outputSpeech"]["text"]
    assert "You can say" in speech
    assert response["response"]["shouldEndSession"] is False


def test_alexa_stop_intent(engine) -> None:
    adapter = AlexaAdapter(engine)
    payload = {
        "version": "1.0",
        "session": {"sessionId": "amzn1.echo-api.session.test-03"},
        "request": {
            "type": "IntentRequest",
            "intent": {"name": "AMAZON.StopIntent"},
        },
    }
    response = adapter.handle(payload)
    speech = response["response"]["outputSpeech"]["text"]
    assert "Goodbye" in speech
    assert response["response"]["shouldEndSession"] is True


def test_alexa_executes_real_task_note_write(engine, temp_workspace: Path) -> None:
    adapter = AlexaAdapter(engine)
    payload = {
        "version": "1.0",
        "session": {"sessionId": "amzn1.echo-api.session.test-04"},
        "request": {
            "type": "IntentRequest",
            "intent": {
                "name": "SidekickIntent",
                "slots": {
                    "Utterance": {"name": "Utterance", "value": "write a note to buy fresh milk"}
                },
            },
        },
    }
    response = adapter.handle(payload)
    output = response["response"]
    speech_text = output["outputSpeech"]["text"]
    assert "note" in speech_text.lower()
    assert output["card"]["title"].startswith("Sidekick")

    # Verify real file was created in workspace
    notes_dir = temp_workspace / "notes"
    notes = list(notes_dir.glob("*.txt"))
    assert len(notes) > 0
    content = notes[0].read_text(encoding="utf-8")
    assert "milk" in content


def test_alexa_skill_id_validation(engine) -> None:
    adapter = AlexaAdapter(engine, skill_id="amzn1.ask.skill.valid-1234")

    # Mismatched skill ID
    bad_payload = {
        "version": "1.0",
        "session": {
            "sessionId": "s-1",
            "application": {"applicationId": "amzn1.ask.skill.wrong-9999"},
        },
        "request": {"type": "LaunchRequest"},
    }
    bad_res = adapter.handle(bad_payload)
    assert "Unauthorized" in bad_res["response"]["outputSpeech"]["text"]

    # Matching skill ID
    good_payload = {
        "version": "1.0",
        "session": {
            "sessionId": "s-2",
            "application": {"applicationId": "amzn1.ask.skill.valid-1234"},
        },
        "request": {"type": "LaunchRequest"},
    }
    good_res = adapter.handle(good_payload)
    assert "Welcome" in good_res["response"]["outputSpeech"]["text"]


def test_alexa_http_endpoint(client: TestClient) -> None:
    payload = {
        "version": "1.0",
        "session": {"sessionId": "amzn1.echo-api.session.http-test"},
        "request": {
            "type": "IntentRequest",
            "intent": {
                "name": "SidekickIntent",
                "slots": {
                    "Utterance": {"name": "Utterance", "value": "set a timer for 5 minutes"}
                },
            },
        },
    }
    res = client.post("/api/v1/alexa", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == "1.0"
    assert "timer" in data["response"]["outputSpeech"]["text"].lower()
