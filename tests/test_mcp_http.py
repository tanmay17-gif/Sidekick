"""Tests for the MCP Streamable HTTP transport (spec 2025-11-25)."""

from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from unittest import mock

from tests.support import REPO_ROOT, TempDirTestCase

from sidekick_execution.http_service import serve_in_thread
from sidekick_execution.service import ExecutionService
from sidekick_execution.workspace import WorkspacePolicy
from sidekick_execution.providers.local_cli import LocalCliCodingProvider

FIXTURE_CLI = REPO_ROOT / "tests" / "fixtures" / "fixture_coding_cli.py"


def build_test_service(roots):
    policy = WorkspacePolicy([str(r) for r in roots])
    chosen = LocalCliCodingProvider(
        cli=sys.executable,
        args=[str(FIXTURE_CLI), "--task", "{task}", "--workspace", "{workspace}"],
    )
    return ExecutionService.create(provider=chosen, workspace_policy=policy)


class McpHttpTransportTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = build_test_service([self.tmp_path])
        self.httpd, self.thread = serve_in_thread(self.service, "127.0.0.1", 0)
        self.addCleanup(self.service.job_manager.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def _post(self, path: str, payload: dict, headers: dict | None = None):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            h.update(headers)
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=h,
        )
        with urllib.request.urlopen(request, timeout=30) as resp:
            content = resp.read()
            body = json.loads(content.decode("utf-8")) if content else None
            return resp.status, body, dict(resp.headers)

    def _get(self, path: str, headers: dict | None = None):
        h = {}
        if headers:
            h.update(headers)
        request = urllib.request.Request(self.base + path, method="GET", headers=h)
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def test_initialize_handshake_returns_2025_11_25(self) -> None:
        status, body, headers = self._post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["jsonrpc"], "2.0")
        result = body["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("serverInfo", result)
        self.assertIn("mcp-session-id", [k.lower() for k in headers.keys()])

    def test_protocol_negotiation_down_to_2024_11_05(self) -> None:
        status, body, _ = self._post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list_has_title_and_annotations(self) -> None:
        status, body, _ = self._post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        self.assertEqual(status, 200)
        tools = body["result"]["tools"]
        self.assertGreaterEqual(len(tools), 10)
        tool_by_name = {t["name"]: t for t in tools}

        # Check coding.execute has annotations matching high risk
        coding = tool_by_name["coding.execute"]
        self.assertEqual(coding["title"], "Execute Code Changes")
        self.assertIn("description", coding)
        self.assertIn("inputSchema", coding)
        self.assertIn("outputSchema", coding)
        self.assertFalse(coding["annotations"]["readOnlyHint"])
        self.assertTrue(coding["annotations"]["destructiveHint"])

        # Check system.info has annotations matching low risk
        sysinfo = tool_by_name["system.info"]
        self.assertEqual(sysinfo["title"], "System Runtime Info")
        self.assertTrue(sysinfo["annotations"]["readOnlyHint"])
        self.assertFalse(sysinfo["annotations"]["destructiveHint"])

    def test_tools_call_returns_structured_content(self) -> None:
        status, body, _ = self._post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "system.info", "arguments": {}},
            },
        )
        self.assertEqual(status, 200)
        result = body["result"]
        self.assertFalse(result["isError"])
        self.assertIn("content", result)
        self.assertIn("structuredContent", result)
        self.assertIn("platform", result["structuredContent"])

    def test_notification_returns_202_accepted(self) -> None:
        # Notifications have no 'id' field per JSON-RPC 2.0
        status, body, headers = self._post(
            "/mcp",
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        self.assertEqual(status, 202)
        self.assertIsNone(body)
        self.assertIn("mcp-session-id", [k.lower() for k in headers.keys()])

    def test_mcp_session_id_header_propagation(self) -> None:
        custom_session = "sess-test-abc-123"
        status, body, headers = self._post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "ping",
                "params": {},
            },
            headers={"Mcp-Session-Id": custom_session},
        )
        self.assertEqual(status, 200)
        found = {k.lower(): v for k, v in headers.items()}.get("mcp-session-id")
        self.assertEqual(found, custom_session)

    def test_bad_origin_returns_403(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(
                "/mcp",
                {"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}},
                headers={"Origin": "https://malicious-attacker-domain.com"},
            )
        self.assertEqual(ctx.exception.code, 403)

    def test_allowed_origin_succeeds(self) -> None:
        status, body, _ = self._post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {}},
            headers={"Origin": "https://sidekick.onrender.com"},
        )
        self.assertEqual(status, 200)

    def test_get_without_sse_accept_returns_405(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/mcp", headers={"Accept": "application/json"})
        self.assertEqual(ctx.exception.code, 405)
        self.assertEqual(ctx.exception.headers.get("Allow"), "POST")

    def test_get_with_sse_accept_returns_endpoint_event(self) -> None:
        status, content, headers = self._get("/mcp", headers={"Accept": "text/event-stream"})
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers.get("Content-Type", ""))
        self.assertIn(b"event: endpoint\ndata: /mcp", content)

    def test_bearer_token_authentication(self) -> None:
        with mock.patch.dict(os.environ, {"SIDEKICK_MCP_TOKEN": "secret-token-123"}):
            # Missing token -> 401
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(
                    "/mcp",
                    {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}},
                )
            self.assertEqual(ctx.exception.code, 401)

            # Invalid token -> 401
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(
                    "/mcp",
                    {"jsonrpc": "2.0", "id": 8, "method": "ping", "params": {}},
                    headers={"Authorization": "Bearer wrong-token"},
                )
            self.assertEqual(ctx.exception.code, 401)

            # Valid token -> 200
            status, body, _ = self._post(
                "/mcp",
                {"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}},
                headers={"Authorization": "Bearer secret-token-123"},
            )
            self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
