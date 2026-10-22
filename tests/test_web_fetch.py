"""Tests for the real web fetch adapter.

The tests run against a **real local HTTP server** started by the test
itself. No external network is used, so the suite is deterministic and does
not depend on any third-party service being reachable.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.support import TempDirTestCase

from sidekick_execution import errors
from sidekick_execution.adapters import web
from sidekick_execution.errors import SidekickError


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # pragma: no cover
        """Silence the default access log."""

    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.path == "/ok":
            body = json.dumps({"hello": "world", "n": 42}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/text":
            body = b"plain text body"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/big":
            body = b"x" * 50000
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class WebFetchTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def test_real_request_returns_the_real_response(self) -> None:
        result = web.fetch(self.base + "/ok")
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(result["body"]), {"hello": "world", "n": 42})
        self.assertIn("application/json", result["headers"].get("content-type", ""))

    def test_text_response_is_returned(self) -> None:
        result = web.fetch(self.base + "/text")
        self.assertEqual(result["body"], "plain text body")
        self.assertIn("text/plain", result["content_type"])

    def test_large_body_is_truncated_and_the_truncation_is_reported(self) -> None:
        result = web.fetch(self.base + "/big", max_bytes=1024)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["body"]), 1024)

    def test_http_error_status_is_reported_not_swallowed(self) -> None:
        result = web.fetch(self.base + "/missing")
        self.assertEqual(result["status"], 404)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "http_error")

    def test_unreachable_host_is_reported_as_unavailable(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            # Port 9 is the discard port; nothing is listening on it.
            web.fetch("http://127.0.0.1:9/nothing", timeout=3)
        self.assertEqual(ctx.exception.code, errors.PROVIDER_UNAVAILABLE)

    def test_non_http_scheme_is_refused(self) -> None:
        for url in ("file:///C:/Windows/win.ini", "ftp://example.com/x", "data:text/plain,hi"):
            with self.assertRaises(SidekickError) as ctx:
                web.fetch(url)
            self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    def test_url_with_credentials_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            web.fetch("https://user:secret@example.com/")
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)
        self.assertNotIn("secret", str(ctx.exception.details))

    def test_empty_url_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            web.fetch("   ")
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    def test_url_without_a_host_is_refused(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            web.fetch("http:///nohost")
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
