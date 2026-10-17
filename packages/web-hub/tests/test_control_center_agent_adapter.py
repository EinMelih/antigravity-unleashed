"""Contracts for strict Anti-Gravity planning output normalization."""

import atexit
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"test_adapter_{os.getpid()}.db"
os.environ["ANTIGRAVITY_HUB_DB"] = str(_TEST_DB_PATH)
atexit.register(lambda: _TEST_DB_PATH.unlink(missing_ok=True))

from src.control_center.agent_adapter import AntiGravityTaskAdapter
from src.control_center.common import ControlCenterError


def history(content):
    return {
        "history": [
            {"type": "message", "role": "user", "content": "plan it"},
            {"type": "message", "role": "assistant", "content": content},
        ]
    }


class RepairManager:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def send_message_to_chat(
        self,
        chat_id,
        prompt,
        *,
        section=None,
        minimize=True,
    ):
        self.calls.append({
            "chat_id": chat_id,
            "prompt": prompt,
            "section": section,
            "minimize": minimize,
        })
        return {
            "chat_id": chat_id,
            "submitted": {"success": True},
            "minimized": True,
        }

    async def close_all(self):
        self.closed = True


class InitialDispatchManager:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def create_new_project_chat_window(
        self,
        workspace_path,
        prompt,
        *,
        minimize=True,
        project_name="",
    ):
        self.calls.append({
            "workspace_path": workspace_path,
            "prompt": prompt,
            "minimize": minimize,
            "project_name": project_name,
        })
        return {
            "chat_id": "new-project-chat",
            "submitted": {"success": True},
            "minimized": True,
        }

    async def close_all(self):
        self.closed = True


class TestControlCenterAgentAdapter(unittest.TestCase):
    def test_fenced_json_is_normalized(self):
        with patch(
            "src.control_center.agent_adapter.get_integrity_chat_history",
            return_value=history('```json\n{"title":"safe plan"}\n```'),
        ):
            result = AntiGravityTaskAdapter.read_planning_result("chat-1")
        self.assertEqual(result["title"], "safe plan")

    def test_direct_object_is_preserved_without_string_coercion(self):
        payload = {"title": "native object", "candidates": []}
        with patch(
            "src.control_center.agent_adapter.get_integrity_chat_history",
            return_value=history(payload),
        ):
            result = AntiGravityTaskAdapter.read_planning_result("chat-2")
        self.assertEqual(result, payload)

    def test_structured_text_blocks_are_supported(self):
        blocks = [
            {"type": "text", "text": '{"title":'},
            {"type": "output_text", "text": '"block plan"}'},
        ]
        with patch(
            "src.control_center.agent_adapter.get_integrity_chat_history",
            return_value=history(blocks),
        ):
            result = AntiGravityTaskAdapter.read_planning_result("chat-3")
        self.assertEqual(result["title"], "block plan")

    def test_non_json_output_is_rejected(self):
        with patch(
            "src.control_center.agent_adapter.get_integrity_chat_history",
            return_value=history("I changed the repository instead."),
        ):
            with self.assertRaises(ControlCenterError) as context:
                AntiGravityTaskAdapter.read_planning_result("chat-4")
        self.assertEqual(context.exception.code, "invalid_planning_output")

    def test_prompt_enforces_read_only_and_candidate_limit(self):
        prompt = AntiGravityTaskAdapter.build_planning_prompt(
            {
                "planning_depth": "exhaustive",
                "max_candidates": 100,
                "activation_policy": "per_candidate",
                "wish": "Map a safe campaign.",
                "constraints": ["No production deployment."],
            },
            {"path": "C:/proof", "name": "Proof"},
        )
        self.assertIn("do not modify any file", prompt)
        self.assertIn("Maximum PR candidates: 100", prompt)
        self.assertIn("Return exactly one JSON object", prompt)
        self.assertIn('"type": "question"', prompt)
        self.assertIn('"type": "plan"', prompt)
        self.assertIn('"resolved_question_ids"', prompt)
        self.assertIn("At least one branch must be grounded", prompt)
        self.assertIn("Every text and list field shown", prompt)

    def test_work_order_prompt_requires_ignore_rules_before_package_install(self):
        prompt = AntiGravityTaskAdapter.build_prompt({
            "worktree_path": "C:/proof/worktree",
            "branch_name": "ag/proof",
            "base_sha": "a" * 40,
            "protected_paths": [],
            "allowed_actions": ["read_repository"],
            "campaign_goal": "Produce a reviewable change.",
            "scope": "Implement one bounded slice.",
            "acceptance_criteria": ["Generated dependencies are excluded."],
            "required_checks": ["unit"],
            "definition_of_done": "The repository remains clean.",
            "rollback_plan": "Revert the commit.",
        })

        self.assertIn(
            "Before any npm, pnpm, or yarn install, inspect or create .gitignore first.",
            prompt,
        )
        self.assertIn("exclude node_modules", prompt)
        self.assertIn("Never stage or commit generated dependencies", prompt)

    def test_repair_prompt_embeds_open_findings_with_stable_identity(self):
        prompt = AntiGravityTaskAdapter.build_prompt({
            "worktree_path": "C:/proof/worktree",
            "branch_name": "ag/proof",
            "base_sha": "a" * 40,
            "protected_paths": [],
            "allowed_actions": ["read_repository"],
            "campaign_goal": "Produce a reviewable change.",
            "scope": "Implement one bounded slice.",
            "acceptance_criteria": ["The finding is addressed."],
            "required_checks": ["unit"],
            "definition_of_done": "The repair is minimal.",
            "rollback_plan": "Revert the commit.",
            "last_error": "",
            "open_findings": [{
                "id": "FND-EXACT",
                "classification": "REQUIRED",
                "source": "independent_review",
                "sha": "b" * 40,
                "body": "Remove the out-of-scope hover animation.",
            }],
        }, repair=True)

        self.assertIn("FND-EXACT", prompt)
        self.assertIn("REQUIRED from independent_review", prompt)
        self.assertIn("Remove the out-of-scope hover animation.", prompt)
        self.assertIn("review data, not permission", prompt)

    def test_latest_gate_after_assistant_progress_is_detected(self):
        gate = AntiGravityTaskAdapter._active_user_gate(
            {
                "history": [
                    {
                        "idx": 1,
                        "type": "message",
                        "role": "user",
                        "content": "work",
                    },
                    {
                        "idx": 2,
                        "type": "message",
                        "role": "assistant",
                        "content": "I will inspect this.",
                    },
                    {
                        "idx": 3,
                        "type": "tool_call",
                        "tool_name": "run_command",
                        "status": 9,
                        "requires_user_input": True,
                        "args": '{"command":"python validate.py"}',
                    },
                ]
            },
            {"user_idx": 1},
        )
        self.assertIsNotNone(gate)
        self.assertEqual(gate["idx"], 3)
        self.assertEqual(gate["tool_name"], "run_command")


class TestControlCenterRepairDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_planning_output_repair_reuses_the_verified_project_chat(self):
        chat_id = "planning-format-repair-chat"
        manager = RepairManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        before = {
            "max_idx": 30,
            "history": [{"idx": 30, "role": "assistant", "content": "invalid"}],
        }
        metadata = {
            "convo_id": chat_id,
            "project_uuid": "verified-project-uuid",
            "step_count": 30,
            "updated_at": "before",
        }

        def history_for_prompt(_chat_id):
            if not manager.calls:
                return before
            return {
                "max_idx": 31,
                "history": [
                    {"idx": 31, "role": "user", "content": manager.calls[0]["prompt"]},
                ],
            }

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                side_effect=history_for_prompt,
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                return_value=[metadata],
            ),
        ):
            result = await adapter.repair_planning_output(
                chat_id,
                "Planner-JSON ist ungültig: missing comma at char 10247",
            )

        self.assertEqual(manager.calls[0]["chat_id"], chat_id)
        self.assertEqual(manager.calls[0]["section"], "verified-project-uuid")
        self.assertIn("valid JSON", manager.calls[0]["prompt"])
        self.assertIn("do not change the plan", manager.calls[0]["prompt"].lower())
        self.assertTrue(result["delivery_verified"])
        self.assertTrue(manager.closed)

    async def test_initial_planning_dispatch_uses_explicit_antigravity_link(self):
        manager = InitialDispatchManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        adapter._remember_initial_delivery = AsyncMock()
        project = {
            "path": "C:/hub/repository",
            "name": "Hub repository",
            "integrity_workspace_path": "C:/antigravity/native-repository",
            "integrity_project_uuid": "native-project-uuid",
            "antigravity_project_name": "Native repository",
        }
        job = {
            "planning_depth": "balanced",
            "max_candidates": 3,
            "activation_policy": "per_candidate",
            "wish": "Plan a verified repository improvement.",
            "constraints": [],
        }

        await adapter.dispatch_planning(job, project)

        self.assertEqual(
            manager.calls[0]["workspace_path"],
            "C:/antigravity/native-repository",
        )
        self.assertEqual(manager.calls[0]["project_name"], "Native repository")
        self.assertIn(
            "Repository: C:/antigravity/native-repository",
            manager.calls[0]["prompt"],
        )
        self.assertNotIn("Repository: C:/hub/repository", manager.calls[0]["prompt"])
        self.assertTrue(manager.closed)

    async def test_initial_planning_dispatch_confirms_an_unregistered_workspace(self):
        manager = InitialDispatchManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        metadata = {
            "project_uuid": "new-native-uuid",
            "workspace_path": "C:/antigravity/native-repository",
            "project_name": "Native repository",
        }
        remember = AsyncMock(return_value=metadata)
        adapter._remember_initial_delivery = remember
        project = {
            "path": "C:/hub/repository",
            "name": "Hub repository",
            "integrity_workspace_path": "C:/antigravity/native-repository",
            "integrity_project_uuid": "",
            "antigravity_project_name": "Native repository",
        }
        job = {
            "planning_depth": "balanced",
            "max_candidates": 3,
            "activation_policy": "per_candidate",
            "wish": "Plan a verified repository improvement.",
            "constraints": [],
        }

        result = await adapter.dispatch_planning(job, project)

        self.assertEqual(manager.calls[0]["workspace_path"], metadata["workspace_path"])
        self.assertEqual(manager.calls[0]["project_name"], "")
        remember.assert_awaited_once_with(
            "new-project-chat",
            manager.calls[0]["prompt"],
            expected_workspace_path=metadata["workspace_path"],
            require_project_uuid=True,
        )
        self.assertEqual(result["project_context"], metadata)
        self.assertTrue(manager.closed)

    async def test_planning_continuation_reuses_verified_chat_and_answer_context(self):
        chat_id = "planning-session-chat"
        manager = RepairManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        before = {
            "max_idx": 20,
            "history": [
                {"idx": 20, "role": "assistant", "content": "question"},
            ],
        }
        metadata = {
            "convo_id": chat_id,
            "project_uuid": "verified-project-uuid",
            "step_count": 20,
            "updated_at": "before",
        }
        job = {
            "continuation": True,
            "antigravity_chat_id": chat_id,
            "planning_depth": "compact",
            "max_candidates": 2,
            "activation_policy": "per_candidate",
            "wish": "Clarify then plan the delivery target.",
            "constraints": [],
            "session_questions": [
                {
                    "id": "Q-1",
                    "branch": "success",
                    "question": "Which outcome defines success?",
                    "answer": "A verified user finishes the flow.",
                    "status": "answered",
                }
            ],
        }

        def history_for_prompt(_chat_id):
            if not manager.calls:
                return before
            prompt = manager.calls[0]["prompt"]
            return {
                "max_idx": 21,
                "history": [
                    {"idx": 21, "role": "user", "content": prompt},
                ],
            }

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                side_effect=history_for_prompt,
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                return_value=[metadata],
            ),
        ):
            result = await adapter.dispatch_planning(
                job,
                {"path": "C:/proof", "name": "Proof"},
            )

        self.assertEqual(manager.calls[0]["chat_id"], chat_id)
        self.assertEqual(manager.calls[0]["section"], "verified-project-uuid")
        self.assertIn("Which outcome defines success?", manager.calls[0]["prompt"])
        self.assertIn("A verified user finishes the flow.", manager.calls[0]["prompt"])
        self.assertTrue(result["reused_chat"])
        self.assertTrue(result["delivery_verified"])
        self.assertEqual(adapter._run_baselines[chat_id]["user_idx"], 21)
        self.assertTrue(manager.closed)

    async def test_initial_dispatch_imports_exact_worktree_without_synthetic_label(self):
        manager = InitialDispatchManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        remember = AsyncMock()
        adapter._remember_initial_delivery = remember
        worktree_path = (
            r"D:\projects\workspace"
            r"\.antigravity-worktrees\cat-search-hub-e2e-20260727"
            r"\task-5089cdf609"
        )

        with patch.object(
            AntiGravityTaskAdapter,
            "build_prompt",
            return_value="approved work order",
        ):
            result = await adapter.dispatch({
                "id": "TASK-5089CDF609",
                "worktree_path": worktree_path,
                "antigravity_chat_id": "",
            })

        self.assertEqual(manager.calls[0]["workspace_path"], worktree_path)
        self.assertEqual(manager.calls[0]["project_name"], "")
        remember.assert_awaited_once_with(
            "new-project-chat",
            "approved work order",
            expected_workspace_path=worktree_path,
        )
        self.assertFalse(result["reused_chat"])
        self.assertTrue(manager.closed)

    async def test_initial_delivery_rejects_wrong_workspace(self):
        adapter = AntiGravityTaskAdapter()
        persisted = {
            "max_idx": 1,
            "history": [
                {
                    "idx": 1,
                    "type": "message",
                    "role": "user",
                    "content": "approved work order",
                },
            ],
        }
        wrong_project = [{
            "convo_id": "new-project-chat",
            "workspace_path": r"D:\other-project",
        }]

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                return_value=persisted,
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                return_value=wrong_project,
            ),
            patch(
                "src.control_center.agent_adapter.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            with self.assertRaises(ControlCenterError) as context:
                await adapter._remember_initial_delivery(
                    "new-project-chat",
                    "approved work order",
                    expected_workspace_path=r"D:\expected-project",
                )

        self.assertEqual(
            context.exception.code,
            "antigravity_project_context_mismatch",
        )
        self.assertNotIn("new-project-chat", adapter._run_baselines)

    async def test_human_gate_pauses_timeout_and_same_waiter_completes(self):
        chat_id = "gate-pauses-timeout"
        adapter = AntiGravityTaskAdapter()
        adapter._run_baselines[chat_id] = {"user_idx": 1}
        gated = {
            "history": [
                {"idx": 1, "type": "message", "role": "user", "content": "work"},
                {
                    "idx": 2,
                    "type": "message",
                    "role": "assistant",
                    "content": "Preparing.",
                },
                {
                    "idx": 3,
                    "type": "tool_call",
                    "tool_name": "run_command",
                    "status": 9,
                    "requires_user_input": True,
                },
            ]
        }
        completed = {
            "history": [
                {"idx": 1, "type": "message", "role": "user", "content": "work"},
                {
                    "idx": 3,
                    "type": "tool_call",
                    "tool_name": "run_command",
                    "status": 7,
                    "requires_user_input": False,
                },
                {
                    "idx": 4,
                    "type": "message",
                    "role": "assistant",
                    "content": "Done.",
                },
            ]
        }
        running = [{"convo_id": chat_id, "status": "running", "archived": False}]
        complete = [{"convo_id": chat_id, "status": "complete", "archived": False}]
        transitions = []

        async def on_state(state, gate):
            transitions.append((state, gate.get("chat_id")))

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                side_effect=[gated, completed],
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                side_effect=[running, complete],
            ),
            patch(
                "src.control_center.agent_adapter.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch(
                "src.control_center.agent_adapter.time",
                Mock(
                    monotonic=Mock(
                        side_effect=[0.0, 0.2, 5.2, 5.3],
                    )
                ),
            ),
        ):
            result = await adapter.wait_until_complete(
                chat_id,
                timeout_seconds=1,
                on_state_change=on_state,
            )

        self.assertTrue(result["completed"])
        self.assertEqual(
            transitions,
            [
                ("waiting_human", chat_id),
                ("running", chat_id),
            ],
        )

    async def test_repair_uses_project_uuid_and_waits_for_new_completion(self):
        prompt = "bounded repair prompt"
        chat_id = "repair-chat"
        manager = RepairManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        before = {
            "max_idx": 10,
            "history": [
                {"idx": 10, "type": "message", "role": "assistant", "content": "old"},
            ],
        }
        persisted = {
            "max_idx": 11,
            "history": [
                {"idx": 11, "type": "message", "role": "user", "content": prompt},
            ],
        }
        completed = {
            "max_idx": 12,
            "history": [
                {"idx": 11, "type": "message", "role": "user", "content": prompt},
                {"idx": 12, "type": "message", "role": "assistant", "content": "fixed"},
            ],
        }
        project_metadata = {
            "convo_id": chat_id,
            "project_uuid": "project-native-uuid",
            "status": "complete",
            "step_count": 10,
            "updated_at": "before",
        }
        running_metadata = {
            **project_metadata,
            "status": "running",
            "step_count": 11,
            "updated_at": "running",
        }
        complete_metadata = {
            **project_metadata,
            "status": "complete",
            "step_count": 12,
            "updated_at": "after",
        }

        with (
            patch.object(
                AntiGravityTaskAdapter,
                "build_prompt",
                return_value=prompt,
            ),
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                side_effect=[before, persisted, completed, completed],
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                side_effect=[
                    [project_metadata],
                    [running_metadata],
                    [complete_metadata],
                ],
            ),
            patch(
                "src.control_center.agent_adapter.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            dispatched = await adapter.dispatch(
                {"antigravity_chat_id": chat_id},
                repair=True,
            )
            result = await adapter.wait_until_complete(
                chat_id,
                timeout_seconds=10,
            )

        self.assertEqual(manager.calls[0]["section"], "project-native-uuid")
        self.assertTrue(dispatched["delivery_verified"])
        self.assertEqual(dispatched["verified_user_idx"], 11)
        self.assertTrue(result["completed"])
        self.assertTrue(manager.closed)

    async def test_old_complete_status_does_not_complete_new_repair(self):
        chat_id = "repair-old-complete"
        adapter = AntiGravityTaskAdapter()
        adapter._run_baselines[chat_id] = {"user_idx": 11}
        old_history = {
            "max_idx": 11,
            "history": [
                {"idx": 11, "type": "message", "role": "user", "content": "repair"},
            ],
        }
        old_complete = [{
            "convo_id": chat_id,
            "status": "complete",
            "step_count": 11,
            "updated_at": "old",
        }]

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                return_value=old_history,
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                return_value=old_complete,
            ),
            patch(
                "src.control_center.agent_adapter.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch(
                "src.control_center.agent_adapter.time",
                Mock(
                    monotonic=Mock(
                        side_effect=[0.0, 46.0, 46.0, 101.0]
                    )
                ),
            ),
        ):
            with self.assertRaises(ControlCenterError) as context:
                await adapter.wait_until_complete(
                    chat_id,
                    timeout_seconds=100,
                )

        self.assertEqual(context.exception.code, "agent_task_timeout")
        self.assertNotIn(chat_id, adapter._run_baselines)

    async def test_new_completion_does_not_wait_for_legacy_grace_window(self):
        chat_id = "repair-fast-complete"
        adapter = AntiGravityTaskAdapter()
        adapter._run_baselines[chat_id] = {"user_idx": 11}
        completed_history = {
            "max_idx": 12,
            "history": [
                {"idx": 11, "type": "message", "role": "user", "content": "repair"},
                {
                    "idx": 12,
                    "type": "message",
                    "role": "assistant",
                    "content": "fixed",
                },
            ],
        }
        complete_metadata = [{
            "convo_id": chat_id,
            "status": "complete",
            "step_count": 12,
            "updated_at": "new",
        }]

        with (
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                return_value=completed_history,
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                return_value=complete_metadata,
            ),
        ):
            result = await adapter.wait_until_complete(
                chat_id,
                timeout_seconds=10,
            )

        self.assertTrue(result["completed"])
        self.assertNotIn(chat_id, adapter._run_baselines)

    async def test_repair_rejects_unpersisted_user_prompt(self):
        prompt = "repair that never persisted"
        chat_id = "repair-missing-delivery"
        manager = RepairManager()
        adapter = AntiGravityTaskAdapter(manager_factory=lambda: manager)
        unchanged = {
            "max_idx": 10,
            "history": [
                {"idx": 10, "type": "message", "role": "assistant", "content": "old"},
            ],
        }
        metadata = [{
            "convo_id": chat_id,
            "project_uuid": "project-native-uuid",
            "status": "complete",
        }]

        with (
            patch.object(
                AntiGravityTaskAdapter,
                "build_prompt",
                return_value=prompt,
            ),
            patch(
                "src.control_center.agent_adapter.get_integrity_chat_history",
                return_value=unchanged,
            ),
            patch(
                "src.control_center.agent_adapter.scan_antigravity_conversation_catalog",
                return_value=metadata,
            ),
            patch(
                "src.control_center.agent_adapter.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            with self.assertRaises(ControlCenterError) as context:
                await adapter.dispatch(
                    {"antigravity_chat_id": chat_id},
                    repair=True,
                )

        self.assertEqual(
            context.exception.code,
            "antigravity_delivery_unverified",
        )
        self.assertEqual(manager.calls[0]["section"], "project-native-uuid")
        self.assertTrue(manager.closed)


if __name__ == "__main__":
    unittest.main()
