"""Alexa Skills Kit (ASK) request signature and timestamp verifier.

Enforces production security compliance for Alexa HTTP web service endpoints:
1. Validates the Alexa Application ID (Skill ID).
2. Validates the request timestamp against current UTC time (150-second tolerance).
3. Validates the SSL/TLS certificate chain URL (protocol, hostname, path, port).
4. Verifies the SHA-256 with RSA request signature against the Amazon public certificate.

In non-production / testing mode (ALEXA_VERIFY_SIGNATURE != true and ENVIRONMENT != production),
unit-test convenience is preserved when signature headers are omitted. When signature headers
are present or when strict verification is enabled, full cryptographic verification is enforced.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

try:
    from ask_sdk_webservice_support.verifier import (
        RequestVerifier,
        TimestampVerifier,
        VerificationException,
        SIGNATURE_CERT_CHAIN_URL_HEADER,
        SIGNATURE_HEADER,
    )
    from ask_sdk_core.serialize import DefaultSerializer
    from ask_sdk_model import RequestEnvelope
    _ASK_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ASK_SDK_AVAILABLE = False
    RequestVerifier = None  # type: ignore[assignment, misc]
    TimestampVerifier = None  # type: ignore[assignment, misc]
    VerificationException = Exception  # type: ignore[assignment, misc]
    DefaultSerializer = None  # type: ignore[assignment, misc]
    RequestEnvelope = None  # type: ignore[assignment, misc]
    SIGNATURE_CERT_CHAIN_URL_HEADER = "SignatureCertChainUrl"
    SIGNATURE_HEADER = "Signature-256"


class AlexaSecurityError(Exception):
    """Base exception for Alexa security verification failures."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AlexaConfigurationError(AlexaSecurityError):
    """Raised when Alexa security configuration is missing in production."""

    def __init__(self, message: str = "Alexa Skill ID not configured in production.") -> None:
        super().__init__(message, status_code=403)


class AlexaSkillMismatchError(AlexaSecurityError):
    """Raised when the request Application ID does not match the configured Skill ID."""

    def __init__(self, message: str = "Unauthorized Alexa Skill ID.") -> None:
        super().__init__(message, status_code=403)


class AlexaTimestampError(AlexaSecurityError):
    """Raised when the Alexa request timestamp is missing, malformed, or expired."""

    def __init__(self, message: str = "Alexa request timestamp expired or invalid.") -> None:
        super().__init__(message, status_code=400)


class AlexaSignatureError(AlexaSecurityError):
    """Raised when the Alexa certificate URL or cryptographic signature is invalid."""

    def __init__(self, message: str = "Alexa request signature verification failed.") -> None:
        super().__init__(message, status_code=400)


class AlexaRequestVerifier:
    """Validates Alexa HTTP request security according to ASK specifications."""

    def __init__(
        self,
        skill_id: Optional[str] = None,
        require_verification: Optional[bool] = None,
        tolerance_in_seconds: float = 150.0,
    ) -> None:
        self.skill_id = skill_id or os.environ.get("ALEXA_SKILL_ID")
        if require_verification is not None:
            self.require_verification = require_verification
        else:
            verify_env = os.environ.get("ALEXA_VERIFY_SIGNATURE", "").strip().lower()
            env_mode = (
                os.environ.get("ENVIRONMENT", "").strip().lower()
                or os.environ.get("SIDEKICK_ENV", "").strip().lower()
            )
            self.require_verification = verify_env in ("true", "1", "yes") or env_mode == "production"

        self.tolerance_in_seconds = tolerance_in_seconds
        self._timestamp_verifier = (
            TimestampVerifier(tolerance_in_millis=tolerance_in_seconds * 1000)
            if _ASK_SDK_AVAILABLE
            else None
        )
        self._request_verifier = RequestVerifier() if _ASK_SDK_AVAILABLE else None
        self._serializer = DefaultSerializer() if _ASK_SDK_AVAILABLE else None

    @property
    def cert_cache(self) -> dict[str, bytes]:
        """Direct access to certificate cache for testing or preloading certificates."""
        if self._request_verifier is not None:
            return self._request_verifier._cert_cache
        return {}

    def extract_skill_id(self, payload: dict[str, Any]) -> Optional[str]:
        """Extract application ID from session or context."""
        session_app = payload.get("session", {}).get("application", {}).get("applicationId")
        if session_app:
            return session_app
        context_app = (
            payload.get("context", {})
            .get("System", {})
            .get("application", {})
            .get("applicationId")
        )
        return context_app

    def verify_request(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """Verify the authenticity, integrity, and freshness of an Alexa request.

        Raises an AlexaSecurityError (or appropriate subclass) if verification fails.
        """
        # Parse payload if not provided
        if payload is None:
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except Exception as exc:
                raise AlexaSecurityError(f"Malformed JSON payload: {exc}", status_code=400) from exc

        # 1. Production Skill Configuration Check
        if self.require_verification and not self.skill_id:
            raise AlexaConfigurationError(
                "Production Alexa endpoint requires ALEXA_SKILL_ID to be configured."
            )

        # 2. Skill ID Verification (if configured or in strict mode)
        app_id = self.extract_skill_id(payload)
        if self.skill_id:
            if not app_id or app_id != self.skill_id:
                raise AlexaSkillMismatchError(
                    f"Mismatched Alexa skill ID: expected '{self.skill_id}', got '{app_id}'."
                )

        # Detect signature headers (case-insensitive)
        header_map = {k.lower(): v for k, v in headers.items()}
        cert_url = header_map.get("signaturecertchainurl")
        sig = header_map.get("signature-256") or header_map.get("signature")

        has_signature_headers = bool(cert_url and sig)

        # In non-strict mode, if no signature headers are sent, preserve unit-test convenience
        if not self.require_verification and not has_signature_headers:
            # If timestamp is provided, still validate its freshness
            req = payload.get("request", {})
            if "timestamp" in req:
                self._verify_timestamp_manual(req["timestamp"])
            return

        # 3. Signature & Certificate Verification
        if not cert_url or not sig:
            raise AlexaSignatureError(
                "Missing required Alexa signature headers ('SignatureCertChainUrl' and 'Signature-256')."
            )

        # URL format sanity checks before network/cache retrieval
        parsed_url = urlparse(cert_url)
        if parsed_url.scheme.lower() != "https":
            raise AlexaSignatureError(f"Signature Certificate URL must use HTTPS: {cert_url}")
        host = (parsed_url.hostname or "").lower()
        if host not in ("s3.amazonaws.com", "echo-api.amazon.com"):
            raise AlexaSignatureError(
                f"Signature Certificate URL has invalid hostname '{host}'. Expecting 's3.amazonaws.com' or 'echo-api.amazon.com'."
            )
        if parsed_url.port and parsed_url.port != 443:
            raise AlexaSignatureError(f"Signature Certificate URL port must be 443, got {parsed_url.port}")

        # 4. Timestamp Verification
        req = payload.get("request", {})
        ts_str = req.get("timestamp")
        if not ts_str:
            raise AlexaTimestampError("Missing required 'request.timestamp' in Alexa request.")
        self._verify_timestamp(ts_str, raw_body)

        # 5. Cryptographic signature verification via ASK SDK or fallback
        raw_body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
        if self._request_verifier is not None and self._serializer is not None:
            try:
                env = self._serializer.deserialize(raw_body_str, RequestEnvelope)
                # Form dict for ASK verifier with expected header casing
                ask_headers = {
                    "SignatureCertChainUrl": cert_url,
                    "Signature-256": sig,
                    "Signature": sig,
                }
                self._request_verifier.verify(ask_headers, raw_body_str, env)
            except VerificationException as exc:
                raise AlexaSignatureError(f"Cryptographic signature verification failed: {exc}") from exc
            except Exception as exc:
                raise AlexaSignatureError(f"Alexa request verification error: {exc}") from exc
        else:
            raise AlexaSignatureError("ASK SDK verification engine not installed.")

    def _verify_timestamp(self, ts_str: str, raw_body: bytes) -> None:
        """Verify timestamp using ASK TimestampVerifier or ISO 8601 parser."""
        if self._timestamp_verifier is not None and self._serializer is not None:
            try:
                raw_body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
                env = self._serializer.deserialize(raw_body_str, RequestEnvelope)
                self._timestamp_verifier.verify({}, raw_body_str, env)
                return
            except VerificationException as exc:
                raise AlexaTimestampError(f"Request timestamp verification failed: {exc}") from exc
            except Exception:
                pass
        self._verify_timestamp_manual(ts_str)

    def _verify_timestamp_manual(self, ts_str: str) -> None:
        """Manual ISO 8601 UTC timestamp freshness check against tolerance window."""
        try:
            # Handle ISO formats with 'Z' or offset
            clean_ts = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = abs((now - dt).total_seconds())
            if diff > self.tolerance_in_seconds:
                raise AlexaTimestampError(
                    f"Timestamp {ts_str} difference ({diff:.1f}s) exceeds tolerance of {self.tolerance_in_seconds:.1f}s."
                )
        except ValueError as exc:
            raise AlexaTimestampError(f"Malformed ISO timestamp '{ts_str}': {exc}") from exc
