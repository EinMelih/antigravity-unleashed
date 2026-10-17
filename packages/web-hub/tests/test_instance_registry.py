import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src import parallel_cdp
from src.instance_registry import build_instance_read_model
from src.parallel_cdp import ParallelCDPManager
from src.project_handlers import handle_get_antigravity_instances
from src.proxy_server import create_app


class ReadOnlyRuntimeClient:
    def __init__(self, runtime):
        self.runtime = runtime
        self.expressions = []

    async def evaluate(self, expression, timeout=5):
        del timeout
        self.expressions.append(expression)
        if "const api = window.electronNative" in expression:
            runtime = dict(self.runtime)
            if "getActiveChatMeta" not in expression:
                runtime.pop("activity_observed", None)
                runtime.pop("native_activity", None)
            return runtime
        return "AG-01"


class ReadOnlySnapshotManager(ParallelCDPManager):
    def __init__(self):
        super().__init__()
        self.runtime_client = ReadOnlyRuntimeClient({
            "role": "duplicate",
            "stamp": None,
            "purpose": "chat",
            "chat_id": None,
            "composer_visible": True,
            "has_draft": False,
            "focused": False,
        })

    async def get_devtools_port(self):
        return 9222

    async def get_all_page_targets(self, _port):
        return [{
            "id": "worker-target",
            "url": "https://127.0.0.1:9999/",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/worker-target",
        }]

    async def get_client_for_target(self, _ws_url):
        return self.runtime_client


class PoolSnapshotManager(ParallelCDPManager):
    def __init__(self):
        super().__init__()
        self.targets = [
            {
                "id": "primary-target",
                "url": "https://127.0.0.1:9999/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/primary-target",
            },
            {
                "id": "idle-target",
                "url": "https://127.0.0.1:9999/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/idle-target",
            },
            {
                "id": "working-target",
                "url": "https://127.0.0.1:9999/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/working-target",
            },
        ]
        self.runtime_clients = {
            "primary-target": ReadOnlyRuntimeClient({
                "role": "primary",
                "stamp": None,
                "purpose": "chat",
                "chat_id": None,
                "focused": True,
            }),
            "idle-target": ReadOnlyRuntimeClient({
                "role": "duplicate",
                "stamp": "AG-01",
                "purpose": "chat",
                "chat_id": None,
                "focused": False,
            }),
            "working-target": ReadOnlyRuntimeClient({
                "role": "duplicate",
                "stamp": "AG-02",
                "purpose": "chat",
                "chat_id": "chat-b",
                "focused": False,
            }),
        }

    async def get_devtools_port(self):
        return 9222

    async def get_all_page_targets(self, _port):
        return list(self.targets)

    async def get_client_for_target(self, ws_url):
        return self.runtime_clients[ws_url.rsplit("/", 1)[-1]]


class UnreachableRuntimeClient:
    async def evaluate(self, _expression, timeout=5):
        del timeout
        raise TimeoutError("secret upstream exception")


class UnreachableSnapshotManager(ParallelCDPManager):
    async def get_devtools_port(self):
        return 9222

    async def get_all_page_targets(self, _port):
        return [{
            "id": "unreachable-target",
            "url": "https://127.0.0.1:9999/private/path",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/unreachable-target",
        }]

    async def get_client_for_target(self, _ws_url):
        return UnreachableRuntimeClient()


class OfflineSnapshotManager:
    closed = False

    async def get_worker_pool_snapshot(self):
        raise ConnectionError("private upstream path must not leak")

    async def close_all(self):
        self.closed = True


class TestInstanceReadModel(unittest.TestCase):
    def test_live_conversation_wins_and_reports_binding_mismatch(self):
        snapshot = {
            "primary": {
                "target_id": "primary-target",
                "window_id": "MAIN",
                "state": "user",
                "chat_id": None,
                "focused": True,
            },
            "workers": [{
                "target_id": "worker-target",
                "window_id": "AG-01",
                "state": "working",
                "chat_id": "assigned-chat",
                "loaded_chat_id": "live-chat",
                "purpose": "chat",
                "has_draft": False,
            }],
            "capacity": {"maximum": 4, "queued": 0},
        }
        conversations = [{
            "convo_id": "live-chat",
            "title": "Live conversation",
            "status": "running",
            "conversation_type": "project",
            "project_name": "Example",
            "repository_name": "example-repo",
        }]

        result = build_instance_read_model(
            snapshot,
            conversations,
            observed_at="2026-08-30T12:00:00Z",
        )

        self.assertEqual(
            {
                "conversation": result["instances"][1]["conversation"],
                "binding_status": result["instances"][1]["binding_status"],
            },
            {
                "conversation": {
                    "conversation_id": "live-chat",
                    "title": "Live conversation",
                    "status": "running",
                    "kind": "project",
                    "project_name": "Example",
                    "repository_name": "example-repo",
                },
                "binding_status": "mismatch",
            },
        )

    def test_statuses_are_closed_and_unreachable_runtime_is_degraded(self):
        result = build_instance_read_model(
            {
                "primary": {
                    "target_id": "primary-target",
                    "window_id": "MAIN",
                    "state": "user",
                    "runtime_reachable": True,
                },
                "workers": [{
                    "target_id": "worker-target",
                    "window_id": "AG-01",
                    "state": "unexpected-upstream-state",
                    "runtime_reachable": False,
                    "error": "C:/private/path and internal exception",
                }],
                "capacity": {"maximum": 4, "queued": 0},
            },
            observed_at="2026-08-30T12:00:00Z",
        )

        worker = result["instances"][1]
        self.assertEqual(result["connection"], "degraded")
        self.assertTrue(result["stale"])
        self.assertEqual(worker["availability"], "unreachable")
        self.assertEqual(worker["activity"], "unknown")
        self.assertEqual(worker["detail_code"], "runtime_unreachable")
        self.assertNotIn("C:/private", str(result))
        self.assertNotIn("internal exception", str(result))

    def test_capacity_excludes_dictation_and_separates_busy_idle_and_open(self):
        result = build_instance_read_model(
            {
                "primary": {
                    "target_id": "primary-target",
                    "window_id": "MAIN",
                    "state": "user",
                },
                "workers": [
                    {
                        "target_id": "idle-target",
                        "window_id": "AG-01",
                        "state": "idle",
                        "purpose": "chat",
                    },
                    {
                        "target_id": "busy-target",
                        "window_id": "AG-02",
                        "state": "waiting_human",
                        "purpose": "chat",
                    },
                    {
                        "target_id": "dictation-target",
                        "window_id": "AG-DIKTAT",
                        "state": "dictation_recording",
                        "purpose": "dictation",
                    },
                ],
                "capacity": {"maximum": 4, "queued": 2},
            },
            observed_at="2026-08-30T12:00:00Z",
        )

        self.assertEqual(result["capacity"], {
            "open_workers": 2,
            "busy_workers": 1,
            "idle_workers": 1,
            "maximum_workers": 4,
            "queued": 2,
        })

    def test_revision_ignores_poll_time_when_observed_state_is_unchanged(self):
        snapshot = {
            "primary": {
                "target_id": "primary-target",
                "window_id": "MAIN",
                "state": "user",
            },
            "workers": [],
            "capacity": {"maximum": 4, "queued": 0},
        }

        first = build_instance_read_model(
            snapshot,
            observed_at="2026-08-30T12:00:00Z",
        )
        second = build_instance_read_model(
            snapshot,
            observed_at="2026-08-30T12:00:01Z",
        )

        self.assertEqual(first["revision"], second["revision"])


class TestReadOnlyWorkerSnapshot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parallel_cdp._DUPLICATE_TARGET_IDS.clear()
        parallel_cdp._WINDOW_STAMPS.clear()
        parallel_cdp._WORKER_STATES.clear()
        parallel_cdp._NEXT_WINDOW_STAMP = 1

    async def test_snapshot_read_does_not_write_renderer_storage_or_dom(self):
        manager = ReadOnlySnapshotManager()

        first = await manager.get_worker_pool_snapshot()

        expressions = "\n".join(manager.runtime_client.expressions)
        self.assertNotIn(".setItem(", expressions)
        self.assertNotIn("document.createElement(", expressions)
        self.assertEqual(parallel_cdp._WINDOW_STAMPS, {})
        self.assertEqual(parallel_cdp._WORKER_STATES, {})
        self.assertEqual(parallel_cdp._DUPLICATE_TARGET_IDS, set())
        self.assertEqual(parallel_cdp._NEXT_WINDOW_STAMP, 1)
        self.assertEqual(first["workers"][0]["state"], "unknown")
        self.assertEqual(first["workers"][0]["detail"], "Status nicht ermittelt")

    async def test_snapshot_uses_live_bridge_activity_when_hub_has_no_state(self):
        manager = ReadOnlySnapshotManager()
        manager.runtime_client.runtime.update({
            "activity_observed": True,
            "native_activity": "working",
        })

        snapshot = await manager.get_worker_pool_snapshot()

        self.assertEqual(snapshot["workers"][0]["state"], "working")
        self.assertEqual(snapshot["workers"][0]["detail"], "Native Oberfläche arbeitet")
        self.assertEqual(snapshot["capacity"]["busy"], 1)

    async def test_unstamped_worker_label_is_stable_without_process_memory(self):
        first_manager = ReadOnlySnapshotManager()
        first = await first_manager.get_worker_pool_snapshot()
        first_label = first["workers"][0]["window_id"]

        parallel_cdp._WINDOW_STAMPS.clear()
        parallel_cdp._WORKER_STATES.clear()
        parallel_cdp._DUPLICATE_TARGET_IDS.clear()
        parallel_cdp._NEXT_WINDOW_STAMP = 91
        second_manager = ReadOnlySnapshotManager()
        second = await second_manager.get_worker_pool_snapshot()

        self.assertRegex(first_label, r"^AG-[A-F0-9]{6}$")
        self.assertEqual(second["workers"][0]["window_id"], first_label)
        self.assertEqual(parallel_cdp._NEXT_WINDOW_STAMP, 91)

    async def test_legacy_capacity_distinguishes_open_busy_and_idle_workers(self):
        manager = PoolSnapshotManager()
        manager._set_worker_state("idle-target", "idle")
        manager._set_worker_state("working-target", "working", chat_id="chat-b")

        snapshot = await manager.get_worker_pool_snapshot()

        self.assertEqual(
            {
                key: snapshot["capacity"].get(key)
                for key in ("active", "open", "busy", "idle")
            },
            {"active": 1, "open": 2, "busy": 1, "idle": 1},
        )

    async def test_snapshot_marks_failed_runtime_observation_unreachable(self):
        parallel_cdp._DUPLICATE_TARGET_IDS.add("unreachable-target")
        parallel_cdp._WINDOW_STAMPS["unreachable-target"] = "AG-01"
        manager = UnreachableSnapshotManager()

        snapshot = await manager.get_worker_pool_snapshot()

        self.assertIs(snapshot["workers"][0]["runtime_reachable"], False)


class TestWorkerSafetyDecisions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parallel_cdp._CHAT_TARGET_IDS.clear()
        parallel_cdp._DUPLICATE_TARGET_IDS.clear()
        parallel_cdp._WINDOW_STAMPS.clear()
        parallel_cdp._WORKER_STATES.clear()
        parallel_cdp._CHAT_LOCKS.clear()
        parallel_cdp._TARGET_LOCKS.clear()
        parallel_cdp._WINDOW_LOCK = None

    @staticmethod
    def target(target_id, runtime):
        return {
            "id": target_id,
            "webSocketDebuggerUrl": f"ws://127.0.0.1/{target_id}",
            "runtime": {"has_draft": False, "purpose": "chat", **runtime},
        }

    async def test_close_requires_positive_reachable_idle_evidence(self):
        cases = [
            {"runtime_reachable": True, "activity_observed": True, "native_activity": "working"},
            {"runtime_reachable": True, "activity_observed": False, "native_activity": "unknown"},
            {"runtime_reachable": False, "activity_observed": False, "native_activity": "unknown"},
        ]
        for index, runtime in enumerate(cases):
            with self.subTest(runtime=runtime):
                target_id = f"unsafe-{index}"
                manager = ParallelCDPManager()
                manager.get_devtools_port = AsyncMock(return_value=9222)
                manager._discover_window_pool = AsyncMock(
                    return_value=([self.target(target_id, runtime)], None)
                )
                manager.close_target_window = AsyncMock()

                result = await manager.close_worker_window(target_id)

                self.assertFalse(result["success"])
                self.assertTrue(result["not_idle"])
                manager.close_target_window.assert_not_awaited()

    async def test_close_allows_a_reachable_natively_confirmed_idle_worker(self):
        target_id = "confirmed-idle"
        target = self.target(target_id, {
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
        })
        manager = ParallelCDPManager()
        manager.get_devtools_port = AsyncMock(return_value=9222)
        manager._discover_window_pool = AsyncMock(return_value=([target], None))
        manager.close_target_window = AsyncMock()

        result = await manager.close_worker_window(target_id)

        self.assertTrue(result["success"])
        manager.close_target_window.assert_awaited_once_with(target)

    async def test_allocator_does_not_reuse_a_natively_working_mapped_worker(self):
        target_id = "mapped-working"
        target = self.target(target_id, {
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "working",
        })
        parallel_cdp._CHAT_TARGET_IDS["chat-a"] = target_id
        manager = ParallelCDPManager()
        manager.get_devtools_port = AsyncMock(return_value=9222)
        manager._discover_window_pool = AsyncMock(return_value=([target], None))
        manager.open_duplicate_window = AsyncMock()

        with (
            patch.object(parallel_cdp, "MAX_WORKERS", 1),
            patch.object(parallel_cdp, "WORKER_WAIT_TIMEOUT_SECONDS", 0),
        ):
            with self.assertRaises(TimeoutError):
                await manager._allocate_worker_target("chat-a")

        manager.open_duplicate_window.assert_not_awaited()

    async def test_pool_trim_keeps_workers_without_confirmed_idle_evidence(self):
        workers = [
            self.target(f"unknown-{index}", {
                "runtime_reachable": False,
                "activity_observed": False,
                "native_activity": "unknown",
            })
            for index in range(5)
        ]
        manager = ParallelCDPManager()
        manager.close_target_window = AsyncMock()

        with patch.object(parallel_cdp, "MAX_WORKERS", 4):
            remaining = await manager._trim_excess_idle_workers(workers)

        self.assertEqual(len(remaining), 5)
        manager.close_target_window.assert_not_awaited()


class TestInstanceRegistryAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app.router.add_get(
            "/api/antigravity/instances",
            handle_get_antigravity_instances,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_unavailable_desktop_returns_sanitized_offline_read_model(self):
        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=OfflineSnapshotManager(),
            ),
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=[],
            ),
        ):
            response = await self.client.get("/api/antigravity/instances")

        payload = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["connection"], "offline")
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["instances"], [])
        self.assertNotIn("error", payload)


class TestInstanceRegistryRoutes(unittest.TestCase):
    def test_proxy_registers_instances_and_keeps_workers_route(self):
        app = create_app()

        routes = {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
        }

        self.assertTrue({
            ("GET", "/api/antigravity/instances"),
            ("GET", "/api/antigravity/workers"),
        }.issubset(routes))


if __name__ == "__main__":
    unittest.main()
