"""Coding providers.

``base``   -- the provider interface and the change-plan model.
``http_api`` -- a real, OpenAI-compatible chat-completions provider.
``local_cli`` -- a real, authorized local coding CLI.
``simulated`` -- a development/test-only substitute, clearly labelled.
"""

from .base import (
    ChangePlan,
    ClaimLevel,
    CodingProvider,
    CodingRequest,
    FileEdit,
    ProviderResult,
    ProviderStatus,
)
from .bedrock import BedrockCodingProvider
from .http_api import HttpApiCodingProvider
from .local_cli import LocalCliCodingProvider
from .simulated import SimulatedCodingProvider

__all__ = [
    "ChangePlan",
    "ClaimLevel",
    "CodingProvider",
    "CodingRequest",
    "FileEdit",
    "ProviderResult",
    "ProviderStatus",
    "BedrockCodingProvider",
    "HttpApiCodingProvider",
    "LocalCliCodingProvider",
    "SimulatedCodingProvider",
]
