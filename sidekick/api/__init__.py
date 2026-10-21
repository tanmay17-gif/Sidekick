"""HTTP API for the core brain.

The API is the contract surface shared with Agent 2 (execution) and Agent 3
(voice/UI). It is intentionally thin: it validates input, delegates to the
engine and renders the documented envelope. No decision logic lives here.
"""

from __future__ import annotations

from .app import create_app, main

__all__ = ["create_app", "main"]
