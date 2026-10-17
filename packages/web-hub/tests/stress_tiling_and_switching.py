import os
import sys
import json
import asyncio
import unittest
from pathlib import Path
from aiohttp import web, WSMsgType, ClientSession

# Resolve project root dynamically (parent of tests directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.database import db
from src.cdp_client import AntigravityCDP
import src.port_finder
from src.parallel_cdp import ParallelCDPManager

class MockCDPState:
    ws_url = "ws://127.0.0.1:0/devtools/page/mock-page"
    port = 0
    evaluated_expressions = []
    location_href_value = "https://127.0.0.1:9225/chat/c/12345678-1234-1234-1234-1234567890ab"
    location_href_delay = 0.0
    disconnect_websocket_during_eval = False

    @classmethod
    def reset(cls):
        cls.evaluated_expressions = []
        cls.location_href_value = "https://127.0.0.1:9225/chat/c/12345678-1234-1234-1234-1234567890ab"
        cls.location_href_delay = 0.0
        cls.disconnect_websocket_during_eval = False

class TestStressAndEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        MockCDPState.reset()
        self.cdp_sessions = []

        # Intercept AntigravityCDP __init__ to track sessions
        self.orig_cdp_init = AntigravityCDP.__init__
        def tracked_init(slf, *args, **kwargs):
            self.orig_cdp_init(slf, *args, **kwargs)
            self.cdp_sessions.append(slf)
        AntigravityCDP.__init__ = tracked_init

        # Start Mock DevTools/CDP WebSocket server
        self.cdp_app = web.Application()
        self.cdp_app.router.add_get('/json', self.handle_cdp_json)
        self.cdp_app.router.add_get('/devtools/page/mock-page', self.handle_cdp_ws)
        self.cdp_runner = web.AppRunner(self.cdp_app)
        await self.cdp_runner.setup()
        self.cdp_site = web.TCPSite(self.cdp_runner, '127.0.0.1', 0)
        await self.cdp_site.start()
        self.cdp_port = self.cdp_runner.addresses[0][1]
        MockCDPState.port = self.cdp_port

        # Start Mock API/Proxy Server
        from src.chat_handlers import handle_navigate_chat
        from src.project_handlers import handle_create_integrity_chat

        self.proxy_app = web.Application()
        self.proxy_app.router.add_post('/api/chats/{chat_id}/navigate', handle_navigate_chat)
        self.proxy_app.router.add_post('/api/integrity/chats', handle_create_integrity_chat)
        self.proxy_runner = web.AppRunner(self.proxy_app)
        await self.proxy_runner.setup()
        self.proxy_site = web.TCPSite(self.proxy_runner, '127.0.0.1', 0)
        await self.proxy_site.start()
        self.proxy_port = self.proxy_runner.addresses[0][1]
        self.base_url = f"http://127.0.0.1:{self.proxy_port}"

        # Monkey-patch find_devtools to point to mock CDP
        self.orig_find_devtools = src.cdp_client.find_devtools
        self.orig_port_finder_find_devtools = src.port_finder.find_devtools

        def mock_find_devtools(recent_ports=None):
            return {
                "devtools_port": self.cdp_port,
                "ws_url": f"ws://127.0.0.1:{self.cdp_port}/devtools/page/mock-page",
                "backend_port": 9225,
                "page_url": "https://127.0.0.1:9225/chat",
                "title": "mock tauri UI"
            }

        src.cdp_client.find_devtools = mock_find_devtools
        src.port_finder.find_devtools = mock_find_devtools

        # Add dummy project to database with a unique name
        import uuid
        self.unique_project_name = f"Mock Test Project {uuid.uuid4()}"
        self.test_project_id = db.add_project(
            name=self.unique_project_name,
            path="C:\\mock\\path",
            test_command="python -m unittest"
        )

    async def asyncTearDown(self):
        # Clean up database
        db.delete_project(self.test_project_id)

        # Restore patches
        src.cdp_client.find_devtools = self.orig_find_devtools
        src.port_finder.find_devtools = self.orig_port_finder_find_devtools
        AntigravityCDP.__init__ = self.orig_cdp_init

        for cdp in self.cdp_sessions:
            try:
                await cdp.disconnect()
            except Exception:
                pass
        self.cdp_sessions.clear()

        await self.proxy_site.stop()
        await self.proxy_runner.cleanup()
        await self.cdp_site.stop()
        await self.cdp_runner.cleanup()

    async def handle_cdp_json(self, request):
        return web.json_response([
            {
                "type": "page",
                "url": "https://127.0.0.1:9225/chat",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.cdp_port}/devtools/page/mock-page"
            }
        ])

    async def handle_cdp_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    mid = data.get("id")
                    method = data.get("method")
                    params = data.get("params", {})
                    if method == "Runtime.evaluate":
                        expr = params.get("expression", "")
                        MockCDPState.evaluated_expressions.append(expr)

                        if MockCDPState.disconnect_websocket_during_eval:
                            await ws.close()
                            break

                        if "window.location.href" in expr:
                            if MockCDPState.location_href_delay > 0:
                                await asyncio.sleep(MockCDPState.location_href_delay)
                            await ws.send_json({"id": mid, "result": {"result": {"value": MockCDPState.location_href_value}}})
                        elif "navigateToChat" in expr:
                            await ws.send_json({"id": mid, "result": {"result": {"value": {"success": True}}}})
                        elif "startNewConversationForProject" in expr:
                            await ws.send_json({"id": mid, "result": {"result": {"value": True}}})
                        else:
                            await ws.send_json({"id": mid, "result": {"result": {"value": True}}})
                    else:
                        await ws.send_json({"id": mid, "result": {}})
        except Exception:
            pass
        return ws

    async def test_happy_path_loop(self):
        """Run standard happy path E2E tests 20 times to detect timing issues."""
        for i in range(20):
            # Check navigate endpoint
            async with ClientSession() as session:
                async with session.post(f"{self.base_url}/api/chats/test-uuid-{i}/navigate") as resp:
                    self.assertEqual(resp.status, 200)
                    data = await resp.json()
                    self.assertTrue(data.get("success"))

                # Check create integrity chat
                async with session.post(f"{self.base_url}/api/integrity/chats", json={"project_id": self.test_project_id}) as resp:
                    self.assertEqual(resp.status, 200)
                    data = await resp.json()
                    self.assertTrue(data.get("success"))
                    self.assertEqual(data.get("convo_id"), "12345678-1234-1234-1234-1234567890ab")

    async def test_invalid_project_id_types(self):
        """Test how API server recovers when project_id is invalid (missing, non-existent, or string)."""
        async with ClientSession() as session:
            # 1. missing project_id
            async with session.post(f"{self.base_url}/api/integrity/chats", json={}) as resp:
                self.assertEqual(resp.status, 400)
                data = await resp.json()
                self.assertIn("project_id is required", data.get("error"))

            # 2. non-existent project_id
            async with session.post(f"{self.base_url}/api/integrity/chats", json={"project_id": 99999}) as resp:
                self.assertEqual(resp.status, 404)
                data = await resp.json()
                self.assertIn("Project not found", data.get("error"))

            # 3. malformed project_id (string that is not an int)
            async with session.post(f"{self.base_url}/api/integrity/chats", json={"project_id": "invalid-id"}) as resp:
                self.assertEqual(resp.status, 500)
                data = await resp.json()
                self.assertTrue("error" in data)

    async def test_missing_devtools_port(self):
        """Test API behavior when no DevTools port is active (Tauri app not running)."""
        # Set find_devtools mock to return None
        def mock_find_devtools_none(recent_ports=None):
            return None

        src.cdp_client.find_devtools = mock_find_devtools_none
        src.port_finder.find_devtools = mock_find_devtools_none

        async with ClientSession() as session:
            # 1. navigate chat (returns 503 text/plain)
            async with session.post(f"{self.base_url}/api/chats/some-chat-id/navigate") as resp:
                self.assertEqual(resp.status, 503)
                text = await resp.text()
                self.assertIn("Cannot connect to Anti-Gravity Desktop App", text)

            # 2. create integrity chat (returns 500 json)
            async with session.post(f"{self.base_url}/api/integrity/chats", json={"project_id": self.test_project_id}) as resp:
                self.assertEqual(resp.status, 500)
                data = await resp.json()
                self.assertIn("Antigravity DevTools not found!", data.get("error"))

    async def test_sidebar_delay_fallback(self):
        """Test API behavior when Tauri sidebar/URL navigation takes more than 1 second."""
        # location_href_value doesn't change to UUID in 1s (remains "https://127.0.0.1:9225/chat/")
        MockCDPState.location_href_value = "https://127.0.0.1:9225/chat/"

        async with ClientSession() as session:
            async with session.post(f"{self.base_url}/api/integrity/chats", json={"project_id": self.test_project_id}) as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data.get("success"))
                # Convo ID should fallback to "new" rather than failing with exception
                self.assertEqual(data.get("convo_id"), "new")

    async def test_cdp_disconnected_targets(self):
        """Test recovery/error handling when CDP target disconnects during request."""
        MockCDPState.disconnect_websocket_during_eval = True

        async with ClientSession() as session:
            async with session.post(f"{self.base_url}/api/chats/some-chat-id/navigate") as resp:
                # Disconnection during bridge injection raises web.HTTPServiceUnavailable (503)
                self.assertEqual(resp.status, 503)
                text = await resp.text()
                self.assertIn("Cannot connect to Anti-Gravity Desktop App", text)

if __name__ == "__main__":
    unittest.main()
