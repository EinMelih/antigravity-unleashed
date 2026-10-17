"""Official SDK contract smoke tests for the optional MCP adapter."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from unittest import mock


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAFE_MCP_ENV = {
    "ANTIGRAVITY_HUB_TOKEN": "",
    "ANTIGRAVITY_HUB_URL": "http://127.0.0.1:8000",
    "ANTIGRAVITY_MCP_ALLOW_REMOTE": "false",
    "ANTIGRAVITY_MCP_MODE": "observe",
    "ANTIGRAVITY_MCP_TIMEOUT_SECONDS": "5",
}


def _safe_process_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ANTIGRAVITY_")
    }
    environment.update(SAFE_MCP_ENV)
    return environment


@contextmanager
def _isolated_mcp_server() -> Iterator[Any]:
    module_name = "_antigravity_mcp_protocol_test_server"
    module_path = PROJECT_ROOT / "src" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the MCP server test module.")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.pop(module_name, None)
    safe_environment = _safe_process_environment()
    try:
        sys.modules[module_name] = module
        with mock.patch.dict(
            os.environ,
            safe_environment,
            clear=True,
        ):
            spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous


class NoNetworkGateway:
    async def get(
        self,
        _path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> Any:
        raise AssertionError("MCP protocol contract tests must not access a live Hub.")

    async def mutate(
        self,
        _method: str,
        _path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str,
    ) -> Any:
        raise AssertionError("MCP protocol contract tests must not access a live Hub.")


@unittest.skipUnless(MCP_AVAILABLE, "optional mcp runtime is not installed")
class TestMCPProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_subprocess_lists_the_same_public_contract(self) -> None:
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_server"],
            cwd=PROJECT_ROOT,
            env=_safe_process_environment(),
        )

        async with Client(parameters) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            protocol_version = client.protocol_version

        self.assertEqual(protocol_version, "2026-07-28")
        self.assertEqual(len(tools.tools), 36)
        self.assertEqual(len(resources.resources), 2)

    async def test_tools_resources_and_observe_boundary_round_trip(self) -> None:
        from mcp import Client
        from src.mcp_control import ControlMode, MCPControlService

        with _isolated_mcp_server() as mcp_server:
            mcp_server.service = MCPControlService(
                NoNetworkGateway(),
                mode=ControlMode.OBSERVE,
            )
            async with Client(mcp_server.mcp, raise_exceptions=True) as client:
                tools = await client.list_tools()
                resources = await client.list_resources()
                capability_result = await client.call_tool(
                    "antigravity_capabilities",
                    {},
                )
                denied_result = await client.call_tool(
                    "antigravity_send_message",
                    {
                        "conversation_id": "test-conversation",
                        "message": "must not be sent",
                        "idempotency_key": "protocol-denied-write-1",
                    },
                )
                mcp_server.service = MCPControlService(
                    NoNetworkGateway(),
                    mode=ControlMode.ADMINISTER,
                )
                invalid_project_id_result = await client.call_tool(
                    "antigravity_project_stack",
                    {"project_id": True},
                )
                invalid_candidate_count_result = await client.call_tool(
                    "antigravity_plan_idea",
                    {
                        "idea_seed_id": "idea-1",
                        "idempotency_key": "protocol-strict-count",
                        "max_candidates": True,
                    },
                )
                invalid_create_github_result = await client.call_tool(
                    "antigravity_create_project",
                    {
                        "name": "must-not-create",
                        "idempotency_key": "protocol-strict-create-flag",
                        "create_github": 1,
                    },
                )
                invalid_confirmation_result = await client.call_tool(
                    "antigravity_create_project",
                    {
                        "name": "must-not-create",
                        "idempotency_key": "protocol-strict-confirmation",
                        "create_github": True,
                        "confirm_remote_creation": "yes",
                    },
                )

        tool_by_name = {tool.name: tool for tool in tools.tools}
        resource_uris = {str(resource.uri) for resource in resources.resources}
        self.assertEqual(len(tool_by_name), 36)
        self.assertIn("antigravity_status", tool_by_name)
        self.assertIn("antigravity_create_chat", tool_by_name)
        self.assertIn("antigravity_advance_campaign_wave", tool_by_name)
        self.assertIn("antigravity_run_executor_once", tool_by_name)
        self.assertNotIn("antigravity_answer_planning_question", tool_by_name)
        for excluded_tool in (
            "antigravity_approve_campaign",
            "antigravity_activate_candidate",
            "antigravity_approve_human_test",
            "antigravity_merge_task",
            "antigravity_deploy_task",
        ):
            self.assertNotIn(excluded_tool, tool_by_name)
        self.assertIn("idempotency_key", tool_by_name["antigravity_create_chat"].input_schema["required"])
        set_model_schema = tool_by_name["antigravity_set_model"].input_schema
        self.assertEqual(
            set_model_schema["properties"]["source"]["enum"],
            ["native", "custom"],
        )
        self.assertNotIn("model_id", set_model_schema["properties"])
        self.assertNotIn("reasoning_effort", set_model_schema["properties"])
        project_id_schema = tool_by_name["antigravity_project_stack"].input_schema[
            "properties"
        ]["project_id"]
        self.assertEqual(project_id_schema["minimum"], 1)
        self.assertEqual(project_id_schema["maximum"], 9_223_372_036_854_775_807)
        self.assertEqual(
            resource_uris,
            {"antigravity://capabilities", "antigravity://status"},
        )
        self.assertFalse(capability_result.is_error)
        self.assertEqual(
            capability_result.structured_content["mode"],
            "observe",
        )
        self.assertTrue(denied_result.is_error)
        denied_text = denied_result.content[0].text
        denied_payload = json.loads(denied_text[denied_text.index("{") :])
        self.assertEqual(denied_payload["code"], "mcp_capability_denied")
        self.assertTrue(invalid_project_id_result.is_error)
        self.assertTrue(invalid_candidate_count_result.is_error)
        self.assertTrue(invalid_create_github_result.is_error)
        self.assertTrue(invalid_confirmation_result.is_error)

    async def test_chat_tools_publish_guarded_inline_image_schema(self) -> None:
        from mcp import Client

        with _isolated_mcp_server() as mcp_server:
            async with Client(mcp_server.mcp, raise_exceptions=True) as client:
                tools = await client.list_tools()

        tool_by_name = {tool.name: tool for tool in tools.tools}
        for tool_name in (
            "antigravity_create_chat",
            "antigravity_send_message",
        ):
            with self.subTest(tool=tool_name):
                schema = tool_by_name[tool_name].input_schema
                attachment_property = schema["properties"]["attachments"]
                array_schema = next(
                    option
                    for option in attachment_property.get(
                        "anyOf",
                        [attachment_property],
                    )
                    if option.get("type") == "array"
                )
                self.assertEqual(array_schema["maxItems"], 5)
                item_ref = array_schema["items"]["$ref"]
                item_schema = schema["$defs"][item_ref.rsplit("/", 1)[-1]]
                self.assertEqual(
                    set(item_schema["required"]),
                    {"name", "type", "data"},
                )
                self.assertFalse(item_schema["additionalProperties"])
                self.assertEqual(
                    item_schema["properties"]["type"]["enum"],
                    [
                        "image/png",
                        "image/jpeg",
                        "image/gif",
                        "image/webp",
                    ],
                )
                self.assertNotIn("file_path", item_schema["properties"])
                self.assertNotIn("url", item_schema["properties"])

    async def test_send_message_dispatches_inline_images_and_rejects_invalid_schema(
        self,
    ) -> None:
        from mcp import Client

        class StubControlService:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def send_message(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(dict(kwargs))
                return {"success": True}

        attachment = {
            "name": "proof.png",
            "type": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        }
        service = StubControlService()
        with _isolated_mcp_server() as mcp_server:
            mcp_server.service = service
            async with Client(mcp_server.mcp, raise_exceptions=True) as client:
                valid = await client.call_tool(
                    "antigravity_send_message",
                    {
                        "conversation_id": "conversation-1",
                        "message": "",
                        "idempotency_key": "protocol-image-message-1",
                        "attachments": [attachment],
                    },
                )
                too_many = await client.call_tool(
                    "antigravity_send_message",
                    {
                        "conversation_id": "conversation-1",
                        "message": "Too many",
                        "idempotency_key": "protocol-image-message-2",
                        "attachments": [attachment] * 6,
                    },
                )
                wrong_type = await client.call_tool(
                    "antigravity_send_message",
                    {
                        "conversation_id": "conversation-1",
                        "message": "Wrong type",
                        "idempotency_key": "protocol-image-message-3",
                        "attachments": [
                            {**attachment, "type": "image/svg+xml"},
                        ],
                    },
                )

        self.assertFalse(valid.is_error)
        self.assertTrue(too_many.is_error)
        self.assertTrue(wrong_type.is_error)
        self.assertEqual(
            service.calls,
            [
                {
                    "conversation_id": "conversation-1",
                    "message": "",
                    "idempotency_key": "protocol-image-message-1",
                    "attachments": [attachment],
                }
            ],
        )

    async def test_status_resource_uses_an_in_memory_service(self) -> None:
        from mcp import Client

        expected = {
            "status": "degraded",
            "hub_reachable": False,
            "native_ready": False,
            "parts": {"hub": {"error": {"code": "test_offline"}}},
            "note": "Hermetic protocol fixture.",
        }

        class StubControlService:
            async def status(self) -> dict[str, object]:
                return expected

        with _isolated_mcp_server() as mcp_server:
            mcp_server.service = StubControlService()
            async with Client(mcp_server.mcp, raise_exceptions=True) as client:
                result = await client.read_resource("antigravity://status")

        payload = json.loads(result.contents[0].text)
        self.assertEqual(payload, expected)


if __name__ == "__main__":
    unittest.main()
