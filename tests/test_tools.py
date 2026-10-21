"""Tool contract: real local adapters, failures and unavailable capabilities."""

from __future__ import annotations

import time

from sidekick.core.catalog import ToolSpec
from sidekick.core.engine import DecisionEngine
from sidekick.core.registry import ToolRegistry, ToolResult
from sidekick.core.schemas import ActionStatus, ResponseStatus, SidekickRequest
from sidekick.tools.local import MEDIA_DESTINATIONS, MediaOpenTool, NoteWriteTool, TimerSetTool


def ask(engine: DecisionEngine, utterance: str, session: str = "s1"):
    return engine.handle(
        SidekickRequest(
            request_id=f"req-{utterance[:20]}-{session}-{time.time_ns()}",
            session_id=session,
            utterance=utterance,
        )
    )


def test_note_tool_writes_a_real_file(engine: DecisionEngine, workspace) -> None:
    response = ask(engine, "write a note that the groceries are done")

    action = response.action_plan[0]
    assert action.state is ActionStatus.SUCCEEDED
    assert action.result is not None
    path = workspace / "notes" / "note.txt"
    assert path.exists()
    assert "groceries are done" in path.read_text(encoding="utf-8")


def test_a_tool_that_raises_produces_a_structured_error(engine: DecisionEngine) -> None:
    response = ask(engine, "explode")

    action = response.action_plan[0]
    assert action.state is ActionStatus.FAILED
    assert action.error is not None
    assert action.error.code == "tool_execution_error"
    assert "exploded" in action.error.message
    assert response.status is ResponseStatus.FAILED


def test_a_declared_but_unimplemented_capability_is_reported_honestly(
    engine: DecisionEngine,
) -> None:
    engine.registry.declare(
        ToolSpec(
            name="future.capability",
            description="A capability that has no adapter yet",
            aliases=("do the future thing",),
        )
    )

    response = ask(engine, "do the future thing")

    action = response.action_plan[0]
    assert action.state is ActionStatus.FAILED
    assert action.error is not None
    assert action.error.code == "tool_unavailable"
    assert "no adapter" in action.error.message


def test_media_open_resolves_destination_urls() -> None:
    assert MediaOpenTool.resolve_url("spotify") == "https://open.spotify.com"
    assert MediaOpenTool.resolve_url("youtube") == "https://www.youtube.com"
    assert MediaOpenTool.resolve_url("not-a-service") is None
    assert set(MEDIA_DESTINATIONS) >= {"spotify", "youtube", "netflix"}


def test_media_open_reports_a_missing_browser(engine: DecisionEngine, monkeypatch) -> None:
    monkeypatch.setattr("sidekick.tools.local.webbrowser.open", lambda *a, **k: False)

    response = ask(engine, "open spotify")

    action = response.action_plan[0]
    assert action.state is ActionStatus.FAILED
    assert action.error is not None
    assert action.error.code == "browser_unavailable"
    assert action.error.retryable is True


def test_registry_translates_adapter_failures() -> None:
    registry = ToolRegistry()

    class Boom:
        spec = ToolSpec(name="boom", description="always fails")

        def execute(self, action, arguments, context):  # noqa: ANN001, ANN003
            raise RuntimeError("nope")

        def cancel(self, action_id):  # noqa: ANN001
            return True

    registry.register(Boom())

    from sidekick.core.schemas import Action

    result = registry.execute(Action(tool="boom"), {}, None)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "tool_execution_error"


def test_registry_reports_a_missing_adapter() -> None:
    registry = ToolRegistry()

    from sidekick.core.schemas import Action

    result = registry.execute(Action(tool="missing"), {}, None)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "tool_unavailable"


def test_timer_tool_reports_the_real_due_date() -> None:
    tool = TimerSetTool()
    from sidekick.core.registry import ToolContext
    from sidekick.core.schemas import Action

    action = Action(tool="timer.set")
    result = tool.execute(action, {"duration_seconds": 60}, ToolContext(session_id="s", action_id=action.action_id))

    assert result.ok is True
    assert result.ongoing is True
    assert result.data["duration_seconds"] == 60
    assert "due_at" in result.data
    tool.cancel(action.action_id)


def test_note_tool_rejects_an_empty_note() -> None:
    from sidekick.core.registry import ToolContext
    from sidekick.core.schemas import Action

    tool = NoteWriteTool("/tmp/sidekick-test-workspace")
    result = tool.execute(Action(tool="note.write"), {"content": "   "}, ToolContext(session_id="s", action_id="a"))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "empty_note"


def test_tool_result_must_be_consistent() -> None:
    from sidekick.core.schemas import ActionError

    try:
        ToolResult(ok=True, error=ActionError(code="x", message="y"))
    except ValueError:
        pass
    else:  # pragma: no cover - the constructor must raise
        raise AssertionError("a successful result must not carry an error")
