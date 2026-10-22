"""Tests for provider configuration, diagnostics and output validation.

The point of these tests is honesty: a misconfigured deployment must say what
is wrong, a rejected credential must be distinguishable from a rate limit, a
malformed answer must never be applied, and the API key must never appear in
a report, an error or a log.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.support import TempDirTestCase

from sidekick_execution import errors
from sidekick_execution.errors import SidekickError
from sidekick_execution.providers.base import (
    ChangePlan,
    ClaimLevel,
    FileEdit,
    validate_change_plan,
)
from sidekick_execution.providers.config import SUPPORTED_PROVIDERS, ProviderConfig
from sidekick_execution.providers.http_api import HttpApiCodingProvider
from sidekick_execution.providers.local_cli import LocalCliCodingProvider
from sidekick_execution.service import select_provider

ENV_KEYS = (
    "SIDEKICK_PROVIDER",
    "SIDEKICK_LLM_API_KEY",
    "SIDEKICK_LLM_BASE_URL",
    "SIDEKICK_LLM_MODEL",
    "SIDEKICK_LLM_TIMEOUT",
    "SIDEKICK_CODING_CLI",
    "SIDEKICK_CODING_CLI_ARGS",
    "SIDEKICK_CODING_CLI_TIMEOUT",
    "SIDEKICK_ALLOW_SIMULATED_PROVIDER",
    "SIDEKICK_ENV",
)


def env(**overrides: str) -> dict:
    base = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    base.update(overrides)
    return base


class ProviderConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        config = ProviderConfig.from_env({})
        self.assertTrue(config.valid)
        self.assertEqual(config.problems, ())
        self.assertEqual(config.name, "auto")

    def test_unknown_provider_is_a_configuration_problem(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_PROVIDER": "gpt4all"})
        self.assertFalse(config.valid)
        self.assertTrue(any("unknown provider" in p for p in config.problems))
        self.assertTrue(any("http_api" in p for p in config.problems))

    def test_non_http_base_url_is_rejected(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_LLM_BASE_URL": "ftp://example.com"})
        self.assertFalse(config.valid)
        self.assertTrue(any("http or https" in p for p in config.problems))

    def test_base_url_with_credentials_is_rejected(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_LLM_BASE_URL": "https://u:p@example.com/v1"})
        self.assertFalse(config.valid)
        self.assertTrue(any("credentials" in p for p in config.problems))

    def test_invalid_timeout_is_rejected(self) -> None:
        for value in ("0", "-5", "not-a-number", "100000"):
            config = ProviderConfig.from_env({"SIDEKICK_LLM_TIMEOUT": value})
            self.assertFalse(config.valid, value)
            self.assertTrue(any("SIDEKICK_LLM_TIMEOUT" in p for p in config.problems), value)

    def test_empty_model_is_rejected(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_LLM_MODEL": "  "})
        self.assertFalse(config.valid)
        self.assertTrue(any("SIDEKICK_LLM_MODEL" in p for p in config.problems))

    def test_invalid_cli_args_are_rejected(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_CODING_CLI_ARGS": "{not json"})
        self.assertFalse(config.valid)
        self.assertTrue(any("SIDEKICK_CODING_CLI_ARGS" in p for p in config.problems))

    def test_cli_args_must_be_a_list_of_strings(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_CODING_CLI_ARGS": '{"a": 1}'})
        self.assertFalse(config.valid)
        self.assertTrue(any("SIDEKICK_CODING_CLI_ARGS" in p for p in config.problems))

    def test_public_dict_never_contains_the_api_key(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_LLM_API_KEY": "super-secret-value"})
        public = config.public_dict()
        self.assertNotIn("super-secret-value", json.dumps(public))
        self.assertTrue(public["api_key_present"])
        self.assertNotIn("api_key", public)

    def test_valid_cli_args_are_parsed(self) -> None:
        config = ProviderConfig.from_env(
            {"SIDEKICK_CODING_CLI_ARGS": json.dumps(["--task", "{task}"])}
        )
        self.assertTrue(config.valid)
        self.assertEqual(config.cli_args, ("--task", "{task}"))


class ProviderSelectionTests(unittest.TestCase):
    def test_broken_configuration_produces_an_unconfigured_provider(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_PROVIDER": "nonsense"})
        provider = select_provider("auto", config=config)
        self.assertEqual(provider.name, "unconfigured")
        status = provider.status()
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "invalid_configuration")
        self.assertTrue(status.detail["problems"])

    def test_unconfigured_provider_reports_the_problems(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_PROVIDER": "nonsense"})
        provider = select_provider("auto", config=config)
        result = provider.plan(_request())
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_CONFIG_INVALID)

    def test_http_provider_without_a_key_is_not_configured(self) -> None:
        config = ProviderConfig.from_env({})
        provider = select_provider("http_api", config=config)
        self.assertEqual(provider.name, "http_api")
        self.assertFalse(provider.status().available)
        self.assertEqual(provider.status().reason, "not_configured")

    def test_http_provider_with_a_key_is_real(self) -> None:
        config = ProviderConfig.from_env({"SIDEKICK_LLM_API_KEY": "k"})
        provider = select_provider("http_api", config=config)
        status = provider.status()
        self.assertTrue(status.available)
        self.assertEqual(status.level, ClaimLevel.REAL)
        self.assertEqual(status.detail["model"], config.model)

    def test_supported_names_are_documented(self) -> None:
        self.assertEqual(
            set(SUPPORTED_PROVIDERS), {"auto", "bedrock", "http_api", "local_cli", "simulated"}
        )


class ChangePlanValidationTests(unittest.TestCase):
    def test_a_normal_plan_is_accepted(self) -> None:
        plan = ChangePlan(edits=[FileEdit(path="src/app.py", content="print('x')")])
        validate_change_plan(plan)

    def test_an_absolute_path_is_rejected(self) -> None:
        for path in ("/etc/passwd", "C:\\Windows\\System32\\x", "C:/Windows/x"):
            plan = ChangePlan(edits=[FileEdit(path=path, content="x")])
            with self.assertRaises(SidekickError) as ctx:
                validate_change_plan(plan)
            self.assertEqual(ctx.exception.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_a_traversing_path_is_rejected(self) -> None:
        for path in ("../outside.py", "a/../../outside.py", "a\\..\\..\\outside.py"):
            plan = ChangePlan(edits=[FileEdit(path=path, content="x")])
            with self.assertRaises(SidekickError) as ctx:
                validate_change_plan(plan)
            self.assertEqual(ctx.exception.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_too_many_edits_are_rejected(self) -> None:
        plan = ChangePlan(edits=[FileEdit(path=f"f{index}.py", content="x") for index in range(5)])
        with self.assertRaises(SidekickError) as ctx:
            validate_change_plan(plan, max_edits=3)
        self.assertEqual(ctx.exception.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_an_oversized_file_is_rejected(self) -> None:
        plan = ChangePlan(edits=[FileEdit(path="big.py", content="x" * 5000)])
        with self.assertRaises(SidekickError) as ctx:
            validate_change_plan(plan, max_file_bytes=1000)
        self.assertEqual(ctx.exception.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_an_empty_edit_is_rejected(self) -> None:
        plan = ChangePlan(edits=[FileEdit(path="x.py")])
        with self.assertRaises(SidekickError) as ctx:
            validate_change_plan(plan)
        self.assertEqual(ctx.exception.code, errors.PROVIDER_OUTPUT_INVALID)


class _FailingHandler(BaseHTTPRequestHandler):
    """Answers with whatever the test asked for."""

    status_code = 500
    body = b'{"error": "boom"}'
    content_type = "application/json"

    def log_message(self, fmt, *args):  # pragma: no cover
        """Silence the access log."""

    def do_POST(self):  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(self.status_code)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        if self.status_code == 429:
            self.send_header("Retry-After", "30")
        self.end_headers()
        self.wfile.write(self.body)


class HttpProviderErrorTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._handler = type("H", (_FailingHandler,), {})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def _provider(self) -> HttpApiCodingProvider:
        config = ProviderConfig.from_env(
            {"SIDEKICK_LLM_API_KEY": "test-secret-key-value", "SIDEKICK_LLM_BASE_URL": self.base_url}
        )
        return HttpApiCodingProvider(config=config)

    def _run(self) -> object:
        return self._provider().plan(_request())

    def test_authentication_failure_is_distinguished(self) -> None:
        self._handler.status_code = 401
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_AUTH_FAILED)
        self.assertFalse(result.error.retryable)

    def test_rate_limit_is_distinguished_and_retryable(self) -> None:
        self._handler.status_code = 429
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_RATE_LIMITED)
        self.assertTrue(result.error.retryable)
        self.assertEqual(result.error.details.get("retry_after"), "30")

    def test_server_error_is_retryable(self) -> None:
        self._handler.status_code = 503
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_ERROR)
        self.assertTrue(result.error.retryable)

    def test_client_error_is_not_retryable(self) -> None:
        self._handler.status_code = 400
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_ERROR)
        self.assertFalse(result.error.retryable)

    def test_malformed_response_is_rejected(self) -> None:
        self._handler.status_code = 200
        self._handler.body = b"not json at all"
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_a_response_without_content_is_rejected(self) -> None:
        self._handler.status_code = 200
        self._handler.body = b'{"choices": []}'
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_a_change_plan_that_is_not_an_object_is_rejected(self) -> None:
        self._handler.status_code = 200
        self._handler.body = b'{"choices": [{"message": {"content": "[1,2,3]"}}]}'
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_a_change_plan_with_an_escaping_path_is_rejected(self) -> None:
        self._handler.status_code = 200
        payload = json.dumps(
            {"choices": [{"message": {"content": json.dumps({"edits": [{"path": "../evil.py", "content": "x"}]})}}]}
        )
        self._handler.body = payload.encode("utf-8")
        result = self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, errors.PROVIDER_OUTPUT_INVALID)

    def test_a_valid_change_plan_is_accepted(self) -> None:
        self._handler.status_code = 200
        payload = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"summary": "ok", "edits": [{"path": "a.py", "content": "x"}]}
                            )
                        }
                    }
                ]
            }
        )
        self._handler.body = payload.encode("utf-8")
        result = self._run()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.plan.edits[0].path, "a.py")
        self.assertEqual(result.plan.model, self._provider().model)

    def test_the_api_key_never_appears_in_an_error(self) -> None:
        self._handler.status_code = 500
        self._handler.body = b'{"error": "boom"}'
        result = self._run()
        rendered = json.dumps(result.error.to_dict())
        self.assertNotIn("test-secret-key-value", rendered)
        self.assertNotIn("Bearer", rendered)


def _request():
    from sidekick_execution.providers.base import CodingRequest

    return CodingRequest(task="do something", workspace="C:\\workspace")


if __name__ == "__main__":
    unittest.main()
