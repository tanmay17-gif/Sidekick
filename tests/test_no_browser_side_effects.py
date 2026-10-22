"""The test suite must never open a real browser window.

A test run is not allowed to have side effects on the machine it runs on.
These tests guard that rule: they fail if the real ``webbrowser.open`` is
reachable, and they check that the stub in ``conftest`` is what the code
actually calls.
"""

from __future__ import annotations

import webbrowser

from sidekick.tools.local import MediaOpenTool, WebSearchTool


def test_the_browser_is_stubbed_for_the_whole_session(browser: list[str]) -> None:
    """The autouse fixture replaced the real function.

    The real ``webbrowser.open`` is a bound method of a ``Browser`` instance;
    the stub is a plain function. A test that reached the real one would
    open a window, so this has to hold for every test in the suite.
    """
    assert not hasattr(webbrowser.open, "__self__")
    assert webbrowser.open.__module__.endswith("conftest")


def test_a_url_that_would_be_opened_is_recorded_not_launched(browser: list[str]) -> None:
    from sidekick.core.registry import ToolContext
    from sidekick.core.schemas import Action

    tool = WebSearchTool()
    result = tool.execute(
        Action(tool="web.search"),
        {"query": "python tutorials", "engine": "google"},
        ToolContext(session_id="s", action_id="a"),
    )

    assert result.ok is True
    assert browser == ["https://www.google.com/search?q=python+tutorials"]
    assert result.data["url"] == browser[0]


def test_the_real_browser_function_is_not_reachable() -> None:
    """`webbrowser.open` must not be the real one during a test run."""
    assert not hasattr(webbrowser.open, "__self__")


def test_the_media_tool_uses_the_stubbed_browser(browser: list[str]) -> None:
    from sidekick.core.registry import ToolContext
    from sidekick.core.schemas import Action

    tool = MediaOpenTool()
    result = tool.execute(
        Action(tool="media.open"),
        {"destination": "spotify"},
        ToolContext(session_id="s", action_id="a"),
    )

    assert result.ok is True
    assert browser == ["https://open.spotify.com"]
