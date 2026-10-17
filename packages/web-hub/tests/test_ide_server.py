import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.ide_server import (
    _code_server_command,
    _conversation_tool_workspace,
    _discover_wsl_code_server,
    _windows_path_to_wsl,
    handle_ide_status,
    handle_open_project_ide,
    resolve_conversation_workspace,
    resolve_project_workspace,
    workspace_url,
)
from src.operation_coordinator import classify_control_operation
from src.proxy_server import create_app


CONVERSATION_ID = "11111111-1111-4111-8111-111111111111"


class TestIdeWorkspaceResolution(unittest.TestCase):
    def test_latest_existing_tool_cwd_is_used_as_artifact_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            with patch(
                "src.integrity_sync.get_integrity_chat_history",
                return_value={
                    "history": [
                        {
                            "type": "tool_call",
                            "enriched": {
                                "kind": "command",
                                "cwd": str(workspace.parent),
                            },
                        },
                        {
                            "type": "tool_call",
                            "enriched": {
                                "kind": "command",
                                "cwd": str(workspace),
                            },
                        },
                    ]
                },
            ):
                result = _conversation_tool_workspace(CONVERSATION_ID)

        self.assertEqual(result, workspace)

    def test_project_path_is_resolved_from_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            with patch("src.ide_server.db.get_project") as get_project:
                get_project.return_value = {
                    "id": 7,
                    "name": "Example",
                    "path": str(workspace),
                    "integrity_workspace_path": "",
                }
                result = resolve_project_workspace(7)

        self.assertEqual(result["scope"], "project")
        self.assertEqual(result["scope_id"], 7)
        self.assertEqual(result["path"], workspace)

    def test_project_conversation_uses_native_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            with patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=[{
                    "convo_id": CONVERSATION_ID,
                    "title": "Project chat",
                    "workspace_path": str(workspace),
                }],
            ):
                result = resolve_conversation_workspace(CONVERSATION_ID)

        self.assertEqual(result["source"], "project")
        self.assertEqual(result["path"], workspace)

    def test_normal_conversation_uses_verified_brain_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            brain = (
                home
                / ".gemini"
                / "antigravity"
                / "brain"
                / CONVERSATION_ID
            )
            brain.mkdir(parents=True)
            with (
                patch("src.ide_server.Path.home", return_value=home),
                patch(
                    "src.ide_server._conversation_tool_workspace",
                    return_value=None,
                ),
                patch(
                    "src.integrity_sync.scan_antigravity_conversation_catalog",
                    return_value=[{
                        "convo_id": CONVERSATION_ID,
                        "title": "Normal chat",
                        "workspace_path": "",
                    }],
                ),
            ):
                result = resolve_conversation_workspace(CONVERSATION_ID)

        self.assertEqual(result["source"], "brain")
        self.assertEqual(result["path"], brain.resolve())

    def test_normal_conversation_prefers_latest_tool_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            with (
                patch(
                    "src.ide_server._conversation_tool_workspace",
                    return_value=workspace,
                ),
                patch(
                    "src.integrity_sync.scan_antigravity_conversation_catalog",
                    return_value=[{
                        "convo_id": CONVERSATION_ID,
                        "title": "Artifact chat",
                        "workspace_path": "",
                    }],
                ),
            ):
                result = resolve_conversation_workspace(CONVERSATION_ID)

        self.assertEqual(result["source"], "tool-workspace")
        self.assertEqual(result["path"], workspace)

    def test_code_server_command_is_loopback_only(self):
        command = _code_server_command(r"C:\Tools\code-server.cmd")
        self.assertIn("127.0.0.1:8080", command)
        self.assertNotIn("0.0.0.0:8080", command)
        self.assertIn("--auth", command)
        self.assertIn("none", command)

    def test_wsl_code_server_command_is_loopback_only(self):
        command = _code_server_command(
            "wsl::Ubuntu::/home/test/.local/bin/code-server"
        )
        self.assertEqual(
            command[:5],
            [
                "wsl.exe",
                "-d",
                "Ubuntu",
                "--exec",
                "/home/test/.local/bin/code-server",
            ],
        )
        self.assertIn("127.0.0.1:8080", command)
        self.assertNotIn("0.0.0.0:8080", command)

    def test_wsl_discovery_timeout_returns_without_pipe_capture(self):
        with (
            patch("src.ide_server.sys.platform", "win32"),
            patch("src.ide_server.shutil.which", return_value="wsl.exe"),
            patch(
                "src.ide_server.subprocess.run",
                side_effect=subprocess.TimeoutExpired("wsl.exe", 3),
            ) as run,
        ):
            self.assertIsNone(_discover_wsl_code_server())
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 3)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("capture_output", kwargs)

    def test_workspace_url_uses_folder_query(self):
        url = workspace_url(Path(r"D:\Projects\Example App"))
        self.assertTrue(url.startswith("http://127.0.0.1:8080/?folder="))
        self.assertIn("Example%20App", url)

    def test_wsl_workspace_url_translates_windows_drive(self):
        workspace = Path(r"D:\Projects\Example App")
        self.assertEqual(
            _windows_path_to_wsl(workspace),
            "/mnt/d/Projects/Example App",
        )
        url = workspace_url(workspace, runtime="wsl2")
        self.assertIn(
            "folder=%2Fmnt%2Fd%2FProjects%2FExample%20App",
            url,
        )


class TestIdeAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app.router.add_get("/api/ide/status", handle_ide_status)
        app.router.add_post(
            "/api/projects/{id}/ide/open",
            handle_open_project_ide,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_status_reports_missing_installation(self):
        with patch(
            "src.ide_server.code_server_status",
            return_value={
                "installed": False,
                "running": False,
                "security": "loopback-only",
            },
        ):
            response = await self.client.get("/api/ide/status")
            payload = await response.json()

        self.assertEqual(response.status, 200)
        self.assertFalse(payload["installed"])
        self.assertEqual(payload["security"], "loopback-only")

    async def test_open_returns_actionable_503_when_code_server_is_missing(self):
        workspace = {
            "scope": "project",
            "scope_id": 7,
            "label": "Example",
            "path": Path("C:/Projects/Example"),
        }
        with (
            patch(
                "src.ide_server.resolve_project_workspace",
                return_value=workspace,
            ),
            patch(
                "src.ide_server.ensure_code_server",
                return_value={
                    "installed": False,
                    "running": False,
                    "node_version": "v24.15.0",
                    "required_node_major": 22,
                    "install_hint": "Install code-server using Node.js 22.",
                },
            ),
        ):
            response = await self.client.post(
                "/api/projects/7/ide/open",
            )
            payload = await response.json()

        self.assertEqual(response.status, 503)
        self.assertEqual(payload["error"], "code-server is not installed.")
        self.assertEqual(payload["workspace"]["scope_id"], 7)
        self.assertEqual(payload["required_node_major"], 22)


class TestIdeIntegrationContract(unittest.TestCase):
    def test_routes_ui_and_global_lease_are_present(self):
        routes = {
            resource.canonical for resource in create_app().router.resources()
        }
        self.assertIn("/api/ide/status", routes)
        self.assertIn("/api/projects/{id}/ide/open", routes)
        self.assertIn(
            "/api/antigravity/chats/{convo_id}/ide/open",
            routes,
        )

        project_spec = classify_control_operation(
            "POST",
            "/api/projects/7/ide/open",
        )
        conversation_spec = classify_control_operation(
            "POST",
            f"/api/antigravity/chats/{CONVERSATION_ID}/ide/open",
        )
        self.assertIn("hub:web-ide", project_spec.resources)
        self.assertIn("hub:web-ide", conversation_spec.resources)

        project_root = Path(__file__).resolve().parents[1]
        html = (project_root / "dashboard" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (project_root / "dashboard" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        style = (project_root / "dashboard" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("review-open-ide-btn", html)
        self.assertIn("requestWebIde", script)
        self.assertIn("openProjectIde", script)
        self.assertIn("openConversationIde", script)
        self.assertIn("button-web-ide", script)
        self.assertIn("project-ide-btn", style)
        self.assertIn("review-open-ide-btn", style)
