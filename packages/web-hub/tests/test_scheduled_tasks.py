import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.proxy_server import create_app
from src.scheduled_task_handlers import (
    handle_create_scheduled_task,
    handle_delete_scheduled_task,
    handle_disable_scheduled_task,
    handle_enable_scheduled_task,
    handle_get_scheduled_task_events,
    handle_list_scheduled_tasks,
    handle_restart_scheduled_task,
    handle_run_scheduled_task,
    handle_update_scheduled_task,
)
from src.scheduled_task_service import (
    normalize_create_payload,
    normalize_update_payload,
    slugify_task_name,
    validate_cron,
)


class FakeScheduledTaskService:
    def __init__(self):
        self.tasks = {
            "morning-check": {
                "id": "morning-check",
                "name": "Morning Check",
                "schedule": "0 9 * * *",
                "prompt": "Check issues.",
                "project_id": "project-1",
                "all_projects": False,
                "enabled": False,
            }
        }

    async def list_tasks(self):
        return {
            "connected": True,
            "tasks": list(self.tasks.values()),
            "count": len(self.tasks),
        }

    async def create_task(self, payload):
        normalized = normalize_create_payload(payload)
        if normalized["id"] in self.tasks:
            raise FileExistsError(normalized["id"])
        self.tasks[normalized["id"]] = dict(normalized)
        return dict(normalized)

    async def update_task(self, task_id, payload):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        self.tasks[task_id].update(normalize_update_payload(payload))
        return dict(self.tasks[task_id])

    async def set_enabled(self, task_id, enabled):
        return await self.update_task(task_id, {"enabled": enabled})

    async def run_task(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return {"success": True, "task_id": task_id}

    async def restart_task(self, task_id):
        return await self.run_task(task_id)

    async def delete_task(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        del self.tasks[task_id]
        return {"success": True, "task_id": task_id}

    async def get_events(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return {"task_id": task_id, "events": [{"timestampMs": "123"}]}


class TestScheduledTaskValidation(unittest.TestCase):
    def test_slug_matches_native_ui(self):
        self.assertEqual(slugify_task_name(" Morning / Issue Check! "), "morning-issue-check")

    def test_native_five_field_cron_is_required(self):
        self.assertEqual(validate_cron(" 0   9 * * * "), "0 9 * * *")
        with self.assertRaises(ValueError):
            validate_cron("0 9 * *")
        with self.assertRaises(ValueError):
            validate_cron("@daily")

    def test_create_defaults_to_disabled(self):
        payload = normalize_create_payload({
            "name": "Morning Check",
            "schedule": "0 9 * * *",
            "prompt": "Check issues.",
            "project_id": "project-1",
        })
        self.assertEqual(payload["id"], "morning-check")
        self.assertFalse(payload["enabled"])

    def test_update_requires_an_editable_field(self):
        with self.assertRaises(ValueError):
            normalize_update_payload({})


class TestScheduledTaskRoutes(unittest.TestCase):
    def test_routes_are_registered(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/antigravity/scheduled-tasks", paths)
        self.assertIn("/api/antigravity/scheduled-tasks/{task_id}", paths)
        self.assertIn("/api/antigravity/scheduled-tasks/{task_id}/enable", paths)
        self.assertIn("/api/antigravity/scheduled-tasks/{task_id}/disable", paths)
        self.assertIn("/api/antigravity/scheduled-tasks/{task_id}/run", paths)
        self.assertIn("/api/antigravity/scheduled-tasks/{task_id}/restart", paths)
        self.assertIn("/api/antigravity/scheduled-tasks/{task_id}/events", paths)

    def test_dashboard_exposes_full_control(self):
        html = Path("dashboard/index.html").read_text(encoding="utf-8")
        javascript = Path("dashboard/js/app.js").read_text(encoding="utf-8")
        self.assertIn('id="scheduled-tasks-tab"', html)
        self.assertIn('id="scheduled-task-modal"', html)
        self.assertIn("/api/antigravity/scheduled-tasks", javascript)
        self.assertIn("setScheduledTaskEnabled", javascript)
        self.assertIn("restartScheduledTask", javascript)
        self.assertIn("deleteScheduledTask", javascript)
        self.assertIn("showScheduledTaskEvents", javascript)


class TestScheduledTaskAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = FakeScheduledTaskService()
        app = web.Application()
        app.router.add_get("/tasks", handle_list_scheduled_tasks)
        app.router.add_post("/tasks", handle_create_scheduled_task)
        app.router.add_patch("/tasks/{task_id}", handle_update_scheduled_task)
        app.router.add_post("/tasks/{task_id}/enable", handle_enable_scheduled_task)
        app.router.add_post("/tasks/{task_id}/disable", handle_disable_scheduled_task)
        app.router.add_post("/tasks/{task_id}/run", handle_run_scheduled_task)
        app.router.add_post("/tasks/{task_id}/restart", handle_restart_scheduled_task)
        app.router.add_get("/tasks/{task_id}/events", handle_get_scheduled_task_events)
        app.router.add_delete("/tasks/{task_id}", handle_delete_scheduled_task)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        self.patch = patch(
            "src.scheduled_task_handlers._scheduled_task_service",
            self.service,
        )
        self.patch.start()
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.patch.stop()

    async def test_complete_task_lifecycle(self):
        response = await self.client.get("/tasks")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["count"], 1)

        response = await self.client.post("/tasks", json={
            "name": "Weekly Audit",
            "schedule": "30 18 * * 5",
            "prompt": "Audit all open work.",
            "project_id": "project-1",
            "enabled": True,
        })
        self.assertEqual(response.status, 201)
        created = await response.json()
        self.assertEqual(created["id"], "weekly-audit")
        self.assertTrue(created["enabled"])

        response = await self.client.patch("/tasks/weekly-audit", json={
            "name": "Friday Audit",
            "schedule": "0 17 * * 5",
            "prompt": "Review open work.",
        })
        self.assertEqual(response.status, 200)
        updated = await response.json()
        self.assertEqual(updated["name"], "Friday Audit")
        self.assertEqual(updated["schedule"], "0 17 * * 5")

        response = await self.client.post("/tasks/weekly-audit/disable")
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())["enabled"])

        response = await self.client.post("/tasks/weekly-audit/enable")
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["enabled"])

        response = await self.client.post("/tasks/weekly-audit/run")
        self.assertEqual(response.status, 200)

        response = await self.client.post("/tasks/weekly-audit/restart")
        self.assertEqual(response.status, 200)

        response = await self.client.get("/tasks/weekly-audit/events")
        self.assertEqual(response.status, 200)
        self.assertEqual(len((await response.json())["events"]), 1)

        response = await self.client.delete("/tasks/weekly-audit")
        self.assertEqual(response.status, 200)
        self.assertNotIn("weekly-audit", self.service.tasks)

    async def test_errors_are_mapped(self):
        response = await self.client.post("/tasks", json={
            "name": "Broken",
            "schedule": "@daily",
            "prompt": "No",
            "project_id": "project-1",
        })
        self.assertEqual(response.status, 400)

        response = await self.client.patch("/tasks/missing", json={"enabled": True})
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
