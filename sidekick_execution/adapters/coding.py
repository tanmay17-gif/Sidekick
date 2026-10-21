"""The coding action adapter: real edits, real diffs, real test results.

This is the heart of the Sidekick coding workflow. Given a task and an
authorized workspace it:

1. Validates the workspace against the authorization policy.
2. Reads the requested context files (bounded size).
3. Asks a **real** coding provider for a change plan.
4. Applies that plan with real file writes / ``git apply``.
5. Captures a **real** diff from the workspace's Git repository.
6. Runs the **real** test command and preserves its exit status.
7. Reports success, partial success, failure or cancellation -- never more
   than what actually happened.

Nothing in this module fabricates a diff, a test result, or a provider
answer. A provider that is not configured produces an honest
``provider_not_configured`` error.
"""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import errors
from ..contracts import CANCELLED, FAILED, SUCCEEDED
from ..errors import SidekickError
from ..providers.base import ChangePlan, ClaimLevel, CodingProvider, CodingRequest, ProviderResult
from ..sandbox import CommandRunner
from ..testing import DEFAULT_TEST_ARGV, TestRunResult, TestRunner, TestSpec
from ..vcs import DiffResult, GitWorkspace
from ..workspace import Workspace, WorkspacePolicy

MAX_CONTEXT_FILE_BYTES = 64 * 1024
MAX_CONTEXT_FILES = 40


@dataclass
class CodingActionRequest:
    """The arguments of a ``coding.execute`` action."""

    task: str
    workspace: str
    context_files: List[str] = field(default_factory=list)
    test_command: Optional[List[str]] = None
    require_tests: bool = True
    approval_required: bool = False
    test_timeout_seconds: float = 300.0

    @classmethod
    def from_arguments(cls, arguments: Dict[str, Any]) -> "CodingActionRequest":
        task = arguments.get("task")
        workspace = arguments.get("workspace")
        if not isinstance(task, str) or not task.strip():
            raise SidekickError(errors.INVALID_REQUEST, "A 'task' string is required.")
        if not isinstance(workspace, str) or not workspace.strip():
            raise SidekickError(errors.INVALID_REQUEST, "A 'workspace' path is required.")
        context = arguments.get("context_files") or []
        if not isinstance(context, list) or any(not isinstance(c, str) for c in context):
            raise SidekickError(
                errors.INVALID_REQUEST, "'context_files' must be a list of relative paths."
            )
        test_command = arguments.get("test_command")
        if test_command is not None and (
            not isinstance(test_command, list)
            or not test_command
            or any(not isinstance(part, str) for part in test_command)
        ):
            raise SidekickError(
                errors.INVALID_REQUEST, "'test_command' must be a non-empty list of strings."
            )
        require_tests = arguments.get("require_tests", True)
        if not isinstance(require_tests, bool):
            raise SidekickError(errors.INVALID_REQUEST, "'require_tests' must be a boolean.")
        approval_required = arguments.get("approval_required", False)
        if not isinstance(approval_required, bool):
            raise SidekickError(errors.INVALID_REQUEST, "'approval_required' must be a boolean.")
        timeout = arguments.get("test_timeout_seconds", 300.0)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise SidekickError(
                errors.INVALID_REQUEST, "'test_timeout_seconds' must be a positive number."
            )
        return cls(
            task=task,
            workspace=workspace,
            context_files=list(context),
            test_command=list(test_command) if test_command else None,
            require_tests=require_tests,
            approval_required=approval_required,
            test_timeout_seconds=float(timeout),
        )


@dataclass
class CodingActionOutcome:
    """What actually happened."""

    status: str
    outcome: str  # succeeded | partial | failed | cancelled
    summary: str
    workspace: str = ""
    changed_files: List[Dict[str, str]] = field(default_factory=list)
    diff: str = ""
    diff_truncated: bool = False
    head_sha: Optional[str] = None
    test_result: Optional[TestRunResult] = None
    provider: Dict[str, Any] = field(default_factory=dict)
    error: Optional[SidekickError] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "outcome": self.outcome,
            "summary": self.summary,
            "workspace": self.workspace,
            "changed_files": list(self.changed_files),
            "diff": self.diff,
            "diff_truncated": self.diff_truncated,
            "head_sha": self.head_sha,
            "provider": dict(self.provider),
            "test_result": self.test_result.to_dict() if self.test_result else None,
        }
        if self.error:
            payload["error"] = self.error.to_dict()["error"]
        return payload


ProgressFn = Callable[[str, str, Dict[str, Any]], None]


class CodingAdapter:
    """Executes a real coding task against a real workspace."""

    def __init__(
        self,
        workspace_policy: WorkspacePolicy,
        provider: CodingProvider,
        *,
        runner: Optional[CommandRunner] = None,
        test_runner: Optional[TestRunner] = None,
    ) -> None:
        self.workspace_policy = workspace_policy
        self.provider = provider
        self.runner = runner or CommandRunner()
        self.test_runner = test_runner or TestRunner(self.runner)

    # -- public API --------------------------------------------------------
    def execute(
        self,
        request: CodingActionRequest,
        *,
        cancel_event: Optional[threading.Event] = None,
        progress: Optional[ProgressFn] = None,
    ) -> CodingActionOutcome:
        """Run the coding workflow and return an honest outcome."""
        emit = progress or (lambda _t, _m, _d: None)
        cancel = cancel_event or threading.Event()

        workspace = self.workspace_policy.validate(request.workspace)
        emit("progress", "Workspace validated.", {"workspace": workspace.path})

        context = self._read_context(workspace, request.context_files)
        emit(
            "progress",
            f"Read {len(context)} context file(s).",
            {"files": sorted(context)},
        )

        provider_result = self.provider.plan(
            CodingRequest(
                task=request.task,
                workspace=workspace.path,
                context_files=context,
                test_command=request.test_command,
            )
        )
        provider_meta = {
            "name": self.provider.name,
            "level": self.provider.level,
            "simulated": self.provider.level == ClaimLevel.SIMULATED,
            "available": provider_result.status.available,
            "reason": provider_result.status.reason,
            "latency_ms": provider_result.latency_ms,
            "model": provider_result.plan.model if provider_result.plan else None,
        }
        if not provider_result.ok:
            error = provider_result.error or SidekickError(
                errors.PROVIDER_ERROR, "The coding provider did not return a change plan."
            )
            emit("error", error.message, {"code": error.code})
            return CodingActionOutcome(
                status=FAILED,
                outcome="failed",
                summary=error.message,
                workspace=workspace.path,
                provider=provider_meta,
                error=error,
            )

        plan = provider_result.plan
        assert plan is not None
        if not plan.edits:
            error = SidekickError(
                errors.NO_CHANGES_PRODUCED,
                "The coding provider produced no changes, so the task was not carried out.",
                details={"provider": self.provider.name},
            )
            emit("error", error.message, {"code": error.code})
            return CodingActionOutcome(
                status=FAILED,
                outcome="failed",
                summary=error.message,
                workspace=workspace.path,
                provider=provider_meta,
                error=error,
            )

        if cancel.is_set():
            return self._cancelled_outcome(workspace, provider_meta)

        applied, apply_error = self._apply_plan(workspace, plan)
        if apply_error is not None:
            emit("error", apply_error.message, {"code": apply_error.code})
            return CodingActionOutcome(
                status=FAILED,
                outcome="failed",
                summary=apply_error.message,
                workspace=workspace.path,
                provider=provider_meta,
                error=apply_error,
            )
        emit(
            "progress",
            f"Applied {len(applied)} file change(s).",
            {"changed_files": applied},
        )

        if cancel.is_set():
            return self._cancelled_outcome(workspace, provider_meta)

        test_result = None
        if request.require_tests:
            spec = TestSpec(
                argv=list(request.test_command) if request.test_command else list(DEFAULT_TEST_ARGV),
                timeout_seconds=request.test_timeout_seconds,
                required=True,
            )
            emit("progress", f"Running tests: {' '.join(spec.argv)}", {"argv": spec.argv})
            test_result = self.test_runner.run(spec, cwd=workspace.root, cancel_event=cancel)
            emit(
                "progress",
                test_result.summary,
                {
                    "exit_code": test_result.exit_code,
                    "passed": test_result.passed,
                    "counts": test_result.counts if test_result.counts_available else None,
                },
            )
            if test_result.cancelled:
                return self._cancelled_outcome(workspace, provider_meta, test_result=test_result)

        # The diff is captured *after* the test run so that it reflects the
        # resulting workspace state exactly, as the contract promises.
        diff_result = self._capture_diff(workspace)
        emit(
            "progress",
            f"Captured a real diff covering {len(diff_result.changed_files)} file(s).",
            {"file_count": len(diff_result.changed_files)},
        )

        if cancel.is_set():
            return self._cancelled_outcome(workspace, provider_meta, diff_result, test_result)

        changed = [c.to_dict() for c in diff_result.changed_files]
        if test_result is not None and test_result.timed_out:
            error = SidekickError(
                errors.COMMAND_TIMEOUT,
                "The test command exceeded its time limit and was terminated.",
                details={"argv": test_result.argv, "timeout_seconds": request.test_timeout_seconds},
                timeout=True,
                retryable=True,
            )
            emit("error", error.message, {"code": error.code})
            return CodingActionOutcome(
                status=FAILED,
                outcome="partial",
                summary=error.message,
                workspace=workspace.path,
                changed_files=changed,
                diff=diff_result.diff,
                diff_truncated=diff_result.truncated,
                head_sha=diff_result.head_sha,
                test_result=test_result,
                provider=provider_meta,
                error=error,
            )

        if test_result is not None and not test_result.passed:
            error = SidekickError(
                errors.TEST_FAILED,
                "The requested tests failed, so the change is not reported as successful.",
                details={
                    "exit_code": test_result.exit_code,
                    "counts": test_result.counts if test_result.counts_available else None,
                },
            )
            emit("error", error.message, {"code": error.code})
            return CodingActionOutcome(
                status=FAILED,
                outcome="partial",
                summary=(
                    f"Applied {len(applied)} change(s) but the test command failed "
                    f"(exit code {test_result.exit_code})."
                ),
                workspace=workspace.path,
                changed_files=changed,
                diff=diff_result.diff,
                diff_truncated=diff_result.truncated,
                head_sha=diff_result.head_sha,
                test_result=test_result,
                provider=provider_meta,
                error=error,
            )

        summary = plan.summary or f"Applied {len(applied)} change(s) to the workspace."
        emit("progress", summary, {"changed_files": changed})
        return CodingActionOutcome(
            status=SUCCEEDED,
            outcome="succeeded",
            summary=summary,
            workspace=workspace.path,
            changed_files=changed,
            diff=diff_result.diff,
            diff_truncated=diff_result.truncated,
            head_sha=diff_result.head_sha,
            test_result=test_result,
            provider=provider_meta,
        )

    # -- internals ---------------------------------------------------------
    def _read_context(self, workspace: Workspace, relatives: List[str]) -> Dict[str, str]:
        context: Dict[str, str] = {}
        for rel in relatives[:MAX_CONTEXT_FILES]:
            try:
                target = workspace.resolve_child(rel)
            except SidekickError:
                continue
            if not target.is_file():
                continue
            try:
                if target.stat().st_size > MAX_CONTEXT_FILE_BYTES:
                    continue
                context[rel] = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return context

    def _apply_plan(
        self, workspace: Workspace, plan: ChangePlan
    ) -> tuple[List[str], Optional[SidekickError]]:
        """Apply the plan with real writes. Returns (applied paths, error)."""
        applied: List[str] = []
        for edit in plan.edits:
            try:
                target = workspace.resolve_child(edit.path)
            except SidekickError as exc:
                return applied, exc
            try:
                if edit.delete:
                    if target.exists():
                        target.unlink()
                    applied.append(edit.path)
                    continue
                if edit.content is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(edit.content, encoding="utf-8", newline="\n")
                    applied.append(edit.path)
                    continue
                if edit.patch is not None:
                    err = self._apply_patch(workspace, edit.patch)
                    if err is not None:
                        return applied, err
                    applied.append(edit.path)
                    continue
                return applied, SidekickError(
                    errors.PROVIDER_OUTPUT_INVALID,
                    f"The edit for {edit.path!r} has neither content nor a patch.",
                    details={"path": edit.path},
                )
            except OSError as exc:
                return applied, SidekickError(
                    errors.EDIT_APPLY_FAILED,
                    f"Could not write {edit.path!r}: {exc.strerror or exc}",
                    details={"path": edit.path},
                )
        return applied, None

    def _apply_patch(self, workspace: Workspace, patch: str) -> Optional[SidekickError]:
        handle, temp_path = tempfile.mkstemp(prefix="sidekick-patch-", suffix=".diff")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(patch)
            result = self.runner.run(
                ["git", "apply", "--whitespace=nowarn", "--unsafe-paths", temp_path],
                cwd=workspace.root,
                timeout=60,
            )
            if result.exit_code != 0:
                return SidekickError(
                    errors.EDIT_APPLY_FAILED,
                    "The patch could not be applied to the workspace.",
                    details={"exit_code": result.exit_code, "stderr": result.stderr[-1000:]},
                )
            return None
        except SidekickError:
            raise
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _capture_diff(self, workspace: Workspace) -> DiffResult:
        git = GitWorkspace(workspace.root, self.runner)
        try:
            return git.diff()
        except SidekickError as exc:
            if exc.code == errors.VCS_NOT_A_REPOSITORY:
                return DiffResult(diff="", changed_files=[], truncated=False, head_sha=None)
            raise

    def _cancelled_outcome(
        self,
        workspace: Workspace,
        provider_meta: Dict[str, Any],
        diff_result: Optional[DiffResult] = None,
        test_result: Optional[TestRunResult] = None,
    ) -> CodingActionOutcome:
        return CodingActionOutcome(
            status=CANCELLED,
            outcome="cancelled",
            summary="The action was cancelled before it finished.",
            workspace=workspace.path,
            changed_files=[c.to_dict() for c in diff_result.changed_files] if diff_result else [],
            diff=diff_result.diff if diff_result else "",
            diff_truncated=diff_result.truncated if diff_result else False,
            head_sha=diff_result.head_sha if diff_result else None,
            test_result=test_result,
            provider=provider_meta,
        )
