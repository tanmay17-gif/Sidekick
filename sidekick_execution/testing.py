"""Real test execution for Sidekick execution.

Runs the project's own test command and reports the *actual* exit status.
The rules this module enforces are the ones the product depends on:

* The exit status of the test process is preserved verbatim.
* A failing test suite never yields a success result.
* Counts (``passed``/``failed``/``skipped``) are reported only when the test
  runner actually printed them; otherwise the result carries the exit code and
  the raw output and says so.
* Output is bounded, and truncation is reported rather than hidden.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import errors
from .errors import SidekickError
from .sandbox import CommandRunner, CommandResult

DEFAULT_TEST_TIMEOUT_SECONDS = 300.0

#: The default test command. This repository's own suite runs on the standard
#: library ``unittest`` runner so that no package installation is required on
#: any teammate's machine.
DEFAULT_TEST_ARGV: List[str] = [
    "python",
    "-m",
    "unittest",
    "discover",
    "-s",
    "tests",
    "-t",
    ".",
]

_COUNT_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|error|errors|skipped|xfailed|xpassed|deselected)\b",
    re.IGNORECASE,
)


@dataclass
class TestSpec:
    """How to run the project's tests."""

    argv: List[str] = field(default_factory=lambda: list(DEFAULT_TEST_ARGV))
    cwd: Optional[Path] = None
    timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS
    required: bool = True
    label: str = "tests"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "argv": list(self.argv),
            "timeout_seconds": self.timeout_seconds,
            "required": self.required,
            "label": self.label,
        }


@dataclass
class TestRunResult:
    """The real result of a test run."""

    argv: List[str]
    exit_code: Optional[int]
    passed: bool
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    counts: Dict[str, int] = field(default_factory=dict)
    counts_available: bool = False
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "passed": self.passed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "truncated": self.truncated,
            "counts": dict(self.counts),
            "counts_available": self.counts_available,
            "summary": self.summary,
        }


def parse_counts(output: str) -> Dict[str, int]:
    """Extract test counts from runner output.

    Returns an empty mapping when the output does not contain a recognizable
    summary, so that callers never report a fabricated count.
    """
    counts: Dict[str, int] = {}
    for match in _COUNT_RE.finditer(output or ""):
        label = match.group("label").lower()
        label = {"error": "errors", "xfailed": "skipped", "xpassed": "passed"}.get(label, label)
        counts[label] = counts.get(label, 0) + int(match.group("count"))
    return counts


class TestRunner:
    """Executes real test commands."""

    def __init__(self, runner: Optional[CommandRunner] = None) -> None:
        self.runner = runner or CommandRunner()

    def run(
        self,
        spec: TestSpec,
        *,
        cwd: Path,
        cancel_event: Optional[threading.Event] = None,
    ) -> TestRunResult:
        """Run the tests and return their real outcome.

        Raises:
            SidekickError: ``invalid_request`` for a malformed spec.
        """
        if not spec.argv:
            raise SidekickError(errors.INVALID_REQUEST, "A test command is required.")
        workdir = Path(spec.cwd) if spec.cwd else Path(cwd)
        if cancel_event is not None:
            raw = self.runner.run_cancellable(
                spec.argv,
                cwd=workdir,
                cancel_event=cancel_event,
                timeout=spec.timeout_seconds,
            )
        else:
            raw = self.runner.run(spec.argv, cwd=workdir, timeout=spec.timeout_seconds)
        return self._to_result(raw)

    @staticmethod
    def _to_result(raw: CommandResult) -> TestRunResult:
        combined = f"{raw.stdout}\n{raw.stderr}"
        counts = parse_counts(combined)
        counts_available = bool(counts)
        passed = raw.exit_code == 0 and not raw.timed_out and not raw.cancelled
        if raw.timed_out:
            summary = "The test command timed out."
        elif raw.cancelled:
            summary = "The test command was cancelled."
        elif passed:
            summary = "All executed tests passed."
        else:
            summary = "The test command reported failures."
        return TestRunResult(
            argv=list(raw.argv),
            exit_code=raw.exit_code,
            passed=passed,
            stdout=raw.stdout,
            stderr=raw.stderr,
            duration_ms=raw.duration_ms,
            timed_out=raw.timed_out,
            cancelled=raw.cancelled,
            truncated=raw.truncated,
            counts=counts,
            counts_available=counts_available,
            summary=summary,
        )


def default_test_spec(argv: Optional[Sequence[str]] = None) -> TestSpec:
    """The default test command for this repository."""
    if argv:
        return TestSpec(argv=list(argv))
    return TestSpec(argv=list(DEFAULT_TEST_ARGV))
