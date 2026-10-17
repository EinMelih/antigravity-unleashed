"""Concurrency and integration tests for the Anti-Gravity Control Plane."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_plane_middleware import control_plane_middleware
from src.operation_coordinator import (
    CONTROL_COORDINATOR_KEY,
    ControlOperationSpec,
    OperationCoordinator,
    classify_control_operation,
)
from src.proxy_server import create_app


class TestOperationCoordinator(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audit_path = Path(self.temp_dir.name) / "operations.jsonl"
        self.coordinator = OperationCoordinator(
            audit_path=self.audit_path,
            wait_timeout_seconds=2,
        )

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_conflicting_operations_run_fifo(self) -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        order: list[str] = []
        spec = ControlOperationSpec(
            "POST /api/antigravity/chats/same/message",
            ("antigravity:conversation:same",),
        )

        async def first():
            order.append("first:start")
            first_started.set()
            await release_first.wait()
            order.append("first:end")
            return web.json_response({"ok": True})

        async def second():
            order.append("second:start")
            order.append("second:end")
            return web.json_response({"ok": True})

        first_task = asyncio.create_task(self.coordinator.run(spec, first))
        await first_started.wait()
        second_task = asyncio.create_task(self.coordinator.run(spec, second))
        await asyncio.sleep(0)

        status = await self.coordinator.status()
        self.assertEqual(status["counts"]["active"], 1)
        self.assertEqual(status["counts"]["waiting"], 1)
        self.assertEqual(order, ["first:start"])

        release_first.set()
        await asyncio.gather(first_task, second_task)
        self.assertEqual(
            order,
            ["first:start", "first:end", "second:start", "second:end"],
        )

    async def test_non_conflicting_conversations_remain_parallel(self) -> None:
        both_started = asyncio.Event()
        release = asyncio.Event()
        started: list[str] = []

        async def callback(label: str):
            started.append(label)
            if len(started) == 2:
                both_started.set()
            await release.wait()
            return web.json_response({"label": label})

        first = asyncio.create_task(
            self.coordinator.run(
                ControlOperationSpec("send a", ("antigravity:conversation:a",)),
                lambda: callback("a"),
            )
        )
        second = asyncio.create_task(
            self.coordinator.run(
                ControlOperationSpec("send b", ("antigravity:conversation:b",)),
                lambda: callback("b"),
            )
        )

        await asyncio.wait_for(both_started.wait(), timeout=1)
        status = await self.coordinator.status()
        self.assertEqual(status["counts"]["active"], 2)
        self.assertEqual(status["counts"]["waiting"], 0)
        release.set()
        await asyncio.gather(first, second)

    async def test_cancelled_waiter_is_removed_without_blocking_followups(
        self,
    ) -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_called = False
        spec = ControlOperationSpec(
            "POST /api/antigravity/chats/same/message",
            ("antigravity:conversation:same",),
        )

        async def first():
            first_started.set()
            await release_first.wait()
            return web.json_response({"ok": True})

        async def second():
            nonlocal second_called
            second_called = True
            return web.json_response({"ok": True})

        first_task = asyncio.create_task(self.coordinator.run(spec, first))
        await first_started.wait()
        waiting_task = asyncio.create_task(self.coordinator.run(spec, second))
        for _ in range(20):
            if (await self.coordinator.status())["counts"]["waiting"] == 1:
                break
            await asyncio.sleep(0)
        self.assertEqual(
            (await self.coordinator.status())["counts"]["waiting"],
            1,
        )

        waiting_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting_task
        status = await self.coordinator.status()
        self.assertEqual(status["counts"]["waiting"], 0)
        self.assertEqual(status["counts"]["active"], 1)
        self.assertFalse(second_called)

        release_first.set()
        await first_task
        followup = await asyncio.wait_for(
            self.coordinator.run(spec, second),
            timeout=1,
        )
        self.assertEqual(followup.operation["state"], "succeeded")
        self.assertTrue(second_called)

    async def test_idempotency_runs_handler_once_and_survives_restart(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        call_count = 0
        spec = ControlOperationSpec("restart task", ("antigravity:scheduler",))

        async def callback():
            nonlocal call_count
            call_count += 1
            started.set()
            await release.wait()
            return web.json_response({"ok": True})

        first = asyncio.create_task(
            self.coordinator.run(
                spec,
                callback,
                idempotency_key="stable-task-restart-1",
            )
        )
        await started.wait()
        duplicate = asyncio.create_task(
            self.coordinator.run(
                spec,
                callback,
                idempotency_key="stable-task-restart-1",
            )
        )
        release.set()
        first_result, duplicate_result = await asyncio.gather(first, duplicate)

        self.assertEqual(call_count, 1)
        self.assertFalse(first_result.deduplicated)
        self.assertTrue(duplicate_result.deduplicated)
        self.assertEqual(
            first_result.operation["operation_id"],
            duplicate_result.operation["operation_id"],
        )

        restarted = OperationCoordinator(audit_path=self.audit_path)
        restarted_result = await restarted.run(
            spec,
            callback,
            idempotency_key="stable-task-restart-1",
        )
        self.assertTrue(restarted_result.deduplicated)
        self.assertEqual(call_count, 1)

    async def test_successful_json_result_reference_is_safe_and_durable(self) -> None:
        spec = ControlOperationSpec("create chat", ("antigravity:desktop-primary",))

        async def callback():
            return web.json_response(
                {
                    "conversation_id": "conversation-123",
                    "convo_id": "conversation-123",
                    "project": {
                        "id": 42,
                        "path": "C:\\private\\workspace",
                    },
                    "campaign": {"id": "CMP-123", "prompt": "private idea"},
                    "task_id": "../private-task-path",
                    "unknown": {"id": "must-not-be-persisted"},
                    "prompt": "do not persist this prompt",
                    "path": "C:\\private\\response-path",
                }
            )

        first = await self.coordinator.run(
            spec,
            callback,
            idempotency_key="safe-result-reference-1",
        )

        self.assertEqual(
            first.operation["result_ref"],
            {
                "campaign_id": "CMP-123",
                "conversation_id": "conversation-123",
                "convo_id": "conversation-123",
                "project_id": 42,
            },
        )
        audit = self.audit_path.read_text(encoding="utf-8")
        self.assertIn('"conversation_id": "conversation-123"', audit)
        self.assertNotIn("private idea", audit)
        self.assertNotIn("private\\\\workspace", audit)
        self.assertNotIn("must-not-be-persisted", audit)

        restarted = OperationCoordinator(audit_path=self.audit_path)
        duplicate = await restarted.run(
            spec,
            callback,
            idempotency_key="safe-result-reference-1",
        )
        self.assertTrue(duplicate.deduplicated)
        self.assertEqual(
            duplicate.operation["result_ref"],
            first.operation["result_ref"],
        )

    async def test_result_reference_requires_successful_json_response(self) -> None:
        spec = ControlOperationSpec("mutate", ("hub:test",))

        failed = await self.coordinator.run(
            spec,
            lambda: asyncio.sleep(
                0,
                result=web.json_response(
                    {"conversation_id": "failed-conversation"},
                    status=422,
                ),
            ),
        )
        text_response = await self.coordinator.run(
            spec,
            lambda: asyncio.sleep(
                0,
                result=web.Response(
                    text='{"conversation_id":"not-json-content-type"}',
                    content_type="text/plain",
                ),
            ),
        )

        self.assertEqual(failed.operation["result_ref"], {})
        self.assertEqual(text_response.operation["result_ref"], {})

    async def test_failed_operation_redacts_durable_and_public_errors(self) -> None:
        spec = ControlOperationSpec("failing mutation", ("hub:redaction",))
        private_path = "C:\\Users\\private\\repo"
        secret = "synthetic-secret"

        async def callback():
            raise RuntimeError(f"api_key={secret} {private_path}")

        with self.assertRaisesRegex(RuntimeError, secret):
            await self.coordinator.run(
                spec,
                callback,
                idempotency_key="redacted-failure-1",
            )

        audit = self.audit_path.read_text(encoding="utf-8")
        status = await self.coordinator.status()
        restarted_status = await OperationCoordinator(
            audit_path=self.audit_path
        ).status()

        for exposed in (
            audit,
            status["recent"][0]["error"],
            restarted_status["recent"][0]["error"],
        ):
            self.assertNotIn(secret, exposed)
            self.assertNotIn(private_path, exposed)
            self.assertIn("[REDACTED]", exposed)
            self.assertIn("[PATH REDACTED]", exposed)

    async def test_audit_io_errors_are_redacted_in_public_status(self) -> None:
        secret = "synthetic-audit-secret"
        private_path = "C:\\Users\\private\\audit"

        with patch.object(
            self.coordinator,
            "_append_audit_line",
            side_effect=OSError(f"api_key={secret} {private_path}"),
        ):
            await self.coordinator.run(
                ControlOperationSpec("audit failure", ("hub:audit",)),
                lambda: asyncio.sleep(0, result=web.json_response({"ok": True})),
            )

        audit_error = (await self.coordinator.status())["policy"]["audit_error"]
        self.assertNotIn(secret, audit_error)
        self.assertNotIn(private_path, audit_error)
        self.assertIn("[REDACTED]", audit_error)
        self.assertIn("[PATH REDACTED]", audit_error)

    def test_persistent_audit_rotates_at_a_bounded_size(self) -> None:
        self.audit_path.write_text('{"old": true}\n', encoding="utf-8")

        with patch("src.operation_coordinator.CONTROL_AUDIT_MAX_BYTES", 1):
            self.coordinator._append_audit_line({"new": True})

        self.assertTrue(self.audit_path.with_name("operations.jsonl.1").is_file())
        self.assertEqual(
            self.audit_path.read_text(encoding="utf-8").strip(),
            '{"new": true}',
        )

    async def test_non_object_audit_lines_do_not_block_startup(self) -> None:
        self.audit_path.write_text(
            '[]\nnull\n"legacy"\n',
            encoding="utf-8",
        )

        restarted = OperationCoordinator(audit_path=self.audit_path)
        status = await restarted.status()

        self.assertEqual(status["counts"]["recent"], 0)
        self.assertEqual(status["policy"]["audit_error"], "")

    async def test_invalid_utf8_audit_keeps_backup_recovery_available(self) -> None:
        backup_path = self.audit_path.with_name(f"{self.audit_path.name}.1")
        backup_path.write_text(
            '{"operation_id":"from-backup","state":"succeeded",'
            '"idempotency_key":""}\n',
            encoding="utf-8",
        )
        self.audit_path.write_bytes(b"\xff\xfe\x00")

        restarted = OperationCoordinator(audit_path=self.audit_path)
        status = await restarted.status()

        self.assertEqual(status["counts"]["recent"], 1)
        self.assertEqual(status["recent"][0]["operation_id"], "from-backup")
        self.assertIn("UnicodeDecodeError", status["policy"]["audit_error"])

    async def test_restart_recovers_idempotency_from_rotated_audit(self) -> None:
        spec = ControlOperationSpec("rotate task", ("hub:test",))

        async def callback():
            return web.json_response({"ok": True})

        original = await self.coordinator.run(
            spec,
            callback,
            idempotency_key="rotated-idempotency-proof",
        )
        self.audit_path.replace(self.audit_path.with_name("operations.jsonl.1"))
        self.audit_path.write_text("", encoding="utf-8")

        restarted = OperationCoordinator(audit_path=self.audit_path)
        duplicate = await restarted.run(
            spec,
            callback,
            idempotency_key="rotated-idempotency-proof",
        )

        self.assertTrue(duplicate.deduplicated)
        self.assertEqual(
            duplicate.operation["operation_id"],
            original.operation["operation_id"],
        )


class TestControlPlaneMiddleware(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_json_charset_is_a_structured_client_error(self) -> None:
        call_count = 0

        async def mutate(_request: web.Request) -> web.Response:
            nonlocal call_count
            call_count += 1
            return web.json_response({"success": True})

        app = web.Application(middlewares=[control_plane_middleware])
        app[CONTROL_COORDINATOR_KEY] = OperationCoordinator()
        app.router.add_post("/api/test-control", mutate)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post(
                "/api/test-control",
                headers={
                    "Content-Type": (
                        "application/json; charset=definitely-not-a-codec"
                    ),
                    "Idempotency-Key": "invalid-charset-1",
                },
                data=b'{"message":"hello"}',
            )
            payload = await response.json()

            self.assertEqual(response.status, 400)
            self.assertEqual(payload["code"], "INVALID_REQUEST_CHARSET")
            self.assertEqual(call_count, 0)
        finally:
            await client.close()

    async def test_internal_lookup_error_is_not_misclassified_as_charset(self) -> None:
        async def mutate(_request: web.Request) -> web.Response:
            raise LookupError("internal lookup failed")

        app = web.Application(middlewares=[control_plane_middleware])
        app[CONTROL_COORDINATOR_KEY] = OperationCoordinator()
        app.router.add_post("/api/test-control", mutate)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            with self.assertLogs("aiohttp.server", level="ERROR"):
                response = await client.post(
                    "/api/test-control",
                    headers={"Idempotency-Key": "internal-lookup-1"},
                    json={"message": "hello"},
                )
            response_text = await response.text()

            self.assertEqual(response.status, 500)
            self.assertNotIn("INVALID_REQUEST_CHARSET", response_text)
        finally:
            await client.close()

    async def test_same_idempotency_key_rejects_changed_http_intent(self) -> None:
        call_count = 0

        async def mutate(request: web.Request) -> web.Response:
            nonlocal call_count
            call_count += 1
            await request.json()
            return web.json_response(
                {"conversation_id": "original-conversation"}
            )

        app = web.Application(middlewares=[control_plane_middleware])
        app[CONTROL_COORDINATOR_KEY] = OperationCoordinator()
        app.router.add_post("/api/test-control/{target}", mutate)
        app.router.add_put("/api/test-control/{target}", mutate)
        app.router.add_post("/api/other-control/{target}", mutate)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            headers = {"Idempotency-Key": "intent-conflict-proof-1"}
            first = await client.post(
                "/api/test-control/alpha",
                headers=headers,
                json={"message": "original"},
            )
            self.assertEqual(first.status, 200)

            changed_requests = (
                client.put(
                    "/api/test-control/alpha",
                    headers=headers,
                    json={"message": "original"},
                ),
                client.post(
                    "/api/other-control/alpha",
                    headers=headers,
                    json={"message": "original"},
                ),
                client.post(
                    "/api/test-control/beta",
                    headers=headers,
                    json={"message": "original"},
                ),
                client.post(
                    "/api/test-control/alpha",
                    headers=headers,
                    json={"message": "changed"},
                ),
            )
            for request in changed_requests:
                response = await request
                payload = await response.json()
                self.assertEqual(response.status, 409)
                self.assertEqual(payload["code"], "IDEMPOTENCY_KEY_CONFLICT")
                self.assertNotIn("result_ref", payload)
                self.assertNotIn("operation", payload)

            self.assertEqual(call_count, 1)
        finally:
            await client.close()

    async def test_middleware_adds_headers_and_deduplicates(self) -> None:
        call_count = 0

        async def mutate(request: web.Request) -> web.Response:
            nonlocal call_count
            call_count += 1
            await request.json()
            return web.json_response(
                {
                    "call_count": call_count,
                    "conversation": {"id": "conversation-middleware-1"},
                    "prompt": "response secret",
                }
            )

        app = web.Application(middlewares=[control_plane_middleware])
        app[CONTROL_COORDINATOR_KEY] = OperationCoordinator()
        app.router.add_post("/api/test-control", mutate)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            headers = {"Idempotency-Key": "middleware-proof-1"}
            payload = {
                "prompt": "request secret",
                "path": "C:\\private\\request-path",
            }
            first = await client.post(
                "/api/test-control",
                headers=headers,
                json=payload,
            )
            second = await client.post(
                "/api/test-control",
                headers=headers,
                json=payload,
            )
            first_payload = await first.json()
            second_payload = await second.json()

            self.assertEqual(first.status, 200)
            self.assertEqual(first_payload["call_count"], 1)
            self.assertEqual(second.status, 200)
            self.assertTrue(second_payload["deduplicated"])
            self.assertEqual(
                second_payload["result_ref"],
                {"conversation_id": "conversation-middleware-1"},
            )
            self.assertNotIn("prompt", second_payload["result_ref"])
            self.assertNotIn("path", second_payload["operation"]["metadata"])
            self.assertEqual(call_count, 1)
            self.assertEqual(
                first.headers["X-Antigravity-Operation-Id"],
                second.headers["X-Antigravity-Operation-Id"],
            )
            self.assertEqual(second.headers["X-Antigravity-Deduplicated"], "true")
        finally:
            await client.close()


class TestControlPlaneRoutes(unittest.TestCase):
    def test_resource_classification(self) -> None:
        same_chat = classify_control_operation(
            "POST",
            "/api/antigravity/chats/abc/message",
        )
        legacy_same_chat = classify_control_operation(
            "POST",
            "/api/integrity/chats/abc/message",
        )
        other_chat = classify_control_operation(
            "POST",
            "/api/antigravity/chats/def/message",
        )
        scheduler = classify_control_operation(
            "PATCH",
            "/api/antigravity/scheduled-tasks/nightly",
        )
        lowercase_native = classify_control_operation(
            "DELETE",
            "/api/antigravity/chats/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        uppercase_native = classify_control_operation(
            "POST",
            "/api/antigravity/chats/AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA/message",
        )

        self.assertEqual(same_chat.resources, legacy_same_chat.resources)
        self.assertNotEqual(same_chat.resources, other_chat.resources)
        self.assertEqual(lowercase_native.resources, uppercase_native.resources)
        self.assertEqual(scheduler.resources, ("antigravity:scheduler",))
        self.assertIsNone(
            classify_control_operation(
                "GET",
                "/api/antigravity/chats/abc/history",
            )
        )

    def test_routes_and_dashboard_documentation_are_present(self) -> None:
        app = create_app()
        routes = {
            route.resource.canonical
            for route in app.router.routes()
            if getattr(route, "resource", None)
        }
        expected_routes = {
            "/api/control-plane/operations",
            "/api/control-plane/docs",
            "/api/control-plane/docs/{document_id}",
            "/docs/control-plane",
            "/docs/control-plane/{document_id}",
            "/api/antigravity/models",
            "/api/antigravity/active-model",
            "/api/antigravity/custom-models",
            "/api/antigravity/quota",
            "/api/antigravity/media",
        }
        self.assertTrue(expected_routes.issubset(routes))

        root = Path(__file__).resolve().parent.parent
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        script = (root / "dashboard" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        manual = (root / "docs" / "antigravity-control-plane.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("control-docs-tab", html)
        self.assertIn("Vollständiges API-Handbuch lesen", html)
        self.assertIn("function controlFetch", script)
        self.assertIn("/api/control-plane/operations", script)
        self.assertIn("Konflikt- und Parallelitätsmodell", manual)
        self.assertIn("Idempotency-Key", manual)


if __name__ == "__main__":
    unittest.main()
