"""Tests for the shared verification tooling.

The contract-compatibility script is the team's cross-agent check: it reads
the *actual* contract definitions from the other agents' branches. A false
positive in it is worse than no check at all, because it sends the merge
gate chasing a problem that does not exist.

These tests pin the two behaviours that were wrong:

* a computed field is part of the serialised payload and must be compared
  (the core's ``Event.ts`` is computed, and the browser client reads it);
* the execution service's package must actually be installed by
  ``pip install -e .`` - ``sidekick*`` does not match ``sidekick_execution``
  because of the underscore.
"""

from __future__ import annotations

import importlib.util
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    """Import a repository script by path."""
    path = REPO_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractCompatToolTests(unittest.TestCase):
    def test_computed_fields_are_compared(self) -> None:
        script = _load_script("check_contract_compat.py")
        from sidekick.core.schemas import Event

        names = script.model_field_names(Event)
        self.assertIn("ts", names, "a computed field is part of the serialised payload")
        self.assertIn("type", names)
        self.assertIn("seq", names)

    def test_the_core_really_serialises_the_computed_field(self) -> None:
        from sidekick.core.schemas import Event

        payload = Event(type="action.progress", message="hello").serialise()
        self.assertIn("ts", payload)
        self.assertTrue(payload["ts"].endswith("Z"))

    def test_the_script_reports_no_problem_for_the_real_browser_client(self) -> None:
        """The check must be clean against the fields the browser client reads."""
        script = _load_script("check_contract_compat.py")
        from sidekick.core.schemas import Event

        # The fields the browser client's ProgressEvent interface reads.
        client_fields = {
            "type",
            "at",
            "action_id",
            "message",
            "data",
            "kind",
            "seq",
            "tool",
            "status",
            "job_id",
            "ts",
        }
        report = script.Report()
        missing = client_fields - script.model_field_names(Event)
        report.require(
            not missing,
            f"the browser client reads event fields the core does not provide: {sorted(missing)}",
        )
        self.assertEqual(report.problems, [])


class PackagingTests(unittest.TestCase):
    def test_the_execution_service_package_is_included(self) -> None:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        include = data["tool"]["setuptools"]["packages"]["find"]["include"]
        self.assertIn("sidekick_execution*", include)
        self.assertIn("sidekick*", include)

    def test_the_entry_points_are_declared(self) -> None:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = data["project"]["scripts"]
        self.assertEqual(scripts["sidekick-execution"], "sidekick_execution.__main__:main")
        self.assertEqual(scripts["sidekick"], "sidekick.api.app:main")

    def test_the_execution_service_adds_no_runtime_dependency(self) -> None:
        """The service is standard library only, on every teammate's machine."""
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = data["project"]["dependencies"]
        # fastapi/uvicorn/pydantic belong to the core; the execution service
        # itself must not add one.
        self.assertEqual(
            sorted(dependencies), ["fastapi>=0.110", "pydantic>=2.6", "uvicorn>=0.27"]
        )


if __name__ == "__main__":
    unittest.main()
