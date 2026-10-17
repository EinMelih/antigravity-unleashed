import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import proxy_handlers


class _ResponseContext:
    def __init__(self) -> None:
        self.status = 200
        self.headers = {"Content-Type": "application/json"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def read(self) -> bytes:
        return b'{"ok": true}'


class _CapturingSession:
    def __init__(self) -> None:
        self.request_kwargs = None

    def request(self, **kwargs):
        self.request_kwargs = kwargs
        return _ResponseContext()


class ProxyStatsAuthTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, *, headers, config):
        session = _CapturingSession()
        request = SimpleNamespace(
            headers=headers,
            method="GET",
            read=AsyncMock(return_value=b""),
        )
        with (
            patch.object(proxy_handlers, "config", config),
            patch.object(proxy_handlers, "get_session", AsyncMock(return_value=session)),
        ):
            response = await proxy_handlers.stats_proxy_handler(request)
        return response, session.request_kwargs

    async def test_preserves_explicit_authorization_and_configured_port(self) -> None:
        config = SimpleNamespace(api_keys={}, auth_token="internal", api_bridge_port=8123)
        response, call = await self._call(
            headers={"Authorization": "Bearer caller-token"},
            config=config,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(call["headers"]["Authorization"], "Bearer caller-token")
        self.assertEqual(call["url"], "http://127.0.0.1:8123/api/stats")

    async def test_uses_server_side_api_key_when_browser_has_no_secret(self) -> None:
        config = SimpleNamespace(
            api_keys={"configured-api-key": {"name": "Hub"}},
            auth_token="fallback-token",
            api_bridge_port=8001,
        )
        _, call = await self._call(headers={}, config=config)

        self.assertEqual(call["headers"]["Authorization"], "Bearer configured-api-key")

    async def test_does_not_create_empty_bearer_header(self) -> None:
        config = SimpleNamespace(api_keys={}, auth_token="", api_bridge_port=8001)
        _, call = await self._call(headers={}, config=config)

        self.assertNotIn("Authorization", call["headers"])


if __name__ == "__main__":
    unittest.main()
