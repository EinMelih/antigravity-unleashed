"""Focused contract tests for the Hub control-plane gateway."""

from __future__ import annotations

import asyncio
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from src.hub_control_gateway import (
    HubControlClient,
    HubControlError,
    HubControlGateway,
    HubResult,
)


class TestHubControlGateway(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.seen: dict[str, object] = {}

        async def inspect(request: web.Request) -> web.Response:
            self.seen = {
                "method": request.method,
                "raw_path": request.raw_path,
                "query": list(request.query.items()),
                "authorization": request.headers.get("Authorization"),
            }
            return web.json_response({"ok": True, "items": []})

        async def inspect_path(request: web.Request) -> web.Response:
            self.seen = {"raw_path": request.raw_path}
            return web.json_response({"ok": True})

        async def mutate(request: web.Request) -> web.Response:
            self.seen = {
                "method": request.method,
                "idempotency_key": request.headers.get("Idempotency-Key"),
                "body": await request.json(),
            }
            return web.json_response(
                {"success": True},
                headers={"X-Antigravity-Operation-Id": "a" * 32},
            )

        async def unavailable(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "error": "Bearer secret-token-value is unavailable",
                    "code": "HUB_BUSY",
                    "token": "github_pat_supersecretvalue",
                    "nested": {"api_key": "sk-alsosecret12345"},
                    "deduplicated": True,
                    "operation": {"operation_id": "b" * 32},
                },
                status=503,
            )

        async def secret_operation_header(_request: web.Request) -> web.Response:
            return web.json_response(
                {"error": "failed", "code": "UPSTREAM_FAILURE"},
                status=503,
                headers={
                    "X-Antigravity-Operation-Id": "sk-supersecret12345"
                },
            )

        async def secret_operation_payload(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "error": "failed",
                    "code": "UPSTREAM_FAILURE",
                    "operation_id": "sk-supersecret12345",
                },
                status=503,
            )

        async def plain_text(_request: web.Request) -> web.Response:
            return web.Response(text="upstream secret", status=502)

        async def invalid_json(_request: web.Request) -> web.Response:
            return web.Response(
                text="{not-json",
                content_type="application/json",
            )

        async def array_json(_request: web.Request) -> web.Response:
            return web.json_response(["unexpected"])

        async def slow(_request: web.Request) -> web.Response:
            await asyncio.sleep(0.2)
            return web.json_response({"ok": True})

        async def oversized(_request: web.Request) -> web.Response:
            return web.json_response({"value": "x" * 2_048})

        app = web.Application()
        app.router.add_get("/inspect", inspect)
        app.router.add_get("/resource/{tail:.*}", inspect_path)
        app.router.add_post("/mutate", mutate)
        app.router.add_get("/unavailable", unavailable)
        app.router.add_get("/secret-operation-header", secret_operation_header)
        app.router.add_get("/secret-operation-payload", secret_operation_payload)
        app.router.add_get("/plain", plain_text)
        app.router.add_get("/invalid", invalid_json)
        app.router.add_get("/array", array_json)
        app.router.add_get("/slow", slow)
        app.router.add_get("/oversized", oversized)
        self.server = TestServer(app)
        await self.server.start_server()
        self.base_url = str(self.server.make_url("/")).rstrip("/")

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def test_get_encodes_query_and_sends_optional_bearer_token(self) -> None:
        async with HubControlGateway(
            self.base_url,
            bearer_token="local-test-token",
        ) as gateway:
            result = await gateway.get(
                "/inspect",
                query={"search": "one & two", "tag": ["a/b", "ümlaut"]},
            )

        self.assertIsInstance(result, HubResult)
        self.assertEqual(result.payload, {"ok": True, "items": []})
        self.assertEqual(result.status, 200)
        self.assertEqual(self.seen["authorization"], "Bearer local-test-token")
        self.assertEqual(
            self.seen["query"],
            [("search", "one & two"), ("tag", "a/b"), ("tag", "ümlaut")],
        )

    def test_encode_path_keeps_untrusted_ids_in_one_segment(self) -> None:
        path = HubControlGateway.encode_path(
            "api",
            "antigravity",
            "chats",
            "chat/with spaces?and=values",
        )

        self.assertEqual(
            path,
            "/api/antigravity/chats/chat%2Fwith%20spaces%3Fand%3Dvalues",
        )

    async def test_path_parameters_are_encoded_before_request(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            await gateway.get(
                "/resource/{resource_id}",
                path_params={"resource_id": "chat/with spaces?and=values"},
            )

        self.assertEqual(
            self.seen["raw_path"],
            "/resource/chat%2Fwith%20spaces%3Fand%3Dvalues",
        )

    async def test_path_parameters_must_match_template_exactly(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            with self.assertRaisesRegex(ValueError, "exactly"):
                await gateway.get(
                    "/resource/{resource_id}",
                    path_params={"other_id": "value"},
                )
            with self.assertRaisesRegex(ValueError, "unresolved"):
                await gateway.get("/resource/{resource_id}")

    async def test_mutation_requires_and_forwards_idempotency_key(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            result = await gateway.mutate(
                "POST",
                "/mutate",
                json_body={"message": "hello"},
                idempotency_key="agent-message-1",
            )

        self.assertEqual(self.seen["idempotency_key"], "agent-message-1")
        self.assertEqual(self.seen["body"], {"message": "hello"})
        self.assertEqual(result.operation_id, "a" * 32)
        self.assertFalse(result.deduplicated)

    async def test_request_rejects_missing_or_misplaced_idempotency_key(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            with self.assertRaisesRegex(ValueError, "idempotency_key"):
                await gateway.request("POST", "/mutate", json_body={})
            with self.assertRaisesRegex(ValueError, "must not carry"):
                await gateway.request(
                    "GET",
                    "/inspect",
                    idempotency_key="not-valid-for-get",
                )

    async def test_http_failure_is_structured_and_redacted(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            with self.assertRaises(HubControlError) as caught:
                await gateway.get("/unavailable")

        error = caught.exception
        self.assertEqual(error.status, 503)
        self.assertEqual(error.code, "HUB_BUSY")
        self.assertTrue(error.retryable)
        self.assertEqual(error.operation_id, "b" * 32)
        self.assertTrue(error.deduplicated)
        self.assertNotIn("secret-token-value", str(error))
        self.assertEqual(error.payload["token"], "[REDACTED]")
        self.assertEqual(error.payload["nested"]["api_key"], "[REDACTED]")
        self.assertEqual(
            error.public(),
            {
                "error": "Bearer [REDACTED] is unavailable",
                "status": 503,
                "code": "HUB_BUSY",
                "retryable": True,
                "operation_id": "b" * 32,
                "deduplicated": True,
                "payload": error.payload,
            },
        )

    async def test_error_operation_ids_are_strictly_validated_and_redacted(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            with self.assertRaises(HubControlError) as header_error:
                await gateway.get("/secret-operation-header")
            with self.assertRaises(HubControlError) as payload_error:
                await gateway.get("/secret-operation-payload")

        for caught in (header_error.exception, payload_error.exception):
            self.assertIsNone(caught.operation_id)
            self.assertIsNone(caught.public()["operation_id"])
            self.assertNotIn("sk-supersecret12345", str(caught.public()))
        self.assertEqual(
            payload_error.exception.payload["operation_id"],
            "[REDACTED]",
        )

        constructed = HubControlError(
            "failed",
            status=503,
            code="UPSTREAM_FAILURE",
            retryable=True,
            operation_id="github_pat_supersecretvalue",
        )
        self.assertIsNone(constructed.public()["operation_id"])

    def test_free_text_errors_share_the_full_sensitive_redactor(self) -> None:
        error = HubControlError(
            (
                "api_key=supersecret password=hunter2 "
                "https://operator:privatepass@example.test/repository "
                "AIza1234567890abcdef "
                r"C:\Users\Private\project\secret.txt"
            ),
            status=503,
            code="UPSTREAM_FAILURE",
            retryable=True,
        )

        exposed = str(error.public())
        for secret in (
            "supersecret",
            "hunter2",
            "privatepass",
            "AIza1234567890abcdef",
            r"C:\Users\Private\project\secret.txt",
        ):
            self.assertNotIn(secret, exposed)
        self.assertIn("[REDACTED]", exposed)
        self.assertIn("[PATH REDACTED]", exposed)

    async def test_non_json_and_invalid_shapes_are_rejected(self) -> None:
        async with HubControlGateway(self.base_url) as gateway:
            with self.assertRaises(HubControlError) as plain:
                await gateway.get("/plain")
            with self.assertRaises(HubControlError) as invalid:
                await gateway.get("/invalid")
            with self.assertRaises(HubControlError) as array:
                await gateway.get("/array")

        self.assertEqual(plain.exception.code, "non_json_response")
        self.assertEqual(invalid.exception.code, "invalid_json_response")
        self.assertEqual(array.exception.code, "invalid_json_shape")

    async def test_timeout_is_structured_and_retryable(self) -> None:
        async with HubControlGateway(
            self.base_url,
            timeout_seconds=0.05,
        ) as gateway:
            with self.assertRaises(HubControlError) as caught:
                await gateway.get("/slow")

        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(caught.exception.code, "hub_timeout")
        self.assertTrue(caught.exception.retryable)

    async def test_response_body_is_rejected_before_unbounded_decode(self) -> None:
        async with HubControlGateway(
            self.base_url,
            max_response_bytes=1_024,
        ) as gateway:
            with self.assertRaises(HubControlError) as caught:
                await gateway.get("/oversized")

        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(caught.exception.code, "hub_response_too_large")
        self.assertFalse(caught.exception.retryable)

    def test_remote_transport_requires_explicit_https(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            HubControlGateway(
                "http://example.com",
                bearer_token="remote-token",
                allow_remote=True,
            )
        with self.assertRaisesRegex(ValueError, "allow_remote"):
            HubControlGateway("https://example.com", bearer_token="remote-token")
        with self.assertRaisesRegex(ValueError, "bearer_token"):
            HubControlGateway("https://example.com", allow_remote=True)

        gateway = HubControlGateway(
            "https://example.com/control",
            bearer_token="remote-token",
            allow_remote=True,
        )
        self.assertIsInstance(gateway, HubControlClient)

    def test_base_url_and_headers_reject_ambiguous_input(self) -> None:
        invalid_urls = (
            "file:///tmp/hub.sock",
            "http://user:pass@127.0.0.1:8000",
            "http://127.0.0.1:8000?token=secret",
            "http://127.0.0.1:8000/%252e%252e/admin",
        )
        for value in invalid_urls:
            with self.subTest(value=value), self.assertRaises(ValueError):
                HubControlGateway(value)

        with self.assertRaisesRegex(ValueError, "line breaks"):
            HubControlGateway(self.base_url, bearer_token="safe\r\nInjected: yes")
        for timeout in (0, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(
                ValueError,
                "finite",
            ):
                HubControlGateway(self.base_url, timeout_seconds=timeout)


if __name__ == "__main__":
    unittest.main()
