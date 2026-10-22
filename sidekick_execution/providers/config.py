"""Provider configuration.

The configuration of a coding provider is read from the environment, parsed
once, and **validated**. A misconfigured deployment must produce a clear
diagnostic, not a crash and not a silent fallback to something else.

Rules:

* Secrets are read from the environment and never logged, printed, returned
  in a capability report, or included in an error message.
* An unknown provider name is a configuration error that names the supported
  options - it never silently becomes "auto".
* Invalid values (a base URL that is not http/https, a non-positive timeout,
  an empty model name) are recorded as *problems* and the provider then
  reports itself as not configured with that reason.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

#: The provider names this deployment understands.
SUPPORTED_PROVIDERS: Tuple[str, ...] = ("auto", "bedrock", "http_api", "local_cli", "simulated")

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CLI_TIMEOUT_SECONDS = 300.0
MAX_TIMEOUT_SECONDS = 600.0

#: Limits on what a provider may ask for. They bound the work the executor
#: has to do and are part of the safety contract, not a preference.
DEFAULT_MAX_EDITS = 50
DEFAULT_MAX_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class ProviderConfig:
    """The validated configuration of the coding provider."""

    name: str = "auto"
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cli: str = ""
    cli_args: Tuple[str, ...] = ()
    cli_timeout_seconds: float = DEFAULT_CLI_TIMEOUT_SECONDS
    max_edits: int = DEFAULT_MAX_EDITS
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    problems: Tuple[str, ...] = field(default=())

    # -- construction ------------------------------------------------------
    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "ProviderConfig":
        """Read and validate the configuration from the environment."""
        env = env if env is not None else os.environ
        problems = []

        name = (env.get("SIDEKICK_PROVIDER") or "auto").strip().lower()
        if name not in SUPPORTED_PROVIDERS:
            problems.append(
                f"unknown provider {name!r}; supported providers are: "
                + ", ".join(SUPPORTED_PROVIDERS)
            )
            name = "auto"

        api_key = (env.get("SIDEKICK_LLM_API_KEY") or "").strip()
        base_url = (env.get("SIDEKICK_LLM_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        model = (env.get("SIDEKICK_LLM_MODEL") or DEFAULT_MODEL).strip()

        timeout, timeout_problem = _positive_float(
            env.get("SIDEKICK_LLM_TIMEOUT"), DEFAULT_TIMEOUT_SECONDS, "SIDEKICK_LLM_TIMEOUT"
        )
        if timeout_problem:
            problems.append(timeout_problem)

        cli_timeout, cli_timeout_problem = _positive_float(
            env.get("SIDEKICK_CODING_CLI_TIMEOUT"),
            DEFAULT_CLI_TIMEOUT_SECONDS,
            "SIDEKICK_CODING_CLI_TIMEOUT",
        )
        if cli_timeout_problem:
            problems.append(cli_timeout_problem)

        base_url_problem = _validate_base_url(base_url)
        if base_url_problem:
            problems.append(base_url_problem)

        if not model:
            problems.append("SIDEKICK_LLM_MODEL must not be empty")

        cli = (env.get("SIDEKICK_CODING_CLI") or "").strip()
        cli_args, cli_args_problem = _parse_cli_args(env.get("SIDEKICK_CODING_CLI_ARGS"))
        if cli_args_problem:
            problems.append(cli_args_problem)

        max_edits = DEFAULT_MAX_EDITS
        max_file_bytes = DEFAULT_MAX_FILE_BYTES

        return cls(
            name=name,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout,
            cli=cli,
            cli_args=cli_args,
            cli_timeout_seconds=cli_timeout,
            max_edits=max_edits,
            max_file_bytes=max_file_bytes,
            problems=tuple(problems),
        )

    # -- reporting ---------------------------------------------------------
    @property
    def valid(self) -> bool:
        return not self.problems

    def public_dict(self) -> Dict[str, Any]:
        """A description that is safe to publish.

        The API key is never included - only whether one is present.
        """
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "api_key_present": bool(self.api_key),
            "cli": self.cli or None,
            "cli_args": list(self.cli_args),
            "cli_timeout_seconds": self.cli_timeout_seconds,
            "max_edits": self.max_edits,
            "max_file_bytes": self.max_file_bytes,
            "valid": self.valid,
            "problems": list(self.problems),
        }


def _positive_float(raw: Optional[str], default: float, name: str) -> Tuple[float, Optional[str]]:
    if raw is None or not str(raw).strip():
        return default, None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default, f"{name} must be a number, got {raw!r}"
    if value <= 0:
        return default, f"{name} must be greater than zero, got {raw!r}"
    if value > MAX_TIMEOUT_SECONDS:
        return default, f"{name} must not exceed {MAX_TIMEOUT_SECONDS} seconds, got {raw!r}"
    return value, None


def _validate_base_url(base_url: str) -> Optional[str]:
    if not base_url:
        return "SIDEKICK_LLM_BASE_URL must not be empty"
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        return f"SIDEKICK_LLM_BASE_URL must use http or https, got {base_url!r}"
    if not parsed.hostname:
        return f"SIDEKICK_LLM_BASE_URL has no host: {base_url!r}"
    if parsed.username or parsed.password:
        return "SIDEKICK_LLM_BASE_URL must not contain credentials"
    return None


def _parse_cli_args(raw: Optional[str]) -> Tuple[Tuple[str, ...], Optional[str]]:
    if raw is None or not str(raw).strip():
        return (), None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (), f"SIDEKICK_CODING_CLI_ARGS must be a JSON array of strings: {exc}"
    if not isinstance(parsed, list):
        return (), "SIDEKICK_CODING_CLI_ARGS must be a JSON array of strings"
    for item in parsed:
        if not isinstance(item, str):
            return (), "SIDEKICK_CODING_CLI_ARGS must be a JSON array of strings"
    return tuple(parsed), None
