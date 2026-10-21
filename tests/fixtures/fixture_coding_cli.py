"""A deterministic fixture that stands in for a real coding CLI.

This is a **test fixture**, not a coding agent. It exists so that the real
:class:`~sidekick_execution.providers.local_cli.LocalCliCodingProvider`
mechanism -- spawning a process, reading its stdout, parsing a change plan --
can be exercised end to end without an LLM credential.

It prints a JSON change plan on stdout, exactly as the documented local-CLI
contract requires.
"""

from __future__ import annotations

import argparse
import json
import sys


def build_plan(task: str, workspace: str, break_tests: bool) -> dict:
    new_file = "feature_added_by_fixture.py"
    new_content = '"""Created by the fixture coding CLI."""\n\n\ndef greet():\n    return "hello"\n'

    if break_tests:
        existing = "tests/test_sample.py"
        broken = (
            "import unittest\n"
            "\n"
            "\n"
            "class AdditionTests(unittest.TestCase):\n"
            "    def test_addition(self):\n"
            "        self.assertEqual(1 + 1, 3)\n"
            "\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    unittest.main()\n"
        )
    else:
        existing = "tests/test_sample.py"
        broken = (
            "import unittest\n"
            "\n"
            "\n"
            "class AdditionTests(unittest.TestCase):\n"
            "    def test_addition(self):\n"
            "        self.assertEqual(1 + 1, 2)\n"
            "\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    unittest.main()\n"
        )

    return {
        "summary": f"Fixture CLI handled task: {task}",
        "edits": [
            {"path": new_file, "content": new_content},
            {"path": existing, "content": broken},
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fixture coding CLI (test double).")
    parser.add_argument("--task", default="")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--break-tests", action="store_true")
    args = parser.parse_args(argv)
    plan = build_plan(args.task, args.workspace, args.break_tests)
    sys.stdout.write(json.dumps(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
