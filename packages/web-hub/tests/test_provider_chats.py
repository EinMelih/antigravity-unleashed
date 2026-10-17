"""Focused integration tests for Hub-local Codex/custom provider chats."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.database import Database
from src.project_handlers import (
    handle_archive_antigravity_conversation,
    handle_get_active_model,
    handle_get_integrity_chat_history,
    handle_restore_antigravity_conversation,
    handle_set_active_model,
)
from src.provider_chat_handlers import (
    handle_create_provider_chat,
    handle_send_provider_message,
)


class _FakeCodexManager:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"available": True, "authenticated": True}

    def list_models(self):
        return [{
            "id": "gpt-test",
            "model": "gpt-test",
            "display_name": "GPT Test",
            "supported_reasoning_efforts": [{"value": "high"}],
            "default_reasoning_effort": "high",
        }]

    def chat(self, model, prompt, *, thread_id=None, reasoning_effort=None, image_urls=None):
        self.calls.append({
            "model": model,
            "prompt": prompt,
            "thread_id": thread_id,
            "reasoning_effort": reasoning_effort,
            "image_urls": image_urls or [],
        })
        return {
            "thread_id": thread_id or "thread-test",
            "turn_id": f"turn-{len(self.calls)}",
            "content": f"answer-{len(self.calls)}",
            "status": "completed",
            "model": model,
            "reasoning_effort": reasoning_effort,
        }


class TestProviderChats(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="provider_chat_test_")
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.manager = _FakeCodexManager()
        self.patches = [
            patch("src.provider_chat_handlers.db", self.database),
            patch("src.project_handlers.db", self.database),
            patch("src.provider_chat_handlers.get_codex_manager", return_value=self.manager),
        ]
        for item in self.patches:
            item.start()

        app = web.Application()
        app.router.add_post("/provider-chats", handle_create_provider_chat)
        app.router.add_post("/chats/{convo_id}/message", handle_send_provider_message)
        app.router.add_get("/chats/{convo_id}/history", handle_get_integrity_chat_history)
        app.router.add_post("/chats/{convo_id}/archive", handle_archive_antigravity_conversation)
        app.router.add_post("/chats/{convo_id}/restore", handle_restore_antigravity_conversation)
        app.router.add_get("/active-model", handle_get_active_model)
        app.router.add_post("/active-model", handle_set_active_model)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    async def _create(self):
        response = await self.client.post("/provider-chats", json={
            "source": "codex",
            "model_id": "gpt-test",
            "reasoning_effort": "high",
            "message": "hello",
            "attachments": [],
        })
        self.assertEqual(response.status, 201, await response.text())
        return (await response.json())["conversation_id"]

    async def test_create_continue_and_read_history(self):
        conversation_id = await self._create()
        response = await self.client.post(
            f"/chats/{conversation_id}/message",
            json={"message": "continue", "attachments": []},
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.manager.calls[1]["thread_id"], "thread-test")

        history = await self.client.get(f"/chats/{conversation_id}/history")
        payload = await history.json()
        self.assertEqual(
            [(item["role"], item["content"]) for item in payload["history"]],
            [("user", "hello"), ("assistant", "answer-1"), ("user", "continue"), ("assistant", "answer-2")],
        )

    async def test_archive_blocks_writes_and_restore_unlocks(self):
        conversation_id = await self._create()
        archived = await self.client.post(f"/chats/{conversation_id}/archive")
        self.assertEqual(archived.status, 200)
        blocked = await self.client.post(
            f"/chats/{conversation_id}/message",
            json={"message": "blocked", "attachments": []},
        )
        self.assertEqual(blocked.status, 409)
        restored = await self.client.post(f"/chats/{conversation_id}/restore")
        self.assertEqual(restored.status, 200)

    async def test_model_selection_is_conversation_scoped(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"
        response = await self.client.post("/active-model", json={
            "convo_id": conversation_id,
            "source": "codex",
            "model": "Codex · GPT Test",
            "model_id": "gpt-test",
            "reasoning_effort": "high",
        })
        self.assertEqual(response.status, 200, await response.text())
        selected = await response.json()
        self.assertEqual(selected["selection_id"], "codex:gpt-test")
        active = await self.client.get(f"/active-model?convo_id={conversation_id}")
        self.assertEqual((await active.json())["selection_id"], "codex:gpt-test")


if __name__ == "__main__":
    unittest.main()
