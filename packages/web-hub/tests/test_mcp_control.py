"""Contract tests for the semantic MCP control service."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from src.hub_control_gateway import HubControlError, HubResult
from src.mcp_control import ControlMode, MCPControlError, MCPControlService


class FakeHubGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[str, dict[str, Any]] = {
            "/health": {
                "status": "ok",
                "antigravity_backend": {"connected": True, "port": 9222},
            },
            "/api/system/overview": {
                "status": "healthy",
                "integrations": {"antigravity": {"connected": True}},
                "services": [
                    {
                        "id": "api_bridge",
                        "status": "healthy",
                        "details": {
                            "ready": True,
                            "cdp_status": "connected",
                            "bridge": "injected",
                        },
                    }
                ],
            },
            "/api/antigravity/instances": {
                "connection": "online",
                "instances": [
                    {"instance_id": "MAIN", "availability": "online"}
                ],
            },
        }
        self.failures: dict[str, HubControlError] = {}

    async def get(
        self,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> HubResult:
        self.calls.append(
            {
                "method": "GET",
                "path": path,
                "path_params": dict(path_params or {}),
                "query": dict(query or {}),
            }
        )
        if path in self.failures:
            raise self.failures[path]
        return HubResult(
            payload=dict(self.responses.get(path, {"ok": True})),
            status=200,
        )

    async def mutate(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str,
    ) -> HubResult:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "path_params": dict(path_params or {}),
                "query": dict(query or {}),
                "body": dict(json_body or {}),
                "idempotency_key": idempotency_key,
            }
        )
        return HubResult(
            payload={"success": True, "conversation_id": "conversation-1"},
            status=200,
            operation_id="operation-1",
        )


class TestMCPControlService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.gateway = FakeHubGateway()

    async def test_default_observe_mode_reads_but_denies_writes(self) -> None:
        service = MCPControlService(self.gateway)

        result = await service.list_conversations(search="demo")
        with self.assertRaises(MCPControlError) as denied:
            await service.send_message(
                conversation_id="conversation-1",
                message="hello",
                idempotency_key="message-1",
            )

        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(denied.exception.code, "mcp_capability_denied")
        self.assertEqual(len(self.gateway.calls), 1)

    async def test_status_requires_all_native_readiness_signals(self) -> None:
        service = MCPControlService(self.gateway)

        ready = await service.status()
        self.gateway.responses["/api/antigravity/instances"] = {
            "connection": "offline",
            "instances": [],
        }
        degraded = await service.status()

        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["native_ready"])
        self.assertEqual(degraded["status"], "degraded")
        self.assertFalse(degraded["native_ready"])

    async def test_status_rejects_non_healthy_system_overview(self) -> None:
        service = MCPControlService(self.gateway)

        for system_status in ("attention", "degraded", "unhealthy"):
            with self.subTest(system_status=system_status):
                self.gateway.responses["/api/system/overview"]["status"] = system_status

                result = await service.status()

                self.assertEqual(result["status"], "degraded")
                self.assertTrue(result["native_ready"])

    async def test_status_requires_injected_api_bridge_proof(self) -> None:
        service = MCPControlService(self.gateway)
        bridge = self.gateway.responses["/api/system/overview"]["services"][0]

        for details in (
            {"ready": False, "cdp_status": "connected", "bridge": "missing"},
            {"ready": True, "cdp_status": "disconnected", "bridge": "injected"},
            {},
        ):
            with self.subTest(details=details):
                bridge["details"] = details

                result = await service.status()

                self.assertEqual(result["status"], "degraded")
                self.assertFalse(result["native_ready"])

    async def test_status_preserves_partial_failure_without_claiming_ready(self) -> None:
        self.gateway.failures["/api/system/overview"] = HubControlError(
            "unavailable",
            status=503,
            code="hub_unavailable",
            retryable=True,
        )
        service = MCPControlService(self.gateway)

        result = await service.status()

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(
            result["parts"]["system"]["error"]["code"],
            "hub_unavailable",
        )

    async def test_operate_message_keeps_idempotency_and_stable_metadata(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        result = await service.send_message(
            conversation_id="conversation/one",
            message="Build the next slice",
            idempotency_key="message:conversation-one:1",
        )

        self.assertEqual(result["control"]["operation_id"], "operation-1")
        self.assertEqual(
            self.gateway.calls[-1],
            {
                "method": "POST",
                "path": "/api/antigravity/chats/{conversation_id}/message",
                "path_params": {"conversation_id": "conversation/one"},
                "query": {},
                "body": {"message": "Build the next slice", "attachments": []},
                "idempotency_key": "message:conversation-one:1",
            },
        )

    async def test_operate_message_forwards_structured_image_attachments(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)
        attachment = {
            "name": "proof.png",
            "type": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        }

        await service.send_message(
            conversation_id="conversation-1",
            message="Inspect this screenshot",
            attachments=[attachment],
            idempotency_key="message-with-image-1",
        )

        self.assertEqual(
            self.gateway.calls[-1]["body"],
            {
                "message": "Inspect this screenshot",
                "attachments": [attachment],
            },
        )

    async def test_create_chat_allows_an_attachment_without_text(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)
        attachment = {
            "name": "diagram.webp",
            "type": "image/webp",
            "data": "data:image/webp;base64,aGVsbG8=",
        }

        await service.create_chat(
            message="",
            attachments=[attachment],
            idempotency_key="create-chat-image-only-1",
        )

        self.assertEqual(
            self.gateway.calls[-1]["body"],
            {
                "message": "",
                "attachments": [attachment],
                "conversation_type": "normal",
            },
        )

    async def test_send_message_allows_an_attachment_without_text(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)
        attachment = {
            "name": "screen.gif",
            "type": "image/gif",
            "data": "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        }

        await service.send_message(
            conversation_id="conversation-1",
            message="",
            attachments=[attachment],
            idempotency_key="send-chat-image-only-1",
        )

        self.assertEqual(
            self.gateway.calls[-1]["body"],
            {"message": "", "attachments": [attachment]},
        )

    async def test_chat_attachments_reject_more_than_five_before_hub(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)
        attachment = {
            "name": "screen.png",
            "type": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        }

        with self.assertRaises(MCPControlError) as caught:
            await service.send_message(
                conversation_id="conversation-1",
                message="Six is one too many",
                attachments=[attachment] * 6,
                idempotency_key="send-chat-too-many-images-1",
            )

        self.assertEqual(caught.exception.code, "too_many_chat_attachments")
        self.assertEqual(self.gateway.calls, [])

    async def test_chat_attachments_reject_file_paths_before_hub(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        with self.assertRaises(MCPControlError) as caught:
            await service.create_chat(
                message="Read this local file",
                attachments=[{"file_path": "C:/private/screenshot.png"}],
                idempotency_key="create-chat-path-attachment-1",
            )

        self.assertEqual(caught.exception.code, "invalid_chat_attachment")
        self.assertEqual(self.gateway.calls, [])

    async def test_mutations_reject_missing_or_unstable_idempotency_keys(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        for key in ("", "contains spaces", "x" * 129):
            with self.subTest(key=key), self.assertRaises(MCPControlError) as caught:
                await service.create_chat(message="hello", idempotency_key=key)
            self.assertEqual(caught.exception.code, "invalid_idempotency_key")

        self.assertEqual(self.gateway.calls, [])

    async def test_set_model_rejects_unknown_provider_source(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        with self.assertRaises(MCPControlError) as caught:
            await service.set_model(
                conversation_id="conversation-1",
                model="Codex",
                source="codex",
                idempotency_key="model-conversation-1",
            )

        self.assertEqual(caught.exception.code, "invalid_model_source")
        self.assertEqual(self.gateway.calls, [])

    async def test_set_model_enforces_custom_provider_identity(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        with self.assertRaises(MCPControlError) as missing:
            await service.set_model(
                conversation_id="conversation-1",
                model="Local model",
                source="custom",
                idempotency_key="model-custom-missing",
            )
        with self.assertRaises(MCPControlError) as invalid:
            await service.set_model(
                conversation_id="conversation-1",
                model="Local model",
                source="custom",
                custom_model_id=0,
                idempotency_key="model-custom-invalid",
            )
        with self.assertRaises(MCPControlError) as native_field:
            await service.set_model(
                conversation_id="conversation-1",
                model="Gemini 3.7 Flash",
                source="native",
                custom_model_id=3,
                idempotency_key="model-native-invalid",
            )

        result = await service.set_model(
            conversation_id="conversation-1",
            model="Local model",
            source="custom",
            custom_model_id=3,
            idempotency_key="model-custom-valid",
        )

        self.assertEqual(missing.exception.code, "custom_model_id_required")
        self.assertEqual(invalid.exception.code, "invalid_custom_model_id")
        self.assertEqual(native_field.exception.code, "custom_model_id_not_allowed")
        self.assertTrue(result["data"]["success"])
        self.assertEqual(
            self.gateway.calls,
            [
                {
                    "method": "POST",
                    "path": "/api/antigravity/active-model",
                    "path_params": {},
                    "query": {},
                    "body": {
                        "convo_id": "conversation-1",
                        "model": "Local model",
                        "source": "custom",
                        "custom_model_id": 3,
                    },
                    "idempotency_key": "model-custom-valid",
                }
            ],
        )

    async def test_set_model_rejects_fields_outside_the_selected_provider(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        cases = (
            (
                {"source": "native", "model_id": "gpt-internal"},
                "model_id_not_allowed",
            ),
            (
                {"source": "native", "reasoning_effort": "high"},
                "reasoning_effort_not_allowed",
            ),
            (
                {
                    "source": "custom",
                    "custom_model_id": 3,
                    "model_id": "configured-server-side",
                },
                "model_id_not_allowed",
            ),
            (
                {
                    "source": "custom",
                    "custom_model_id": 3,
                    "reasoning_effort": "high",
                },
                "reasoning_effort_not_allowed",
            ),
        )
        for extra, error_code in cases:
            with self.subTest(extra=extra), self.assertRaises(
                MCPControlError
            ) as caught:
                await service.set_model(
                    conversation_id="conversation-1",
                    model="Selected model",
                    idempotency_key="model-provider-fields",
                    **extra,
                )
            self.assertEqual(caught.exception.code, error_code)

        self.assertEqual(self.gateway.calls, [])

    async def test_set_model_bounds_optional_provider_metadata(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        with self.assertRaises(MCPControlError) as model_id_error:
            await service.set_model(
                conversation_id="conversation-1",
                model="Selected model",
                idempotency_key="model-id-too-long",
                model_id="m" * 301,
            )
        with self.assertRaises(MCPControlError) as effort_error:
            await service.set_model(
                conversation_id="conversation-1",
                model="Selected model",
                idempotency_key="model-effort-too-long",
                reasoning_effort="e" * 51,
            )

        self.assertEqual(model_id_error.exception.code, "model_id_too_long")
        self.assertEqual(
            effort_error.exception.code,
            "reasoning_effort_too_long",
        )
        self.assertEqual(self.gateway.calls, [])

    async def test_remote_project_creation_requires_explicit_confirmation(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        with self.assertRaises(MCPControlError) as denied:
            await service.create_project(
                name="demo",
                create_github=True,
                idempotency_key="project-demo-1",
            )

        self.assertEqual(
            denied.exception.code,
            "remote_creation_confirmation_required",
        )
        self.assertEqual(self.gateway.calls, [])

    async def test_project_ids_are_strict_positive_sqlite_integers(self) -> None:
        service = MCPControlService(self.gateway)

        for invalid_project_id in (
            True,
            "1",
            1.0,
            0,
            -1,
            9_223_372_036_854_775_808,
        ):
            with self.subTest(project_id=invalid_project_id), self.assertRaises(
                MCPControlError
            ) as caught:
                await service.project_stack(invalid_project_id)  # type: ignore[arg-type]
            self.assertEqual(caught.exception.code, "invalid_project_id")

        result = await service.project_stack(7)

        self.assertTrue(result["data"]["ok"])
        self.assertEqual(
            self.gateway.calls,
            [
                {
                    "method": "GET",
                    "path": "/api/projects/{project_id}/stack",
                    "path_params": {"project_id": 7},
                    "query": {},
                }
            ],
        )

    async def test_numeric_controls_are_strict_at_service_boundary(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        for invalid_custom_model_id in (
            True,
            "3",
            3.0,
            0,
            9_223_372_036_854_775_808,
        ):
            with self.subTest(
                custom_model_id=invalid_custom_model_id
            ), self.assertRaises(MCPControlError) as caught:
                await service.set_model(
                    conversation_id="conversation-1",
                    model="Local model",
                    source="custom",
                    custom_model_id=invalid_custom_model_id,  # type: ignore[arg-type]
                    idempotency_key="strict-custom-model-id",
                )
            self.assertEqual(caught.exception.code, "invalid_custom_model_id")

        for invalid_max_candidates in (True, "12", 12.0, 0, 101):
            with self.subTest(
                max_candidates=invalid_max_candidates
            ), self.assertRaises(MCPControlError) as caught:
                await service.plan_idea(
                    idea_seed_id="idea-1",
                    idempotency_key="strict-max-candidates",
                    max_candidates=invalid_max_candidates,  # type: ignore[arg-type]
                )
            self.assertEqual(caught.exception.code, "invalid_max_candidates")

        self.assertEqual(self.gateway.calls, [])

    async def test_remote_creation_flags_are_strict_booleans(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        cases = (
            ({"create_github": 1}, "invalid_create_github"),
            (
                {"create_github": True, "confirm_remote_creation": "yes"},
                "invalid_confirm_remote_creation",
            ),
        )
        for values, expected_code in cases:
            with self.subTest(values=values), self.assertRaises(
                MCPControlError
            ) as caught:
                await service.create_project(
                    name="strict-flags",
                    idempotency_key="strict-remote-flags",
                    **values,
                )
            self.assertEqual(caught.exception.code, expected_code)

        with self.assertRaises(MCPControlError) as include_archived:
            await service.list_projects(include_archived="false")  # type: ignore[arg-type]
        self.assertEqual(include_archived.exception.code, "invalid_include_archived")
        self.assertEqual(self.gateway.calls, [])

    async def test_operate_mode_routes_campaign_wave_without_approval_payload(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        result = await service.advance_campaign_wave(
            campaign_id="campaign-1",
            idempotency_key="campaign-wave-1",
        )

        self.assertTrue(result["data"]["success"])
        self.assertEqual(
            self.gateway.calls[-1],
            {
                "method": "POST",
                "path": "/api/control-center/campaigns/{campaign_id}/activate-wave",
                "path_params": {"campaign_id": "campaign-1"},
                "query": {},
                "body": {"actor": "mcp-orchestrator"},
                "idempotency_key": "campaign-wave-1",
            },
        )

    async def test_operate_mode_wakes_executor_without_approval_payload(self) -> None:
        service = MCPControlService(self.gateway, mode=ControlMode.OPERATE)

        result = await service.run_executor_once(
            idempotency_key="executor-tick-1",
        )

        self.assertTrue(result["data"]["success"])
        self.assertEqual(
            self.gateway.calls[-1],
            {
                "method": "POST",
                "path": "/api/control-center/executor/tick",
                "path_params": {},
                "query": {},
                "body": {},
                "idempotency_key": "executor-tick-1",
            },
        )

    async def test_administer_mode_is_required_for_irreversible_chat_delete(self) -> None:
        operate = MCPControlService(self.gateway, mode=ControlMode.OPERATE)
        administer = MCPControlService(
            self.gateway,
            mode=ControlMode.ADMINISTER,
        )

        with self.assertRaises(MCPControlError):
            await operate.delete_chat(
                conversation_id="conversation-1",
                idempotency_key="delete-chat-1",
            )
        result = await administer.delete_chat(
            conversation_id="conversation-1",
            idempotency_key="delete-chat-1",
        )

        self.assertTrue(result["data"]["success"])
        self.assertEqual(self.gateway.calls[-1]["method"], "DELETE")

    async def test_capabilities_never_delegate_human_or_raw_access(self) -> None:
        service = MCPControlService(
            self.gateway,
            mode=ControlMode.ADMINISTER,
        )

        capabilities = service.capabilities()

        self.assertFalse(capabilities["human_gates"]["delegated"])
        self.assertIn(
            "github_merge",
            capabilities["human_gates"]["excluded_actions"],
        )
        self.assertIn(
            "planning_question_answer",
            capabilities["human_gates"]["excluded_actions"],
        )
        self.assertIn(
            "direct_manual_work_order_approval",
            capabilities["human_gates"]["excluded_actions"],
        )
        capability_by_name = {
            item["name"]: item for item in capabilities["capabilities"]
        }
        self.assertFalse(
            capability_by_name["advance_campaign_wave"]["requires_desktop"]
        )
        self.assertTrue(
            capability_by_name["run_executor_once"]["requires_desktop"]
        )
        self.assertEqual(
            capabilities["human_gates"]["handoff"],
            {
                "surface": "Hub > Automation > Braucht deine Entscheidung",
                "instruction": (
                    "Open the planning job in the Hub and let a human answer "
                    "the waiting question there."
                ),
            },
        )
        self.assertFalse(hasattr(service, "answer_planning_question"))
        self.assertFalse(any(capabilities["raw_access"].values()))


if __name__ == "__main__":
    unittest.main()
