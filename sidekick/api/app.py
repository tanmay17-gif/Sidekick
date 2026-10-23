"""FastAPI application.

The HTTP surface is the contract shared with Agent 2 (execution) and Agent 3
(voice/UI). It is intentionally thin: it validates input, delegates to the
engine and renders the documented envelope. No decision logic lives here.

Two path families are served:

- ``/api/v1/...`` - the paths the browser client uses by default
  (``web/src/lib/api/endpoints.ts``),
- ``/v1/...`` - the shorter aliases.

Both call the same handlers, so there is exactly one implementation of every
behaviour.

Session identity: the ``X-Sidekick-Session-Id`` header wins over the
``session_id`` body field. The rule is defined once, here, and applied
everywhere.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..bootstrap import build_engine
from ..core.errors import SidekickError
from ..core.schemas import CONTRACT_VERSION, SidekickRequest, SidekickResponse
from ..core.engine import DecisionEngine

#: The header the browser client sends.
SESSION_HEADER = "X-Sidekick-Session-Id"
#: A shorter alias, kept so both spellings work.
SESSION_HEADER_ALIAS = "X-Sidekick-Session"

_CAPABILITY_STATES = ("live", "simulated", "unavailable", "unconfigured", "disconnected")


def create_app(engine: DecisionEngine | None = None, alexa_verifier: Any = None) -> FastAPI:
    """Build the application. Pre-built engine or verifier can be injected by tests."""
    engine = engine or build_engine()

    app = FastAPI(
        title="Sidekick Core Brain",
        version=CONTRACT_VERSION,
        description=(
            "Intent resolution, safety policy and session orchestration for "
            "the Sidekick voice companion."
        ),
    )
    app.state.engine = engine

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # The real demo is the browser client (Agent 3's `web/`). When it has
    # been built, the core serves it - so a demo never accidentally shows
    # only the backend's placeholder page. The build is Agent 3's; the core
    # only serves it.
    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    web_public = Path(__file__).resolve().parents[2] / "web" / "public"

    media_dir = web_dist / "media" if (web_dist / "media").is_dir() else (web_public / "media")
    if media_dir.is_dir():
        app.mount("/media", StaticFiles(directory=str(media_dir)), name="web-media")

    if (web_dist / "index.html").exists():
        assets = web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="web-assets")

    # -- error envelope ---------------------------------------------------

    @app.exception_handler(SidekickError)
    async def _sidekick_error_handler(_request: Request, exc: SidekickError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "the request payload is not valid",
                    "retryable": False,
                    "timeout": False,
                    "details": {"errors": _jsonable_errors(exc.errors())},
                }
            },
        )

    # -- routes -----------------------------------------------------------

    @app.get("/healthz")
    @app.get("/api/v1/health")
    @app.get("/v1/health")
    async def healthz() -> dict[str, Any]:
        model = engine.primary_model
        info = model.describe()
        extra: dict[str, Any] = {}
        describe_extra = getattr(model, "describe_extra", None)
        if callable(describe_extra):
            extra = describe_extra()
        return {
            "status": "ok",
            "contract_version": CONTRACT_VERSION,
            "model": {
                "provider": info.provider,
                "model": info.model,
                "source": info.source.value,
                "fallback_used": info.fallback_used,
                "fallback_reason": info.fallback_reason,
                "available": info.model_available,
                "load_error": info.load_error,
                **extra,
            },
            "tools": engine.registry.available_tools(),
            "sessions": engine.sessions.session_count,
        }

    @app.get("/v1/tools")
    async def tools() -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "tools": [spec.to_dict() for spec in engine.registry.catalog],
            "available": engine.registry.available_tools(),
        }

    @app.get("/api/v1/capabilities")
    @app.get("/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        """The honest capability inventory.

        The response carries both vocabularies the team uses: ``capabilities``
        with the UI's ``state`` values and ``tools`` with the execution
        service's ``status`` values. Nothing is upgraded on the UI side, so
        both are computed from the same source of truth - the engine's
        inventory.
        """
        server = engine.server_capabilities()
        client = engine.client_capabilities()
        by_id = {item["id"]: item for item in server}

        tool_items: list[dict[str, Any]] = []
        status_counts: dict[str, int] = {}
        for spec in engine.registry.catalog:
            if spec.execution_target == "client":
                # The client side has its own list; a server tool report
                # would either claim it works or claim it does not exist.
                continue
            # An adapter may describe itself more precisely than "there is
            # an adapter" (the execution service reports whether a *real*
            # coding provider is behind it), so the browser never sees
            # "live" for a capability that would fail.
            reported = _adapter_status(engine, spec.name)
            default_status = (
                "REAL" if engine.registry.is_available(spec.name) else "NOT_IMPLEMENTED"
            )
            status = str(reported.get("status") or default_status)
            detail = str(reported.get("detail") or by_id.get(spec.name, {}).get("detail", ""))
            simulated = status == "SIMULATED"
            state = _STATE_BY_STATUS.get(status, by_id.get(spec.name, {}).get("state", "unavailable"))
            status_counts[status] = status_counts.get(status, 0) + 1
            tool_items.append(
                {
                    "tool": spec.name,
                    "description": spec.description,
                    "arguments_schema": {arg.name: arg.to_dict() for arg in spec.arguments},
                    "approval_required": spec.requires_approval,
                    "risk_level": spec.risk.value,
                    "status": status,
                    "status_detail": detail,
                    "simulated": simulated,
                    "execution_target": spec.execution_target,
                    "owner": spec.owner,
                }
            )
            # The browser renders the state vocabulary it already knows.
            if spec.name in by_id:
                by_id[spec.name]["state"] = state
                by_id[spec.name]["detail"] = detail

        return {
            "contract_version": CONTRACT_VERSION,
            "mode": "live",
            "capabilities": list(by_id.values()),
            "client_capabilities": client,
            "tools": tool_items,
            "tool_count": len(tool_items),
            "status_counts": status_counts,
            "any_simulated": any(item["simulated"] for item in tool_items),
            "games": [],
            "providers": [],
        }

    @app.get("/api/v1/media/catalog")
    async def media_catalog() -> dict[str, Any]:
        """The core ships no media assets.

        The browser client falls back to the film that is bundled with the web
        app, so an empty catalog is the truthful answer here.
        """
        return {"contract_version": CONTRACT_VERSION, "assets": []}

    @app.post("/api/v1/requests")
    @app.post("/v1/decide")
    async def decide(
        request: Request,
        payload: SidekickRequest,
        x_sidekick_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
        x_sidekick_session: str | None = Header(default=None, alias=SESSION_HEADER_ALIAS),
        accept: str | None = Header(default=None),
    ) -> Any:
        turn = _apply_session_override(
            payload, x_sidekick_session_id or x_sidekick_session
        )
        response = engine.handle(turn)
        if _wants_event_stream(accept):
            return _event_stream(response)
        return response

    @app.get("/v1/sessions/{session_id}")
    async def session_state(session_id: str) -> dict[str, Any]:
        session = engine.sessions.peek(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        return {
            "session": {
                "session_id": session.session_id,
                "active_task_id": session.active_task_id,
                "suspended_task_ids": list(session.suspended_task_ids),
                "turn_count": session.turn_count,
                "last_intent": session.last_intent,
                "last_tool": session.last_tool,
            },
            "tasks": [
                {
                    "task_id": task.task_id,
                    "tool": task.tool,
                    "state": task.state.value,
                    "action_ids": list(task.action_ids),
                    "description": task.description,
                }
                for task in session.tasks.values()
            ],
            "actions": [
                {
                    "action_id": action.action_id,
                    "job_id": action.job_id or action.action_id,
                    "tool": action.tool,
                    "state": action.state.value,
                    "approval_required": action.approval_required,
                    "arguments": action.arguments,
                    "result": action.result,
                    "error": action.error.model_dump() if action.error else None,
                    "superseded_by": action.superseded_by,
                    "plan_hash": action.plan_hash,
                    "progress": action.progress,
                }
                for action in session.actions.values()
            ],
        }

    @app.get("/v1/sessions/{session_id}/events")
    async def session_events(session_id: str) -> dict[str, Any]:
        session = engine.sessions.peek(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        return {"events": [event.serialise() for event in session.events]}

    @app.get("/api/v1/actions/{action_id}")
    @app.get("/v1/actions/{action_id}")
    async def action_state(action_id: str, session_id: str | None = None) -> dict[str, Any]:
        found = _find_action(engine, action_id, session_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown action")
        action, session = found
        return {
            "action": action.model_dump(mode="json"),
            "events": [
                event.serialise()
                for event in session.events
                if event.action_id == action.action_id
            ],
        }

    @app.post("/api/v1/actions/{action_id}/complete")
    @app.post("/v1/actions/{action_id}/complete")
    async def complete_action(
        action_id: str,
        session_id: str = Body(..., embed=True),
        status: str = Body(..., embed=True),
        result: dict | None = Body(default=None, embed=True),
        error: dict | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        """Report the outcome of a capability the *client* executed.

        The core plans the capabilities that belong to the browser (media,
        movies, games). The client runs them and reports the real outcome
        here. Without this call the action stays ``pending`` - the core never
        claims the client did something.
        """
        from ..core.schemas import ActionError

        parsed_error = None
        if error:
            parsed_error = ActionError(
                code=str(error.get("code", "client_error")),
                message=str(error.get("message", "the client reported a failure")),
                retryable=bool(error.get("retryable", False)),
                timeout=bool(error.get("timeout", False)),
                details=error.get("details") or {},
            )
        action = engine.complete_action(
            session_id,
            action_id,
            status=status,
            result=result,
            error=parsed_error,
        )
        return {"action": action.model_dump(mode="json")}

    @app.get("/api/v1/actions/{action_id}/events")
    @app.get("/v1/actions/{action_id}/events")
    async def action_events(
        action_id: str,
        session_id: str | None = None,
        after: int = 0,
        timeout: float = 30.0,
    ) -> Any:
        """Stream the events of one action as they happen.

        The stream is resumable: ``?after=<seq>`` continues after a
        disconnect without gaps and without duplicates. It ends when the
        action reaches a terminal state or when the timeout expires.
        """
        found = _find_action(engine, action_id, session_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown action")
        _action, session = found
        return StreamingResponse(
            _event_stream_for_action(engine, session.session_id, action_id, after, timeout),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v1/actions/{action_id}/approve")
    @app.post("/api/v1/actions/{action_id}/confirm")
    @app.post("/v1/actions/{action_id}/confirm")
    async def confirm_action(
        action_id: str,
        session_id: str = Body(..., embed=True),
        approved: bool | None = Body(default=None, embed=True),
        confirmed: bool | None = Body(default=None, embed=True),
        plan_hash: str | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        decision = approved if approved is not None else confirmed
        if decision is None:
            decision = True
        action = engine.confirm_action(
            session_id,
            action_id,
            approved=bool(decision),
            plan_hash=plan_hash,
        )
        return {"action": action.model_dump(mode="json")}

    @app.post("/api/v1/actions/{action_id}/cancel")
    @app.post("/v1/actions/{action_id}/cancel")
    async def cancel_action(
        action_id: str,
        session_id: str = Body(..., embed=True),
    ) -> dict[str, Any]:
        action = engine.cancel_action(session_id, action_id)
        return {"action": action.model_dump(mode="json")}

    from .alexa import AlexaAdapter
    from .alexa_verifier import AlexaRequestVerifier, AlexaSecurityError
    alexa_adapter = AlexaAdapter(engine)
    verifier = alexa_verifier or AlexaRequestVerifier()
    app.state.alexa_verifier = verifier
    app.state.alexa_adapter = alexa_adapter

    @app.post("/api/v1/alexa")
    @app.post("/v1/alexa")
    async def alexa_request(request: Request) -> Any:
        """Alexa Skills Kit (ASK) HTTP interface with signature and timestamp verification."""
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc

        try:
            verifier.verify_request(request.headers, raw_body, payload)
        except AlexaSecurityError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)

        return alexa_adapter.handle(payload)

    @app.api_route("/mcp", methods=["GET", "POST", "OPTIONS"])
    @app.api_route("/api/v1/mcp", methods=["GET", "POST", "OPTIONS"])
    @app.api_route("/v1/mcp", methods=["GET", "POST", "OPTIONS"])
    async def mcp_streamable_http(request: Request) -> Any:
        """Streamable HTTP endpoint for Model Context Protocol (spec 2025-11-25).

        Enables Alexa+, Claude Desktop, Cursor, and web clients to connect over
        standard HTTP/SSE without needing local stdio pipes.
        """
        from fastapi.responses import JSONResponse, Response, StreamingResponse
        import urllib.request
        import urllib.error
        import uuid

        origin = request.headers.get("origin", "*")
        if request.method == "OPTIONS":
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version, Accept",
                    "Access-Control-Expose-Headers": "Mcp-Session-Id, MCP-Protocol-Version",
                },
            )

        exec_base = os.environ.get("SIDEKICK_EXECUTION_URL", "http://127.0.0.1:8088").rstrip("/")
        target_url = f"{exec_base}/mcp"

        fwd_headers: dict[str, str] = {}
        for h in ("content-type", "authorization", "mcp-session-id", "mcp-protocol-version", "accept", "origin"):
            val = request.headers.get(h)
            if val is not None:
                fwd_headers[h] = val

        body_bytes = await request.body()
        req = urllib.request.Request(
            target_url,
            data=body_bytes if request.method == "POST" else None,
            headers=fwd_headers,
            method=request.method,
        )

        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                resp_bytes = resp.read()
                out_headers = {
                    "Access-Control-Allow-Origin": origin,
                    "Content-Type": resp.headers.get("Content-Type", "application/json"),
                }
                if resp.headers.get("Mcp-Session-Id"):
                    out_headers["Mcp-Session-Id"] = resp.headers.get("Mcp-Session-Id")
                if resp.headers.get("MCP-Protocol-Version"):
                    out_headers["MCP-Protocol-Version"] = resp.headers.get("MCP-Protocol-Version")

                return Response(
                    content=resp_bytes,
                    status_code=resp.status,
                    headers=out_headers,
                )
        except urllib.error.HTTPError as exc:
            err_body = exc.read()
            out_headers = {"Access-Control-Allow-Origin": origin}
            if exc.headers.get("Mcp-Session-Id"):
                out_headers["Mcp-Session-Id"] = exc.headers.get("Mcp-Session-Id")
            if exc.headers.get("Allow"):
                out_headers["Allow"] = exc.headers.get("Allow")
            return Response(
                content=err_body,
                status_code=exc.code,
                headers=out_headers,
                media_type=exc.headers.get("Content-Type", "application/json"),
            )
        except Exception:
            from sidekick_execution.service import ExecutionService, ExecutionConfig
            from sidekick_execution.mcp_server import MCPServer

            session_id = request.headers.get("mcp-session-id") or str(uuid.uuid4())
            service = ExecutionService.create(ExecutionConfig.from_env())
            mcp = MCPServer(service, session_id=session_id)
            if request.method == "GET":
                accept = request.headers.get("accept", "")
                if "text/event-stream" not in accept:
                    return JSONResponse(
                        {"error": {"code": "method_not_allowed", "message": "GET only supported for SSE streams"}},
                        status_code=405,
                        headers={"Allow": "POST", "Access-Control-Allow-Origin": origin},
                    )
                return StreamingResponse(
                    iter(["event: endpoint\ndata: /mcp\n\n"]),
                    media_type="text/event-stream",
                    headers={
                        "Mcp-Session-Id": session_id,
                        "MCP-Protocol-Version": "2025-11-25",
                        "Access-Control-Allow-Origin": origin,
                    },
                )

            try:
                body_json = json.loads(body_bytes.decode("utf-8") if body_bytes else "{}")
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON")
            result = mcp.handle(body_json)
            if result is None:
                return Response(status_code=202, headers={"Mcp-Session-Id": session_id, "Access-Control-Allow-Origin": origin})
            return JSONResponse(
                result,
                status_code=200,
                headers={
                    "Mcp-Session-Id": session_id,
                    "MCP-Protocol-Version": mcp.negotiated_version,
                    "Access-Control-Allow-Origin": origin,
                },
            )

    @app.get("/")
    async def index() -> Any:
        # The built browser client wins over the placeholder page.
        client_index = web_dist / "index.html"
        if client_index.exists():
            return FileResponse(str(client_index))
        page = static_dir / "index.html"
        if page.exists():
            return FileResponse(str(page))
        return JSONResponse(
            {
                "service": "sidekick-core",
                "contract_version": CONTRACT_VERSION,
                "endpoints": [
                    "POST /api/v1/requests",
                    "GET /api/v1/capabilities",
                    "GET /api/v1/actions/{id}",
                    "POST /api/v1/actions/{id}/approve",
                    "POST /api/v1/actions/{id}/cancel",
                    "GET /v1/sessions/{session_id}",
                    "GET /v1/sessions/{session_id}/events",
                    "GET /healthz",
                ],
            }
        )

    @app.get("/{path:path}")
    async def client_routes(path: str) -> Any:
        """Client side routes of the built browser app (single page app)."""
        client_index = web_dist / "index.html"
        if not client_index.exists():
            raise HTTPException(status_code=404, detail="not found")
        if path.startswith(("api/", "v1/", "static/", "healthz")):
            raise HTTPException(status_code=404, detail="not found")
        # Direct static file check (for media, favicon, etc.)
        dist_file = web_dist / path
        if dist_file.is_file():
            return FileResponse(str(dist_file))
        pub_file = web_public / path
        if pub_file.is_file():
            return FileResponse(str(pub_file))
        return FileResponse(str(client_index))

    return app


#: The execution status vocabulary, mapped onto the states the browser
#: already renders (``live | simulated | unavailable | unconfigured |
#: disconnected``).
_STATE_BY_STATUS = {
    "REAL": "live",
    "SIMULATED": "simulated",
    "NOT_CONFIGURED": "unconfigured",
    "NOT_IMPLEMENTED": "unavailable",
    "UNAVAILABLE": "unavailable",
}


def _adapter_status(engine: DecisionEngine, tool: str) -> dict[str, Any]:
    """What an adapter says about itself, when it says anything.

    An adapter may implement ``capability_status()`` and report e.g.
    ``{"status": "NOT_CONFIGURED", "detail": "..."}``. The report is never
    allowed to break the capability inventory.
    """
    adapter = engine.registry.get(tool)
    if adapter is None:
        return {}
    describe = getattr(adapter, "capability_status", None)
    if not callable(describe):
        return {}
    try:
        reported = describe()
    except Exception:  # noqa: BLE001 - never break the report
        return {}
    return reported if isinstance(reported, dict) else {}


def _find_action(
    engine: DecisionEngine, action_id: str, session_id: str | None
) -> tuple[Any, Any] | None:
    if session_id:
        session = engine.sessions.peek(session_id)
        if session is None:
            return None
        action = session.get_action(action_id)
        return (action, session) if action is not None else None
    for session_id_ in engine.sessions.session_ids():
        session = engine.sessions.peek(session_id_)
        if session is None:
            continue
        action = session.get_action(action_id)
        if action is not None:
            return action, session
    return None


def _event_stream_for_action(
    engine: DecisionEngine,
    session_id: str,
    action_id: str,
    after: int,
    timeout: float,
):
    """Yield the events of one action as they are produced."""
    from ..core.schemas import ActionStatus

    terminal = {
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.CANCELLED,
        ActionStatus.SUPERSEDED,
    }
    seq = after
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        events = engine.wait_for_action_events(
            session_id, action_id, seq, timeout=min(1.0, remaining)
        )
        for event in events:
            seq = event.seq
            yield f"data: {json.dumps(event.serialise())}\n\n"
        action = engine.get_action(session_id, action_id)
        if action is None or action.state in terminal:
            break
    action = engine.get_action(session_id, action_id)
    if action is not None:
        yield f"data: {json.dumps({'action': action.model_dump(mode='json'), 'seq': seq})}\n\n"


def _apply_session_override(payload: SidekickRequest, header_value: str | None) -> SidekickRequest:
    """The session header wins over the body field (defined once)."""
    if not header_value:
        return payload
    return payload.model_copy(update={"session_id": header_value})


def _wants_event_stream(accept: str | None) -> bool:
    """Does the client prefer a server sent event stream?"""
    if not accept:
        return False
    if "application/json" in accept and "text/event-stream" not in accept:
        return False
    return "text/event-stream" in accept


def _event_stream(response: SidekickResponse) -> StreamingResponse:
    """Render the turn as SSE: one frame per event, then the final response."""

    def generate():
        for index, event in enumerate(response.events, start=1):
            payload = event.serialise()
            payload["seq"] = payload.get("seq") or index
            yield f"data: {json.dumps(payload)}\n\n"
        yield f"data: {json.dumps(response.model_dump(mode='json'))}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _jsonable_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for error in errors:
        cleaned.append(
            {
                "location": [str(part) for part in error.get("loc", ())],
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
        )
    return cleaned


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    host = os.environ.get("SIDEKICK_HOST", "127.0.0.1")
    port = int(os.environ.get("SIDEKICK_PORT", "8000"))
    uvicorn.run("sidekick.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()


# Module-level application instance. Uvicorn can reference this as
# ``sidekick.api.app:app`` (e.g. ``uvicorn sidekick.api.app:app``).
app = create_app()
