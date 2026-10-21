"""Shared helpers for the execution-service tests.

The helpers create *real* Git repositories and run *real* commands. Nothing in
the test suite fabricates a diff, a commit or a test result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sidekick_execution.sandbox import resolve_executable  # noqa: E402


GIT = resolve_executable("git")
GIT_AVAILABLE = GIT is not None


def requires_git(test: unittest.TestCase) -> None:
    if not GIT_AVAILABLE:
        test.skipTest("git is not available on this machine")


def run_git(args: List[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a real git command in ``cwd``."""
    assert GIT is not None
    proc = subprocess.run(
        [GIT, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc


def make_git_repo(path: Path, files: Optional[Dict[str, str]] = None) -> Path:
    """Create a real Git repository at ``path`` with an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch=main"], path)
    run_git(["config", "user.email", "tests@sidekick.invalid"], path)
    run_git(["config", "user.name", "Sidekick Tests"], path)
    run_git(["config", "commit.gpgsign", "false"], path)
    for relative, content in (files or {}).items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_git(["add", "-A"], path)
    run_git(["commit", "-m", "initial commit"], path)
    return path


#: A tiny unittest-based test project used as the "real" project under test.
PASSING_TEST_MODULE = '''\
import unittest


class AdditionTests(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(1 + 1, 2)


if __name__ == "__main__":
    unittest.main()
'''

FAILING_TEST_MODULE = '''\
import unittest


class AdditionTests(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(1 + 1, 3)


if __name__ == "__main__":
    unittest.main()
'''


def write_test_project(root: Path, *, failing: bool = False) -> Path:
    """Create a small real Python project with a real test suite."""
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_sample.py").write_text(
        FAILING_TEST_MODULE if failing else PASSING_TEST_MODULE, encoding="utf-8"
    )
    (root / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    return root


class TempDirTestCase(unittest.TestCase):
    """Base class providing a per-test temporary directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="sidekick-test-")
        self.tmp_path = Path(self._tmp)
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def make_repo(self, name: str = "repo", files: Optional[Dict[str, str]] = None) -> Path:
        requires_git(self)
        return make_git_repo(self.tmp_path / name, files)


def isolated_env(**overrides: str) -> Dict[str, str]:
    """Return an environment mapping for provider tests."""
    env = dict(os.environ)
    for key in (
        "SIDEKICK_LLM_API_KEY",
        "SIDEKICK_LLM_BASE_URL",
        "SIDEKICK_LLM_MODEL",
        "SIDEKICK_CODING_CLI",
        "SIDEKICK_CODING_CLI_ARGS",
        "SIDEKICK_ALLOW_SIMULATED_PROVIDER",
        "SIDEKICK_ENV",
    ):
        env.pop(key, None)
    env.update(overrides)
    return env
