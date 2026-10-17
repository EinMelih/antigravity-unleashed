"""Parallel API delivery must stay in its verified profile and report failures."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.api_handlers import send_parallel_handler


class Request(dict):
    def __init__(self, body):
        super().__init__()
        self.body = body
        self.app = {}

    async def json(self):
        return self.body


class ParallelApiIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clients = [
            SimpleNamespace(
                inject_bridge=AsyncMock(),
                get_active_conversation_id=AsyncMock(return_value=f"api-chat-{index}"),
                navigate_to_chat=AsyncMock(return_value={"success": True}),
                select_verified_model=AsyncMock(),
                evaluate=AsyncMock(return_value={"success": True}),
                send_chat=AsyncMock(return_value={"response": f"answer-{index}"}),
                last_model_selection={"id": "native-high", "native_name": "Native High", "reasoning_effort": "high"},
            )
            for index in range(2)
        ]
        self.manager = SimpleNamespace(
            profile_runtime=SimpleNamespace(validate_conversation=Mock()),
            get_client_for_target=AsyncMock(side_effect=self.clients),
            close_all=AsyncMock(),
        )
        self.targets = [{"webSocketDebuggerUrl": f"ws://127.0.0.1:9229/devtools/page/{index}"} for index in range(2)]
        self.factory = self.enterContext(patch("src.parallel_cdp.ParallelCDPManager", return_value=self.manager))
        self.tile = self.enterContext(patch("src.window_tiling.ensure_and_tile_windows", new=AsyncMock(return_value=self.targets)))
        self.private_monitor = self.enterContext(patch("src.log_monitor.monitor_subagent_transcript", new=AsyncMock(return_value={"response": "legacy-private-result"})))
        self.enterContext(patch("src.api_helpers.config", SimpleNamespace(debug_mode=True)))

    async def test_uses_scoped_delivery_and_starts_new_chats(self):
        request = Request({"requests": [{"prompt": "first", "model": "native-high", "reasoning_effort": "high"}, {"prompt": "second"}]})
        response = await send_parallel_handler(request)
        payload = json.loads(response.text)
        self.assertEqual(200, response.status)
        self.assertEqual("success", payload["status"])
        self.assertEqual(["answer-0", "answer-1"], [row["response"] for row in payload["responses"]])
        self.factory.assert_called_once_with(profile="api")
        self.clients[0].send_chat.assert_awaited_once_with("first", model="native-high", reasoning_effort="high", new_chat=True, timeout=300, req_id=response.headers["X-Request-Id"])
        self.private_monitor.assert_not_awaited()
        self.manager.close_all.assert_awaited_once()

    async def test_missing_targets_does_not_silently_drop_work(self):
        self.tile.return_value = self.targets[:1]
        response = await send_parallel_handler(Request({"requests": [{"prompt": "first"}, {"prompt": "second"}]}))
        self.assertEqual(503, response.status)
        self.assertIn("error", json.loads(response.text))
        self.manager.get_client_for_target.assert_not_awaited()
        self.manager.close_all.assert_awaited_once()

    async def test_partial_failure_is_visible_to_caller_and_monitor(self):
        self.clients[1].send_chat.return_value = {"error": "native response timeout"}
        request = Request({"requests": [{"prompt": "first"}, {"prompt": "second"}]})
        response = await send_parallel_handler(request)
        payload = json.loads(response.text)
        self.assertEqual("partial_error", payload["status"])
        self.assertEqual("native response timeout", payload["responses"][1]["error"]["message"])
        self.assertTrue(request["operation_error"])
        self.manager.close_all.assert_awaited_once()

    async def test_existing_conversation_must_belong_to_api_profile(self):
        self.manager.profile_runtime.validate_conversation.side_effect = ValueError("Private conversation rejected")
        request = Request({"requests": [{"prompt": "first", "conversation_id": "private-chat"}]})
        response = await send_parallel_handler(request)
        payload = json.loads(response.text)
        self.assertEqual("error", payload["status"])
        self.assertEqual("invalid_request_error", payload["responses"][0]["error"]["type"])
        self.clients[0].send_chat.assert_not_awaited()
        self.clients[0].navigate_to_chat.assert_not_awaited()

    async def test_invalid_body_rejected_before_opening_windows(self):
        for body in ([], {"requests": [None]}, {"requests": [{"prompt": ""}]}, {"requests": [{"prompt": "first", "reasoning_effort": "extreme"}]}):
            with self.subTest(body=body):
                response = await send_parallel_handler(Request(body))
                self.assertEqual(400, response.status)
        self.factory.assert_not_called()

    async def test_owned_conversation_is_navigated_without_new_chat(self):
        self.clients[0].get_active_conversation_id.side_effect = ["api-chat-0", "owned-api-chat", "owned-api-chat"]
        response = await send_parallel_handler(Request({"requests": [{"prompt": "continue", "conversation_id": "owned-api-chat"}]}))
        self.assertEqual("success", json.loads(response.text)["status"])
        self.manager.profile_runtime.validate_conversation.assert_called_once_with("owned-api-chat")
        self.clients[0].navigate_to_chat.assert_awaited_once_with("owned-api-chat")
        self.assertFalse(self.clients[0].send_chat.await_args.kwargs["new_chat"])


if __name__ == "__main__":
    unittest.main()
