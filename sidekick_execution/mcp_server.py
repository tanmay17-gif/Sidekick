"""MCP tool surface for the Sidekick execution service.

Exposes the execution capabilities as Model Context Protocol tools over
stdio (JSON-RPC 2.0). An MCP host can therefore drive real Sidekick
execution -- real edits, real diffs, real test results -- instead of a
simulated tool call.

Supported methods
-----------------
``initialize``          Handshake. Reports the protocol version and the server.
``notifications/initialized``  Acknowledged silently (it is a notification).
``tools/list``          Lists the tools with their JSON schemas.
``tools/call``          Runs a tool and returns its real result.
``ping``                Liveness.

Every tool call runs a real job and waits for it to finish. For long-running
work with live progress, use the HTTP/SSE transport instead; this transport
returns the same final result.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, Dict, Optional, TextIO

from .errors import SidekickError
from .service import ExecutionService

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sidekick-execution"
SERVER_VERSION = "0.1.0"

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class MCPServer:
    """A minimal but correct MCP server over stdio."""

    def __init__(self, service: ExecutionService, *, stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> None:
        self.service = service
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    def serve_forever(self) -> None:
        """Read JSON-RPC messages until stdin closes."""
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._send({"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": str(exc)}})
                continue
            response = self.handle(message)
            if response is not None:
                self._send(response)

    def _send(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self.stdout.write(json.dumps(payload, default=str) + "\n")
            self.stdout.flush()

    # -- dispatch ----------------------------------------------------------
    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle one JSON-RPC message and return the response (if any)."""
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "A JSON-RPC object is required.")
        method = message.get("method")
        message_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return self._error(message_id, INVALID_PARAMS, "'params' must be an object.")

        if method == "initialize":
            return self._result(
                message_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return self._result(message_id, {})
        if method == "tools/list":
            return self._result(message_id, {"tools": self._tool_list()})
        if method == "tools/call":
            return self._call_tool(message_id, params)
        if message_id is None:
            return None
        return self._error(message_id, METHOD_NOT_FOUND, f"Unknown method: {method!r}")

    # -- tools -------------------------------------------------------------
    def _tool_list(self) -> list:
        tools = []
        for spec in self.service.registry.list_tools():
            tools.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "inputSchema": spec.arguments_schema or {"type": "object", "properties": {}},
                }
            )
        return tools

    def _call_tool(self, message_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            return self._error(message_id, INVALID_PARAMS, "A tool 'name' is required.")
        if not isinstance(arguments, dict):
            return self._error(message_id, INVALID_PARAMS, "Tool 'arguments' must be an object.")
        try:
            payload = self.service.job_manager.submit(name, arguments)
        except SidekickError as exc:
            return self._result(
                message_id,
                {
                    "content": [{"type": "text", "text": json.dumps(exc.to_dict(), default=str)}],
                    "isError": True,
                },
            )
        action_id = payload["action"]["action_id"]
        action = self.service.job_manager.wait(action_id, timeout=3600)
        body = {
            "action": action.to_dict(),
            "result": action.result,
            "error": action.error.to_dict() if action.error else None,
        }
        return self._result(
            message_id,
            {
                "content": [{"type": "text", "text": json.dumps(body, default=str)}],
                "isError": action.state != "succeeded",
            },
        )

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _result(message_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    @staticmethod
    def _error(message_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}
