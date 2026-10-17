import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.project_handlers import (
    handle_create_antigravity_project,
    handle_get_antigravity_conversations,
    handle_get_antigravity_projects,
    handle_get_integrity_chats,
    handle_link_integrity_workspace,
    handle_unlink_integrity_workspace,
)
from src.proxy_server import create_app
from src.parallel_cdp import ParallelCDPManager


class FakeProjectDatabase:
    def __init__(self, project):
        self.project = dict(project)

    def get_project(self, project_id):
        return dict(self.project) if int(project_id) == int(self.project["id"]) else None

    def get_projects(self, source_kind=None, *, include_archived=False):
        return [dict(self.project)]

    def update_project_integrity_link(
        self, project_id, workspace_path, project_uuid="", project_name=""
    ):
        assert int(project_id) == int(self.project["id"])
        self.project["integrity_workspace_path"] = workspace_path
        self.project["integrity_project_uuid"] = project_uuid
        self.project["antigravity_project_name"] = project_name

    def list_proxy_conversations(self, project_id):
        return []

    def list_provider_conversations(self, project_id):
        return []

    def list_managed_antigravity_conversations(self, *, state=None):
        return []


class FakeAntigravityCDP:
    projects = []

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def get_project_list(self):
        return {"projects": list(self.projects), "count": len(self.projects)}


class FakeParallelCDPManager:
    last_project_name = None

    async def ensure_project_in_primary(self, workspace_path, project_name=""):
        self.__class__.last_project_name = project_name
        return {
            "imported": True,
            "project": {"success": True, "text": Path(workspace_path).name},
            "target_id": "primary-target",
        }

    async def disconnect_all(self):
        return None


class TestAntigravityProjectRoutes(unittest.TestCase):
    def test_routes_are_registered(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/github/repos", paths)
        self.assertIn("/api/projects/import", paths)
        self.assertIn("/api/antigravity/projects", paths)
        self.assertIn("/api/projects/{id}/antigravity-link", paths)
        self.assertIn("/api/projects/{id}/antigravity-project", paths)
        self.assertIn("/api/antigravity/chats", paths)
        self.assertIn("/api/antigravity/conversations", paths)
        self.assertIn("/api/antigravity/chats/{convo_id}/archive", paths)
        self.assertIn("/api/antigravity/chats/{convo_id}/restore", paths)

    def test_hub_no_longer_auto_registers_system_config(self):
        source = Path("src/database.py").read_text(encoding="utf-8")
        self.assertNotIn("Auto-register global config repo", source)
        self.assertIn("source_kind TEXT NOT NULL DEFAULT 'legacy'", source)

    def test_dashboard_has_no_manual_workspace_path_input(self):
        html = Path("dashboard/index.html").read_text(encoding="utf-8")
        javascript = Path("dashboard/js/app.js").read_text(encoding="utf-8")
        self.assertNotIn('id="integrity-workspace-input"', html)
        self.assertIn('id="antigravity-project-select"', html)
        self.assertIn('id="github-local-path"', html)
        self.assertIn('id="antigravity-create-workspace-path"', html)
        self.assertIn('fetch("/api/github/repos")', javascript)
        self.assertIn("antigravity_project_id", javascript)
        self.assertIn("/api/antigravity/conversations?", javascript)
        self.assertIn('["running", "complete", "archived"]', javascript)
        self.assertIn('id="new-project-base-path"', html)
        self.assertIn('id="new-project-create-github"', html)
        self.assertIn('id="new-project-create-antigravity"', html)
        self.assertIn("createHubProjectWorkflow", javascript)
        self.assertIn("startConversationAutoRefresh", javascript)
        self.assertIn("2000,", javascript)
        self.assertIn('{cache: "no-store"}', javascript)
        self.assertIn('requestedTab === "dashboard"', javascript)
        self.assertIn('if (initialTab === "chats-tab")', javascript)


class TestAntigravityProjectAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = str(Path(self.temp.name).resolve())
        self.display_name = Path(self.workspace).name
        self.fake_db = FakeProjectDatabase({
            "id": 7,
            "name": "Example repo",
            "path": self.workspace,
            "integrity_workspace_path": "",
            "integrity_project_uuid": "",
            "antigravity_project_name": "",
        })
        FakeAntigravityCDP.projects = [{
            "id": self.display_name.lower(),
            "name": self.display_name,
            "display_name": self.display_name,
        }]
        self.conversations = [{
            "convo_id": "normal-chat-id",
            "workspace_path": self.workspace,
            "project_uuid": "workspace-uuid",
            "title": "Neuer Chat",
            "created_at": 1234.0,
        }]

        app = web.Application()
        app.router.add_get("/api/antigravity/projects", handle_get_antigravity_projects)
        app.router.add_post("/api/projects/{id}/antigravity-link", handle_link_integrity_workspace)
        app.router.add_delete("/api/projects/{id}/antigravity-link", handle_unlink_integrity_workspace)
        app.router.add_post(
            "/api/projects/{id}/antigravity-project",
            handle_create_antigravity_project,
        )
        app.router.add_get("/api/antigravity/chats", handle_get_integrity_chats)
        app.router.add_get(
            "/api/antigravity/conversations",
            handle_get_antigravity_conversations,
        )
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        self.db_patch = patch("src.project_handlers.db", self.fake_db)
        self.cdp_patch = patch("src.cdp_client.AntigravityCDP", FakeAntigravityCDP)
        self.scan_patch = patch(
            "src.integrity_sync.scan_integrity_convos",
            return_value=self.conversations,
        )
        self.catalog_patch = patch(
            "src.integrity_sync.scan_antigravity_conversation_catalog",
            return_value=self.conversations,
        )
        self.project_config_patch = patch(
            "src.antigravity_project_settings.is_antigravity_project_configured",
            return_value=True,
        )
        self.sidebar_patch = patch(
            "src.project_handlers._get_live_antigravity_sidebar_snapshot",
            new=AsyncMock(return_value={
                "available": True,
                "stale": False,
                "chats": [{
                    "id": "normal-chat-id",
                    "title": "Neuer Chat",
                    "position": 0,
                }],
                "active_id": "normal-chat-id",
                "count": 1,
            }),
        )
        self.db_patch.start()
        self.cdp_patch.start()
        self.scan_patch.start()
        self.catalog_patch.start()
        self.project_config_patch.start()
        self.sidebar_patch.start()
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.sidebar_patch.stop()
        self.project_config_patch.stop()
        self.catalog_patch.stop()
        self.scan_patch.stop()
        self.cdp_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    async def test_live_project_list_and_selection_link(self):
        response = await self.client.get("/api/antigravity/projects")
        self.assertEqual(response.status, 200)
        projects = (await response.json())["projects"]
        self.assertEqual([project["display_name"] for project in projects], [self.display_name])
        self.assertNotIn("workspace_path", projects[0])
        self.assertEqual(projects[0]["chat_count"], 1)

        response = await self.client.post("/api/projects/7/antigravity-link", json={
            "antigravity_project_id": "workspace-uuid",
        })
        self.assertEqual(response.status, 200)
        linked = await response.json()
        self.assertEqual(linked["antigravity_project_name"], self.display_name)
        self.assertEqual(self.fake_db.project["integrity_workspace_path"], self.workspace)

        response = await self.client.delete("/api/projects/7/antigravity-link")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.fake_db.project["integrity_workspace_path"], "")

    async def test_manual_workspace_path_is_rejected(self):
        response = await self.client.post("/api/projects/7/antigravity-link", json={
            "workspace_path": self.workspace,
        })
        self.assertEqual(response.status, 400)

    async def test_create_native_project_uses_registered_repo_folder(self):
        self.fake_db.project["integrity_project_uuid"] = "workspace-uuid"
        self.fake_db.project["antigravity_project_name"] = self.display_name
        FakeParallelCDPManager.last_project_name = None
        live_project = {
            "id": "workspace-uuid",
            "display_name": self.display_name,
            "workspace_path": self.workspace,
        }
        with patch(
            "src.parallel_cdp.ParallelCDPManager",
            FakeParallelCDPManager,
        ), patch(
            "src.project_handlers._build_live_antigravity_project_catalog",
            return_value=[live_project],
        ):
            response = await self.client.post(
                "/api/projects/7/antigravity-project",
                json={"workspace_path": self.workspace},
            )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["created"])
        self.assertEqual(payload["antigravity_project_id"], "workspace-uuid")
        self.assertEqual(
            self.fake_db.project["integrity_workspace_path"],
            self.workspace,
        )
        self.assertEqual(
            FakeParallelCDPManager.last_project_name,
            self.display_name,
        )

    async def test_create_native_project_repairs_a_stale_saved_link(self):
        self.fake_db.project["integrity_project_uuid"] = "stale-project-uuid"
        self.fake_db.project["antigravity_project_name"] = "Old project label"
        FakeParallelCDPManager.last_project_name = None
        live_project = {
            "id": "new-workspace-uuid",
            "display_name": self.display_name,
            "workspace_path": self.workspace,
        }
        with patch(
            "src.parallel_cdp.ParallelCDPManager",
            FakeParallelCDPManager,
        ), patch(
            "src.project_handlers._build_live_antigravity_project_catalog",
            side_effect=[[], [live_project]],
        ):
            response = await self.client.post(
                "/api/projects/7/antigravity-project",
                json={"workspace_path": self.workspace},
            )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["antigravity_project_id"], "new-workspace-uuid")
        self.assertEqual(FakeParallelCDPManager.last_project_name, "")
        self.assertEqual(
            self.fake_db.project["integrity_workspace_path"],
            self.workspace,
        )
        self.assertEqual(
            self.fake_db.project["antigravity_project_name"],
            self.display_name,
        )

    async def test_create_native_project_rejects_a_different_folder(self):
        other_path = str((Path(self.temp.name) / "other").resolve())
        response = await self.client.post(
            "/api/projects/7/antigravity-project",
            json={"workspace_path": other_path},
        )
        self.assertEqual(response.status, 400)

    async def test_normal_empty_chats_are_not_filtered_out(self):
        self.fake_db.project["integrity_workspace_path"] = self.workspace
        response = await self.client.get("/api/antigravity/chats?project_id=7")
        self.assertEqual(response.status, 200)
        chats = await response.json()
        self.assertEqual([chat["convo_id"] for chat in chats], ["normal-chat-id"])

    async def test_global_conversation_catalog_supports_official_filters(self):
        self.conversations[0].update({
            "conversation_type": "project",
            "project_name": self.display_name,
            "archived": False,
            "status": "complete",
            "updated_at": 1234.0,
        })
        self.conversations.append({
            "convo_id": "archived-normal-chat",
            "workspace_path": "",
            "project_uuid": "outside-of-project",
            "project_name": "",
            "repository_name": "",
            "title": "Archived note",
            "conversation_type": "normal",
            "archived": True,
            "status": "complete",
            "created_at": 1000.0,
            "updated_at": 2000.0,
        })

        response = await self.client.get(
            "/api/antigravity/conversations?type=normal&status=archived"
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(
            [item["convo_id"] for item in payload["conversations"]],
            ["archived-normal-chat"],
        )
        self.assertEqual(payload["counts"]["project"], 1)
        self.assertEqual(payload["counts"]["normal"], 0)
        self.assertEqual(payload["counts"]["archived"], 1)

    async def test_stale_conversation_projects_are_not_listed(self):
        stale_dir = str(Path(self.temp.name) / "stale-project")
        self.conversations.append({
            "convo_id": "stale-chat",
            "workspace_path": stale_dir,
            "project_uuid": "stale-uuid",
            "title": "Old",
            "created_at": 9999.0,
        })
        response = await self.client.get("/api/antigravity/projects")
        projects = (await response.json())["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["display_name"], self.display_name)

    async def test_persisted_project_chat_survives_sidebar_materialization_lag(self):
        self.fake_db.project["integrity_workspace_path"] = self.workspace
        self.fake_db.project["integrity_project_uuid"] = "workspace-uuid"
        self.fake_db.project["antigravity_project_name"] = self.display_name
        FakeAntigravityCDP.projects = []

        response = await self.client.get("/api/antigravity/projects")
        projects = (await response.json())["projects"]

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["id"], "workspace-uuid")
        self.assertEqual(projects[0]["display_name"], self.display_name)
        self.assertEqual(projects[0]["chat_count"], 1)

    async def test_missing_native_config_does_not_hide_project_deletion(self):
        self.fake_db.project["integrity_workspace_path"] = self.workspace
        self.fake_db.project["integrity_project_uuid"] = "workspace-uuid"
        self.fake_db.project["antigravity_project_name"] = self.display_name
        FakeAntigravityCDP.projects = []

        with patch(
            "src.antigravity_project_settings.is_antigravity_project_configured",
            return_value=False,
        ):
            response = await self.client.get("/api/antigravity/projects")

        self.assertEqual((await response.json())["projects"], [])

    async def test_live_basename_collision_does_not_restore_deleted_uuid(self):
        self.fake_db.project["integrity_workspace_path"] = self.workspace
        self.fake_db.project["integrity_project_uuid"] = "workspace-uuid"
        self.fake_db.project["antigravity_project_name"] = self.display_name
        FakeAntigravityCDP.projects = [{
            "name": self.display_name,
            "display_name": self.display_name,
        }]

        with patch(
            "src.antigravity_project_settings.is_antigravity_project_configured",
            return_value=False,
        ):
            response = await self.client.get("/api/antigravity/projects")

        projects = (await response.json())["projects"]
        self.assertEqual(len(projects), 1)
        self.assertTrue(projects[0]["id"].startswith("live-"))
        self.assertEqual(projects[0]["project_uuid"], "")

    async def test_same_project_uuid_is_not_duplicated_by_full_path_label(self):
        FakeAntigravityCDP.projects = [
            {"name": self.display_name, "display_name": self.display_name},
            {"name": self.workspace, "display_name": self.workspace},
        ]

        response = await self.client.get("/api/antigravity/projects")
        projects = (await response.json())["projects"]

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["id"], "workspace-uuid")
        self.assertEqual(projects[0]["display_name"], self.display_name)

    async def test_latest_conversation_uuid_wins_for_the_same_workspace(self):
        self.conversations.append({
            "convo_id": "newest-project-chat",
            "workspace_path": self.workspace,
            "project_uuid": "newest-workspace-uuid",
            "title": "Newest project chat",
            "created_at": 9999.0,
        })

        response = await self.client.get("/api/antigravity/projects")
        projects = (await response.json())["projects"]

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["id"], "newest-workspace-uuid")
        self.assertEqual(projects[0]["chat_count"], 2)

    async def test_latest_valid_uuid_wins_when_newest_conversation_is_stale(self):
        self.conversations.append({
            "convo_id": "newest-stale-project-chat",
            "workspace_path": self.workspace,
            "project_uuid": "stale-workspace-uuid",
            "title": "Newest stale project chat",
            "created_at": 9999.0,
        })

        with patch(
            "src.antigravity_project_settings.is_antigravity_project_configured",
            side_effect=lambda **kwargs: kwargs["project_uuid"] == "workspace-uuid",
        ):
            response = await self.client.get("/api/antigravity/projects")

        projects = (await response.json())["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["id"], "workspace-uuid")
        self.assertEqual(projects[0]["chat_count"], 2)


class FakeProjectWizardCDP:
    def __init__(self):
        self.expressions = []

    async def evaluate(self, expression, timeout=0):
        self.expressions.append(expression)
        if "prepareWorkspaceOpen" in expression:
            return {"success": True}
        if "typeof window.electronNative?.prepareWorkspaceOpen" in expression:
            return True
        return None


class FakeProjectEntryCDP:
    def __init__(self):
        self.expressions = []

    async def evaluate(self, expression, timeout=0):
        self.expressions.append(expression)
        if "control.click()" in expression:
            return True
        return [{"index": 0, "text": "Current Project"}]


class FakeCollapsedProjectEntryCDP:
    def __init__(self):
        self.expressions = []

    async def evaluate(self, expression, timeout=0):
        self.expressions.append(expression)
        if len(self.expressions) == 1:
            return [{
                "index": -1,
                "header_index": 0,
                "text": "Current Project",
                "expanded": "false",
                "has_control": False,
            }]
        return True


class FakeActionabilityCDP:
    def __init__(self, result):
        self.result = result
        self.expressions = []

    async def evaluate(self, expression, timeout=0):
        self.expressions.append(expression)
        return self.result


class FakeActiveProjectContextCDP:
    def __init__(self, project_name):
        self.project_name = project_name
        self.expressions = []

    async def evaluate(self, expression, timeout=0):
        self.expressions.append(expression)
        return {
            "text": self.project_name,
            "selector_visible": True,
            "composer_visible": True,
            "composer_text": "",
        }


class TestNativeProjectWizard(unittest.IsolatedAsyncioTestCase):
    async def test_text_actions_reject_hidden_stale_and_ambiguous_controls(self):
        wait_client = FakeActionabilityCDP(1)
        click_client = FakeActionabilityCDP(True)
        unavailable_client = FakeActionabilityCDP(0)

        self.assertTrue(await ParallelCDPManager._wait_for_button_text(
            wait_client,
            "Next",
            attempts=1,
        ))
        self.assertTrue(await ParallelCDPManager._click_text(
            click_client,
            "Next",
        ))
        self.assertTrue(await ParallelCDPManager._wait_for_button_unavailable(
            unavailable_client,
            "Next",
            attempts=1,
        ))

        for expression in [
            wait_client.expressions[-1],
            click_client.expressions[-1],
            unavailable_client.expressions[-1],
        ]:
            self.assertIn("element.offsetParent !== null", expression)
            self.assertIn("getBoundingClientRect()", expression)
            self.assertIn("aria-disabled", expression)
            self.assertIn("aria-hidden", expression)
            self.assertIn("[data-state=\"closed\"]", expression)
            self.assertIn("style.pointerEvents !== 'none'", expression)
        self.assertIn("matches.length !== 1", click_client.expressions[-1])

    async def test_active_project_basename_is_only_accepted_post_wizard(self):
        workspace = r"D:\Projects\.antigravity-worktrees\repo\task-6fa0347d85"
        client = FakeActiveProjectContextCDP("task-6fa0347d85")

        strict = await ParallelCDPManager._active_project_context(
            client,
            workspace,
        )
        post_wizard = await ParallelCDPManager._active_project_context(
            client,
            workspace,
            allow_basename=True,
        )

        self.assertFalse(strict["success"])
        self.assertTrue(post_wizard["success"])
        self.assertTrue(post_wizard["active_context"])
        self.assertFalse(post_wizard["sidebar_materialized"])
        for expression in client.expressions:
            self.assertIn(
                'button[data-testid="project-selector-trigger"]',
                expression,
            )
            self.assertIn('aria-label="Message input"', expression)

    def test_virtual_sidebar_positions_are_strictly_bounded(self):
        positions = ParallelCDPManager._project_sidebar_scroll_positions({
            "scroll_top": 1234.0,
            "scroll_height": 100_000.0,
            "client_height": 300.0,
        })

        self.assertLessEqual(len(positions), 32)
        self.assertIn(0.0, positions)
        self.assertIn(99_700.0, positions)

    def test_basename_fallback_requires_one_unique_visible_project(self):
        workspace = r"D:\Projects\Current Project"
        unique = ParallelCDPManager._choose_project_entry(
            [{"index": 0, "text": "Current Project"}],
            workspace,
            allow_basename=True,
        )
        ambiguous = ParallelCDPManager._choose_project_entry(
            [
                {"index": 0, "text": "Current Project"},
                {"index": 1, "text": "Current Project"},
            ],
            workspace,
            allow_basename=True,
        )

        self.assertEqual(unique["index"], 0)
        self.assertIsNone(ambiguous)

    async def test_project_button_supports_legacy_buttons_and_current_anchors(self):
        client = FakeProjectEntryCDP()

        result = await ParallelCDPManager._project_button(
            client,
            r"D:\Projects\Current Project",
            project_name="Current Project",
            click=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "Current Project")
        for expression in client.expressions:
            self.assertIn(
                'button[aria-label="New Conversation in Project"]',
                expression,
            )
            self.assertIn(
                'a[aria-label="New Conversation in Project"]',
                expression,
            )
            self.assertIn('button[data-project-card="true"]', expression)

    async def test_project_button_expands_exact_collapsed_header_before_anchor_click(self):
        client = FakeCollapsedProjectEntryCDP()

        result = await ParallelCDPManager._project_button(
            client,
            r"D:\Projects\Current Project",
            project_name="Current Project",
            click=True,
        )

        self.assertTrue(result["success"])
        click_expression = client.expressions[-1]
        self.assertIn("matchingHeaders.length === 1", click_expression)
        self.assertIn("header.getAttribute('aria-expanded') === 'false'", click_expression)
        self.assertIn("header.click()", click_expression)
        self.assertIn("control.click()", click_expression)
        self.assertIn('a[aria-label="New Conversation in Project"]', click_expression)

    async def test_empty_project_labels_are_not_a_ready_catalog(self):
        client = FakeProjectEntryCDP()
        client.evaluate = AsyncMock(return_value=[{"index": 0, "text": ""}])

        result = await ParallelCDPManager._project_button(
            client,
            r"D:\Projects\Current Project",
            project_name="Current Project",
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["catalog_ready"])

    async def test_linked_project_searches_virtual_sidebar_until_exact_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            project_name = Path(workspace).name
            target = {
                "id": "worker-target",
                "webSocketDebuggerUrl": "ws://worker",
            }
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="AG-01")
            manager.get_client_for_target = AsyncMock(
                return_value=FakeProjectWizardCDP()
            )
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._click_text = AsyncMock()

            current_scroll = 0.0
            moved_positions = []

            async def sidebar_state(_client, scroll_top=None):
                nonlocal current_scroll
                if scroll_top is not None:
                    current_scroll = float(scroll_top)
                    moved_positions.append(current_scroll)
                return {
                    "available": True,
                    "scroll_top": current_scroll,
                    "scroll_height": 1200.0,
                    "client_height": 300.0,
                }

            async def project_button(
                _client,
                _workspace,
                *,
                project_name="",
                allow_basename=False,
                **_kwargs,
            ):
                self.assertFalse(allow_basename)
                if current_scroll < 600.0:
                    return {
                        "success": False,
                        "catalog_ready": False,
                        "details": [
                            {"index": 0, "text": ""},
                            {"index": 1, "text": ""},
                        ],
                    }
                return {
                    "success": True,
                    "catalog_ready": True,
                    "text": project_name,
                    "index": 0,
                    "details": [{"index": 0, "text": project_name}],
                }

            manager._project_sidebar_state = AsyncMock(side_effect=sidebar_state)
            manager._project_button = AsyncMock(side_effect=project_button)

            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ):
                result = await manager.ensure_project_in_window(
                    target,
                    workspace,
                    project_name=project_name,
                )

            self.assertFalse(result["imported"])
            self.assertTrue(any(position >= 600.0 for position in moved_positions))
            self.assertGreaterEqual(current_scroll, 600.0)
            manager._click_text.assert_not_awaited()

    async def test_failed_virtual_search_restores_scroll_at_deadline(self):
        manager = ParallelCDPManager()
        manager._project_button = AsyncMock(return_value={
            "success": False,
            "catalog_ready": False,
            "details": [{"index": 0, "text": ""}],
        })
        manager._project_sidebar_state = AsyncMock(return_value={
            "available": True,
            "scroll_top": 123.0,
            "scroll_height": 1200.0,
            "client_height": 300.0,
        })

        with patch(
            "src.parallel_cdp.time.monotonic",
            side_effect=[100.0, 100.0, 131.0, 131.0],
        ):
            result = await manager._find_linked_project_in_sidebar(
                FakeProjectWizardCDP(),
                r"D:\Projects\Missing Project",
                "Missing Project",
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["virtual_scroll_searched"])
        self.assertEqual(
            manager._project_sidebar_state.await_args_list[-1].args[1],
            123.0,
        )

    async def test_virtual_sidebar_click_search_propagates_click_after_scroll(self):
        manager = ParallelCDPManager()
        current_scroll = 0.0
        moved_positions = []
        probes = []

        async def sidebar_state(_client, scroll_top=None):
            nonlocal current_scroll
            if scroll_top is not None:
                current_scroll = float(scroll_top)
                moved_positions.append(current_scroll)
            return {
                "available": True,
                "scroll_top": current_scroll,
                "scroll_height": 1200.0,
                "client_height": 300.0,
            }

        async def project_button(
            _client,
            _workspace,
            *,
            click=False,
            project_name="",
            **_kwargs,
        ):
            probes.append((current_scroll, click, project_name))
            if current_scroll < 600.0:
                return {
                    "success": False,
                    "catalog_ready": True,
                    "details": [{"index": 0, "text": "Another Project"}],
                }
            return {
                "success": True,
                "catalog_ready": True,
                "text": project_name,
                "index": 0,
                "details": [{"index": 0, "text": project_name}],
            }

        manager._project_sidebar_state = AsyncMock(side_effect=sidebar_state)
        manager._project_button = AsyncMock(side_effect=project_button)

        with patch(
            "src.parallel_cdp.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await manager._find_linked_project_in_sidebar(
                FakeProjectWizardCDP(),
                r"D:\Projects\task-eca75006b4",
                "task-eca75006b4",
                click=True,
            )

        self.assertTrue(result["success"])
        self.assertTrue(any(position >= 600.0 for position in moved_positions))
        self.assertLessEqual(len(moved_positions), 32)
        self.assertTrue(probes)
        self.assertTrue(all(click for _, click, _ in probes))
        self.assertTrue(all(name == "task-eca75006b4" for _, _, name in probes))

    async def test_project_chat_reuses_confirmed_import_label_for_virtual_scroll_click(self):
        workspace = r"D:\Projects\.antigravity-worktrees\repo\task-eca75006b4"
        target = {
            "id": "worker-target",
            "webSocketDebuggerUrl": "ws://worker",
        }
        client = FakeProjectWizardCDP()
        manager = ParallelCDPManager()
        manager.ensure_project_in_window = AsyncMock(return_value={
            "imported": True,
            "project": {
                "success": True,
                "text": "task-eca75006b4",
                "index": 9,
                "details": [{"index": 9, "text": "task-eca75006b4"}],
            },
        })
        manager.get_client_for_target = AsyncMock(return_value=client)
        manager._find_linked_project_in_sidebar = AsyncMock(return_value={
            "success": True,
            "text": "task-eca75006b4",
            "index": 9,
        })
        manager._project_button = AsyncMock()
        manager._wait_for_message_composer = AsyncMock()
        manager._submit_first_message = AsyncMock(return_value=(
            "chat-id",
            {"success": True},
        ))
        manager._finalize_created_chat_window = AsyncMock(return_value={
            "chat_id": "chat-id",
            "ready": True,
        })

        with patch(
            "src.parallel_cdp.asyncio.to_thread",
            new=AsyncMock(return_value={"changed": False}),
        ):
            result = await manager.create_project_chat_with_message(
                target,
                workspace,
                "Implement the candidate",
                project_name="",
            )

        self.assertTrue(result["verified"])
        manager.ensure_project_in_window.assert_awaited_once_with(
            target,
            workspace,
            project_name="",
        )
        manager._find_linked_project_in_sidebar.assert_awaited_once_with(
            client,
            workspace,
            "task-eca75006b4",
            click=True,
        )
        manager._project_button.assert_not_awaited()

    async def test_retry_reuses_a_project_visible_before_wizard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            target = {
                "id": "primary-target",
                "webSocketDebuggerUrl": "ws://primary",
            }
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="MAIN")
            manager.get_client_for_target = AsyncMock(
                return_value=FakeProjectWizardCDP()
            )
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._project_button = AsyncMock(return_value={
                "success": True,
                "text": workspace,
                "index": 0,
                "details": [{"index": 0, "text": workspace}],
            })
            manager._click_text = AsyncMock()

            result = await manager.ensure_project_in_window(target, workspace)

            self.assertFalse(result["imported"])
            manager._click_text.assert_not_awaited()

    async def test_add_folder_sequence_uses_prepared_registered_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            target = {
                "id": "primary-target",
                "webSocketDebuggerUrl": "ws://primary",
            }
            client = FakeProjectWizardCDP()
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="MAIN")
            manager.get_client_for_target = AsyncMock(return_value=client)
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._wait_for_button_unavailable = AsyncMock(return_value=True)

            project_checks = [
                {"success": False, "details": []}
                for _ in range(40)
            ]
            project_checks.append(
                {
                    "success": True,
                    "text": Path(workspace).name,
                    "index": 0,
                    "details": [{"index": 0, "text": Path(workspace).name}],
                }
            )
            manager._project_button = AsyncMock(side_effect=project_checks)
            clicked = []

            async def click_text(_client, text):
                clicked.append(text)
                return text != "Use Existing"

            manager._click_text = click_text
            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ):
                result = await manager.ensure_project_in_window(
                    target,
                    workspace,
                )

            self.assertTrue(result["imported"])
            for preflight in manager._project_button.await_args_list[:40]:
                self.assertFalse(preflight.kwargs.get("allow_basename", False))
                self.assertEqual(preflight.kwargs.get("project_name", ""), "")
            self.assertTrue(
                manager._project_button.await_args_list[-1].kwargs["allow_basename"]
            )
            self.assertEqual(
                clicked[:4],
                ["File", "Create Project", "Add Folder", "Next"],
            )
            self.assertEqual(
                [call.args[1] for call in manager._wait_for_button_text.await_args_list],
                ["File", "Create Project", "Add Folder", "Next"],
            )
            manager._wait_for_button_unavailable.assert_awaited_once_with(
                client,
                "Next",
            )
            self.assertIn("Use Existing", clicked)
            prepared = next(
                expression
                for expression in client.expressions
                if "prepareWorkspaceOpen(" in expression
                and "typeof" not in expression
            )
            self.assertIn(workspace.replace("\\", "\\\\"), prepared)

    async def test_project_can_appear_after_previous_sixteen_second_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            target = {
                "id": "primary-target",
                "webSocketDebuggerUrl": "ws://primary",
            }
            client = FakeProjectWizardCDP()
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="MAIN")
            manager.get_client_for_target = AsyncMock(return_value=client)
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._wait_for_button_unavailable = AsyncMock(return_value=True)

            missing = {"success": False, "details": []}
            visible = {
                "success": True,
                "text": workspace,
                "index": 0,
                "details": [{"index": 0, "text": workspace}],
            }
            manager._project_button = AsyncMock(
                side_effect=[missing] * 40 + [missing] * 70 + [visible]
            )
            manager._click_text = AsyncMock(
                side_effect=lambda _client, text: text != "Use Existing"
            )

            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ):
                result = await manager.ensure_project_in_window(target, workspace)

            self.assertTrue(result["imported"])
            self.assertGreater(manager._project_button.await_count - 40, 64)

    async def test_next_must_advance_the_active_project_wizard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            target = {
                "id": "worker-target",
                "webSocketDebuggerUrl": "ws://worker",
            }
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="AG-02")
            manager.get_client_for_target = AsyncMock(
                return_value=FakeProjectWizardCDP()
            )
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._wait_for_button_unavailable = AsyncMock(return_value=False)
            manager._project_button = AsyncMock(return_value={
                "success": False,
                "details": [{"index": 0, "text": "task-eca75006b4"}],
            })
            clicked = []

            async def click_text(_client, text):
                clicked.append(text)
                return True

            manager._click_text = AsyncMock(side_effect=click_text)

            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ):
                with self.assertRaisesRegex(
                    TimeoutError,
                    r"did not advance after Next.*retrying is safe",
                ):
                    await manager.ensure_project_in_window(target, workspace)

            self.assertEqual(
                clicked,
                ["File", "Create Project", "Add Folder", "Next"],
            )
            self.assertEqual(manager._project_button.await_count, 40)

    async def test_use_existing_is_clicked_once_while_reuse_becomes_visible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            project_name = Path(workspace).name
            target = {
                "id": "worker-target",
                "webSocketDebuggerUrl": "ws://worker",
            }
            client = FakeProjectWizardCDP()
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="AG-03")
            manager.get_client_for_target = AsyncMock(return_value=client)
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._wait_for_button_unavailable = AsyncMock(return_value=True)
            missing = {
                "success": False,
                "details": [{"index": 0, "text": "task-eca75006b4"}],
            }
            visible = {
                "success": True,
                "text": project_name,
                "index": 0,
                "details": [{"index": 0, "text": project_name}],
            }
            manager._project_button = AsyncMock(
                side_effect=[missing] * 40 + [missing, visible]
            )
            clicked = []

            async def click_text(_client, text):
                clicked.append(text)
                return True

            manager._click_text = AsyncMock(side_effect=click_text)

            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ):
                result = await manager.ensure_project_in_window(target, workspace)

            self.assertFalse(result["imported"])
            self.assertTrue(result["reused_existing"])
            self.assertEqual(clicked.count("Use Existing"), 1)
            self.assertEqual(
                manager._wait_for_button_unavailable.await_args_list[-1].args,
                (client, "Use Existing"),
            )

    async def test_post_wizard_active_context_succeeds_before_sidebar_materializes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            project_name = Path(workspace).name
            target = {
                "id": "worker-target",
                "webSocketDebuggerUrl": "ws://worker",
            }
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="AG-07")
            manager.get_client_for_target = AsyncMock(
                return_value=FakeProjectWizardCDP()
            )
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._wait_for_button_unavailable = AsyncMock(return_value=True)
            missing = {
                "success": False,
                "details": [{"index": 0, "text": "task-eca75006b4"}],
            }
            manager._project_button = AsyncMock(return_value=missing)
            manager._click_text = AsyncMock(
                side_effect=lambda _client, text: text != "Use Existing"
            )
            active = {
                "success": True,
                "active_context": True,
                "sidebar_materialized": False,
                "text": project_name,
                "index": 0,
                "details": [{"index": 0, "text": project_name}],
            }
            manager._active_project_context = AsyncMock(return_value=active)

            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ):
                result = await manager.ensure_project_in_window(target, workspace)

            self.assertTrue(result["imported"])
            self.assertTrue(result["project"]["active_context"])
            manager._active_project_context.assert_awaited_once_with(
                manager.get_client_for_target.return_value,
                workspace,
                allow_basename=True,
                project_name="",
            )

    async def test_project_chat_submits_in_active_context_without_sidebar_click(self):
        workspace = r"D:\Projects\.antigravity-worktrees\repo\task-6fa0347d85"
        target = {
            "id": "worker-target",
            "webSocketDebuggerUrl": "ws://worker",
        }
        client = FakeProjectWizardCDP()
        active = {
            "success": True,
            "active_context": True,
            "sidebar_materialized": False,
            "text": "task-6fa0347d85",
            "index": 0,
            "details": [{"index": 0, "text": "task-6fa0347d85"}],
        }
        manager = ParallelCDPManager()
        manager.ensure_project_in_window = AsyncMock(return_value={
            "imported": True,
            "project": active,
        })
        manager.get_client_for_target = AsyncMock(return_value=client)
        manager._active_project_context = AsyncMock(return_value=active)
        manager._find_linked_project_in_sidebar = AsyncMock()
        manager._wait_for_message_composer = AsyncMock()
        manager._submit_first_message = AsyncMock(return_value=(
            "chat-id",
            {"success": True},
        ))
        manager._finalize_created_chat_window = AsyncMock(return_value={
            "chat_id": "chat-id",
            "ready": True,
        })

        with patch(
            "src.parallel_cdp.asyncio.to_thread",
            new=AsyncMock(return_value={"changed": False}),
        ):
            result = await manager.create_project_chat_with_message(
                target,
                workspace,
                "Implement dependency-aware ready queue",
                project_name="",
            )

        self.assertTrue(result["verified"])
        manager._active_project_context.assert_awaited_once_with(
            client,
            workspace,
            project_name="task-6fa0347d85",
        )
        manager._find_linked_project_in_sidebar.assert_not_awaited()
        manager._submit_first_message.assert_awaited_once()

    async def test_visibility_timeout_is_bounded_and_safe_to_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = str(Path(temp_dir).resolve())
            target = {
                "id": "primary-target",
                "webSocketDebuggerUrl": "ws://primary",
            }
            client = FakeProjectWizardCDP()
            manager = ParallelCDPManager()
            manager.prepare_target_for_automation = AsyncMock(
                return_value={"success": True}
            )
            manager.apply_window_stamp = AsyncMock(return_value="MAIN")
            manager.get_client_for_target = AsyncMock(return_value=client)
            manager._wait_for_button_text = AsyncMock(return_value=True)
            manager._wait_for_button_unavailable = AsyncMock(return_value=True)
            manager._project_button = AsyncMock(return_value={
                "success": False,
                "details": [{"index": 0, "text": "Another Project"}],
            })
            manager._click_text = AsyncMock(
                side_effect=lambda _client, text: text != "Use Existing"
            )

            with patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ), patch(
                "src.parallel_cdp.time.monotonic",
                side_effect=[100.0, 161.0],
            ):
                with self.assertRaisesRegex(
                    TimeoutError,
                    r"within 60 seconds.*retrying this request is safe.*Another Project",
                ):
                    await manager.ensure_project_in_window(target, workspace)

            # Forty pre-flight checks plus one final, idempotent boundary read.
            self.assertEqual(manager._project_button.await_count, 41)


if __name__ == "__main__":
    unittest.main()
