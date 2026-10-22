"""Packaging regression tests.

The repository ships two Python distributions in one project: the core brain
(``sidekick``) and the execution service (``sidekick_execution``, Agent 2).
A future edit to ``pyproject.toml`` must not silently drop either of them, or
one of the console entry points.

The slow check - building a wheel and inspecting it - is opt-in:
``SIDEKICK_PACKAGING_BUILD=1 python -m pytest tests/test_packaging.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_packaging  # noqa: E402

REQUIRED_PACKAGES = ("sidekick", "sidekick_execution")
REQUIRED_SCRIPTS = {
    "sidekick": "sidekick.api.app:main",
    "sidekick-execution": "sidekick_execution.__main__:main",
}


def test_the_configuration_declares_both_console_scripts() -> None:
    config = check_packaging.read_config()
    scripts = config["project"].get("scripts", {})

    for name, target in REQUIRED_SCRIPTS.items():
        assert scripts.get(name) == target


def test_the_configuration_covers_both_packages() -> None:
    config = check_packaging.read_config()
    include = (
        config.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("include", [])
    )

    assert include, "no package glob is configured"
    for package in REQUIRED_PACKAGES:
        assert any(
            pattern == package or pattern.rstrip("*").startswith(package[:1])
            for pattern in include
        ), f"{package} is not covered by {include}"


def test_the_runtime_dependencies_and_extras_are_present() -> None:
    config = check_packaging.read_config()
    project = config["project"]

    dependencies = " ".join(project.get("dependencies", [])).lower()
    for dependency in ("fastapi", "uvicorn", "pydantic"):
        assert dependency in dependencies

    extras = project.get("optional-dependencies", {})
    assert "laya" in extras
    assert "dev" in extras
    # The model is heavy and optional: the suite must stay installable without it.
    assert "laya" not in " ".join(project.get("dependencies", [])).lower()


def test_the_packaging_check_script_reports_no_problem() -> None:
    assert check_packaging.check_configuration() == []


@pytest.mark.skipif(
    os.environ.get("SIDEKICK_PACKAGING_BUILD", "").lower() not in {"1", "true", "yes"},
    reason="set SIDEKICK_PACKAGING_BUILD=1 to build a wheel and inspect it",
)
def test_the_built_wheel_contains_both_packages() -> None:
    problems = check_packaging.build_and_inspect()
    assert problems == []
