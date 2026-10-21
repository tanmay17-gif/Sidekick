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


def create_app(engine: DecisionEngine | None = None) -> FastAPI:
    """Build the application. A pre-built engine can be injected by tests."""
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
        inventory = engine.capability_inventory()
        by_id = {item["id"]: item for item in inventory}

        tool_items: list[dict[str, Any]] = []
        status_counts: dict[str, int] = {}
        for spec in engine.registry.catalog:
            item = by_id.get(spec.name, {})
            state = item.get("state", "unavailable")
            if state == "live":
                status = "REAL"
            elif state == "client":
                status = "NOT_IMPLEMENTED"
            else:
                status = "NOT_IMPLEMENTED"
            status_counts[status] = status_counts.get(status, 0) + 1
            tool_items.append(
                {
                    "tool": spec.name,
                    "description": spec.description,
                    "arguments_schema": {arg.name: arg.to_dict() for arg in spec.arguments},
                    "approval_required": spec.requires_approval,
                    "risk_level": spec.risk.value,
                    "status": status,
                    "status_detail": item.get("detail", ""),
                    "simulated": False,
                    "execution_target": spec.execution_target,
                    "owner": spec.owner,
                }
            )

        return {
            "contract_version": CONTRACT_VERSION,
            "mode": "live",
            "capabilities": inventory,
            "tools": tool_items,
            "tool_count": len(tool_items),
            "status_counts": status_counts,
            "any_simulated": False,
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

    @app.get("/")
    async def index() -> Any:
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

    return app


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
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
