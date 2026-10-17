import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import api_handlers, api_server
from src.cdp_client import AntigravityCDP


class _OpenWebSocket:
    closed = False


class _Request(SimpleNamespace):
    """Provide the per-request storage contract of aiohttp.web.Request."""
    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __getitem__(self, key):
        return self.__dict__[key]

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class _BlockingCDP:
    def __init__(self) -> None:
        self._connected = False
        self._bridge_injected = False
        self.ws = None
        self.connect_started = asyncio.Event()
        self.release_connect = asyncio.Event()
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connect_started.set()
        await self.release_connect.wait()

    async def inject_bridge(self) -> None:
        raise AssertionError("Bridge injection must wait for a CDP connection.")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


class _RecoveringCDP:
    def __init__(self, failures_before_ready: int = 2) -> None:
        self._connected = False
        self._bridge_injected = False
        self.ws = None
        self.failures_before_ready = failures_before_ready
        self.connect_attempts = 0
        self.inject_attempts = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connect_attempts += 1
        if self.connect_attempts <= self.failures_before_ready:
            raise ConnectionError("renderer not ready")
        self._connected = True
        self.ws = _OpenWebSocket()

    async def inject_bridge(self) -> None:
        self.inject_attempts += 1
        if not self._connected:
            raise ConnectionError("CDP not connected")
        self._bridge_injected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False
        self.ws = None


class _ConcurrentProbeCDP(_RecoveringCDP):
    def __init__(self) -> None:
        super().__init__(failures_before_ready=0)
        self.connect_started = asyncio.Event()
        self.release_connect = asyncio.Event()
        self.active_connects = 0
        self.maximum_active_connects = 0
        self.send_chat_calls = 0

    async def connect(self) -> None:
        self.connect_attempts += 1
        self.active_connects += 1
        self.maximum_active_connects = max(
            self.maximum_active_connects,
            self.active_connects,
        )
        self.connect_started.set()
        try:
            await self.release_connect.wait()
            self._connected = True
            self.ws = _OpenWebSocket()
        finally:
            self.active_connects -= 1

    async def diagnose(self):
        return {"inputFound": True}

    async def send_chat(self, *_args, **_kwargs):
        self.send_chat_calls += 1
        return {"response": "ok"}


class _BlockingDiagnoseCDP(_RecoveringCDP):
    def __init__(self) -> None:
        super().__init__(failures_before_ready=0)
        self._connected = True
        self._bridge_injected = True
        self.ws = _OpenWebSocket()
        self.diagnose_started = asyncio.Event()
        self.release_diagnose = asyncio.Event()
        self.diagnosing = False
        self.disconnect_during_diagnose = False

    async def diagnose(self):
        self.diagnosing = True
        self.diagnose_started.set()
        try:
            await self.release_diagnose.wait()
            return {"inputFound": True}
        finally:
            self.diagnosing = False

    async def disconnect(self) -> None:
        if self.diagnosing:
            self.disconnect_during_diagnose = True
        await super().disconnect()


async def _wait_until(predicate, timeout: float = 0.5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Timed out waiting for startup bridge readiness.")
        await asyncio.sleep(0.005)


class ApiBridgeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_does_not_wait_for_a_missing_renderer(self) -> None:
        cdp = _BlockingCDP()
        app = {}

        with (
            patch.object(api_server, "AntigravityCDP", return_value=cdp),
            patch.object(api_server, "send_telegram", new=AsyncMock()),
        ):
            await asyncio.wait_for(api_server.on_startup(app), timeout=0.05)
            await asyncio.wait_for(cdp.connect_started.wait(), timeout=0.05)
            await api_server.on_shutdown(app)

        self.assertEqual(cdp.disconnect_calls, 1)

    async def test_startup_retries_until_cdp_and_bridge_are_ready(self) -> None:
        cdp = _RecoveringCDP(failures_before_ready=2)
        app = {}
        notify = AsyncMock()

        with (
            patch.object(api_server, "AntigravityCDP", return_value=cdp),
            patch.object(api_server, "CDP_STARTUP_RETRY_SECONDS", 0.005),
            patch.object(api_server, "send_telegram", new=notify),
        ):
            await api_server.on_startup(app)
            await _wait_until(lambda: cdp._bridge_injected)
            await api_server.on_shutdown(app)

        self.assertEqual(cdp.connect_attempts, 3)
        self.assertEqual(cdp.inject_attempts, 1)
        notify.assert_awaited_once_with(
            "Server gestartet und erfolgreich mit Antigravity verbunden."
        )

    async def test_health_only_reports_ready_after_bridge_injection(self) -> None:
        fake_config = SimpleNamespace(api_keys={}, auth_token="")
        cdp = _RecoveringCDP(failures_before_ready=0)
        cdp._connected = True
        cdp.ws = _OpenWebSocket()

        with patch.object(api_server, "config", fake_config):
            before = await api_server.health_handler(
                SimpleNamespace(app={"cdp": cdp})
            )
            cdp._bridge_injected = True
            after = await api_server.health_handler(
                SimpleNamespace(app={"cdp": cdp})
            )

        before_payload = json.loads(before.text)
        after_payload = json.loads(after.text)
        self.assertEqual(before_payload["status"], "degraded")
        self.assertFalse(before_payload["ready"])
        self.assertEqual(before_payload["cdp"]["status"], "connected")
        self.assertEqual(before_payload["cdp"]["bridge"], "missing")
        self.assertEqual(after_payload["status"], "ok")
        self.assertTrue(after_payload["ready"])
        self.assertEqual(after_payload["cdp"]["bridge"], "injected")

    async def test_startup_and_diagnostic_serialize_connection_attempts(self) -> None:
        cdp = _ConcurrentProbeCDP()
        supervisor = api_server.CDPStartupSupervisor(cdp, retry_seconds=0.005)
        app = {"cdp": cdp, "cdp_startup_supervisor": supervisor}
        diagnostic_task = None

        supervisor.start()
        try:
            await asyncio.wait_for(cdp.connect_started.wait(), timeout=0.05)
            diagnostic_task = asyncio.create_task(
                api_server.cdp_diagnose_handler(SimpleNamespace(app=app))
            )
            await asyncio.sleep(0.01)
            maximum_active_connects = cdp.maximum_active_connects
            connect_attempts = cdp.connect_attempts
        finally:
            cdp.release_connect.set()
            if diagnostic_task is not None:
                response = await asyncio.wait_for(diagnostic_task, timeout=0.1)
                self.assertEqual(response.status, 200)
            await supervisor.stop()

        self.assertEqual(maximum_active_connects, 1)
        self.assertEqual(connect_attempts, 1)

    async def test_shutdown_waits_for_in_flight_diagnostic(self) -> None:
        cdp = _BlockingDiagnoseCDP()
        supervisor = api_server.CDPStartupSupervisor(cdp, retry_seconds=0.005)
        app = {"cdp": cdp, "cdp_startup_supervisor": supervisor}
        diagnostic_task = asyncio.create_task(
            api_server.cdp_diagnose_handler(SimpleNamespace(app=app))
        )

        await asyncio.wait_for(cdp.diagnose_started.wait(), timeout=0.05)
        shutdown_task = asyncio.create_task(supervisor.stop())
        await asyncio.sleep(0.01)
        disconnected_early = cdp.disconnect_calls
        cdp.release_diagnose.set()
        response = await asyncio.wait_for(diagnostic_task, timeout=0.1)
        await asyncio.wait_for(shutdown_task, timeout=0.1)

        self.assertEqual(response.status, 200)
        self.assertEqual(disconnected_early, 0)
        self.assertFalse(cdp.disconnect_during_diagnose)
        self.assertEqual(cdp.disconnect_calls, 1)

    async def test_chat_handler_waits_for_startup_connection(self) -> None:
        cdp = _ConcurrentProbeCDP()
        supervisor = api_server.CDPStartupSupervisor(cdp, retry_seconds=0.005)
        app = {"cdp": cdp, "cdp_startup_supervisor": supervisor}
        request = _Request(
            app=app,
            json=AsyncMock(return_value={"message": "lifecycle probe"}),
        )
        supervisor.start()
        chat_task = None
        try:
            await asyncio.wait_for(cdp.connect_started.wait(), timeout=0.05)
            with (
                patch.object(api_handlers, "log_interaction"),
                patch.object(api_handlers, "track_usage"),
            ):
                chat_task = asyncio.create_task(api_server.simple_chat_handler(request))
                await asyncio.sleep(0.01)
                self.assertEqual(cdp.send_chat_calls, 0)
                cdp.release_connect.set()
                response = await asyncio.wait_for(chat_task, timeout=0.1)
        finally:
            cdp.release_connect.set()
            if chat_task is not None and not chat_task.done():
                chat_task.cancel()
            await supervisor.stop()

        self.assertEqual(response.status, 200)
        self.assertEqual(cdp.send_chat_calls, 1)

    async def test_chat_endpoints_return_503_when_bridge_cannot_be_prepared(self) -> None:
        cases = [
            (api_server.simple_chat_handler, {"message": "probe"}),
            (api_server.chat_completions_handler, {
                "messages": [{"role": "user", "content": "probe"}],
            }),
            (api_server.chat_completions_handler, {
                "messages": [{"role": "user", "content": "probe"}],
                "stream": True,
            }),
        ]
        for handler, payload in cases:
            with self.subTest(handler=handler.__name__, stream=payload.get("stream", False)):
                cdp = _RecoveringCDP(failures_before_ready=99)
                supervisor = api_server.CDPStartupSupervisor(
                    cdp,
                    retry_seconds=0.005,
                )
                request = _Request(
                    app={"cdp": cdp, "cdp_startup_supervisor": supervisor},
                    json=AsyncMock(return_value=payload),
                )

                response = await handler(request)

                self.assertEqual(response.status, 503)

    async def test_renderer_navigation_invalidates_cached_bridge_readiness(self) -> None:
        cdp = AntigravityCDP()
        cdp._connected = True
        cdp._bridge_injected = True
        cdp.ws = _OpenWebSocket()

        cdp.observe_protocol_event({"method": "Runtime.executionContextsCleared"})

        self.assertFalse(api_server.bridge_is_ready(cdp))

    async def test_supervisor_reinjects_after_renderer_bridge_invalidation(self) -> None:
        cdp = _RecoveringCDP(failures_before_ready=0)
        notify = AsyncMock()
        supervisor = api_server.CDPStartupSupervisor(
            cdp,
            retry_seconds=0.005,
            on_ready=notify,
        )
        supervisor.start()
        try:
            await _wait_until(lambda: cdp.inject_attempts == 1)
            cdp._bridge_injected = False
            await _wait_until(lambda: cdp.inject_attempts == 2)
        finally:
            await supervisor.stop()

        notify.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
