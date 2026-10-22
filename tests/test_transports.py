"""Tests for the HTTP/SSE transport and the MCP tool surface."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests.support import REPO_ROOT, TempDirTestCase, requires_git, run_git, write_test_project

from sidekick_execution.adapters.registry import ToolRegistry, ToolSpec
from sidekick_execution.approval import ApprovalStore
from sidekick_execution.events import EventBus
from sidekick_execution.http_service import serve_in_thread
from sidekick_execution.jobs import JobManager
from sidekick_execution.mcp_server import MCPServer
from sidekick_execution.service import ExecutionService

FIXTURE_CLI = REPO_ROOT / "tests" / "fixtures" / "fixture_coding_cli.py"


def build_service(roots, provider=None):
    from sidekick_execution.providers.local_cli import LocalCliCodingProvider
    from sidekick_execution.workspace import WorkspacePolicy

    policy = WorkspacePolicy([str(r) for r in roots])
    chosen = provider or LocalCliCodingProvider(
        cli=sys.executable, args=[str(FIXTURE_CLI), "--task", "{task}", "--workspace", "{workspace}"]
    )
    return ExecutionService.create(provider=chosen, workspace_policy=policy)


class HttpTransportTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = build_service([self.tmp_path])
        self.httpd, self.thread = serve_in_thread(self.service, "127.0.0.1", 0)
        self.addCleanup(self.service.job_manager.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, payload: dict):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health_endpoint(self) -> None:
        status, body = self._get("/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_capabilities_report_is_truthful(self) -> None:
        status, body = self._get("/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertIn("tools", body)
        self.assertIn("provider", body)
        names = {tool["tool"] for tool in body["tools"]}
        self.assertIn("coding.execute", names)

    def test_unknown_endpoint_returns_a_structured_error(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/v1/nope")
        self.assertEqual(ctx.exception.code, 404)
        with ctx.exception:
            body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("error", body)
        self.assertIn("code", body["error"])

    def test_submit_and_poll_a_real_action(self) -> None:
        status, body = self._post(
            "/v1/actions",
            {"tool": "system.info", "arguments": {}},
        )
        self.assertEqual(status, 202)
        action_id = body["action"]["action_id"]
        # The job may already be running by the time the response is built --
        # that is the honest state, not a fabricated one.
        self.assertIn(body["action"]["state"], ("pending", "running", "succeeded"))

        for _ in range(100):
            _, action = self._get(f"/v1/actions/{action_id}")
            if action["state"] in ("succeeded", "failed", "cancelled"):
                break
            threading.Event().wait(0.05)

        self.assertEqual(action["state"], "succeeded")
        self.assertIn("git_version", action["result"])

    def test_submitting_an_unknown_tool_returns_a_structured_error(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/v1/actions", {"tool": "nope", "arguments": {}})
        self.assertEqual(ctx.exception.code, 400)
        with ctx.exception:
            body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "not_implemented")

    def test_event_stream_emits_ordered_events_and_ends(self) -> None:
        _, body = self._post("/v1/actions", {"tool": "system.info", "arguments": {}})
        action_id = body["action"]["action_id"]

        request = urllib.request.Request(self.base + f"/v1/actions/{action_id}/events")
        events = []
        with urllib.request.urlopen(request, timeout=30) as resp:
            self.assertEqual(resp.headers.get("Content-Type"), "text/event-stream")
            buffer = ""
            for raw in resp:
                buffer += raw.decode("utf-8")
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    for line in frame.splitlines():
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "job.created")
        seqs = [e["seq"] for e in events]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(seqs[0], 1)
        self.assertIn(events[-1]["type"], ("job.result", "job.error"))

    def test_cancellation_endpoint_works(self) -> None:
        registry = ToolRegistry()

        def slow(arguments, ctx):
            while not ctx.cancel_event.wait(0.05):
                pass
            return {"stopped": True}

        registry.register(ToolSpec(name="slow", description="s", handler=slow))
        manager = JobManager(registry, ApprovalStore(), EventBus())
        self.addCleanup(manager.shutdown)
        payload = manager.submit("slow", {})
        action = manager.cancel(payload["action"]["action_id"])
        self.assertEqual(action.state, "cancelled")


class McpServerTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = build_service([self.tmp_path])
        self.addCleanup(self.service.job_manager.shutdown)
        self.server = MCPServer(self.service)

    def test_initialize_handshake(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(response["jsonrpc"], "2.0")
        result = response["result"]
        self.assertIn("protocolVersion", result)
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "sidekick-execution")

    def test_tools_list_exposes_the_real_tools(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = response["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertIn("coding.execute", names)
        for tool in tools:
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)

    def test_tools_call_runs_a_real_tool(self) -> None:
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "system.info", "arguments": {}},
            }
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        body = json.loads(result["content"][0]["text"])
        self.assertEqual(body["action"]["state"], "succeeded")
        self.assertIn("platform", body["result"])

    def test_unknown_method_returns_a_jsonrpc_error(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_unknown_tool_call_is_reported_as_an_error_result(self) -> None:
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "does-not-exist", "arguments": {}},
            }
        )
        self.assertTrue(response["result"]["isError"])
        body = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(body["error"]["code"], "not_implemented")


if __name__ == "__main__":
    unittest.main()
