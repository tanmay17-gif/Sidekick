"""Workspace authorization for Sidekick execution.

A workspace is the only place the execution service is allowed to read or
write. Every path that enters the system is validated here before any command
runs.

Rules enforced by :class:`WorkspacePolicy`:

* A workspace path must be absolute, must exist, and must be a directory.
* The resolved path (symlinks followed) must live under one of the authorized
  roots. A path that resolves outside every root is rejected as
  ``workspace_unauthorized`` -- this is what stops ``..`` traversal and
  symlink escapes.
* Paths that are ambiguous (empty, relative, or not fully resolvable) are
  rejected as ``workspace_invalid`` rather than guessed at.
* Disposable workspaces are created under a controlled temporary root so that
  a job can never scribble on the user's real project by accident.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from . import errors
from .errors import SidekickError


@dataclass(frozen=True)
class Workspace:
    """An authorized workspace."""

    root: Path
    name: str = ""
    disposable: bool = False
    allowed_roots: tuple = field(default=())

    @property
    def path(self) -> str:
        return str(self.root)

    def resolve_child(self, relative: str) -> Path:
        """Resolve ``relative`` inside this workspace or raise.

        Raises:
            SidekickError: ``edit_outside_workspace`` when the resolved path
                escapes the workspace root.
        """
        if not relative or not isinstance(relative, str):
            raise SidekickError(
                errors.EDIT_OUTSIDE_WORKSPACE,
                "A relative path inside the workspace is required.",
            )
        candidate = Path(relative)
        if candidate.is_absolute():
            resolved = Path(os.path.normpath(str(candidate)))
        else:
            resolved = Path(os.path.normpath(str(self.root / candidate)))
        # normpath collapses "..", but a Windows drive-relative path or a
        # different drive would still escape -- check containment explicitly.
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise SidekickError(
                errors.EDIT_OUTSIDE_WORKSPACE,
                f"Path {relative!r} resolves outside the authorized workspace.",
                details={"path": relative},
            ) from None
        return resolved


class WorkspacePolicy:
    """Validates and creates workspaces."""

    def __init__(
        self,
        allowed_roots: Optional[Sequence[str | os.PathLike]] = None,
        *,
        disposable_root: Optional[str | os.PathLike] = None,
        require_git: bool = False,
        allow_create: bool = False,
    ) -> None:
        roots: List[Path] = []
        for raw in allowed_roots or ():
            path = Path(raw).expanduser()
            try:
                roots.append(path.resolve(strict=False))
            except OSError:  # pragma: no cover - unreadable path
                roots.append(Path(os.path.abspath(str(path))))
        if not roots:
            roots.append(Path(tempfile.gettempdir()).resolve(strict=False))
        self.allowed_roots: List[Path] = roots
        self.disposable_root = Path(disposable_root).resolve(strict=False) if disposable_root else None
        self.require_git = require_git
        self.allow_create = allow_create

    # -- validation --------------------------------------------------------
    def validate(self, raw_path: str | os.PathLike) -> Workspace:
        """Validate ``raw_path`` and return an authorized :class:`Workspace`.

        Raises:
            SidekickError: ``workspace_invalid``, ``workspace_not_found``,
                ``workspace_not_a_directory`` or ``workspace_unauthorized``.
        """
        if raw_path is None or (isinstance(raw_path, str) and not raw_path.strip()):
            raise SidekickError(
                errors.WORKSPACE_INVALID,
                "A workspace path is required; refusing to guess one.",
            )
        if not isinstance(raw_path, (str, os.PathLike)):
            raise SidekickError(
                errors.WORKSPACE_INVALID,
                "The workspace path must be a string.",
            )
        text = os.fspath(raw_path)
        if not text.strip():
            raise SidekickError(
                errors.WORKSPACE_INVALID,
                "A workspace path is required; refusing to guess one.",
            )
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            raise SidekickError(
                errors.WORKSPACE_INVALID,
                "The workspace path must be absolute; relative paths are ambiguous.",
                details={"path": text},
            )
        resolved = candidate.resolve(strict=False)
        if not resolved.exists():
            if not self.allow_create:
                raise SidekickError(
                    errors.WORKSPACE_NOT_FOUND,
                    f"No workspace exists at {text}.",
                    details={"path": text},
                )
            resolved.mkdir(parents=True, exist_ok=True)
            resolved = resolved.resolve(strict=False)
        if not resolved.is_dir():
            raise SidekickError(
                errors.WORKSPACE_NOT_A_DIRECTORY,
                f"The workspace path {text} is not a directory.",
                details={"path": text},
            )
        self._assert_authorized(resolved, text)
        if self.require_git and not (resolved / ".git").exists():
            raise SidekickError(
                errors.VCS_NOT_A_REPOSITORY,
                f"The workspace {text} is not a version-controlled repository.",
                details={"path": text},
            )
        return Workspace(
            root=resolved,
            name=resolved.name,
            disposable=False,
            allowed_roots=tuple(self.allowed_roots),
        )

    def _assert_authorized(self, resolved: Path, original: str) -> None:
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return
            except ValueError:
                continue
        raise SidekickError(
            errors.WORKSPACE_UNAUTHORIZED,
            f"The workspace {original} is outside every authorized root.",
            details={
                "path": original,
                "authorized_roots": [str(r) for r in self.allowed_roots],
            },
        )

    # -- disposable workspaces --------------------------------------------
    def create_disposable(self, prefix: str = "sidekick-job-") -> Workspace:
        """Create a fresh, empty, disposable workspace.

        The directory is created under the configured disposable root (or the
        system temp dir) with a unique name, so two concurrent jobs can never
        share state.
        """
        parent = self.disposable_root or Path(tempfile.gettempdir())
        parent.mkdir(parents=True, exist_ok=True)
        name = f"{prefix}{uuid.uuid4().hex[:12]}"
        target = parent / name
        target.mkdir(parents=True, exist_ok=False)
        return Workspace(
            root=target.resolve(strict=False),
            name=name,
            disposable=True,
            allowed_roots=tuple(self.allowed_roots) + (parent.resolve(strict=False),),
        )

    def destroy_disposable(self, workspace: Workspace) -> None:
        """Remove a disposable workspace. Never touches a non-disposable one."""
        if not workspace.disposable:
            raise SidekickError(
                errors.INVALID_REQUEST,
                "Refusing to delete a workspace that was not created as disposable.",
            )
        shutil.rmtree(workspace.root, ignore_errors=True)

    # -- helpers -----------------------------------------------------------
    def is_authorized(self, raw_path: str | os.PathLike) -> bool:
        try:
            self.validate(raw_path)
            return True
        except SidekickError:
            return False

    def describe(self) -> dict:
        """Return a truthful description of the policy for capability reporting."""
        return {
            "allowed_roots": [str(r) for r in self.allowed_roots],
            "disposable_root": str(self.disposable_root) if self.disposable_root else None,
            "require_git": self.require_git,
            "allow_create": self.allow_create,
        }


def default_workspace_policy() -> WorkspacePolicy:
    """A policy suitable for local development.

    Authorized roots are the current working directory and the system temp
    directory. A deployment should pass explicit roots instead.
    """
    roots: List[str] = [os.getcwd(), tempfile.gettempdir()]
    return WorkspacePolicy(roots)
