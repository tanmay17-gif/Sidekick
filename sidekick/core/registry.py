"""Tool registry - the contract between the core brain and the execution layer.

Agent 2 owns the *adapters*; Agent 1 owns this contract. The core never
imports an adapter implementation directly: it only knows the
:class:`ToolAdapter` protocol and the :class:`ToolSpec` metadata.

Lifecycle of one action:

1. the engine plans an :class:`~sidekick.core.schemas.Action` and hands it to
   :meth:`ToolRegistry.execute`;
2. the adapter returns a :class:`ToolResult`;
3. the engine writes the result (or a structured error) back into the action.

Two shapes of result are supported:

- **completed** - the work finished inside ``execute``;
- **ongoing** - the work continues in the background (``ToolResult.ongoing``).
  The action stays ``running`` and the adapter reports the final outcome
  through :meth:`ToolContext.complete`.

Cancellation is optional per adapter. When an adapter cannot cancel, the core
reports that honestly instead of pretending the work stopped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from .catalog import CapabilityCatalog, ToolSpec
from .schemas import Action, ActionError


@dataclass
class ToolResult:
    """Outcome of one tool execution."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: ActionError | None = None
    cancelled: bool = False
    compensated: bool = False
    #: ``True`` when the work continues in the background. The action stays
    #: ``running`` until the adapter calls :meth:`ToolContext.complete`.
    ongoing: bool = False

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ValueError("a successful result must not carry an error")
        if not self.ok and self.error is None:
            self.error = ActionError(
                code="tool_unknown_error",
                message="the tool reported a failure without an error description",
            )


@dataclass
class ToolContext:
    """Everything an adapter is allowed to know about the caller."""

    session_id: str
    action_id: str
    deadline_seconds: float | None = None
    _complete: Callable[[ToolResult], None] | None = None
    _progress: Callable[[str, dict[str, Any]], None] | None = None

    def complete(self, result: ToolResult) -> None:
        """Report the final outcome of an ongoing action."""
        if self._complete is None:
            return
        self._complete(result)

    def progress(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Report intermediate progress of an ongoing action."""
        if self._progress is None:
            return
        self._progress(message, data or {})


@runtime_checkable
class ToolAdapter(Protocol):
    """What an execution adapter must provide."""

    spec: ToolSpec

    def execute(self, action: Action, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Perform the work for ``action`` and return the real outcome."""
        ...

    def cancel(self, action_id: str) -> bool:
        """Try to stop a running action.

        Return ``True`` when the work actually stopped, ``False`` when the
        adapter cannot stop it. ``False`` is not an error - the core then
        reports a best-effort stop with an explanation.
        """
        ...


class ToolUnavailableError(RuntimeError):
    """Raised when a requested tool is not registered."""

    def __init__(self, tool: str) -> None:
        super().__init__(f"tool not available: {tool}")
        self.tool = tool


class ToolRegistry:
    """Holds the available adapters and the capability catalog they describe."""

    def __init__(self) -> None:
        self._adapters: dict[str, ToolAdapter] = {}
        self._catalog = CapabilityCatalog()

    # -- registration -----------------------------------------------------

    def register(self, adapter: ToolAdapter) -> ToolSpec:
        spec = adapter.spec
        if spec.name in self._adapters:
            raise ValueError(f"tool already registered: {spec.name}")
        self._adapters[spec.name] = adapter
        self._catalog.add(spec)
        return spec

    def declare(self, spec: ToolSpec) -> ToolSpec:
        """Register a capability *without* an adapter.

        Declared capabilities are visible to the model, the UI and the intent
        layer, but calling them fails honestly with ``tool_unavailable``
        instead of pretending to work.
        """
        self._catalog.add(spec)
        return spec

    def unregister(self, name: str) -> None:
        self._adapters.pop(name, None)
        self._catalog.tools.pop(name, None)

    # -- lookup -----------------------------------------------------------

    @property
    def catalog(self) -> CapabilityCatalog:
        return self._catalog

    def get(self, name: str) -> ToolAdapter | None:
        return self._adapters.get(name)

    def spec(self, name: str) -> ToolSpec | None:
        """The metadata of a capability (declared or implemented)."""
        return self._catalog.get(name)

    def require(self, name: str) -> ToolAdapter:
        adapter = self._adapters.get(name)
        if adapter is None:
            raise ToolUnavailableError(name)
        return adapter

    def is_available(self, name: str) -> bool:
        return name in self._adapters

    def available_tools(self) -> list[str]:
        return sorted(self._adapters)

    def __contains__(self, name: object) -> bool:
        return name in self._adapters

    def __len__(self) -> int:
        return len(self._adapters)

    # -- execution --------------------------------------------------------

    def execute(
        self,
        action: Action,
        arguments: dict[str, Any],
        context: ToolContext | None = None,
    ) -> ToolResult:
        """Execute an action through its adapter, translating failures."""
        adapter = self.get(action.tool)
        if adapter is None:
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="tool_unavailable",
                    message=f"no adapter is registered for '{action.tool}'",
                    retryable=False,
                ),
            )
        if context is None:
            context = ToolContext(session_id="", action_id=action.action_id)
        try:
            return adapter.execute(action, arguments, context)
        except Exception as exc:  # noqa: BLE001 - adapters are untrusted
            return ToolResult(
                ok=False,
                error=ActionError(
                    code="tool_execution_error",
                    message=f"{type(exc).__name__}: {exc}",
                    retryable=False,
                ),
            )

    def cancel(self, action_id: str, tool: str) -> bool:
        """Ask an adapter to stop an in-flight action."""
        adapter = self.get(tool)
        if adapter is None:
            return False
        try:
            return bool(adapter.cancel(action_id))
        except Exception:  # noqa: BLE001 - cancellation is best effort
            return False
