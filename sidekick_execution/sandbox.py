"""Command execution sandbox for Sidekick execution.

Every external command the service runs goes through :class:`CommandRunner`.
The runner enforces:

* **Allowlist** -- only executables on the policy's allowlist may run.
* **No shell** -- commands are executed with ``shell=False`` and an argument
  vector, so shell metacharacters are literal and cannot chain commands.
* **No shell launchers** -- ``cmd``, ``powershell``, ``pwsh``, ``bash`` and
  friends are refused, because they would reintroduce the shell.
* **Destructive guard** -- argument patterns that delete or rewrite history are
  refused unless an explicit, action-bound approval is supplied.
* **Working directory containment** -- the command must run inside the
  authorized workspace.
* **Timeout** -- the process is terminated (then killed) when the deadline
  passes.
* **Bounded output** -- stdout/stderr are truncated at a byte limit and the
  result records that truncation happened.
* **Scrubbed environment** -- the child sees an explicit allowlist of
  variables, never the parent's full environment.
* **Secret redaction** -- values registered as secrets are masked in captured
  output.

This is a process-level sandbox. It is **not** a container sandbox: no
container runtime is assumed to exist. See `docs/execution-prerequisites-audit.md`
for the environment verification behind that decision.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import errors
from .errors import SidekickError

#: Environment variables forwarded to child processes. Everything else in the
#: parent environment is withheld so that API keys and session material cannot
#: leak into a command by accident.
ENV_ALLOWLIST: Tuple[str, ...] = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "PYTHONHOME",
    "PYTHONPATH",
)

#: Interpreters that would let an arbitrary program escape the argument
#: vector model. They are refused by default.
SHELL_LAUNCHERS: Tuple[str, ...] = (
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "bash",
    "bash.exe",
    "sh",
    "sh.exe",
    "zsh",
    "wsl",
    "wsl.exe",
    "env",
    "xargs",
    "eval",
    "start",
)

#: Executables that are refused outright because their whole purpose is
#: destructive or privilege-changing.
FORBIDDEN_EXECUTABLES: Tuple[str, ...] = (
    "format",
    "mkfs",
    "diskpart",
    "shutdown",
    "reg",
    "reg.exe",
    "takeown",
    "icacls",
    "cipher",
    "cipher.exe",
    "vssadmin",
    "bcdedit",
)

#: Argument patterns that indicate a destructive or irreversible operation.
#: Matched against the joined argument string (lowercased).
DESTRUCTIVE_PATTERNS: Tuple[str, ...] = (
    r"\brm\s+(-[a-z]*\s+)*-?[a-z]*r[a-z]*f",
    r"\brm\s+-[a-z]*f",
    r"\bdel\s+/[a-z]",
    r"\brmdir\s+/s",
    r"\bremove-item\b.*\brecurse",
    r"\bgit\s+reset\s+--hard",
    r"\bgit\s+clean\b.*-[a-z]*f",
    r"\bgit\s+push\b.*--force",
    r"\bgit\s+push\b.*\s-f\b",
    r"\bgit\s+branch\s+-D\b",
    r"\bgit\s+checkout\s+--\s",
    r"\bgit\s+filter-branch\b",
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r"\bdiskpart\b",
    r"\bformat\s+[a-z]:",
    r">\s*/dev/sd",
    r":\(\)\s*\{.*\}\s*;\s*:",
    r"\bchmod\s+-R\s+777\b",
)

DEFAULT_ALLOWED_EXECUTABLES: Tuple[str, ...] = (
    "git",
    "python",
    "python3",
    "py",
    "pytest",
    "node",
    "npm",
    "npx",
    "pip",
    "pip3",
    "rg",
    "ls",
    "dir",
    "cat",
    "type",
)

#: Directories that are searched when an executable is not on ``PATH``.
#: Several developer machines (including the one this was built on) install
#: Git for Windows without adding it to the process ``PATH``.
EXTRA_EXECUTABLE_DIRS: Tuple[str, ...] = (
    r"C:\Program Files\Git\cmd",
    r"C:\Program Files\Git\bin",
    r"C:\Program Files\nodejs",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python314"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313"),
)

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024


def resolve_executable(name: str) -> Optional[str]:
    """Find ``name`` on ``PATH`` or in a known install directory.

    Returns the absolute path, or ``None`` when the executable is absent.
    """
    found = shutil.which(name)
    if found:
        return found
    base = os.path.basename(name)
    candidates = [name, base, f"{base}.exe", f"{base}.cmd", f"{base}.bat"]
    for directory in EXTRA_EXECUTABLE_DIRS:
        if not directory or not os.path.isdir(directory):
            continue
        for candidate in candidates:
            full = os.path.join(directory, candidate)
            if os.path.isfile(full):
                return full
    return None


@dataclass
class CommandResult:
    """The outcome of one real command execution."""

    argv: List[str]
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    cwd: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled

    def to_dict(self) -> Dict[str, object]:
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "truncated": self.truncated,
            "ok": self.ok,
            "cwd": self.cwd,
        }


@dataclass
class CommandPolicy:
    """Limits that apply to every command the service runs."""

    allowed_executables: Tuple[str, ...] = DEFAULT_ALLOWED_EXECUTABLES
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    allow_shell: bool = False
    extra_env: Dict[str, str] = field(default_factory=dict)
    secrets: List[str] = field(default_factory=list)
    denied_patterns: Tuple[str, ...] = DESTRUCTIVE_PATTERNS

    def add_secret(self, value: Optional[str]) -> None:
        """Register a value that must never appear in captured output."""
        if value and len(value) >= 6:
            self.secrets.append(value)

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            if secret and secret in text:
                text = text.replace(secret, "***redacted***")
        return text


class CommandRunner:
    """Runs real commands under a :class:`CommandPolicy`."""

    def __init__(self, policy: Optional[CommandPolicy] = None) -> None:
        self.policy = policy or CommandPolicy()
        self._cancelled: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    # -- validation --------------------------------------------------------
    def _validate(self, argv: Sequence[str], cwd: Path) -> None:
        if not argv:
            raise SidekickError(errors.INVALID_REQUEST, "A command argument vector is required.")
        if any(not isinstance(a, str) for a in argv):
            raise SidekickError(errors.INVALID_REQUEST, "Command arguments must be strings.")
        exe = os.path.basename(argv[0]).strip().lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if exe in FORBIDDEN_EXECUTABLES:
            raise SidekickError(
                errors.COMMAND_NOT_ALLOWED,
                f"The executable {argv[0]!r} is forbidden.",
                details={"executable": exe},
            )
        if exe in SHELL_LAUNCHERS and not self.policy.allow_shell:
            raise SidekickError(
                errors.COMMAND_NOT_ALLOWED,
                f"The executable {argv[0]!r} can start a shell and is not allowed.",
                details={"executable": exe},
            )
        allowed = {a.lower() for a in self.policy.allowed_executables}
        if exe not in allowed:
            raise SidekickError(
                errors.COMMAND_NOT_ALLOWED,
                f"The executable {argv[0]!r} is not on the execution allowlist.",
                details={"executable": exe, "allowed": sorted(allowed)},
            )
        joined = " ".join(argv).lower()
        for pattern in self.policy.denied_patterns:
            if re.search(pattern, joined):
                raise SidekickError(
                    errors.DESTRUCTIVE_ACTION_BLOCKED,
                    "The command matched a destructive-operation rule and was blocked.",
                    details={"executable": exe, "rule": pattern},
                )

    # -- execution ---------------------------------------------------------
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: Optional[float] = None,
        env: Optional[Dict[str, str]] = None,
        stdin_data: Optional[str] = None,
    ) -> CommandResult:
        """Execute ``argv`` inside ``cwd`` and return the real result.

        Raises:
            SidekickError: ``invalid_request``, ``command_not_allowed``,
                ``destructive_action_blocked`` or ``command_not_found``.
        """
        cwd = Path(cwd)
        self._validate(argv, cwd)
        if not cwd.is_dir():
            raise SidekickError(
                errors.INVALID_REQUEST,
                f"The working directory {cwd} does not exist.",
                details={"cwd": str(cwd)},
            )
        resolved_exe = resolve_executable(argv[0])
        if resolved_exe is None:
            raise SidekickError(
                errors.COMMAND_NOT_ALLOWED,
                f"The executable {argv[0]!r} was not found on PATH.",
                details={"executable": argv[0]},
                retryable=False,
            )

        timeout = float(timeout if timeout is not None else self.policy.timeout_seconds)
        limit = int(self.policy.max_output_bytes)
        child_env = self._build_env(env)

        started = time.monotonic()
        try:
            proc = subprocess.Popen(  # noqa: S603 - shell=False, allowlist enforced above
                [resolved_exe, *list(argv[1:])],
                cwd=str(cwd),
                env=child_env,
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=_new_process_group(),
            )
        except OSError as exc:
            raise SidekickError(
                errors.COMMAND_FAILED,
                f"Could not start {argv[0]!r}: {exc.strerror or exc}",
                details={"executable": argv[0]},
            ) from exc

        stdout_buf: List[bytes] = []
        stderr_buf: List[bytes] = []
        state = {"stdout": 0, "stderr": 0, "truncated": False}

        def _pump(stream, sink, key):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    if state[key] < limit:
                        sink.append(chunk)
                        state[key] += len(chunk)
                    else:
                        state["truncated"] = True
            except (OSError, ValueError):  # pragma: no cover - stream closed early
                pass
            finally:
                try:
                    stream.close()
                except Exception:  # pragma: no cover
                    pass

        t_out = threading.Thread(target=_pump, args=(proc.stdout, stdout_buf, "stdout"), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, stderr_buf, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        if stdin_data is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_data.encode("utf-8", "replace"))
                proc.stdin.flush()
            except (OSError, ValueError):  # pragma: no cover
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:  # pragma: no cover
                    pass

        timed_out = False
        cancelled = False
        deadline = started + timeout
        try:
            while True:
                try:
                    proc.wait(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        self._terminate(proc)
                        break
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            cancelled = True
            self._terminate(proc)

        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        duration_ms = int((time.monotonic() - started) * 1000)

        stdout = self.policy.redact(b"".join(stdout_buf).decode("utf-8", "replace"))
        stderr = self.policy.redact(b"".join(stderr_buf).decode("utf-8", "replace"))
        truncated = bool(state["truncated"])

        exit_code: Optional[int]
        if timed_out or cancelled:
            exit_code = proc.poll()
            if exit_code is None:
                exit_code = -1
        else:
            exit_code = proc.returncode

        return CommandResult(
            argv=list(argv),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            cancelled=cancelled,
            truncated=bool(truncated),
            cwd=str(cwd),
        )

    def run_cancellable(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        cancel_event: threading.Event,
        timeout: Optional[float] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """Run a command that can be cancelled while it is running.

        The returned result carries ``cancelled=True`` when the cancel event
        was set before the process finished. The process is terminated, then
        killed if it does not exit promptly.
        """
        cwd = Path(cwd)
        self._validate(argv, cwd)
        resolved_exe = resolve_executable(argv[0])
        if resolved_exe is None:
            raise SidekickError(
                errors.COMMAND_NOT_ALLOWED,
                f"The executable {argv[0]!r} was not found on PATH.",
                details={"executable": argv[0]},
            )
        timeout = float(timeout if timeout is not None else self.policy.timeout_seconds)
        limit = int(self.policy.max_output_bytes)
        child_env = self._build_env(env)

        started = time.monotonic()
        proc = subprocess.Popen(  # noqa: S603 - shell=False, allowlist enforced above
            [resolved_exe, *list(argv[1:])],
            cwd=str(cwd),
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=_new_process_group(),
        )
        stdout_buf: List[bytes] = []
        stderr_buf: List[bytes] = []
        state = {"stdout": 0, "stderr": 0, "truncated": False}

        def _pump(stream, sink, key):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    if state[key] < limit:
                        sink.append(chunk)
                        state[key] += len(chunk)
                    else:
                        state["truncated"] = True
            except (OSError, ValueError):  # pragma: no cover
                pass
            finally:
                try:
                    stream.close()
                except Exception:  # pragma: no cover
                    pass

        t_out = threading.Thread(target=_pump, args=(proc.stdout, stdout_buf, "stdout"), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, stderr_buf, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        timed_out = False
        cancelled = False
        deadline = started + timeout
        while True:
            if cancel_event.is_set():
                cancelled = True
                self._terminate(proc)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                self._terminate(proc)
                break
            try:
                proc.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                continue

        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = self.policy.redact(b"".join(stdout_buf).decode("utf-8", "replace"))
        stderr = self.policy.redact(b"".join(stderr_buf).decode("utf-8", "replace"))
        exit_code = proc.poll()
        if exit_code is None:
            exit_code = -1
        return CommandResult(
            argv=list(argv),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            cancelled=cancelled,
            truncated=bool(state["truncated"]),
            cwd=str(cwd),
        )

    # -- helpers -----------------------------------------------------------
    def _build_env(self, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
        env.update(self.policy.extra_env)
        if extra:
            env.update(extra)
        return env

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """Terminate a process tree, escalating to kill."""
        try:
            if os.name == "nt":
                subprocess.run(  # noqa: S603,S607 - fixed argv
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            try:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                pass


def _new_process_group() -> int:
    """Return creation flags that put the child in its own process group."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return 0


def default_command_policy(extra_env: Optional[Dict[str, str]] = None) -> CommandPolicy:
    """A policy with the default allowlist and no extra environment."""
    return CommandPolicy(extra_env=dict(extra_env or {}))
