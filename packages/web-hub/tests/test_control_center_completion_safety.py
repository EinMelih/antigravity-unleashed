"""Completion safety for Work Orders with tool and background activity."""

import unittest
from unittest.mock import AsyncMock, patch

from src.control_center.agent_adapter import AntiGravityTaskAdapter
from src.integrity_sync import _tool_step_state


class TestControlCenterCompletionSafety(unittest.IsolatedAsyncioTestCase):
    async def test_assistant_reply_does_not_complete_until_tool_and_final_reply(self):
        chat_id = "tool-still-running"
        adapter = AntiGravityTaskAdapter()
        adapter._run_baselines[chat_id] = {"user_idx": 10}
        running_history = {
            "max_idx": 13,
            "history": [
                {
                    "idx": 10,
                    "type": "message",
                    "role": "user",
                    "content": "Implement the Work Order.",
                },
                {
                    "idx": 11,
                    "type": "message",
                    "role": "assistant",
                    "content": "The preview server has started.",
                },
                {
                    "idx": 12,
                    "type": "tool_call",
                    "tool_name": "run_command",
                    "status": 2,
                    "state": "running",
                    "is_running": True,
                    "is_terminal": False,
                    "complete": False,
                    "enriched": {
                        "server_command": True,
                        "background_task": True,
                    },
                },
                {
                    "idx": 13,
                    "type": "message",
                    "role": "assistant",
                    "content": "The site is available for inspection.",
                },
            ],
        }
        terminal_history = {
            "max_idx": 14,
            "history": [
                *running_history["history"][:2],
                {
                    **running_history["history"][2],
                    "status": 6,
                    "state": "cancelled",
                    "is_running": False,
                    "is_terminal": True,
                    "complete": True,
                    "enriched": {
                        "server_command": True,
                        "background_task": False,
                    },
                },
                {
                    "idx": 14,
                    "type": "message",
                    "role": "assistant",
                    "content": "Checks passed and the preview server is stopped.",
                },
            ],
        }
        complete_catalog = [{
            "convo_id": chat_id,
            "status": "complete",
            "archived": False,
            "step_count": 14,
        }]

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                side_effect=[running_history, terminal_history],
            ) as history_reader,
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                side_effect=[complete_catalog, complete_catalog],
            ) as catalog_reader,
            patch(
                "src.control_center.agent_adapter.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await adapter.wait_until_complete(
                chat_id,
                timeout_seconds=10,
            )

        self.assertTrue(result["completed"])
        self.assertEqual(history_reader.call_count, 2)
        self.assertEqual(catalog_reader.call_count, 2)
        self.assertNotIn(chat_id, adapter._run_baselines)

    def test_terminal_tool_still_requires_final_reply_after_tool(self):
        baseline = {"user_idx": 1}
        no_final_reply = {
            "history": [
                {
                    "idx": 1,
                    "type": "message",
                    "role": "user",
                    "content": "Work.",
                },
                {
                    "idx": 2,
                    "type": "message",
                    "role": "assistant",
                    "content": "Starting checks.",
                },
                {
                    "idx": 3,
                    "type": "tool_call",
                    "tool_name": "run_command",
                    "status": 3,
                    "is_terminal": True,
                    "complete": True,
                },
            ],
        }
        self.assertFalse(
            AntiGravityTaskAdapter._history_has_new_assistant_completion(
                no_final_reply,
                baseline,
            )
        )
        no_final_reply["history"].append({
            "idx": 4,
            "type": "message",
            "role": "assistant",
            "content": "All checks are complete.",
        })
        self.assertTrue(
            AntiGravityTaskAdapter._history_has_new_assistant_completion(
                no_final_reply,
                baseline,
            )
        )

    def test_tool_status_mapping_is_precisely_terminal(self):
        self.assertEqual(_tool_step_state(2), "running")
        self.assertEqual(_tool_step_state(3), "complete")
        self.assertEqual(_tool_step_state(6), "cancelled")
        self.assertEqual(_tool_step_state(7), "failed")
        self.assertEqual(_tool_step_state(9), "waiting_user")
        self.assertEqual(_tool_step_state(0), "pending")
        self.assertFalse(
            AntiGravityTaskAdapter._tool_call_is_terminal({
                "status": 2,
                "is_terminal": True,
                "complete": True,
            })
        )
