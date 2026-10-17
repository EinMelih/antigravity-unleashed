import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import healer_logic


class _FakeResponse:
    def __init__(self, *, status=200, payload=None, body=""):
        self.status = status
        self._payload = payload or {}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)


class HealerBridgeAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def _config(self, *, auth_token="bridge-secret", api_keys=()):
        return SimpleNamespace(
            auth_token=auth_token,
            api_keys=list(api_keys),
            auto_healer={"api_bridge_url": "http://127.0.0.1:8001"},
        )

    async def test_level_1_uses_authenticated_get(self):
        session = _FakeSession([_FakeResponse(status=200)])
        with (
            patch.object(healer_logic, "config", self._config()),
            patch.object(
                healer_logic,
                "get_http_session",
                AsyncMock(return_value=session),
            ),
            patch.object(healer_logic, "record_event"),
        ):
            self.assertTrue(await healer_logic.heal_level_1())

        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "http://127.0.0.1:8001/health/cdp")
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer bridge-secret"},
        )

    async def test_bridge_check_uses_authenticated_diagnostics(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    status=200,
                    payload={
                        "status": "ok",
                        "cdp": {"status": "connected"},
                        "diagnostics": (
                            "Authenticate and call GET /health/cdp."
                        ),
                    },
                ),
                _FakeResponse(
                    status=200,
                    payload={
                        "status": "ok",
                        "diagnostics": {"inputFound": True},
                    },
                ),
            ]
        )
        with (
            patch.object(healer_logic, "config", self._config()),
            patch.object(
                healer_logic,
                "get_http_session",
                AsyncMock(return_value=session),
            ),
        ):
            result = await healer_logic.check_api_bridge()

        self.assertTrue(result["reachable"])
        self.assertTrue(result["cdp_connected"])
        self.assertTrue(result["bridge_injected"])
        self.assertEqual(result["diagnostics_status_code"], 200)
        self.assertEqual(len(session.calls), 2)
        method, url, kwargs = session.calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "http://127.0.0.1:8001/health/cdp")
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer bridge-secret"},
        )

    async def test_level_2_uses_api_key_when_auth_token_is_empty(self):
        session = _FakeSession(
            [_FakeResponse(status=200, payload={"status": "ok"})]
        )
        with (
            patch.object(
                healer_logic,
                "config",
                self._config(auth_token="", api_keys=("internal-api-key",)),
            ),
            patch.object(
                healer_logic,
                "get_http_session",
                AsyncMock(return_value=session),
            ),
            patch.object(healer_logic, "record_event"),
        ):
            self.assertTrue(await healer_logic.heal_level_2())

        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer internal-api-key"},
        )

    async def test_level_3_reuses_internal_auth_headers(self):
        session = _FakeSession([_FakeResponse(status=200)])
        with (
            patch.object(healer_logic, "config", self._config()),
            patch.object(
                healer_logic,
                "get_http_session",
                AsyncMock(return_value=session),
            ),
            patch.object(healer_logic, "record_event"),
        ):
            self.assertTrue(await healer_logic.heal_level_3())

        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://127.0.0.1:8001/api/chat")
        self.assertEqual(
            kwargs["headers"],
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer bridge-secret",
            },
        )


if __name__ == "__main__":
    unittest.main()
