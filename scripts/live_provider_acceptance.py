#!/usr/bin/env python
"""Live coding-provider acceptance.

This is the **only** test that may report that a coding agent works against
a real model. It never substitutes a fixture: if no provider is configured it
exits with the code ``2`` (BLOCKED) and prints exactly what has to be set up.

Usage::

    python scripts/live_provider_acceptance.py

    # or with a local coding CLI:
    $env:SIDEKICK_CODING_CLI = "aider"
    python scripts/live_provider_acceptance.py

Exit codes
----------
``0``  the live provider produced a correct change and the tests passed
``1``  the live provider ran but the result was not correct
``2``  no live provider is configured - the acceptance could not be run

What it does
------------
1. creates a disposable Git repository with a real bug and a failing test;
2. asks the *real* core to carry out the task, which routes it through the
   real adapter to the real execution service;
3. shows the edits the provider proposed, the approval that was required,
   and the files that were really changed;
4. runs the project's real test command and reports the real exit code;
5. prints the real diff.

The credentials are never printed. Only the provider name, the model id and
whether a key was present are reported.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sidekick.core.engine import DecisionEngine  # noqa: E402
from sidekick.core.registry import ToolRegistry  # noqa: E402
from sidekick.core.safety import SafetyPolicy  # noqa: E402
from sidekick.core.schemas import ActionStatus, SidekickRequest  # noqa: E402
from sidekick.core.sessions import SessionStore  # noqa: E402
from sidekick.tools.execution import ExecutionServiceAdapter  # noqa: E402

from sidekick_execution.http_service import serve_in_thread  # noqa: E402
from sidekick_execution.service import ExecutionService  # noqa: E402
from sidekick_execution.workspace import WorkspacePolicy  # noqa: E402

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2

BROKEN_MODULE = '''\
def add(a, b):
    """Add two numbers."""
    return a - b
'''

TEST_MODULE = '''\
import unittest

from broken import add


class AdditionTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)


if __name__ == "__main__":
    unittest.main()
'''


def _git(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr}")


def build_disposable_repo(root: Path) -> Path:
    """A disposable repository with a real bug and a real failing test."""
    repo = root / "live-acceptance-repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "broken.py").write_text(BROKEN_MODULE, encoding="utf-8")
    (repo / "test_broken.py").write_text(TEST_MODULE, encoding="utf-8")
    _git(["init", "--initial-branch=main"], repo)
    _git(["config", "user.email", "acceptance@sidekick.invalid"], repo)
    _git(["config", "user.name", "Sidekick Acceptance"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "a repository with a real bug"], repo)
    return repo


def provider_status() -> dict:
    """The live provider's status, without leaking anything secret."""
    from sidekick_execution.providers.config import ProviderConfig
    from sidekick_execution.service import select_provider

    config = ProviderConfig.from_env()
    provider = select_provider(config.name, config=config)
    status = provider.status()
    return {
        "status": status.to_dict(),
        "config": config.public_dict(),
        "simulated": provider.level == "SIMULATED",
    }


def main() -> int:
    print("=" * 72)
    print("Sidekick live coding-provider acceptance")
    print("=" * 72)

    info = provider_status()
    status = info["status"]
    config = info["config"]

    print(f"provider      : {status.get('detail', {}).get('provider', '?')}")
    print(f"model         : {status.get('detail', {}).get('model', '-')}")
    print(f"api key present: {config.get('api_key_present')}")
    print(f"local CLI      : {config.get('cli') or '-'}")
    print()

    if info["simulated"]:
        print(
            "BLOCKED: the configured provider is the SIMULATED development substitute.\n"
            "         This acceptance only accepts a real provider. Disable "
            "SIDEKICK_ALLOW_SIMULATED_PROVIDER or configure a real one."
        )
        return EXIT_BLOCKED

    if not status.get("available"):
        print("BLOCKED: no live coding provider is configured.")
        print()
        print("Set up a real provider, then run this again:")
        print()
        print("  A. An OpenAI-compatible HTTP endpoint:")
        print("       $env:SIDEKICK_LLM_API_KEY = '<your key>'")
        print("       $env:SIDEKICK_LLM_BASE_URL = 'https://api.openai.com/v1'")
        print("       $env:SIDEKICK_LLM_MODEL = 'gpt-4o-mini'")
        print()
        print("  B. An authorized local coding CLI:")
        print("       $env:SIDEKICK_CODING_CLI = 'aider'")
        print('       $env:SIDEKICK_CODING_CLI_ARGS = \'["--yes", "--no-auto-commits"]\'')
        print()
        print(f"reason: {status.get('reason')} - {status.get('detail', {}).get('hint', '')}")
        return EXIT_BLOCKED

    workdir = Path(tempfile.mkdtemp(prefix="sidekick-live-acceptance-"))
    try:
        repo = build_disposable_repo(workdir)
        print(f"disposable repository: {repo}")

        service = ExecutionService.create(
            workspace_policy=WorkspacePolicy([str(workdir)]),
        )
        httpd, _ = serve_in_thread(service, "127.0.0.1", 0)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        print(f"execution service     : {base}")
        print()

        registry = ToolRegistry()
        registry.register(ExecutionServiceAdapter(base_url=base))
        engine = DecisionEngine(
            registry=registry,
            sessions=SessionStore(),
            policy=SafetyPolicy(workspace_root=workdir),
        )

        utterance = (
            f'fix the failing test in "{repo}". '
            "broken.py has a bug: add() subtracts instead of adding."
        )
        print(f"utterance: {utterance}")
        response = engine.handle(
            SidekickRequest(request_id="live-1", session_id="live-session", utterance=utterance)
        )
        if not response.action_plan:
            print("FAILED: the core did not plan an action.")
            print(json.dumps(response.model_dump(mode="json"), indent=2)[:2000])
            return EXIT_FAILED

        action = response.action_plan[0]
        print(f"planned action       : {action.tool} ({action.state})")
        print(f"approval required    : {action.approval_required}")
        if action.state != ActionStatus.AWAITING_CONFIRMATION:
            print("FAILED: the action was not held for approval.")
            return EXIT_FAILED

        engine.confirm_action(
            "live-session", action.action_id, approved=True, plan_hash=action.plan_hash
        )
        deadline = time.monotonic() + 900
        final = None
        while time.monotonic() < deadline:
            current = engine.get_action("live-session", action.action_id)
            if current is not None and current.state in (
                ActionStatus.SUCCEEDED,
                ActionStatus.FAILED,
                ActionStatus.CANCELLED,
            ):
                final = current
                break
            time.sleep(0.25)

        if final is None:
            print("FAILED: the job did not finish within 15 minutes.")
            return EXIT_FAILED

        print()
        print("-" * 72)
        print(f"final state          : {final.state.value}")
        print(f"job id               : {final.job_id}")
        result = final.result or {}
        provider = result.get("provider") or {}
        print(f"provider level       : {provider.get('level')}")
        print(f"provider model       : {provider.get('model')}")
        print(f"provider simulated   : {provider.get('simulated')}")
        print()
        print("proposed edits:")
        for edit in result.get("proposed_edits") or []:
            print(f"  - {edit.get('path')}")
        print("applied files:")
        for path in result.get("applied_files") or []:
            print(f"  - {path}")
        print()
        print(f"changed files        : {[c.get('path') for c in result.get('changed_files') or []]}")
        print(f"diff state           : {result.get('diff_state')}")
        diff = result.get("diff") or ""
        print("diff:")
        print(diff[:4000] if diff else "  (empty)")
        print()

        test_result = result.get("test_result") or {}
        print(f"test command         : {test_result.get('argv')}")
        print(f"test exit code       : {test_result.get('exit_code')}")
        print(f"test passed          : {test_result.get('passed')}")
        print(f"test summary         : {test_result.get('summary')}")
        if test_result.get("stdout"):
            print("test stdout:")
            print(test_result["stdout"][:2000])

        if final.error:
            print()
            print(f"error code           : {final.error.code}")
            print(f"error message        : {final.error.message}")

        print("-" * 72)
        ok = (
            final.state == ActionStatus.SUCCEEDED
            and bool(test_result.get("passed"))
            and test_result.get("exit_code") == 0
            and not provider.get("simulated")
        )
        if ok:
            print("RESULT: PASSED - a live provider fixed the bug and the tests pass.")
            return EXIT_PASSED
        print("RESULT: FAILED - the live provider did not produce a correct result.")
        return EXIT_FAILED
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
