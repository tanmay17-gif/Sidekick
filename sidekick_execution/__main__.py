"""Command-line entry point for the Sidekick execution service.

Usage::

    python -m sidekick_execution serve       # HTTP + SSE service
    python -m sidekick_execution mcp         # MCP tool server over stdio
    python -m sidekick_execution capabilities  # truthful capability report
    python -m sidekick_execution info         # real runtime capabilities
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Load .env from the project root (two levels up from this package) so that
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, BEDROCK_MODEL_ID and all other
# settings are available before boto3 / service initialisation.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv as _load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        _load_dotenv(dotenv_path=str(_env_path), override=False)
except Exception:  # noqa: BLE001  – dotenv is optional
    pass

from .http_service import serve
from .mcp_server import MCPServer
from .service import ExecutionConfig, ExecutionService


def build_service() -> ExecutionService:
    return ExecutionService.create(ExecutionConfig.from_env())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sidekick-execution", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Run the HTTP + SSE service.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8088)

    mcp_http_parser = sub.add_parser("mcp-http", help="Run the MCP Streamable HTTP service (spec 2025-11-25).")
    mcp_http_parser.add_argument("--host", default="127.0.0.1")
    mcp_http_parser.add_argument("--port", type=int, default=8089)

    sub.add_parser("mcp", help="Run the MCP tool server over stdio.")
    sub.add_parser("capabilities", help="Print the truthful capability report.")
    sub.add_parser("info", help="Print the real runtime capabilities of this machine.")

    args = parser.parse_args(argv)
    service = build_service()

    if args.command == "serve":
        httpd = serve(service, args.host, args.port)
        print(f"sidekick-execution listening on http://{args.host}:{args.port}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:  # pragma: no cover - interactive
            pass
        finally:
            httpd.server_close()
            service.job_manager.shutdown()
        return 0

    if args.command == "mcp-http":
        from .http_service import serve_mcp_http

        httpd = serve_mcp_http(service, args.host, args.port)
        print(f"sidekick-execution MCP Streamable HTTP listening on http://{args.host}:{args.port}/mcp", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:  # pragma: no cover - interactive
            pass
        finally:
            httpd.server_close()
            service.job_manager.shutdown()
        return 0

    if args.command == "mcp":
        MCPServer(service).serve_forever()
        return 0

    if args.command == "capabilities":
        print(json.dumps(service.capabilities(), indent=2, default=str))
        return 0

    if args.command == "info":
        report = service.registry.get("system.info")
        result = report.handler({}, _NullContext())
        print(json.dumps(result, indent=2, default=str))
        return 0

    parser.print_help()
    return 1


class _NullContext:
    """A minimal tool context for direct handler calls."""

    def __init__(self) -> None:
        import threading

        self.progress = lambda *_args: None
        self.cancel_event = threading.Event()
        self.session_id = None
        self.action_id = None


if __name__ == "__main__":
    raise SystemExit(main())
