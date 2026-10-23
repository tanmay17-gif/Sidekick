"""HTTP + Server-Sent-Events transport for the Sidekick execution service.

This is the surface the Sidekick core (Agent 1) and the browser UI (Agent 3)
talk to. It is deliberately language-neutral: JSON over HTTP, so the core can
be written in any language without depending on this implementation.

Endpoints
---------
``GET  /v1/health``                  Liveness plus the real runtime summary.
``GET  /v1/capabilities``            Truthful capability report.
``POST /v1/actions``                 Submit an action. Returns the action and,
                                     when approval is required, a confirmation
                                     request.
``GET  /v1/actions``                 List actions (optionally per session).
``GET  /v1/actions/{id}``            One action.
``POST /v1/actions/{id}/approve``    Approve a pending action.
``POST /v1/actions/{id}/cancel``     Cancel an action.
``GET  /v1/actions/{id}/events``     SSE stream of job events.

The SSE stream emits one ``data:`` frame per event, in the event order
documented in :mod:`sidekick_execution.events`. A client may pass
``?after=<seq>`` to resume a stream it disconnected from.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .errors import SidekickError
from .events import TERMINAL_EVENT_TYPES
from .service import ExecutionService

JSON_CONTENT_TYPE = "application/json"
SSE_CONTENT_TYPE = "text/event-stream"


def _is_origin_allowed(origin: Optional[str]) -> bool:
    """Allow localhost, local ips, render domains, hackathon and spec domains."""
    if not origin:
        return True
    origin_lower = origin.lower()
    allowed_substrings = (
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        ".onrender.com",
        "amazonappdev2026.devpost.com",
        "modelcontextprotocol.io",
    )
    return any(sub in origin_lower for sub in allowed_substrings)


class ExecutionHTTPServer(ThreadingHTTPServer):
    """A threading HTTP server that holds the execution service."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], service: ExecutionService) -> None:
        super().__init__(address, ExecutionRequestHandler)
        self.service = service


class ExecutionRequestHandler(BaseHTTPRequestHandler):
    server_version = "SidekickExecution/0.1"

    # -- plumbing ----------------------------------------------------------
    @property
    def service(self) -> ExecutionService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        """Keep the default stderr access log out of the event stream."""

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_payload(self, exc: SidekickError, status: int = 400) -> None:
        self._send_json(status, exc.to_dict())

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SidekickError("invalid_request", f"The request body is not valid JSON: {exc}")
        if not isinstance(parsed, dict):
            raise SidekickError("invalid_request", "The request body must be a JSON object.")
        return parsed

    def _is_authorized(self) -> bool:
        required_token = os.environ.get("SIDEKICK_MCP_TOKEN")
        if not required_token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip() == required_token
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        origin = self.headers.get("Origin", "*")
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version, Accept",
        )
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id, MCP-Protocol-Version")
        self.end_headers()

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        try:
            if parts in (["mcp"], ["v1", "mcp"]):
                origin = self.headers.get("Origin")
                if not _is_origin_allowed(origin):
                    self._send_json(403, {"error": {"code": "forbidden", "message": "Origin not allowed."}})
                    return
                if not self._is_authorized():
                    self._send_json(401, {"error": {"code": "unauthorized", "message": "Missing or invalid Bearer token."}})
                    return
                accept = self.headers.get("Accept", "")
                if "text/event-stream" not in accept:
                    self.send_response(405)
                    self.send_header("Allow", "POST")
                    self.send_header("Content-Type", JSON_CONTENT_TYPE)
                    self.end_headers()
                    self.wfile.write(
                        json.dumps({"error": {"code": "method_not_allowed", "message": "GET only supported for SSE streams with Accept: text/event-stream"}}).encode("utf-8")
                    )
                    return
                session_id = self.headers.get("Mcp-Session-Id") or str(uuid.uuid4())
                self._stream_mcp_sse(session_id)
                return
            if parts == ["v1", "health"]:
                self._send_json(200, self._health())
                return
            if parts == ["v1", "capabilities"]:
                self._send_json(200, self.service.capabilities())
                return
            if parts == ["v1", "actions"]:
                session_id = query.get("session_id", [None])[0]
                actions = self.service.job_manager.list_jobs(session_id)
                self._send_json(200, {"actions": [a.to_dict() for a in actions]})
                return
            if len(parts) == 3 and parts[0] == "v1" and parts[1] == "actions":
                action = self.service.job_manager.get(parts[2])
                self._send_json(200, action.to_dict())
                return
            if len(parts) == 4 and parts[0] == "v1" and parts[1] == "actions" and parts[3] == "events":
                after = int((query.get("after", ["0"])[0]) or 0)
                self._stream_events(parts[2], after)
                return
            self._send_json(404, {"error": {"code": "not_found", "message": "Unknown endpoint.", "retryable": False, "timeout": False}})
        except SidekickError as exc:
            self._send_error_payload(exc, 404 if exc.code == "job_not_found" else 400)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": {"code": "internal_error", "message": str(exc), "retryable": False, "timeout": False}})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        try:
            body = self._read_json()
            if parts in (["mcp"], ["v1", "mcp"]):
                origin = self.headers.get("Origin")
                if not _is_origin_allowed(origin):
                    self._send_json(403, {"error": {"code": "forbidden", "message": "Origin not allowed."}})
                    return
                if not self._is_authorized():
                    self._send_json(401, {"error": {"code": "unauthorized", "message": "Missing or invalid Bearer token."}})
                    return
                self._handle_mcp_post(body)
                return
            if parts == ["v1", "actions"]:
                self._submit(body)
                return
            if len(parts) == 4 and parts[0] == "v1" and parts[1] == "actions":
                action_id, suffix = parts[2], parts[3]
                if suffix == "approve":
                    self._approve(action_id, body)
                    return
                if suffix == "cancel":
                    action = self.service.job_manager.cancel(action_id)
                    self._send_json(200, action.to_dict())
                    return
            self._send_json(404, {"error": {"code": "not_found", "message": "Unknown endpoint.", "retryable": False, "timeout": False}})
        except SidekickError as exc:
            self._send_error_payload(exc, 400)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": {"code": "internal_error", "message": str(exc), "retryable": False, "timeout": False}})

    # -- handlers ----------------------------------------------------------
    def _health(self) -> Dict[str, Any]:
        manager = self.service.job_manager
        jobs = manager.list_jobs()
        return {
            "status": "ok",
            "service": "sidekick-execution",
            "version": "0.1.0",
            "active_jobs": sum(1 for a in jobs if not a.is_terminal),
            "total_jobs": len(jobs),
        }

    def _submit(self, body: Dict[str, Any]) -> None:
        tool = body.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise SidekickError("invalid_request", "A 'tool' name is required.")
        arguments = body.get("arguments", {})
        if arguments is None:
            arguments = {}
        session_id = body.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise SidekickError("invalid_request", "'session_id' must be a string.")
        confirmation_token = body.get("confirmation_token")
        if confirmation_token is not None and not isinstance(confirmation_token, str):
            raise SidekickError("invalid_request", "'confirmation_token' must be a string.")
        payload = self.service.job_manager.submit(
            tool,
            arguments,
            session_id=session_id,
            confirmation_token=confirmation_token,
        )
        self._send_json(202, payload)

    def _approve(self, action_id: str, body: Dict[str, Any]) -> None:
        token = body.get("confirmation_token")
        if not isinstance(token, str) or not token:
            raise SidekickError("approval_required", "A 'confirmation_token' is required.")
        approved_by = body.get("approved_by")
        if approved_by is not None and not isinstance(approved_by, str):
            raise SidekickError("invalid_request", "'approved_by' must be a string.")
        action = self.service.job_manager.approve(action_id, token, approved_by=approved_by)
        self._send_json(200, action.to_dict())

    # -- SSE ---------------------------------------------------------------
    def _stream_events(self, job_id: str, after: int) -> None:
        bus = self.service.job_manager.events
        subscription = bus.subscribe(job_id)
        self.send_response(200)
        self.send_header("Content-Type", SSE_CONTENT_TYPE)
        self.send_header("Cache-Control", "no-cache")
        # Deliberately no "Connection: keep-alive" header: this handler
        # signals the end of the event stream by closing the connection, and
        # advertising keep-alive would leave the client waiting forever.
        self.end_headers()
        try:
            for event in bus.replay(job_id, after):
                if self._write_event(event):
                    return
            deadline = time.monotonic() + 3600
            while time.monotonic() < deadline:
                try:
                    event = subscription.get(timeout=1.0)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                if self._write_event(event):
                    return
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            pass
        finally:
            bus.unsubscribe(job_id, subscription)
            self.close_connection = True

    def _write_event(self, event) -> bool:
        """Write one SSE frame. Returns True when the job reached its end."""
        frame = f"id: {event.seq}\ndata: {json.dumps(event.to_dict(), default=str)}\n\n"
        try:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            return True
        return event.type in TERMINAL_EVENT_TYPES


    # -- MCP Streamable HTTP -----------------------------------------------
    def _handle_mcp_post(self, body: Dict[str, Any]) -> None:
        session_id = self.headers.get("Mcp-Session-Id") or str(uuid.uuid4())
        from .mcp_server import MCPServer

        mcp = MCPServer(self.service, session_id=session_id)
        response = mcp.handle(body)

        origin = self.headers.get("Origin", "*")

        # Handle notifications (e.g. notifications/initialized or messages without id)
        if response is None:
            self.send_response(202)
            self.send_header("Mcp-Session-Id", session_id)
            self.send_header("MCP-Protocol-Version", mcp.negotiated_version)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        accept = self.headers.get("Accept", "")
        if "text/event-stream" in accept and "application/json" not in accept:
            self.send_response(200)
            self.send_header("Content-Type", SSE_CONTENT_TYPE)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Mcp-Session-Id", session_id)
            self.send_header("MCP-Protocol-Version", mcp.negotiated_version)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            frame = f"event: message\ndata: {json.dumps(response, default=str)}\n\n".encode("utf-8")
            self.wfile.write(frame)
            self.wfile.flush()
        else:
            payload_bytes = json.dumps(response, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", JSON_CONTENT_TYPE)
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.send_header("Mcp-Session-Id", session_id)
            self.send_header("MCP-Protocol-Version", mcp.negotiated_version)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(payload_bytes)

    def _stream_mcp_sse(self, session_id: str) -> None:
        origin = self.headers.get("Origin", "*")
        self.send_response(200)
        self.send_header("Content-Type", SSE_CONTENT_TYPE)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Mcp-Session-Id", session_id)
        self.send_header("MCP-Protocol-Version", "2025-11-25")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /mcp\n\n")
        self.wfile.flush()


def serve(service: ExecutionService, host: str = "127.0.0.1", port: int = 8088) -> ExecutionHTTPServer:
    """Create (but do not start) the HTTP server."""
    return ExecutionHTTPServer((host, port), service)


def serve_mcp_http(
    service: ExecutionService, host: str = "127.0.0.1", port: int = 8089
) -> ExecutionHTTPServer:
    """Create (but do not start) the dedicated MCP Streamable HTTP server."""
    return ExecutionHTTPServer((host, port), service)


def serve_in_thread(
    service: ExecutionService, host: str = "127.0.0.1", port: int = 0
) -> Tuple[ExecutionHTTPServer, threading.Thread]:
    """Start the server on a background thread. Used by tests and the CLI."""
    httpd = serve(service, host, port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread

