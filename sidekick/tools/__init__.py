"""Execution adapters.

The adapters that ship with the core are *real* local actions: they touch the
file system, schedule real timers or open the system browser. They exist so
the product has a working vertical slice without any external account.

Agent 2 owns the service adapters (coding agent, media providers, APIs) and
registers them against the same :class:`~sidekick.core.registry.ToolAdapter`
protocol.
"""

from __future__ import annotations

from .local import (
    MediaOpenTool,
    NoteReadTool,
    NoteWriteTool,
    TimerSetTool,
    default_tool_specs,
)

__all__ = [
    "MediaOpenTool",
    "NoteReadTool",
    "NoteWriteTool",
    "TimerSetTool",
    "default_tool_specs",
]
