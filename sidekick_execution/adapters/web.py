"""A real HTTP fetch adapter for Sidekick execution.

A voice assistant needs to be able to *look something up*. This adapter makes
a **real** HTTP request and returns what the server actually returned.

Safety rules enforced here:

* Only ``http`` and ``https`` are allowed -- ``file:``, ``ftp:`` and friends
  are refused, so the adapter cannot be used to read local files.
* URLs carrying credentials (``https://user:pass@host``) are refused.
* The response body is capped; oversized bodies are truncated and the
  truncation is reported.
* A hard timeout applies to the connection and the read.
* Redirects are followed by ``urllib`` within its own bounded limit.

Every failure is reported as a structured error with the real HTTP status
code -- a 404 is reported as a 404, never as an empty success.
"""

from __future__ import annotations

import gzip
import socket
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, Optional, Tuple

from .. import errors
from ..errors import SidekickError

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_BYTES = 512 * 1024
ALLOWED_SCHEMES = ("http", "https")

#: Header names returned to the caller. Everything else (cookies, auth
#: headers, set-cookie) is dropped.
RETURNED_HEADERS = ("content-type", "content-length", "last-modified", "etag")


def _redact_url(url: str) -> str:
    """Return ``url`` with any embedded credentials removed.

    Error details are returned to callers, so a URL that carries a password
    must never be echoed back.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:  # pragma: no cover - malformed URL
        return "<unparseable url>"
    if not (parsed.username or parsed.password):
        return url
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:  # pragma: no cover - malformed port
        port = None
    if port:
        host = f"{host}:{port}"
    return urllib.parse.urlunparse(
        (parsed.scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise SidekickError(errors.INVALID_REQUEST, "A non-empty 'url' is required.")
    candidate = url.strip()
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SidekickError(
            errors.INVALID_REQUEST,
            f"Only http and https URLs can be fetched (got {parsed.scheme or 'no scheme'!r}).",
            details={"url": _redact_url(candidate), "allowed": list(ALLOWED_SCHEMES)},
        )
    if not parsed.hostname:
        raise SidekickError(
            errors.INVALID_REQUEST,
            "The URL has no host.",
            details={"url": _redact_url(candidate)},
        )
    if parsed.username or parsed.password:
        raise SidekickError(
            errors.INVALID_REQUEST,
            "URLs containing credentials are refused.",
            details={"url": _redact_url(candidate)},
        )
    return candidate


def _decompress(raw: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    try:
        if encoding == "gzip":
            return gzip.decompress(raw)
        if encoding == "deflate":
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    except (OSError, zlib.error):  # pragma: no cover - corrupt payload
        return raw
    return raw


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    method: str = "GET",
) -> Dict[str, Any]:
    """Perform a real HTTP request and return what the server returned.

    Raises:
        SidekickError: ``invalid_request`` for a bad URL, ``command_timeout``
            when the request times out, ``provider_unavailable`` when the host
            cannot be reached, ``provider_error`` for any other HTTP or
            protocol failure.
    """
    target = _validate_url(url)
    request = urllib.request.Request(
        target,
        method=method.upper(),
        headers={
            "User-Agent": "sidekick-execution/0.1",
            "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            headers = response.headers
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        # An HTTP error status is a real, reportable outcome -- not an
        # exception the caller has to guess about.
        return {
            "url": target,
            "status": exc.code,
            "ok": False,
            "headers": {},
            "body": "",
            "bytes": 0,
            "truncated": False,
            "error": {
                "code": "http_error",
                "message": f"The server responded with HTTP {exc.code}.",
            },
        }
    except socket.timeout:
        raise SidekickError(
            errors.COMMAND_TIMEOUT,
            f"The request to {target} timed out.",
            details={"url": target, "timeout_seconds": timeout},
            timeout=True,
            retryable=True,
        ) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise SidekickError(
                errors.COMMAND_TIMEOUT,
                f"The request to {target} timed out.",
                details={"url": target, "timeout_seconds": timeout},
                timeout=True,
                retryable=True,
            ) from None
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            f"The host could not be reached: {reason}",
            details={"url": target},
            retryable=True,
        ) from None
    except (OSError, ValueError) as exc:
        raise SidekickError(
            errors.PROVIDER_ERROR,
            f"The request failed: {exc}",
            details={"url": target},
            retryable=True,
        ) from None

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    content_encoding = headers.get("Content-Encoding", "") if headers else ""
    raw = _decompress(raw, content_encoding)

    charset = "utf-8"
    content_type = headers.get("Content-Type", "") if headers else ""
    if "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    try:
        body = raw.decode(charset, "replace")
    except LookupError:
        body = raw.decode("utf-8", "replace")

    returned: Dict[str, str] = {}
    if headers:
        for name in RETURNED_HEADERS:
            value = headers.get(name)
            if value is not None:
                returned[name.lower()] = value

    return {
        "url": target,
        "status": status,
        "ok": 200 <= status < 300,
        "headers": returned,
        "body": body,
        "bytes": len(raw),
        "truncated": truncated,
        "content_type": content_type,
    }
