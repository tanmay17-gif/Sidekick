"""Regression tests for Alexa Skills Kit (ASK) request security.

Verifies:
1. Valid cryptographic request signature, certificate chain, and timestamp.
2. Rejection of invalid / tampered signatures (HTTP 400).
3. Rejection of expired timestamps outside the 150-second tolerance window (HTTP 400).
4. Rejection of mismatched skill application IDs (HTTP 403).
5. Rejection of untrusted or invalid certificate URLs (HTTP 400).
6. Enforcement of required skill ID configuration in production mode (HTTP 403).
7. Preservation of development/testing convenience when signature headers are omitted in non-production.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
import pytest
from starlette.testclient import TestClient

from sidekick.api.alexa_verifier import AlexaRequestVerifier
from sidekick.api.app import create_app
from sidekick.bootstrap import build_engine


@pytest.fixture
def temp_workspace() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def crypto_materials():
    """Generates an in-memory test RSA key pair and signed certificate with Amazon SAN."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "echo-api.amazon.com"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("echo-api.amazon.com")]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_url = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"
    return {
        "private_key": private_key,
        "cert_pem": cert_pem,
        "cert_url": cert_url,
    }


def _create_signed_payload(
    crypto_materials: dict[str, Any],
    skill_id: str,
    timestamp: str | None = None,
    utterance: str = "what can you do",
) -> tuple[bytes, dict[str, str]]:
    """Builds an Alexa JSON body and headers with a valid SHA256-RSA signature."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload_dict = {
        "version": "1.0",
        "session": {
            "sessionId": "amzn1.echo-api.session.test-security",
            "application": {"applicationId": skill_id},
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "amzn1.echo-api.request.test-req",
            "timestamp": timestamp,
            "intent": {
                "name": "SidekickIntent",
                "slots": {"Utterance": {"name": "Utterance", "value": utterance}},
            },
        },
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig = crypto_materials["private_key"].sign(raw_body, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig).decode("ascii")

    headers = {
        "Content-Type": "application/json",
        "SignatureCertChainUrl": crypto_materials["cert_url"],
        "Signature-256": sig_b64,
    }
    return raw_body, headers


def test_alexa_valid_request_with_signature(temp_workspace: Path, crypto_materials: dict[str, Any]) -> None:
    skill_id = "amzn1.ask.skill.prod-sidekick-001"
    verifier = AlexaRequestVerifier(skill_id=skill_id, require_verification=True)
    verifier.cert_cache[crypto_materials["cert_url"]] = crypto_materials["cert_pem"]
    # In unit tests, our test certificate is self-signed, so bypass external CA trust-chain validation
    if verifier._request_verifier is not None:
        verifier._request_verifier._validate_cert_chain = lambda cert_chain: None

    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    raw_body, headers = _create_signed_payload(crypto_materials, skill_id)
    res = client.post("/api/v1/alexa", content=raw_body, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["version"] == "1.0"
    speech = data["response"]["outputSpeech"]["text"]
    assert len(speech) > 0


def test_alexa_invalid_signature_rejected(temp_workspace: Path, crypto_materials: dict[str, Any]) -> None:
    skill_id = "amzn1.ask.skill.prod-sidekick-001"
    verifier = AlexaRequestVerifier(skill_id=skill_id, require_verification=True)
    verifier.cert_cache[crypto_materials["cert_url"]] = crypto_materials["cert_pem"]

    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    raw_body, headers = _create_signed_payload(crypto_materials, skill_id)
    # Corrupt signature
    headers["Signature-256"] = base64.b64encode(b"invalid_signature_bytes_here" * 8).decode("ascii")

    res = client.post("/api/v1/alexa", content=raw_body, headers=headers)
    assert res.status_code == 400
    assert "signature verification failed" in res.json()["detail"].lower()


def test_alexa_expired_timestamp_rejected(temp_workspace: Path, crypto_materials: dict[str, Any]) -> None:
    skill_id = "amzn1.ask.skill.prod-sidekick-001"
    verifier = AlexaRequestVerifier(skill_id=skill_id, require_verification=True)
    verifier.cert_cache[crypto_materials["cert_url"]] = crypto_materials["cert_pem"]

    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    # 10 minutes in the past
    expired_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_body, headers = _create_signed_payload(crypto_materials, skill_id, timestamp=expired_time)

    res = client.post("/api/v1/alexa", content=raw_body, headers=headers)
    assert res.status_code == 400
    assert "timestamp" in res.json()["detail"].lower()


def test_alexa_mismatched_skill_id_rejected(temp_workspace: Path, crypto_materials: dict[str, Any]) -> None:
    configured_skill_id = "amzn1.ask.skill.correct-123"
    verifier = AlexaRequestVerifier(skill_id=configured_skill_id, require_verification=True)
    verifier.cert_cache[crypto_materials["cert_url"]] = crypto_materials["cert_pem"]

    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    # Payload has wrong skill ID
    raw_body, headers = _create_signed_payload(crypto_materials, skill_id="amzn1.ask.skill.malicious-999")

    res = client.post("/api/v1/alexa", content=raw_body, headers=headers)
    assert res.status_code == 403
    assert "skill id" in res.json()["detail"].lower()


def test_alexa_invalid_cert_url_rejected(temp_workspace: Path, crypto_materials: dict[str, Any]) -> None:
    skill_id = "amzn1.ask.skill.prod-sidekick-001"
    verifier = AlexaRequestVerifier(skill_id=skill_id, require_verification=True)

    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    raw_body, headers = _create_signed_payload(crypto_materials, skill_id)
    # Untrusted certificate URL domain
    headers["SignatureCertChainUrl"] = "https://attacker-domain.com/evil-cert.pem"

    res = client.post("/api/v1/alexa", content=raw_body, headers=headers)
    assert res.status_code == 400
    assert "hostname" in res.json()["detail"].lower()


def test_alexa_production_mode_requires_skill_id(temp_workspace: Path, crypto_materials: dict[str, Any]) -> None:
    # Verifier with no skill_id but strict verification enabled
    verifier = AlexaRequestVerifier(skill_id=None, require_verification=True)
    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    raw_body, headers = _create_signed_payload(crypto_materials, skill_id="amzn1.ask.skill.any")

    res = client.post("/api/v1/alexa", content=raw_body, headers=headers)
    assert res.status_code == 403
    assert "requires alexa_skill_id" in res.json()["detail"].lower()


def test_alexa_dev_convenience_preserved_without_signature(temp_workspace: Path) -> None:
    # In dev mode (require_verification=False), requests without signature headers succeed
    verifier = AlexaRequestVerifier(skill_id=None, require_verification=False)
    engine = build_engine(prefer_model="rule", workspace=temp_workspace)
    app = create_app(engine, alexa_verifier=verifier)
    client = TestClient(app)

    payload = {
        "version": "1.0",
        "session": {"sessionId": "dev-session-01"},
        "request": {
            "type": "LaunchRequest",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    res = client.post("/api/v1/alexa", json=payload)
    assert res.status_code == 200
    assert "Welcome to Sidekick" in res.json()["response"]["outputSpeech"]["text"]
