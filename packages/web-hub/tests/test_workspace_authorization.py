import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.proxy_server import create_app
from src.workspace_authorization import (
    ACTIVE_TASK_STATES,
    authorized_workspace_kind,
    handle_workspace_authorization,
)


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, tasks):
        self.tasks = tasks

    def execute(self, query, params):
        allowed = set(params)
        return FakeRows([
            {"worktree_path": task["worktree_path"]}
            for task in self.tasks
            if task["status"] in allowed and task.get("worktree_path")
        ])


class FakeDatabase:
    def __init__(self, projects, tasks):
        self.projects = projects
        self.tasks = tasks

    def get_projects(self):
        return list(self.projects)

    @contextmanager
    def _get_connection(self):
        yield FakeConnection(self.tasks)


class WorkspaceAuthorizationTests(unittest.TestCase):
    def test_allows_root_and_active_worktree_but_not_terminal_or_foreign_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            active = base / "active-task"
            terminal = base / "completed-task"
            foreign = base / "foreign"
            for path in (root, active, terminal, foreign):
                path.mkdir()
            database = FakeDatabase(
                [{"path": str(root)}],
                [
                    {"worktree_path": str(active), "status": "running"},
                    {"worktree_path": str(terminal), "status": "completed"},
                ],
            )

            self.assertEqual(authorized_workspace_kind(str(root), database=database), "project")
            self.assertEqual(
                authorized_workspace_kind(str(active), database=database),
                "active_task_worktree",
            )
            self.assertEqual(authorized_workspace_kind(str(terminal), database=database), "")
            self.assertEqual(authorized_workspace_kind(str(foreign), database=database), "")
            self.assertEqual(authorized_workspace_kind("relative/path", database=database), "")
            self.assertNotIn("completed", ACTIVE_TASK_STATES)


class WorkspaceAuthorizationHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.database = FakeDatabase([{"path": str(self.root)}], [])
        app = web.Application()
        app.router.add_post("/authorize", handle_workspace_authorization)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_handler_is_bounded_no_store_and_origin_protected(self):
        with patch("src.workspace_authorization.db", self.database):
            response = await self.client.post("/authorize", json={"path": str(self.root)})
            payload = await response.json()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload, {"authorized": True, "kind": "project"})
            self.assertEqual(response.headers["Cache-Control"], "no-store")

            rejected = await self.client.post(
                "/authorize",
                json={"path": str(self.root)},
                headers={"Origin": "https://example.com"},
            )
            self.assertEqual(rejected.status, 403)

    def test_route_is_registered(self):
        routes = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/internal/workspace-authorization", routes)


if __name__ == "__main__":
    unittest.main()
