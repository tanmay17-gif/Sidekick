"""Service wiring for Sidekick execution.

:class:`ExecutionService` is the single place where the pieces are connected:
workspace policy, command policy, coding provider, tool registry, approval
store and job manager.

It also exposes the truthful capability report that the UI uses, so that the
user is told which actions are real, which are simulated, and which are not
configured in this deployment.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters.coding import CodingActionRequest, CodingAdapter
from .adapters import system as system_adapter
from .adapters import web as web_adapter
from .adapters.registry import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    STATUS_NOT_CONFIGURED,
    STATUS_NOT_IMPLEMENTED,
    STATUS_REAL,
    STATUS_SIMULATED,
    ToolContext,
    ToolRegistry,
    ToolSpec,
)
from .approval import ApprovalStore
from .errors import SidekickError
from .events import EventBus
from .jobs import JobManager, JobStore
from .providers.base import ClaimLevel, CodingProvider, ProviderStatus, UnconfiguredCodingProvider
from .providers.config import ProviderConfig
from .providers.bedrock import BedrockCodingProvider
from .providers.http_api import HttpApiCodingProvider
from .providers.local_cli import LocalCliCodingProvider
from .providers.simulated import SimulatedCodingProvider
from .sandbox import CommandPolicy, CommandRunner, resolve_executable
from .testing import TestRunner
from .vcs import GitWorkspace
from .workspace import WorkspacePolicy

TOOL_CODING_EXECUTE = "coding.execute"
TOOL_CODING_RUN_TESTS = "coding.run_tests"
TOOL_WORKSPACE_INSPECT = "workspace.inspect"
TOOL_VCS_DIFF = "vcs.diff"
TOOL_VCS_COMMIT = "vcs.commit"
TOOL_SYSTEM_INFO = "system.info"
TOOL_SYSTEM_VOLUME = "system.volume"
TOOL_SYSTEM_MEDIA_CONTROL = "system.media_control"
TOOL_SYSTEM_CLIPBOARD = "system.clipboard"
TOOL_SYSTEM_OPEN = "system.open"
TOOL_WEB_FETCH = "web.fetch"


@dataclass
class ExecutionConfig:
    """Deployment configuration for the execution service."""

    allowed_roots: List[str] = field(default_factory=list)
    disposable_root: Optional[str] = None
    provider: str = "auto"
    require_approval: bool = False
    job_store_path: Optional[str] = None
    max_workers: int = 4
    command_timeout_seconds: float = 120.0
    test_timeout_seconds: float = 300.0
    max_output_bytes: int = 256 * 1024

    @classmethod
    def from_env(cls) -> "ExecutionConfig":
        roots = [
            r
            for r in os.environ.get("SIDEKICK_ALLOWED_ROOTS", "").split(os.pathsep)
            if r.strip()
        ]
        return cls(
            allowed_roots=roots,
            disposable_root=os.environ.get("SIDEKICK_DISPOSABLE_ROOT") or None,
            provider=os.environ.get("SIDEKICK_PROVIDER", "auto").strip() or "auto",
            require_approval=os.environ.get("SIDEKICK_REQUIRE_APPROVAL", "") == "1",
            job_store_path=os.environ.get("SIDEKICK_JOB_STORE") or None,
        )


class ExecutionService:
    """Wires the execution components together."""

    def __init__(
        self,
        *,
        workspace_policy: WorkspacePolicy,
        registry: ToolRegistry,
        job_manager: JobManager,
        provider: CodingProvider,
        command_policy: CommandPolicy,
    ) -> None:
        self.workspace_policy = workspace_policy
        self.registry = registry
        self.job_manager = job_manager
        self.provider = provider
        self.command_policy = command_policy

    # -- construction ------------------------------------------------------
    @classmethod
    def create(
        cls,
        config: Optional[ExecutionConfig] = None,
        *,
        provider: Optional[CodingProvider] = None,
        workspace_policy: Optional[WorkspacePolicy] = None,
        event_bus: Optional[EventBus] = None,
    ) -> "ExecutionService":
        config = config or ExecutionConfig.from_env()
        policy = workspace_policy or WorkspacePolicy(
            config.allowed_roots or None,
            disposable_root=config.disposable_root,
        )
        command_policy = CommandPolicy(
            timeout_seconds=config.command_timeout_seconds,
            max_output_bytes=config.max_output_bytes,
        )
        chosen = provider or select_provider(
            config.provider,
            command_policy,
            config=ProviderConfig.from_env(),
        )
        for secret in chosen.secret_values():
            command_policy.add_secret(secret)

        registry = ToolRegistry()
        bus = event_bus or EventBus()
        approvals = ApprovalStore()
        store = JobStore(Path(config.job_store_path)) if config.job_store_path else None
        manager = JobManager(
            registry,
            approvals,
            bus,
            store=store,
            max_workers=config.max_workers,
        )

        service = cls(
            workspace_policy=policy,
            registry=registry,
            job_manager=manager,
            provider=chosen,
            command_policy=command_policy,
        )
        service._register_tools(config)
        return service

    # -- tool registration -------------------------------------------------
    def _register_tools(self, config: ExecutionConfig) -> None:
        provider_status = self.provider.status()
        coding_status = self._coding_status(provider_status)

        self.registry.register(
            ToolSpec(
                name=TOOL_CODING_EXECUTE,
                description=(
                    "Run a real coding task in an authorized workspace: apply file "
                    "changes, capture a real diff, and run the project's tests."
                ),
                handler=self._handle_coding_execute,
                arguments_schema={
                    "type": "object",
                    "required": ["task", "workspace"],
                    "properties": {
                        "task": {"type": "string"},
                        "workspace": {"type": "string", "description": "Absolute path"},
                        "context_files": {"type": "array", "items": {"type": "string"}},
                        "test_command": {"type": "array", "items": {"type": "string"}},
                        "require_tests": {"type": "boolean"},
                        "approval_required": {"type": "boolean"},
                    },
                },
                approval_required=config.require_approval,
                risk_level=RISK_HIGH,
                status=coding_status[0],
                status_detail=coding_status[1],
                simulated=self.provider.level == ClaimLevel.SIMULATED,
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_CODING_RUN_TESTS,
                description="Run the project's real test command and report its actual exit status.",
                handler=self._handle_run_tests,
                arguments_schema={
                    "type": "object",
                    "required": ["workspace"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "test_command": {"type": "array", "items": {"type": "string"}},
                        "timeout_seconds": {"type": "number"},
                    },
                },
                risk_level=RISK_LOW,
                status=STATUS_REAL,
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_WORKSPACE_INSPECT,
                description="Inspect an authorized workspace and report what is really there.",
                handler=self._handle_workspace_inspect,
                arguments_schema={
                    "type": "object",
                    "required": ["workspace"],
                    "properties": {"workspace": {"type": "string"}},
                },
                risk_level=RISK_LOW,
                status=STATUS_REAL,
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_VCS_DIFF,
                description="Capture the real Git diff of an authorized workspace.",
                handler=self._handle_vcs_diff,
                arguments_schema={
                    "type": "object",
                    "required": ["workspace"],
                    "properties": {"workspace": {"type": "string"}},
                },
                risk_level=RISK_LOW,
                status=STATUS_REAL,
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_SYSTEM_INFO,
                description="Report the real runtime capabilities available on this machine.",
                handler=self._handle_system_info,
                arguments_schema={"type": "object", "properties": {}},
                risk_level=RISK_LOW,
                status=STATUS_REAL,
            )
        )
        self._register_system_tools()

    def _register_system_tools(self) -> None:
        """Register the real local operating-system capabilities."""
        caps = system_adapter.capabilities()
        available = caps.get("windows", False)

        self.registry.register(
            ToolSpec(
                name=TOOL_SYSTEM_VOLUME,
                description="Read or set the real master system volume (0-100).",
                handler=self._handle_system_volume,
                arguments_schema={
                    "type": "object",
                    "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
                },
                risk_level=RISK_MEDIUM,
                status=STATUS_REAL if caps.get("volume") else STATUS_NOT_CONFIGURED,
                status_detail="" if caps.get("volume") else "The Windows audio API is unavailable.",
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_SYSTEM_MEDIA_CONTROL,
                description=(
                    "Send a real multimedia key press (play_pause, next, previous, stop, "
                    "mute, volume_up, volume_down) to the running media player."
                ),
                handler=self._handle_system_media_control,
                arguments_schema={
                    "type": "object",
                    "required": ["action"],
                    "properties": {"action": {"type": "string"}},
                },
                risk_level=RISK_LOW,
                status=STATUS_REAL if caps.get("media_keys") else STATUS_NOT_CONFIGURED,
                status_detail="" if caps.get("media_keys") else caps.get("reason", ""),
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_SYSTEM_CLIPBOARD,
                description="Read or write the real system clipboard.",
                handler=self._handle_system_clipboard,
                arguments_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
                risk_level=RISK_MEDIUM,
                status=STATUS_REAL if caps.get("clipboard") else STATUS_NOT_CONFIGURED,
                status_detail="" if caps.get("clipboard") else caps.get("reason", ""),
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_SYSTEM_OPEN,
                description="Open a file or URL with the operating system's default handler.",
                handler=self._handle_system_open,
                arguments_schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
                risk_level=RISK_MEDIUM,
                status=STATUS_REAL if caps.get("open_path") else STATUS_NOT_CONFIGURED,
                status_detail="" if caps.get("open_path") else caps.get("reason", ""),
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_VCS_COMMIT,
                description="Create a real Git commit of the changes in an authorized workspace.",
                handler=self._handle_vcs_commit,
                arguments_schema={
                    "type": "object",
                    "required": ["workspace", "message"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
                risk_level=RISK_MEDIUM,
                status=STATUS_REAL,
            )
        )
        self.registry.register(
            ToolSpec(
                name=TOOL_WEB_FETCH,
                description=(
                    "Perform a real HTTP(S) request and return what the server actually "
                    "returned. Only http and https URLs are accepted."
                ),
                handler=self._handle_web_fetch,
                arguments_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                        "timeout_seconds": {"type": "number"},
                        "max_bytes": {"type": "integer"},
                    },
                },
                risk_level=RISK_LOW,
                status=STATUS_REAL,
            )
        )

    @staticmethod
    def _coding_status(status: ProviderStatus) -> tuple:
        if status.available and status.level == ClaimLevel.REAL:
            return STATUS_REAL, ""
        if status.available and status.level == ClaimLevel.SIMULATED:
            return STATUS_SIMULATED, "The configured coding provider is a simulated development substitute."
        if status.level == ClaimLevel.SIMULATED:
            return STATUS_NOT_CONFIGURED, (
                f"The simulated coding provider is not enabled ({status.reason})."
            )
        return STATUS_NOT_CONFIGURED, (
            f"No coding provider is available ({status.reason}). "
            "Supported options: AWS Bedrock (with AWS credentials), "
            "HTTP API (set SIDEKICK_LLM_API_KEY), or an authorized local CLI (set SIDEKICK_CODING_CLI)."
        )

    # -- tool handlers -----------------------------------------------------
    def _handle_coding_execute(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        request = CodingActionRequest.from_arguments(arguments)
        adapter = CodingAdapter(
            self.workspace_policy,
            self.provider,
            runner=CommandRunner(self.command_policy),
        )
        outcome = adapter.execute(request, cancel_event=ctx.cancel_event, progress=ctx.progress)
        payload = outcome.to_dict()
        if outcome.error is not None:
            # The failure carries the real outcome with it: the diff, the
            # changed files and the test result must reach the UI even when
            # the action failed, otherwise the user cannot see what happened.
            error = SidekickError(
                outcome.error.code,
                outcome.error.message,
                retryable=outcome.error.retryable,
                timeout=outcome.error.timeout,
                details={
                    **(outcome.error.details or {}),
                    "outcome": payload,
                },
            )
            raise error
        return payload

    def _handle_run_tests(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        workspace_path = arguments.get("workspace")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise SidekickError("invalid_request", "A 'workspace' path is required.")
        workspace = self.workspace_policy.validate(workspace_path)
        argv = arguments.get("test_command") or ["python", "-m", "pytest", "-q"]
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) for a in argv):
            raise SidekickError("invalid_request", "'test_command' must be a non-empty list of strings.")
        timeout = float(arguments.get("timeout_seconds", self.command_policy.timeout_seconds))
        runner = TestRunner(CommandRunner(self.command_policy))
        result = runner.run(
            TestSpec(argv=list(argv), timeout_seconds=timeout),
            cwd=workspace.root,
            cancel_event=ctx.cancel_event,
        )
        return result.to_dict()

    def _handle_workspace_inspect(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        workspace_path = arguments.get("workspace")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise SidekickError("invalid_request", "A 'workspace' path is required.")
        workspace = self.workspace_policy.validate(workspace_path)
        entries: List[Dict[str, Any]] = []
        for child in sorted(workspace.root.iterdir())[:500]:
            try:
                stat = child.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": stat.st_size,
                }
            )
        git = GitWorkspace(workspace.root, CommandRunner(self.command_policy))
        return {
            "workspace": workspace.path,
            "name": workspace.name,
            "disposable": workspace.disposable,
            "is_git_repository": git.is_repository(),
            "head_sha": git.head_sha(),
            "entry_count": len(entries),
            "entries": entries,
        }

    def _handle_vcs_diff(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        workspace_path = arguments.get("workspace")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise SidekickError("invalid_request", "A 'workspace' path is required.")
        workspace = self.workspace_policy.validate(workspace_path)
        git = GitWorkspace(workspace.root, CommandRunner(self.command_policy))
        diff = git.diff()
        return diff.to_dict()

    def _handle_system_info(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        """Report the *real* runtime capabilities of this machine."""
        git_path = resolve_executable("git")
        git_version = None
        if git_path:
            try:
                proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    [git_path, "--version"], capture_output=True, text=True, timeout=20, check=False
                )
                git_version = proc.stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                git_version = None
        node_path = resolve_executable("node")
        return {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable,
            "git_available": bool(git_path),
            "git_path": git_path,
            "git_version": git_version,
            "node_available": node_path is not None,
            "container_runtime_available": any(
                resolve_executable(name) for name in ("docker", "podman")
            ),
            "system_capabilities": system_adapter.capabilities(),
            "sandbox_model": "process-level (allowlist, timeout, bounded output, workspace containment)",
        }

    def _handle_web_fetch(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        url = arguments.get("url")
        if not isinstance(url, str) or not url.strip():
            raise SidekickError("invalid_request", "A 'url' is required.")
        timeout = float(arguments.get("timeout_seconds", 20.0))
        max_bytes = int(arguments.get("max_bytes", 512 * 1024))
        return web_adapter.fetch(url, timeout=timeout, max_bytes=max_bytes)

    # -- real local system capabilities -------------------------------------
    def _handle_system_volume(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        level = arguments.get("level")
        if level is None:
            return {"level": system_adapter.get_volume(), "changed": False}
        return {"level": system_adapter.set_volume(level), "changed": True}

    def _handle_system_media_control(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        action = arguments.get("action")
        if not isinstance(action, str) or not action.strip():
            raise SidekickError("invalid_request", "A media 'action' is required.")
        applied = system_adapter.send_media_key(action)
        return {"action": applied, "delivered": True}

    def _handle_system_clipboard(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        text = arguments.get("text")
        if text is None:
            return {"text": system_adapter.get_clipboard()}
        if not isinstance(text, str):
            raise SidekickError("invalid_request", "'text' must be a string.")
        written = system_adapter.set_clipboard(text)
        return {"characters": written, "written": True}

    def _handle_system_open(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise SidekickError("invalid_request", "A 'path' is required.")
        return {"opened": system_adapter.open_path(path)}

    def _handle_vcs_commit(self, arguments: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        workspace_path = arguments.get("workspace")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise SidekickError("invalid_request", "A 'workspace' path is required.")
        message = arguments.get("message")
        if not isinstance(message, str) or not message.strip():
            raise SidekickError("invalid_request", "A non-empty commit 'message' is required.")
        workspace = self.workspace_policy.validate(workspace_path)
        runner = CommandRunner(self.command_policy)

        add = runner.run(["git", "add", "-A"], cwd=workspace.root, timeout=60)
        if add.exit_code != 0:
            raise SidekickError(
                "vcs_error",
                "Could not stage the workspace changes.",
                details={"exit_code": add.exit_code, "stderr": add.stderr[-1000:]},
            )
        status = runner.run(["git", "status", "--porcelain=v1"], cwd=workspace.root, timeout=60)
        if status.exit_code == 0 and not status.stdout.strip():
            return {
                "committed": False,
                "reason": "no_changes",
                "head_sha": GitWorkspace(workspace.root, runner).head_sha(),
            }
        # The message goes in on stdin so that its text is never part of the
        # command line (and can never be mistaken for a command).
        commit = runner.run(
            ["git", "commit", "-F", "-"],
            cwd=workspace.root,
            timeout=120,
            stdin_data=message,
        )
        if commit.exit_code != 0:
            raise SidekickError(
                "vcs_error",
                "The commit failed.",
                details={"exit_code": commit.exit_code, "stderr": commit.stderr[-1000:]},
            )
        return {
            "committed": True,
            "head_sha": GitWorkspace(workspace.root, runner).head_sha(),
            "message": message,
        }

    # -- reporting ---------------------------------------------------------
    def capabilities(self) -> Dict[str, Any]:
        report = self.registry.capabilities()
        report["provider"] = self.provider.status().to_dict()
        report["provider_config"] = ProviderConfig.from_env().public_dict()
        report["workspace_policy"] = self.workspace_policy.describe()
        return report


def select_provider(
    name: str = "auto",
    command_policy: Optional[CommandPolicy] = None,
    *,
    config: Optional[ProviderConfig] = None,
) -> CodingProvider:
    """Choose a coding provider by name.

    ``auto`` prefers a real provider (HTTP API, then an authorized local CLI)
    and falls back to the simulated provider only when it is explicitly
    enabled. It never returns an unconfigured provider silently -- the caller
    gets a provider whose ``status()`` explains exactly what is missing, and a
    broken configuration produces an
    :class:`~sidekick_execution.providers.base.UnconfiguredCodingProvider`
    that names the problems instead of quietly using something else.
    """
    config = config or ProviderConfig.from_env()
    if config.problems:
        return UnconfiguredCodingProvider(list(config.problems), {"requested": name})

    name = (name or config.name or "auto").strip().lower()
    runner = CommandRunner(command_policy) if command_policy else None
    if name == "bedrock":
        return BedrockCodingProvider(config=config)
    if name == "http_api":
        return HttpApiCodingProvider(config=config)
    if name == "local_cli":
        return LocalCliCodingProvider(config=config, runner=runner)
    if name == "simulated":
        return SimulatedCodingProvider()

    candidates = [
        BedrockCodingProvider(config=config),
        HttpApiCodingProvider(config=config),
        LocalCliCodingProvider(config=config, runner=runner),
    ]
    for candidate in candidates:
        if candidate.status().available:
            return candidate
    simulated = SimulatedCodingProvider()
    if simulated.status().available:
        return simulated
    return candidates[0]
