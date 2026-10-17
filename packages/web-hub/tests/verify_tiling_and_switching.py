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

class MockCDPState:
    ws_url = "ws://127.0.0.1:0/devtools/page/mock-page"
    port = 0
    evaluated_expressions = []

    @classmethod
    def reset(cls):
        cls.evaluated_expressions = []

class TestTilingAndSwitching(unittest.IsolatedAsyncioTestCase):
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

        # Add dummy project to database
        self.test_project_id = db.add_project(
            name="Mock Test Project Name",
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

                        # Return success values depending on the evaluated method
                        if "navigateToChat" in expr:
                            await ws.send_json({"id": mid, "result": {"result": {"value": {"success": True}}}})
                        elif "startNewConversationForProject" in expr:
                            await ws.send_json({"id": mid, "result": {"result": {"value": True}}})
                        elif "window.location.href" in expr:
                            await ws.send_json({"id": mid, "result": {"result": {"value": "https://127.0.0.1:9225/chat/c/12345678-1234-1234-1234-1234567890ab"}}})
                        else:
                            await ws.send_json({"id": mid, "result": {"result": {"value": True}}})
                    else:
                        await ws.send_json({"id": mid, "result": {}})
        except Exception:
            pass
        return ws

    async def test_r1_synchronized_chat_switching(self):
        """Verify that POST /api/chats/{chat_id}/navigate calls window.__agBridge.navigateToChat"""
        chat_id = "test-chat-uuid-999"
        async with ClientSession() as session:
            async with session.post(f"{self.base_url}/api/chats/{chat_id}/navigate") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data.get("success"))

        # Verify CDP was called with navigateToChat
        called_nav = any("navigateToChat" in expr and chat_id in expr for expr in MockCDPState.evaluated_expressions)
        self.assertTrue(called_nav, f"navigateToChat was not called on CDP. Expressions: {MockCDPState.evaluated_expressions}")

    async def test_r2_project_specific_chat_creation(self):
        """Verify that POST /api/integrity/chats clicks project-specific plus button via CDP"""
        async with ClientSession() as session:
            async with session.post(f"{self.base_url}/api/integrity/chats", json={"project_id": self.test_project_id}) as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data.get("success"))
                self.assertEqual(data.get("convo_id"), "12345678-1234-1234-1234-1234567890ab")

        # Verify startNewConversationForProject with DB name was called
        called_create = any("startNewConversationForProject" in expr and "Mock Test Project Name" in expr for expr in MockCDPState.evaluated_expressions)
        self.assertTrue(called_create, f"startNewConversationForProject was not called with project name. Expressions: {MockCDPState.evaluated_expressions}")

    def test_static_js_verification(self):
        """Verify that dashboard/js/app.js contains the required modifications for R1 and R3"""
        app_js_path = PROJECT_ROOT / "dashboard" / "js" / "app.js"
        self.assertTrue(app_js_path.exists(), "app.js not found")
        content = app_js_path.read_text(encoding="utf-8")

        # Check R1: openChatHistory calls navigate endpoint
        self.assertIn("/navigate", content, "openChatHistory navigation endpoint call is missing in app.js")

        # Check R3: createIntegrityChat calls openChatHistory with data.convo_id
        self.assertIn("openChatHistory(data.convo_id)", content.replace(" ", ""), "createIntegrityChat is missing automatic call to openChatHistory")

if __name__ == "__main__":
    unittest.main()
