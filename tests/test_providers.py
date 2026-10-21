"""Tests for provider honesty.

A provider must never be mistaken for a real integration. These tests check
that:

* an unconfigured provider says so, with a reason;
* an unreachable provider reports a real error rather than an empty result;
* the simulated provider is unavailable unless explicitly enabled, is
  unavailable in production, and is always labelled ``SIMULATED``.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.support import TempDirTestCase

from sidekick_execution import errors
from sidekick_execution.errors import SidekickError
from sidekick_execution.providers.base import ClaimLevel, CodingRequest
from sidekick_execution.providers.http_api import HttpApiCodingProvider
from sidekick_execution.providers.local_cli import LocalCliCodingProvider
from sidekick_execution.providers.simulated import SimulatedCodingProvider
from sidekick_execution.service import select_provider

ENV_KEYS = (
    "SIDEKICK_LLM_API_KEY",
    "SIDEKICK_LLM_BASE_URL",
    "SIDEKICK_LLM_MODEL",
    "SIDEKICK_CODING_CLI",
    "SIDEKICK_CODING_CLI_ARGS",
    "SIDEKICK_ALLOW_SIMULATED_PROVIDER",
    "SIDEKICK_ENV",
)


def clean_env(**overrides: str):
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update(overrides)
    return mock.patch.dict(os.environ, env, clear=True)


class HttpApiProviderTests(unittest.TestCase):
    def test_missing_credentials_report_not_configured(self) -> None:
        with clean_env():
            provider = HttpApiCodingProvider()
            status = provider.status()
            self.assertFalse(status.available)
            self.assertEqual(status.reason, "not_configured")
            self.assertEqual(status.level, ClaimLevel.UNAVAILABLE)
            self.assertIn("SIDEKICK_LLM_API_KEY", status.detail.get("hint", ""))

    def test_configured_credentials_report_a_real_provider(self) -> None:
        with clean_env(SIDEKICK_LLM_API_KEY="test-key"):
            provider = HttpApiCodingProvider()
            status = provider.status()
            self.assertTrue(status.available)
            self.assertEqual(status.level, ClaimLevel.REAL)

    def test_planning_without_credentials_returns_a_structured_error(self) -> None:
        with clean_env():
            provider = HttpApiCodingProvider()
            result = provider.plan(CodingRequest(task="t", workspace="C:\\"))
            self.assertFalse(result.ok)
            self.assertIsNotNone(result.error)
            self.assertEqual(result.error.code, errors.PROVIDER_NOT_CONFIGURED)

    def test_unreachable_endpoint_reports_a_provider_error(self) -> None:
        with clean_env(
            SIDEKICK_LLM_API_KEY="test-key",
            SIDEKICK_LLM_BASE_URL="http://127.0.0.1:9/v1",
            SIDEKICK_LLM_TIMEOUT="3",
        ):
            provider = HttpApiCodingProvider()
            result = provider.plan(CodingRequest(task="t", workspace="C:\\"))
            self.assertFalse(result.ok)
            self.assertIsNotNone(result.error)
            self.assertIn(
                result.error.code, (errors.PROVIDER_UNAVAILABLE, errors.PROVIDER_ERROR)
            )

    def test_api_key_is_registered_as_a_secret(self) -> None:
        with clean_env(SIDEKICK_LLM_API_KEY="super-secret-key"):
            provider = HttpApiCodingProvider()
            self.assertIn("super-secret-key", provider.secret_values())


class LocalCliProviderTests(unittest.TestCase):
    def test_missing_configuration_is_reported(self) -> None:
        with clean_env():
            provider = LocalCliCodingProvider()
            status = provider.status()
            self.assertFalse(status.available)
            self.assertEqual(status.reason, "not_configured")

    def test_missing_binary_is_reported_as_not_installed(self) -> None:
        with clean_env():
            provider = LocalCliCodingProvider(cli="sidekick-no-such-cli")
            status = provider.status()
            self.assertFalse(status.available)
            self.assertEqual(status.reason, "not_installed")

    def test_installed_binary_is_reported_as_real(self) -> None:
        with clean_env():
            provider = LocalCliCodingProvider(cli="git")
            status = provider.status()
            self.assertTrue(status.available)
            self.assertEqual(status.level, ClaimLevel.REAL)

    def test_planning_without_a_cli_returns_a_structured_error(self) -> None:
        with clean_env():
            provider = LocalCliCodingProvider(cli="sidekick-no-such-cli")
            result = provider.plan(CodingRequest(task="t", workspace="C:\\"))
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, errors.PROVIDER_UNAVAILABLE)


class SimulatedProviderTests(unittest.TestCase):
    def test_simulated_provider_is_unavailable_unless_enabled(self) -> None:
        with clean_env():
            provider = SimulatedCodingProvider()
            status = provider.status()
            self.assertFalse(status.available)
            self.assertEqual(status.reason, "not_enabled")
            self.assertEqual(status.level, ClaimLevel.SIMULATED)

    def test_simulated_provider_is_unavailable_in_production(self) -> None:
        with clean_env(SIDEKICK_ALLOW_SIMULATED_PROVIDER="1", SIDEKICK_ENV="production"):
            provider = SimulatedCodingProvider()
            status = provider.status()
            self.assertFalse(status.available)
            self.assertEqual(status.reason, "not_allowed_in_production")

    def test_simulated_provider_is_labelled_when_enabled(self) -> None:
        with clean_env(SIDEKICK_ALLOW_SIMULATED_PROVIDER="1"):
            provider = SimulatedCodingProvider()
            status = provider.status()
            self.assertTrue(status.available)
            self.assertEqual(status.level, ClaimLevel.SIMULATED)
            self.assertTrue(status.detail.get("simulated"))

            result = provider.plan(CodingRequest(task="t", workspace="C:\\"))
            self.assertTrue(result.ok)
            self.assertEqual(result.plan.provider, "simulated")
            self.assertEqual(result.status.level, ClaimLevel.SIMULATED)

    def test_simulated_output_is_marked_as_simulated(self) -> None:
        with clean_env(SIDEKICK_ALLOW_SIMULATED_PROVIDER="1"):
            provider = SimulatedCodingProvider()
            result = provider.plan(CodingRequest(task="t", workspace="C:\\"))
            content = result.plan.edits[0].content
            self.assertIn("SIMULATED", content)
            self.assertNotIn("SIMULATED", content.upper().replace("SIMULATED", ""))

    def test_simulated_provider_cannot_be_disabled_explicitly(self) -> None:
        with clean_env(SIDEKICK_ALLOW_SIMULATED_PROVIDER="1"):
            provider = SimulatedCodingProvider(enabled=False)
            self.assertFalse(provider.status().available)


class ProviderSelectionTests(unittest.TestCase):
    def test_auto_selection_does_not_pretend_to_be_connected(self) -> None:
        with clean_env():
            provider = select_provider("auto")
            status = provider.status()
            self.assertFalse(status.available)
            self.assertNotEqual(status.level, ClaimLevel.SIMULATED)

    def test_auto_selection_prefers_a_real_provider_when_one_exists(self) -> None:
        with clean_env(SIDEKICK_CODING_CLI="git"):
            provider = select_provider("auto")
            self.assertTrue(provider.status().available)
            self.assertEqual(provider.level, ClaimLevel.REAL)

    def test_auto_selection_uses_the_simulated_provider_only_when_enabled(self) -> None:
        with clean_env(SIDEKICK_ALLOW_SIMULATED_PROVIDER="1"):
            provider = select_provider("auto")
            self.assertEqual(provider.name, "simulated")
            self.assertEqual(provider.level, ClaimLevel.SIMULATED)


if __name__ == "__main__":
    unittest.main()
