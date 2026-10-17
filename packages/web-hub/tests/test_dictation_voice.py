import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import src.voice_handlers as voice_handlers
import src.parallel_cdp as parallel_cdp
from src.parallel_cdp import ParallelCDPManager
from src.proxy_server import create_app
from src.voice_handlers import (
    handle_dictation_start,
    handle_dictation_status,
    handle_dictation_stop,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeDictationCDP:
    def __init__(self):
        self.calls = []
        self.live_text = ""

    async def inject_bridge(self):
        self.calls.append("inject")

    async def evaluate(self, expression, timeout=0):
        self.calls.append(expression)
        if "startVoiceRecording" in expression:
            self.live_text = "Vorhandener Text"
            return True
        if "stopVoiceRecording" in expression:
            self.live_text = "Vorhandener Text plus Diktat"
            return True
        if "getVoiceState" in expression:
            return {"isRecording": True, "text": self.live_text}
        if "clearVoiceDraft" in expression:
            return True
        return None


class FakeDictationManager:
    instances = []

    def __init__(self):
        self.cdp = FakeDictationCDP()
        self.states = []
        self.closed = False
        self.__class__.instances.append(self)

    async def ensure_dictation_window(self):
        return {
            "id": "dictation-target",
            "webSocketDebuggerUrl": "ws://dictation",
            "window_id": "AG-DIKTAT",
            "purpose": "dictation",
            "created": True,
        }

    async def get_client_for_target(self, _ws_url):
        return self.cdp

    def set_dictation_state(
        self,
        target_id,
        state_name,
        detail,
        *,
        reserved,
        error="",
    ):
        state = {
            "target_id": target_id,
            "state": state_name,
            "detail": detail,
            "reserved": reserved,
            "error": error,
        }
        self.states.append(state)
        return state

    async def close_dictation_window(self):
        self.closed = True
        return True

    async def disconnect_all(self):
        return None


class TestDictationVoiceAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeDictationManager.instances = []
        voice_handlers._global_cdp = None
        voice_handlers._last_known_text = ""
        voice_handlers._is_recording = False
        voice_handlers._start_time = 0.0
        voice_handlers._proxy_shutting_down = False
        voice_handlers._active_voice_mode = ""
        voice_handlers._dictation_manager = None
        voice_handlers._dictation_cdp = None
        voice_handlers._dictation_target = None

        app = web.Application()
        app.router.add_post("/api/voice/dictation/start", handle_dictation_start)
        app.router.add_get("/api/voice/dictation/status", handle_dictation_status)
        app.router.add_post("/api/voice/dictation/stop", handle_dictation_stop)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        self.manager_patch = patch(
            "src.voice_handlers.ParallelCDPManager",
            FakeDictationManager,
        )
        self.network_patch = patch(
            "src.voice_handlers.is_network_online",
            new=AsyncMock(return_value=True),
        )
        self.auth_patch = patch(
            "src.voice_handlers.check_auth",
            return_value=True,
        )
        self.manager_patch.start()
        self.network_patch.start()
        self.auth_patch.start()
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.auth_patch.stop()
        self.network_patch.stop()
        self.manager_patch.stop()
        voice_handlers._is_recording = False
        voice_handlers._active_voice_mode = ""
        voice_handlers._dictation_manager = None
        voice_handlers._dictation_cdp = None
        voice_handlers._dictation_target = None

    async def test_start_status_and_stop_use_one_reserved_window(self):
        response = await self.client.post(
            "/api/voice/dictation/start",
            json={
                "text": "Vorhandener Text",
                "field_label": "Campaign · Ziel",
            },
        )
        self.assertEqual(response.status, 200)
        started = await response.json()
        self.assertTrue(started["isRecording"])
        self.assertEqual(started["window"]["window_id"], "AG-DIKTAT")
        self.assertEqual(started["window"]["purpose"], "dictation")
        self.assertEqual(len(FakeDictationManager.instances), 1)

        manager = FakeDictationManager.instances[0]
        manager.cdp.live_text = "Vorhandener Text plus"
        response = await self.client.get("/api/voice/dictation/status")
        self.assertEqual(response.status, 200)
        live = await response.json()
        self.assertTrue(live["isRecording"])
        self.assertEqual(live["text"], "Vorhandener Text plus")

        response = await self.client.post("/api/voice/dictation/stop")
        self.assertEqual(response.status, 200)
        stopped = await response.json()
        self.assertFalse(stopped["isRecording"])
        self.assertEqual(stopped["text"], "Vorhandener Text plus Diktat")
        self.assertIn(
            "window.__agBridge.clearVoiceDraft()",
            manager.cdp.calls,
        )
        self.assertEqual(manager.states[-1]["state"], "dictation_ready")
        self.assertFalse(manager.states[-1]["reserved"])

    async def test_second_start_is_rejected_without_second_window(self):
        first = await self.client.post(
            "/api/voice/dictation/start",
            json={"text": "", "field_label": "Recommendation · Titel"},
        )
        self.assertEqual(first.status, 200)

        second = await self.client.post(
            "/api/voice/dictation/start",
            json={"text": "", "field_label": "Campaign · Ziel"},
        )
        self.assertEqual(second.status, 409)
        payload = await second.json()
        self.assertEqual(payload["mode"], "dictation")
        self.assertEqual(len(FakeDictationManager.instances), 1)

    async def test_payload_types_and_lengths_are_validated(self):
        response = await self.client.post(
            "/api/voice/dictation/start",
            json={"text": {"not": "text"}, "field_label": "Titel"},
        )
        self.assertEqual(response.status, 400)


class TestDictationVoiceAssets(unittest.TestCase):
    def test_routes_are_registered(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/voice/dictation/start", paths)
        self.assertIn("/api/voice/dictation/status", paths)
        self.assertIn("/api/voice/dictation/stop", paths)

    def test_control_center_fields_share_the_dictation_controller(self):
        html = (PROJECT_ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        script = (
            PROJECT_ROOT / "dashboard" / "js" / "control-center.js"
        ).read_text(encoding="utf-8")
        style = (
            PROJECT_ROOT / "dashboard" / "css" / "control-center.css"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(html.count("data-cc-dictation-label="), 10)
        self.assertIn("/api/voice/dictation/start", script)
        self.assertIn("finishControlDictationForForm", script)
        self.assertIn("stopControlDictationForModal", script)
        self.assertIn(".cc-dictation-button.is-recording", style)

    def test_all_hub_microphones_use_the_reserved_dictation_api(self):
        script = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"/api/voice/start"', script)
        self.assertNotIn('"/api/voice/status"', script)
        self.assertNotIn('"/api/voice/stop"', script)
        self.assertIn('"/api/voice/dictation/start"', script)
        self.assertIn("Nativer Diktatdienst", script)
        self.assertGreaterEqual(
            script.count("const data = await response.json();"),
            2,
        )
        self.assertGreaterEqual(
            script.count('typeof data.text === "string"'),
            2,
        )


class FakeWindowCDP:
    def __init__(self):
        self.expressions = []

    async def inject_bridge(self):
        return None

    async def evaluate(self, expression, timeout=0):
        self.expressions.append(expression)
        if "getComposerState" in expression:
            return {"ready": True}
        if "clearVoiceDraft" in expression:
            return True
        return None


class TestDictationWindowIsolation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parallel_cdp._CHAT_TARGET_IDS.clear()
        parallel_cdp._DUPLICATE_TARGET_IDS.clear()
        parallel_cdp._WINDOW_STAMPS.clear()
        parallel_cdp._WORKER_STATES.clear()
        parallel_cdp._CHAT_LOCKS.clear()
        parallel_cdp._TARGET_LOCKS.clear()
        parallel_cdp._WINDOW_LOCK = None
        parallel_cdp._DICTATION_TARGET_ID = None

    async def test_chat_allocator_never_reuses_dictation_window(self):
        manager = ParallelCDPManager()
        dictation = {
            "id": "dictation-target",
            "runtime": {"has_draft": False, "purpose": "dictation"},
        }
        chat_worker = {
            "id": "chat-target",
            "runtime": {
                "activity_observed": True,
                "has_draft": False,
                "native_activity": "idle",
                "purpose": "chat",
                "runtime_reachable": True,
            },
        }
        parallel_cdp._worker_state("dictation-target")["purpose"] = "dictation"
        parallel_cdp._worker_state("chat-target")["purpose"] = "chat"
        manager.get_devtools_port = AsyncMock(return_value=9222)
        manager._discover_window_pool = AsyncMock(
            return_value=([dictation, chat_worker], None)
        )

        allocated = await manager._allocate_worker_target("conversation-id")

        self.assertEqual(allocated["id"], "chat-target")
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS["conversation-id"],
            "chat-target",
        )

    async def test_existing_dictation_window_is_reused(self):
        manager = ParallelCDPManager()
        target = {
            "id": "dictation-target",
            "webSocketDebuggerUrl": "ws://dictation",
            "runtime": {
                "chat_id": None,
                "composer_visible": True,
                "purpose": "dictation",
            },
        }
        parallel_cdp._worker_state("dictation-target")["purpose"] = "dictation"
        parallel_cdp._DICTATION_TARGET_ID = "dictation-target"
        client = FakeWindowCDP()
        manager.get_devtools_port = AsyncMock(return_value=9222)
        manager._discover_window_pool = AsyncMock(return_value=([target], None))
        manager.open_duplicate_window = AsyncMock()
        manager.apply_window_stamp = AsyncMock(return_value="AG-DIKTAT")
        manager.prepare_target_for_automation = AsyncMock(
            return_value={"success": True}
        )
        manager.get_client_for_target = AsyncMock(return_value=client)
        manager._inspect_target_runtime = AsyncMock(
            return_value={
                "chat_id": None,
                "composer_visible": True,
                "purpose": "dictation",
            }
        )

        result = await manager.ensure_dictation_window()

        self.assertEqual(result["id"], "dictation-target")
        self.assertEqual(result["window_id"], "AG-DIKTAT")
        self.assertEqual(result["purpose"], "dictation")
        self.assertFalse(result["created"])
        manager.open_duplicate_window.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
