"""Tests for the real local operating-system capabilities.

These adapters call real Windows APIs. The tests are written so that they do
not disturb the machine they run on:

* the system volume is restored to its original value afterwards;
* the clipboard is restored to its original contents afterwards;
* the media key test presses ``play_pause`` twice, which is a net no-op for
  whatever the user is currently playing.

Anything that would launch an application (``system.open``) is tested only
through its validation path, because launching apps during a test run would
be intrusive.
"""

from __future__ import annotations

import unittest

from tests.support import TempDirTestCase, requires_git, run_git

from sidekick_execution import errors
from sidekick_execution.adapters import system as system_adapter
from sidekick_execution.adapters.registry import ToolRegistry
from sidekick_execution.adapters.system import (
    IS_WINDOWS,
    MEDIA_KEYS,
    capabilities,
    get_clipboard,
    get_volume,
    send_media_key,
    set_clipboard,
    set_volume,
)
from sidekick_execution.approval import ApprovalStore
from sidekick_execution.errors import SidekickError
from sidekick_execution.events import EventBus
from sidekick_execution.jobs import JobManager
from sidekick_execution.service import ExecutionService
from sidekick_execution.workspace import WorkspacePolicy

requires_windows = unittest.skipUnless(IS_WINDOWS, "Windows-only capability")


class SystemCapabilityTests(unittest.TestCase):
    @requires_windows
    def test_capability_report_is_truthful(self) -> None:
        report = capabilities()
        self.assertTrue(report["windows"])
        self.assertIn("volume", report)
        self.assertIn("media_keys", report)
        self.assertIn("clipboard", report)

    @requires_windows
    def test_volume_can_be_read_and_restored(self) -> None:
        try:
            original = get_volume()
        except SidekickError as exc:
            self.skipTest(f"the Windows audio API is unavailable here: {exc.message}")
        try:
            applied = set_volume(42)
            self.assertGreaterEqual(applied, 38)
            self.assertLessEqual(applied, 46)
            self.assertGreaterEqual(get_volume(), 38)
        finally:
            set_volume(original)

    @requires_windows
    def test_volume_rejects_an_out_of_range_level(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            set_volume(150)
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    @requires_windows
    def test_volume_rejects_a_non_integer_level(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            set_volume("loud")  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    @requires_windows
    def test_media_key_press_is_delivered_twice_so_the_state_is_unchanged(self) -> None:
        # play_pause twice returns whatever was playing to its original state.
        first = send_media_key("play_pause")
        second = send_media_key("play_pause")
        self.assertEqual(first, "play_pause")
        self.assertEqual(second, "play_pause")

    def test_unknown_media_key_is_rejected(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            send_media_key("self_destruct")
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)
        self.assertIn("play_pause", ctx.exception.details["supported"])

    @requires_windows
    def test_clipboard_round_trip_restores_the_original_contents(self) -> None:
        try:
            original = get_clipboard()
        except SidekickError as exc:
            self.skipTest(f"the clipboard is unavailable here: {exc.message}")
        try:
            marker = "sidekick-clipboard-test"
            written = set_clipboard(marker)
            self.assertEqual(written, len(marker))
            self.assertEqual(get_clipboard(), marker)
        finally:
            if original:
                set_clipboard(original)

    @requires_windows
    def test_clipboard_rejects_non_string_input(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            set_clipboard(1234)  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    def test_open_path_requires_a_path(self) -> None:
        with self.assertRaises(SidekickError) as ctx:
            system_adapter.open_path("   ")
        self.assertEqual(ctx.exception.code, errors.INVALID_REQUEST)

    def test_media_key_table_covers_the_documented_actions(self) -> None:
        for action in ("play_pause", "next", "previous", "stop", "mute", "volume_up", "volume_down"):
            self.assertIn(action, MEDIA_KEYS)


class VcsCommitTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        requires_git(self)
        self.repo = self.tmp_path / "repo"
        self.repo.mkdir()
        run_git(["init", "--initial-branch=main"], self.repo)
        run_git(["config", "user.email", "tests@sidekick.invalid"], self.repo)
        run_git(["config", "user.name", "Sidekick Tests"], self.repo)
        (self.repo / "a.txt").write_text("hello\n", encoding="utf-8")
        run_git(["add", "-A"], self.repo)
        run_git(["commit", "-m", "initial"], self.repo)

        self.service = ExecutionService.create(
            workspace_policy=WorkspacePolicy([str(self.tmp_path)]),
        )
        self.addCleanup(self.service.job_manager.shutdown)

    def _submit(self, tool: str, arguments: dict) -> dict:
        manager = self.service.job_manager
        payload = manager.submit(tool, arguments)
        action = manager.wait(payload["action"]["action_id"], timeout=60)
        return action.to_dict()

    def test_commit_creates_a_real_commit(self) -> None:
        (self.repo / "b.txt").write_text("second file\n", encoding="utf-8")
        action = self._submit(
            "vcs.commit", {"workspace": str(self.repo), "message": "add b.txt"}
        )

        self.assertEqual(action["state"], "succeeded", action.get("error"))
        self.assertTrue(action["result"]["committed"])
        sha = action["result"]["head_sha"]
        self.assertTrue(sha)

        log = run_git(["log", "-1", "--pretty=%s"], self.repo).stdout.strip()
        self.assertEqual(log, "add b.txt")
        files = run_git(["show", "--name-only", "--pretty=", sha], self.repo).stdout
        self.assertIn("b.txt", files)

    def test_commit_without_changes_reports_that_nothing_was_committed(self) -> None:
        action = self._submit(
            "vcs.commit", {"workspace": str(self.repo), "message": "nothing to do"}
        )
        self.assertEqual(action["state"], "succeeded")
        self.assertFalse(action["result"]["committed"])
        self.assertEqual(action["result"]["reason"], "no_changes")

    def test_commit_requires_a_message(self) -> None:
        action = self._submit("vcs.commit", {"workspace": str(self.repo)})
        self.assertEqual(action["state"], "failed")
        self.assertEqual(action["error"]["code"], "invalid_request")

    def test_commit_in_an_unauthorized_workspace_is_refused(self) -> None:
        outside = self.tmp_path.parent / "outside-the-allowed-roots"
        outside.mkdir(exist_ok=True)
        action = self._submit(
            "vcs.commit", {"workspace": str(outside), "message": "should not run"}
        )
        self.assertEqual(action["state"], "failed")
        self.assertEqual(action["error"]["code"], "workspace_unauthorized")


class SystemToolRegistrationTests(unittest.TestCase):
    def test_system_tools_are_registered_with_honest_status(self) -> None:
        service = ExecutionService.create(
            workspace_policy=WorkspacePolicy([str(__import__("tempfile").gettempdir())]),
        )
        self.addCleanup(service.job_manager.shutdown)
        report = service.capabilities()
        names = {tool["tool"] for tool in report["tools"]}
        for expected in (
            "system.info",
            "system.volume",
            "system.media_control",
            "system.clipboard",
            "system.open",
            "vcs.commit",
        ):
            self.assertIn(expected, names)

        by_name = {tool["tool"]: tool for tool in report["tools"]}
        if IS_WINDOWS:
            self.assertEqual(by_name["system.volume"]["status"], "REAL")
            self.assertEqual(by_name["system.media_control"]["status"], "REAL")
        else:
            self.assertEqual(by_name["system.volume"]["status"], "NOT_CONFIGURED")
            self.assertTrue(by_name["system.volume"]["status_detail"])


if __name__ == "__main__":
    unittest.main()
