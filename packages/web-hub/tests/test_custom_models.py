"""Tests for secure Hub-managed OpenAI-compatible models."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.custom_model_handlers import (
    handle_create_proxy_chat,
    handle_delete_custom_model,
    handle_list_custom_models,
    handle_save_custom_model,
    handle_send_proxy_message,
    handle_test_custom_model,
)
from src.custom_model_proxy import (
    CustomModelError,
    normalize_base_url,
    protect_extra_headers,
    protect_secret,
    public_provider,
    unprotect_extra_headers,
    unprotect_secret,
    validate_extra_headers,
    validate_provider_payload,
)
from src.database import Database
from src.project_handlers import (
    handle_delete_integrity_chat,
    handle_get_active_model,
    handle_get_integrity_chat_history,
    handle_get_integrity_models,
    handle_set_active_model,
)
from src.proxy_server import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _OpenAIHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        return

    def _json(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        type(self).requests.append(("GET", self.path, dict(self.headers), None))
        if self.path == "/v1/models":
            self._json(200, {"data": [{"id": "mock-model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(("POST", self.path, dict(self.headers), body))
        if self.path == "/v1/chat/completions":
            self._json(200, {
                "id": "mock-response",
                "choices": [{"message": {"role": "assistant", "content": "Mock-Antwort"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            })
        else:
            self._json(404, {"error": "not found"})


class TestCustomModelValidation(unittest.TestCase):
    def test_dpapi_roundtrip(self):
        protected = protect_secret("top-secret")
        self.assertNotIn(b"top-secret", protected)
        self.assertEqual(unprotect_secret(protected), "top-secret")

    def test_provider_validation_blocks_unsafe_values(self):
        with self.assertRaises(CustomModelError):
            validate_provider_payload({"name": "x", "model_id": "m", "base_url": "file:///tmp/model"})
        with self.assertRaises(CustomModelError):
            validate_provider_payload({"name": "x", "model_id": "m", "base_url": "https://user:pass@example.test/v1"})
        with self.assertRaises(CustomModelError):
            validate_extra_headers({"Host": "attacker.test"})
        with self.assertRaises(CustomModelError):
            validate_extra_headers({"X-Test": "value\r\nInjected: yes"})
        with self.assertRaises(CustomModelError):
            normalize_base_url("http://provider.example.test/v1")
        self.assertEqual(normalize_base_url("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")
        with self.assertRaises(CustomModelError):
            validate_provider_payload({
                "name": "x",
                "model_id": "m",
                "base_url": "https://provider.example.test/v1",
                "verify_tls": False,
            })

    def test_extra_header_values_are_encrypted_and_redacted(self):
        protected = protect_extra_headers({"X-Custom-Secret": "hidden-value"})
        self.assertNotIn("hidden-value", json.dumps(protected))
        self.assertEqual(unprotect_extra_headers(protected), {"X-Custom-Secret": "hidden-value"})
        public = public_provider({
            "id": 1,
            "name": "Secure",
            "base_url": "https://provider.example.test/v1",
            "model_id": "model",
            "extra_headers": json.dumps(protected),
        })
        self.assertEqual(public["extra_headers"], {"X-Custom-Secret": None})

    def test_create_app_registers_custom_model_routes(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/antigravity/custom-models", paths)
        self.assertIn("/api/antigravity/proxy-chats", paths)
        self.assertIn("/api/antigravity/chats/{convo_id}/proxy-message", paths)
        self.assertIn("/api/integrity/custom-models", paths)
        self.assertIn("/api/integrity/proxy-chats", paths)
        self.assertIn("/api/integrity/chats/{convo_id}/proxy-message", paths)

    def test_dashboard_exposes_custom_model_manager_and_proxy_transport(self):
        html = (PROJECT_ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        stylesheet = (PROJECT_ROOT / "dashboard" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn('id="custom-model-modal"', html)
        self.assertIn("js/app.js?v=20260824-16", html)
        self.assertIn("openCustomModelManager", javascript)
        self.assertIn("/api/antigravity/proxy-chats", javascript)
        self.assertNotIn("/api/integrity/", javascript)
        self.assertIn("/proxy-message", javascript)
        self.assertIn("custom-model-layout", stylesheet)


class TestCustomModelAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="antigravity_proxy_test_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.database = Database(self.db_path)
        self.project_id = self.database.add_project("Proxy Test Project", self.temp_dir.name)

        _OpenAIHandler.requests = []
        self.provider_server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIHandler)
        self.provider_thread = threading.Thread(target=self.provider_server.serve_forever, daemon=True)
        self.provider_thread.start()
        self.provider_url = f"http://127.0.0.1:{self.provider_server.server_port}/v1"

        self.db_patches = [
            patch("src.custom_model_handlers.db", self.database),
            patch("src.project_handlers.db", self.database),
        ]
        for db_patch in self.db_patches:
            db_patch.start()

        app = web.Application()
        app.router.add_get("/api/integrity/custom-models", handle_list_custom_models)
        app.router.add_post("/api/integrity/custom-models", handle_save_custom_model)
        app.router.add_delete("/api/integrity/custom-models/{custom_model_id}", handle_delete_custom_model)
        app.router.add_post("/api/integrity/custom-models/{custom_model_id}/test", handle_test_custom_model)
        app.router.add_post("/api/integrity/proxy-chats", handle_create_proxy_chat)
        app.router.add_post("/api/integrity/chats/{convo_id}/proxy-message", handle_send_proxy_message)
        app.router.add_get("/api/integrity/chats/{convo_id}/history", handle_get_integrity_chat_history)
        app.router.add_delete("/api/integrity/chats/{convo_id}", handle_delete_integrity_chat)
        app.router.add_get("/api/integrity/models", handle_get_integrity_models)
        app.router.add_get("/api/integrity/active-model", handle_get_active_model)
        app.router.add_post("/api/integrity/active-model", handle_set_active_model)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for db_patch in reversed(self.db_patches):
            db_patch.stop()
        self.provider_server.shutdown()
        self.provider_server.server_close()
        self.provider_thread.join(timeout=2)
        self.temp_dir.cleanup()

    async def _create_model(self):
        response = await self.client.post("/api/integrity/custom-models", json={
            "name": "Local Mock",
            "base_url": self.provider_url,
            "model_id": "mock-model",
            "api_key": "test-api-key",
            "extra_headers": {"X-Hub-Test": "yes"},
            "system_prompt": "Reply briefly.",
            "temperature": 0.2,
        })
        self.assertEqual(response.status, 201, await response.text())
        return (await response.json())["model"]

    async def test_model_catalog_uses_live_native_models(self):
        class FakeModelManager:
            async def read_native_models_from_primary(self):
                return {
                    "current": "Gemini 3.6 Flash (High)",
                    "models": [{
                        "label": "Gemini 3.6 Flash (High)",
                        "badge": "Fast",
                    }],
                }

            async def disconnect_all(self):
                return None

        from src import project_handlers

        project_handlers._NATIVE_MODEL_CACHE.update({
            "models": [],
            "current": "",
            "source": "",
            "updated_at": 0.0,
        })
        with patch(
            "src.parallel_cdp.ParallelCDPManager",
            FakeModelManager,
        ):
            response = await self.client.get("/api/integrity/models")

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload["source"], "native_combobox")
        self.assertEqual(payload["current"], "Gemini 3.6 Flash (High)")
        self.assertEqual(payload["models"][0]["label"], "Gemini 3.6 Flash (High)")
        self.assertNotIn("Gemini 3.5 Flash (Medium)", {
            model["label"] for model in payload["models"]
        })

    async def test_native_model_switch_is_confirmed_and_persisted_per_chat(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"

        class FakeModelManager:
            async def select_model_for_chat(
                self,
                chat_id,
                model_name,
                *,
                section=None,
                minimize=True,
            ):
                self.selection = (chat_id, model_name, section, minimize)
                return {
                    "target_id": "target-7",
                    "window_id": "AG-07",
                    "chat_id": chat_id,
                    "model": model_name,
                    "confirmed": True,
                    "ready": True,
                    "minimized": True,
                }

            async def close_all(self):
                return None

        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                FakeModelManager,
            ),
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=[{
                    "convo_id": conversation_id,
                    "project_uuid": "project-section",
                }],
            ),
        ):
            response = await self.client.post(
                "/api/integrity/active-model",
                json={
                    "convo_id": conversation_id,
                    "model": "Claude Sonnet 4.6 (Thinking)",
                    "source": "official",
                },
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["confirmed"])
        self.assertEqual(payload["method"], "dedicated_cdp")
        self.assertEqual(payload["window"]["window_id"], "AG-07")

        active_response = await self.client.get(
            f"/api/integrity/active-model?convo_id={conversation_id}"
        )
        active = await active_response.json()
        self.assertEqual(active["model"], "Claude Sonnet 4.6 (Thinking)")
        self.assertEqual(active["source"], "native_preference")
        self.assertEqual(active["window_id"], "AG-07")
        self.assertTrue(active["confirmed"])

    async def test_proxy_message_rejects_archived_native_conversation(self):
        conversation_id = "22222222-2222-4222-8222-222222222222"

        with patch(
            "src.integrity_sync.scan_antigravity_conversation_catalog",
            return_value=[{
                "convo_id": conversation_id,
                "archived": True,
            }],
        ):
            response = await self.client.post(
                f"/api/integrity/chats/{conversation_id}/proxy-message",
                json={"message": "Must stay blocked", "custom_model_id": 1},
            )

        self.assertEqual(response.status, 409, await response.text())
        payload = await response.json()
        self.assertEqual(payload["code"], "conversation_archived")
        self.assertTrue(payload["requires_restore"])
        self.assertEqual(payload["conversation_id"], conversation_id)

    async def test_custom_model_full_flow(self):
        model = await self._create_model()
        self.assertTrue(model["has_api_key"])
        self.assertNotIn("api_key", model)
        self.assertNotIn("api_key_protected", model)
        self.assertEqual(model["extra_headers"], {"X-Hub-Test": None})
        stored_model = self.database.get_custom_model(model["id"])
        self.assertNotIn("yes", stored_model["extra_headers"])

        update_response = await self.client.post("/api/integrity/custom-models", json={
            **model,
            "api_key": "",
        })
        self.assertEqual(update_response.status, 200, await update_response.text())
        self.assertEqual((await update_response.json())["model"]["extra_headers"], {"X-Hub-Test": None})

        list_response = await self.client.get("/api/integrity/custom-models")
        list_text = await list_response.text()
        self.assertNotIn("test-api-key", list_text)
        self.assertEqual((json.loads(list_text)["models"])[0]["name"], "Local Mock")

        test_response = await self.client.post(f"/api/integrity/custom-models/{model['id']}/test")
        self.assertEqual(test_response.status, 200, await test_response.text())
        self.assertEqual((await test_response.json())["model_count"], 1)

        create_response = await self.client.post("/api/integrity/proxy-chats", json={
            "project_id": self.project_id,
            "custom_model_id": model["id"],
            "message": "Hallo Proxy",
            "attachments": [{
                "name": "pixel.png",
                "type": "image/png",
                "data": "data:image/png;base64,iVBORw0KGgo=",
            }],
        })
        self.assertEqual(create_response.status, 201, await create_response.text())
        created = await create_response.json()
        self.assertTrue(created["verified"])
        conversation_id = created["convo_id"]
        self.assertTrue(conversation_id.startswith("proxy-"))
        self.assertEqual(created["assistant"]["content"], "Mock-Antwort")

        post_requests = [entry for entry in _OpenAIHandler.requests if entry[0] == "POST"]
        self.assertEqual(post_requests[-1][2]["Authorization"], "Bearer test-api-key")
        self.assertEqual(post_requests[-1][2]["X-Hub-Test"], "yes")
        user_content = post_requests[-1][3]["messages"][-1]["content"]
        self.assertTrue(any(part.get("type") == "image_url" for part in user_content))

        send_response = await self.client.post(
            f"/api/integrity/chats/{conversation_id}/proxy-message",
            json={"message": "Noch eine Frage", "custom_model_id": model["id"]},
        )
        self.assertEqual(send_response.status, 200, await send_response.text())

        history_response = await self.client.get(f"/api/integrity/chats/{conversation_id}/history")
        history = (await history_response.json())["history"]
        self.assertEqual([entry["role"] for entry in history], ["user", "assistant", "user", "assistant"])
        self.assertTrue(all(entry["source"] == "custom" for entry in history))

        active_response = await self.client.get(f"/api/integrity/active-model?convo_id={conversation_id}")
        active = await active_response.json()
        self.assertEqual(active["source"], "custom")
        self.assertEqual(active["custom_model_id"], model["id"])

        models_response = await self.client.get("/api/integrity/models")
        models = (await models_response.json())["models"]
        self.assertTrue(any(item.get("source") == "custom" and item["label"] == "Local Mock" for item in models))

        protected_delete = await self.client.delete(f"/api/integrity/custom-models/{model['id']}")
        self.assertEqual(protected_delete.status, 409)
        chat_delete = await self.client.delete(f"/api/integrity/chats/{conversation_id}")
        self.assertEqual(chat_delete.status, 200)
        model_delete = await self.client.delete(f"/api/integrity/custom-models/{model['id']}")
        self.assertEqual(model_delete.status, 200, await model_delete.text())


if __name__ == "__main__":
    unittest.main()
