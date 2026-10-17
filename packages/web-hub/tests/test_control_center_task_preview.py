import asyncio
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from src.ide_server import resolve_control_task_workspace
from src.project_handlers import (
    _ensure_preview_server,
    _preview_status,
    _stop_preview_server,
)


class TestControlTaskWorkspace(unittest.TestCase):
    def test_active_task_resolves_exact_isolated_worktree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir) / "task-worktree"
            worktree.mkdir()
            task = {
                "id": "TASK-PREVIEW",
                "project_id": 7,
                "status": "waiting_review",
                "branch_name": "ag/task-preview",
                "worktree_path": str(worktree),
            }
            with patch("src.control_center.control_center.get_task", return_value=task):
                workspace = resolve_control_task_workspace(task["id"])

            self.assertEqual(workspace["path"], worktree.resolve())
            self.assertEqual(workspace["source"], "pr_worktree")
            self.assertEqual(workspace["branch_name"], "ag/task-preview")

    def test_completed_task_falls_back_to_merged_project_after_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project"
            project_path.mkdir()
            task = {
                "id": "TASK-MERGED",
                "project_id": 8,
                "status": "completed",
                "branch_name": "ag/task-merged",
                "worktree_path": str(Path(temp_dir) / "removed-worktree"),
            }
            with (
                patch("src.control_center.control_center.get_task", return_value=task),
                patch("src.ide_server.db.get_project", return_value={"path": str(project_path)}),
            ):
                workspace = resolve_control_task_workspace(task["id"])

            self.assertEqual(workspace["path"], project_path.resolve())
            self.assertEqual(workspace["source"], "merged_project")


class TestControlTaskPreviewServer(unittest.IsolatedAsyncioTestCase):
    async def test_preview_reuses_port_and_stops_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<h1>PR preview proof</h1>", encoding="utf-8")
            key = "task:TASK-PREVIEW-PROOF"
            try:
                first, started = await _ensure_preview_server(
                    key,
                    root,
                    source="pr_worktree",
                )
                self.assertTrue(started)
                self.assertTrue(first["active"])
                self.assertEqual(first["path"], str(root.resolve()))

                body = await asyncio.to_thread(
                    lambda: urllib.request.urlopen(first["url"], timeout=3)
                    .read()
                    .decode("utf-8")
                )
                self.assertIn("PR preview proof", body)

                second, started_again = await _ensure_preview_server(
                    key,
                    root,
                    source="pr_worktree",
                )
                self.assertFalse(started_again)
                self.assertEqual(second["port"], first["port"])
                self.assertTrue(_preview_status(
                    key,
                    path=root,
                    source="pr_worktree",
                )["active"])
            finally:
                stopped = _stop_preview_server(key)
                self.assertFalse(stopped["active"])
                self.assertEqual(_stop_preview_server(key)["status"], "already_stopped")


if __name__ == "__main__":
    unittest.main()
