import atexit
import base64
import asyncio
import inspect
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"test_dedicated_{os.getpid()}.db"
os.environ["ANTIGRAVITY_HUB_DB"] = str(_TEST_DB_PATH)
atexit.register(lambda: _TEST_DB_PATH.unlink(missing_ok=True))

import src.parallel_cdp as parallel_cdp
from src.cdp_client import AntigravityCDP
from src.integrity_sync import encode_field_bytes, get_user_prompt_from_payload
from src.parallel_cdp import ParallelCDPManager
from src.project_handlers import _save_chat_attachments


class FailingSession:
    def __init__(self):
        self.closed = False

    async def ws_connect(self, _url):
        raise OSError("simulated connection failure")

    async def close(self):
        self.closed = True


class IdleSocket:
    def __init__(self):
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Future()

    async def close(self):
        self.closed = True


class SuccessfulSession:
    def __init__(self):
        self.closed = False
        self.socket = IdleSocket()

    async def ws_connect(self, _url):
        return self.socket

    async def close(self):
        self.closed = True


class CDPErrorResponseSocket:
    def __init__(self, client):
        self.client = client
        self.closed = False

    async def send_json(self, payload):
        self.client.pending[payload["id"]].set_result({
            "id": payload["id"],
            "error": {
                "code": -32601,
                "message": f"Unknown method {payload['method']}",
            },
        })


class DelayedComposerClient(AntigravityCDP):
    def __init__(self, *, focus_confirmed=True, fail_atomic_insert=False):
        super().__init__()
        self.ready_checks = 0
        self.key_events = []
        self.focus_confirmed = focus_confirmed
        self.fail_atomic_insert = fail_atomic_insert

    async def evaluate(self, expression, timeout=60.0):
        del timeout
        if "textMatches" in expression and "sendEnabled" in expression:
            self.ready_checks += 1
            ready = self.ready_checks >= 3
            return {
                "inputFound": True,
                "textMatches": ready,
                "sendEnabled": ready,
                "ready": ready,
            }
        if "return value.replace(" in expression and "=== ''" in expression:
            return True
        if "document.activeElement === input" in expression:
            return self.focus_confirmed
        raise AssertionError(f"Unexpected expression: {expression}")

    async def call_cdp(self, method, params, timeout=10.0):
        del timeout
        if method == "Input.insertText" and self.fail_atomic_insert:
            raise RuntimeError("Input.insertText unavailable")
        self.key_events.append((method, params))
        return {"result": {}}


class AttachmentInputClient(AntigravityCDP):
    def __init__(self):
        super().__init__()
        self.file_input_payload = None

    async def call_cdp(self, method, params, timeout=10.0):
        del timeout
        if method == "DOM.getDocument":
            return {"result": {"root": {"nodeId": 1}}}
        if method == "DOM.querySelector":
            self.asserted_selector = params["selector"]
            return {"result": {"nodeId": 7}}
        if method == "DOM.setFileInputFiles":
            self.file_input_payload = params
            return {}
        raise AssertionError(f"Unexpected CDP method: {method}")

    async def evaluate(self, expression, timeout=60.0):
        del timeout
        if "Array.from(document.querySelectorAll('img')).filter" in expression:
            return 1
        return {
            "fileCount": 1,
            "matchedNames": 0,
            "expectedCount": 1,
            "mediaCount": 2,
            "sendEnabled": True,
        }


class ComposerRaceClient:
    def __init__(self, chat_id, *, fail_first_text=False):
        self.chat_id = chat_id
        self.fail_first_text = fail_first_text
        self.inject_count = 0
        self.text_attempts = 0
        self.state_checks = 0

    async def inject_bridge(self):
        self.inject_count += 1

    async def get_active_conversation_id(self):
        return self.chat_id

    async def set_input_text_native(self, _message):
        self.text_attempts += 1
        return not self.fail_first_text or self.text_attempts >= 2

    async def evaluate(self, expression, timeout=5):
        del timeout
        if "getComposerState" in expression:
            self.state_checks += 1
            if self.state_checks == 1:
                return {
                    "ready": False,
                    "inputFound": True,
                    "modelLoading": True,
                    "reason": "model-loading",
                }
            if self.state_checks == 2:
                return {
                    "ready": False,
                    "inputFound": True,
                    "stableSamples": 2,
                    "reason": "composer-stabilizing",
                }
            return {
                "ready": True,
                "inputFound": True,
                "stableSamples": 3,
                "reason": "ready",
            }
        if "diagnose" in expression:
            return {"inputFound": True, "reason": "react-remounted"}
        if "prepareAndSend" in expression:
            return {
                "success": True,
                "submissionMethod": "send-button",
            }
        raise AssertionError(f"Unexpected expression: {expression}")


class FakeWindowManager(ParallelCDPManager):
    def __init__(self, fail_navigation=False):
        super().__init__()
        self.fail_navigation = fail_navigation
        self.open_count = 0
        self.navigations = []
        self.targets = {}
        self.target = {
            "id": "duplicate-target-1",
            "url": "https://127.0.0.1:9999/c/example",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/duplicate-target-1",
        }

    async def get_devtools_port(self):
        return 9222

    async def _get_target_by_id(self, _port, target_id):
        return self.targets.get(target_id)

    async def get_all_page_targets(self, _port):
        return list(self.targets.values())

    async def _inspect_target_runtime(self, target):
        return {
            "role": "duplicate",
            "stamp": parallel_cdp._WINDOW_STAMPS.get(target["id"]) or "AG-01",
            "chat_id": target.get("active_chat"),
            "composer_visible": True,
            "has_draft": False,
        }

    async def open_duplicate_window(self, _port=None):
        self.open_count += 1
        self.targets[self.target["id"]] = self.target
        return self.target

    async def close_target_window(self, target):
        target_id = target["id"]
        self.targets.pop(target_id, None)
        parallel_cdp._DUPLICATE_TARGET_IDS.discard(target_id)
        parallel_cdp._WORKER_STATES.pop(target_id, None)
        parallel_cdp._WINDOW_STAMPS.pop(target_id, None)
        self._unbind_target(target_id)

    async def navigate_target_to_chat(
        self,
        target,
        chat_id,
        minimize=True,
        section=None,
    ):
        if self.fail_navigation:
            raise TimeoutError("simulated composer timeout")
        self.navigations.append((chat_id, section))
        target["active_chat"] = chat_id
        return {
            "target_id": target["id"],
            "chat_id": chat_id,
            "ready": True,
            "minimized": minimize,
            "reused": False,
        }


class DeletionGateManager(ParallelCDPManager):
    def __init__(
        self,
        chat_id,
        *,
        discovery_runtime=None,
        recheck_runtime=None,
        primary_runtime=None,
        final_primary_runtime=None,
        extra_worker_runtime=None,
        close_confirmed=True,
        target_disappears=None,
        discovery_error=None,
    ):
        super().__init__()
        self.chat_id = chat_id
        self.target = {
            "id": "delete-target",
            "webSocketDebuggerUrl": (
                "ws://127.0.0.1:9222/devtools/page/delete-target"
            ),
        }
        self.discovery_runtime = discovery_runtime
        self.recheck_runtime = recheck_runtime
        self.primary_runtime = primary_runtime
        self.final_primary_runtime = final_primary_runtime
        self.extra_worker_runtime = extra_worker_runtime
        self.close_confirmed = close_confirmed
        self.target_disappears = (
            close_confirmed
            if target_disappears is None
            else target_disappears
        )
        self.target_closed = False
        self.discovery_error = discovery_error
        self.close_requests = 0
        self.lock_observations = []
        self.discovery_mutation_flags = []

    async def get_devtools_port(self):
        return 9222

    async def _discover_window_pool(self, _port, *, mutate_registry=True):
        self.discovery_mutation_flags.append(mutate_registry)
        if self.discovery_error is not None:
            raise self.discovery_error
        workers = []
        if self.discovery_runtime is not None:
            workers.append({
                **self.target,
                "runtime": dict(self.discovery_runtime),
            })
        if self.extra_worker_runtime is not None:
            workers.append({
                "id": "extra-target",
                "webSocketDebuggerUrl": (
                    "ws://127.0.0.1:9222/devtools/page/extra-target"
                ),
                "runtime": dict(self.extra_worker_runtime),
            })
        primary = None
        primary_runtime = self.primary_runtime
        if len(self.discovery_mutation_flags) > 1:
            primary_runtime = self.final_primary_runtime or primary_runtime
        if primary_runtime is not None:
            primary = {
                "id": "primary-target",
                "webSocketDebuggerUrl": (
                    "ws://127.0.0.1:9222/devtools/page/primary-target"
                ),
                "runtime": dict(primary_runtime),
            }
        return workers, primary

    async def _get_target_by_id(self, _port, target_id):
        if self.target_closed:
            return None
        return self.target if target_id == self.target["id"] else None

    async def _inspect_target_runtime(self, target):
        self.lock_observations.append((
            parallel_cdp._chat_lock(self.chat_id).locked(),
            parallel_cdp._target_lock(target["id"]).locked(),
        ))
        if isinstance(self.recheck_runtime, Exception):
            raise self.recheck_runtime
        return dict(self.recheck_runtime or {})

    async def _request_target_window_close(self, target):
        self.close_requests += 1
        self.lock_observations.append((
            parallel_cdp._chat_lock(self.chat_id).locked(),
            parallel_cdp._target_lock(target["id"]).locked(),
        ))
        if self.close_confirmed and self.target_disappears:
            self.target_closed = True
        return self.close_confirmed


class DistinctWindowManager(FakeWindowManager):
    def __init__(self):
        super().__init__()
        self.active_creations = 0
        self.max_active_creations = 0

    async def _get_target_by_id(self, _port, target_id):
        return self.targets.get(target_id)

    async def open_duplicate_window(self, _port=None):
        self.open_count += 1
        target_id = f"duplicate-target-{self.open_count}"
        target = {
            "id": target_id,
            "url": "https://127.0.0.1:9999/",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
        }
        self.targets[target_id] = target
        return target

    async def create_project_chat_with_message(
        self, target, _workspace_path, message, minimize=True, project_name=""
    ):
        del project_name
        self.active_creations += 1
        self.max_active_creations = max(
            self.max_active_creations,
            self.active_creations,
        )
        try:
            await __import__("asyncio").sleep(0.05)
            chat_id = message
            self.bind_chat_target(chat_id, target["id"])
            return {
                "target_id": target["id"],
                "chat_id": chat_id,
                "ready": True,
                "minimized": minimize,
                "reused": False,
            }
        finally:
            self.active_creations -= 1

    async def create_normal_chat_with_message(
        self, target, message, minimize=True
    ):
        self.active_creations += 1
        self.max_active_creations = max(
            self.max_active_creations,
            self.active_creations,
        )
        try:
            await __import__("asyncio").sleep(0.05)
            chat_id = message
            self.bind_chat_target(chat_id, target["id"])
            return {
                "target_id": target["id"],
                "chat_id": chat_id,
                "ready": True,
                "minimized": minimize,
                "reused": False,
            }
        finally:
            self.active_creations -= 1


class ModelSelectionClient:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.current_model = "Gemini 3.6 Flash (High)"
        self.bridge_injected = False
        self.minimized = False

    async def get_active_conversation_id(self):
        return self.chat_id

    async def inject_bridge(self):
        self.bridge_injected = True
        return "bridge_injected"

    async def evaluate(self, expression, timeout=5):
        del timeout
        if "window.__agBridge.selectModel" in expression:
            self.current_model = (
                "Gemini 3.6 Flash Medium"
                if "Gemini 3.6 Flash" in expression
                else "Claude Sonnet 4.6 (Thinking)"
            )
            return True
        if '[aria-label^="Select model"]' in expression:
            return self.current_model
        if "window.electronNative?.minimize" in expression:
            self.minimized = True
            return True
        raise AssertionError(f"Unexpected expression: {expression}")


class ModelSelectionManager(FakeWindowManager):
    def __init__(self, chat_id):
        super().__init__()
        self.chat_id = chat_id
        self.target["active_chat"] = chat_id
        self.targets[self.target["id"]] = self.target
        self.bind_chat_target(chat_id, self.target["id"])
        parallel_cdp._WINDOW_STAMPS[self.target["id"]] = "AG-07"
        self.client = ModelSelectionClient(chat_id)

    async def ensure_chat_window(
        self,
        chat_id,
        minimize=True,
        section=None,
        reserve=False,
    ):
        del minimize, section, reserve
        self.asserted_chat_id = chat_id
        return {
            "target_id": self.target["id"],
            "window_id": "AG-07",
            "chat_id": chat_id,
            "ready": True,
        }

    async def prepare_target_for_automation(self, target):
        self.prepared_target = target["id"]
        return {"success": True}

    async def get_client_for_target(self, _ws_url):
        return self.client


class MessageDeliveryClient(ComposerRaceClient):
    async def evaluate(self, expression, timeout=5):
        if "window.electronNative?.minimize" in expression:
            return False
        return await super().evaluate(expression, timeout=timeout)


class MessageDeliveryManager(FakeWindowManager):
    def __init__(self, chat_id):
        super().__init__()
        self.chat_id = chat_id
        self.target["active_chat"] = chat_id
        self.targets[self.target["id"]] = self.target
        self.bind_chat_target(chat_id, self.target["id"])
        self.client = MessageDeliveryClient(chat_id)

    async def ensure_chat_window(
        self,
        chat_id,
        minimize=True,
        section=None,
        reserve=False,
    ):
        del minimize, section, reserve
        return {
            "target_id": self.target["id"],
            "window_id": "AG-09",
            "chat_id": chat_id,
            "ready": True,
        }

    async def prepare_target_for_automation(self, target):
        del target
        return {"success": True}

    async def get_client_for_target(self, _ws_url):
        return self.client


class DuplicateSourceClient:
    def __init__(self, manager, target_id):
        self.manager = manager
        self.target_id = target_id

    async def evaluate(self, expression, timeout=5):
        del timeout
        if "getWindowRole" in expression:
            return None
        if "typeof window.electronNative?.openDuplicateWindow" in expression:
            return True
        if "window.electronNative.openDuplicateWindow" in expression:
            self.manager.duplicate_sources.append(self.target_id)
            duplicate_id = f"duplicate-{len(self.manager.duplicate_sources)}"
            self.manager.targets.insert(
                0,
                {
                    "id": duplicate_id,
                    "url": "https://127.0.0.1:9999/",
                    "webSocketDebuggerUrl": (
                        f"ws://127.0.0.1:9222/devtools/page/{duplicate_id}"
                    ),
                },
            )
            return {"success": True}
        raise AssertionError(f"Unexpected expression: {expression}")


class DuplicateSourceManager(ParallelCDPManager):
    def __init__(self):
        super().__init__()
        self.targets = [
            {
                "id": "primary",
                "url": "https://127.0.0.1:9999/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/primary",
            }
        ]
        self.duplicate_sources = []

    async def get_all_page_targets(self, _port):
        return list(self.targets)

    async def get_client_for_target(self, ws_url):
        return DuplicateSourceClient(self, ws_url.rsplit("/", 1)[-1])


class TestCDPConnectionLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_failed_connect_closes_new_aiohttp_session(self):
        session = FailingSession()
        client = AntigravityCDP()

        with patch("src.cdp_client.aiohttp.ClientSession", return_value=session):
            with self.assertRaises(OSError):
                await client.connect("ws://127.0.0.1:1/devtools/page/missing")

        self.assertTrue(session.closed)
        self.assertIsNone(client._session)
        self.assertIsNone(client.ws)

    async def test_connect_enables_runtime_and_page_events(self):
        session = SuccessfulSession()
        client = AntigravityCDP()
        client.call_cdp = AsyncMock(return_value={})

        with patch("src.cdp_client.aiohttp.ClientSession", return_value=session):
            await client.connect("ws://127.0.0.1:9222/devtools/page/main")

        self.assertEqual(
            client.call_cdp.await_args_list,
            [
                unittest.mock.call("Runtime.enable", {}, timeout=5),
                unittest.mock.call("Page.enable", {}, timeout=5),
            ],
        )
        await client.disconnect()
        self.assertTrue(session.closed)

    async def test_call_cdp_raises_top_level_protocol_error(self):
        client = AntigravityCDP()
        client._connected = True
        client.ws = CDPErrorResponseSocket(client)

        with self.assertRaisesRegex(
            RuntimeError,
            r"Input\.insertText failed \(-32601\)",
        ):
            await client.call_cdp(
                "Input.insertText",
                {"text": "hello"},
            )

        self.assertEqual(client.pending, {})

    async def test_reconnect_preserves_pinned_worker_websocket(self):
        client = AntigravityCDP()
        worker_ws = "ws://127.0.0.1:60000/devtools/page/worker-7"
        client.ws_url = worker_ws
        client._pinned_ws_url = worker_ws
        client.devtools_port = 60000
        client.backend_port = 60001
        observed = []

        async def fake_disconnect():
            return None

        async def fake_connect(ws_url=None):
            observed.append((ws_url, client.ws_url, client.devtools_port, client.backend_port))

        client.disconnect = fake_disconnect
        client.connect = fake_connect
        await client.reconnect()

        self.assertEqual(observed, [(worker_ws, None, None, None)])

    async def test_native_input_waits_for_delayed_send_button(self):
        client = DelayedComposerClient()

        accepted = await client.set_input_text_native("second message")

        self.assertTrue(accepted)
        self.assertEqual(client.ready_checks, 3)
        insert_calls = [
            params
            for method, params in client.key_events
            if method == "Input.insertText"
        ]
        self.assertEqual(insert_calls, [{"text": "second message"}])
        self.assertFalse(
            any(
                method == "Input.dispatchKeyEvent"
                and params.get("type") == "char"
                for method, params in client.key_events
            )
        )

    async def test_native_input_rejects_unconfirmed_composer_focus(self):
        client = DelayedComposerClient(focus_confirmed=False)

        accepted = await client.set_input_text_native("must not be typed")

        self.assertFalse(accepted)
        self.assertEqual(client.key_events, [])

    async def test_native_input_falls_back_when_atomic_insert_is_unavailable(self):
        client = DelayedComposerClient(fail_atomic_insert=True)

        accepted = await client.set_input_text_native("fallback")

        self.assertTrue(accepted)
        inserted_characters = [
            params["text"]
            for method, params in client.key_events
            if method == "Input.dispatchKeyEvent"
            and params.get("type") == "char"
        ]
        self.assertEqual("".join(inserted_characters), "fallback")

    async def test_native_input_chunks_long_unicode_multiline_fallback_exactly(self):
        client = DelayedComposerClient(fail_atomic_insert=True)
        message = "  süß 😺\n\tböse  " * 80

        accepted = await client.set_input_text_native(message)

        self.assertTrue(accepted)
        chunks = [
            params["text"]
            for method, params in client.key_events
            if method == "Input.dispatchKeyEvent"
            and params.get("type") == "char"
        ]
        self.assertEqual("".join(chunks), message)
        self.assertTrue(
            all(
                len(chunk.encode("utf-16-le")) // 2 <= 4
                for chunk in chunks
            )
        )
        self.assertGreater(len(chunks), 1)

    def test_native_fallback_chunks_never_split_surrogate_pairs(self):
        message = "ab😺cd🧶ef"

        chunks = AntigravityCDP._key_event_chunks(message)

        self.assertEqual("".join(chunks), message)
        self.assertTrue(
            all(
                len(chunk.encode("utf-16-le")) // 2 <= 4
                for chunk in chunks
            )
        )

    async def test_native_input_preserves_unicode_multiline_and_edge_whitespace(self):
        client = DelayedComposerClient()
        message = "  süß 😺\n\tböse  "

        accepted = await client.set_input_text_native(message)

        self.assertTrue(accepted)
        insert_calls = [
            params
            for method, params in client.key_events
            if method == "Input.insertText"
        ]
        self.assertEqual(insert_calls, [{"text": message}])

    async def test_native_input_rejects_non_string_payload(self):
        client = DelayedComposerClient()

        with self.assertRaisesRegex(TypeError, "must be a string"):
            await client.set_input_text_native({"text": "not a string"})

        self.assertEqual(client.key_events, [])

    async def test_prepare_automation_requires_native_capability(self):
        class MissingAutomationClient:
            async def evaluate(self, expression, timeout=5):
                del timeout
                if "typeof window.electronNative?.prepareAutomation" in expression:
                    return False
                raise AssertionError(f"Unexpected expression: {expression}")

        manager = ParallelCDPManager()
        target = {
            "id": "worker-without-automation",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/worker",
        }
        with (
            patch.object(
                manager,
                "get_client_for_target",
                new=AsyncMock(return_value=MissingAutomationClient()),
            ),
            patch("src.parallel_cdp.asyncio.sleep", new=AsyncMock()),
        ):
            with self.assertRaisesRegex(RuntimeError, "prepareAutomation"):
                await manager.prepare_target_for_automation(target)

    async def test_composer_waits_through_model_loading_and_react_stabilization(self):
        client = ComposerRaceClient("chat-a")

        with patch(
            "src.parallel_cdp.asyncio.sleep",
            new=AsyncMock(),
        ):
            state = await ParallelCDPManager._wait_for_message_composer(
                client,
                attempts=3,
            )

        self.assertTrue(state["ready"])
        self.assertEqual(client.state_checks, 3)
        self.assertGreaterEqual(client.inject_count, 1)

    async def test_failed_native_input_retries_on_same_chat_worker(self):
        client = ComposerRaceClient("chat-a", fail_first_text=True)
        manager = ParallelCDPManager()
        parallel_cdp._WINDOW_STAMPS["target-a"] = "AG-02"

        with patch(
            "src.parallel_cdp.asyncio.sleep",
            new=AsyncMock(),
        ):
            attempt = await manager._enter_message_with_retries(
                client,
                target_id="target-a",
                chat_id="chat-a",
                message="retry me",
                attempts=3,
            )

        self.assertEqual(attempt, 2)
        self.assertEqual(client.text_attempts, 2)
        self.assertEqual(client.chat_id, "chat-a")

    async def test_first_message_waits_and_retries_before_single_submit(self):
        client = ComposerRaceClient("chat-new", fail_first_text=True)

        with (
            patch(
                "src.parallel_cdp.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch(
                "src.integrity_sync.get_integrity_chat_history",
                return_value={
                    "history": [{
                        "idx": 1,
                        "role": "user",
                        "content": "first message",
                    }]
                },
            ),
        ):
            conversation_id, submitted = (
                await ParallelCDPManager._submit_first_message(
                    client,
                    "first message",
                )
            )

        self.assertEqual(conversation_id, "chat-new")
        self.assertEqual(client.text_attempts, 2)
        self.assertTrue(submitted["success"])

    async def test_native_attachment_uses_real_file_input(self):
        client = AttachmentInputClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "preview.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

            result = await client.set_file_input_files([str(image_path)])

        self.assertTrue(result["success"])
        self.assertEqual(client.asserted_selector, 'input[type="file"]')
        self.assertEqual(client.file_input_payload["nodeId"], 7)
        self.assertEqual(
            client.file_input_payload["files"],
            [str(image_path.resolve())],
        )


class TestAttachmentValidation(unittest.TestCase):
    def test_data_url_is_validated_and_filename_is_sanitized(self):
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.project_handlers.Path.home", return_value=Path(temp_dir)):
                saved = _save_chat_attachments(
                    [{
                        "name": "../unsafe.png",
                        "type": "image/png",
                        "data": f"data:image/png;base64,{encoded}",
                    }],
                    storage_key="chat:test",
                )

            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["file_name"], "unsafe.png")
            self.assertTrue(Path(saved[0]["file_path"]).is_file())
            self.assertIn("chat_test", saved[0]["file_path"])

    def test_invalid_base64_is_rejected_before_native_delivery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.project_handlers.Path.home", return_value=Path(temp_dir)):
                with self.assertRaisesRegex(ValueError, "invalid base64"):
                    _save_chat_attachments(
                        [{
                            "name": "broken.png",
                            "type": "image/png",
                            "data": "data:image/png;base64,not-valid!",
                        }],
                        storage_key="chat-a",
                    )


class TestDedicatedChatWindowMapping(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parallel_cdp._CHAT_TARGET_IDS.clear()
        parallel_cdp._DUPLICATE_TARGET_IDS.clear()
        parallel_cdp._WINDOW_STAMPS.clear()
        parallel_cdp._NEXT_WINDOW_STAMP = 1
        parallel_cdp._PRIMARY_TARGET_ID = None
        parallel_cdp._WINDOW_LOCK = None
        parallel_cdp._CHAT_LOCKS.clear()
        parallel_cdp._TARGET_LOCKS.clear()
        parallel_cdp._WORKER_STATES.clear()
        for task in parallel_cdp._WORKER_MONITORS.values():
            task.cancel()
        parallel_cdp._WORKER_MONITORS.clear()
        parallel_cdp._POOL_WAITERS = 0

    async def test_one_duplicate_is_reused_for_the_same_chat(self):
        manager = FakeWindowManager()

        first = await manager.ensure_chat_window("chat-a")
        second = await manager.ensure_chat_window("chat-a")

        self.assertEqual(manager.open_count, 1)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(parallel_cdp._CHAT_TARGET_IDS["chat-a"], "duplicate-target-1")

    async def test_failed_navigation_does_not_leave_a_mapping(self):
        manager = FakeWindowManager(fail_navigation=True)

        with self.assertRaises(TimeoutError):
            await manager.ensure_chat_window("chat-b")

        self.assertNotIn("chat-b", parallel_cdp._CHAT_TARGET_IDS)

    def _bind_deletion_worker(self, chat_id):
        target_id = "delete-target"
        ParallelCDPManager.bind_chat_target(chat_id, target_id)
        parallel_cdp._WINDOW_STAMPS[target_id] = "AG-07"
        state = parallel_cdp._worker_state(target_id)
        state.update({
            "state": "idle",
            "activity_known": True,
            "chat_id": chat_id,
            "reserved": False,
            "purpose": "chat",
        })

    async def test_chat_deletion_rechecks_runtime_under_chat_and_target_locks(self):
        chat_id = "11111111-1111-4111-8111-111111111111"
        self._bind_deletion_worker(chat_id)
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime={
                "role": "duplicate",
                "stamp": "AG-07",
                "chat_id": chat_id,
                "runtime_reachable": True,
                "activity_observed": True,
                "native_activity": "idle",
                "has_draft": False,
            },
            recheck_runtime={
                "role": "duplicate",
                "stamp": "AG-07",
                "chat_id": chat_id,
                "activity_observed": True,
                "native_activity": "working",
                "has_draft": False,
            },
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_busy")
        self.assertEqual(result["worker"]["activity"], "working")
        self.assertEqual(manager.lock_observations, [(True, True)])
        self.assertEqual(manager.close_requests, 0)
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS[chat_id],
            "delete-target",
        )

    async def test_chat_deletion_rejects_loaded_chat_mismatch(self):
        chat_id = "22222222-2222-4222-8222-222222222222"
        self._bind_deletion_worker(chat_id)
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime={
                "role": "duplicate",
                "stamp": "AG-07",
                "chat_id": chat_id,
                "runtime_reachable": True,
            },
            recheck_runtime={
                "role": "duplicate",
                "stamp": "AG-07",
                "chat_id": "33333333-3333-4333-8333-333333333333",
                "activity_observed": True,
                "native_activity": "idle",
                "has_draft": False,
            },
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_busy")
        self.assertEqual(result["worker"]["binding_status"], "mismatch")
        self.assertEqual(result["worker"]["detail_code"], "conversation_mismatch")
        self.assertEqual(manager.close_requests, 0)
        self.assertIn(chat_id, parallel_cdp._CHAT_TARGET_IDS)

    async def test_chat_deletion_rejects_main_window_bound_to_chat(self):
        chat_id = "44444444-4444-4444-8444-444444444444"
        manager = DeletionGateManager(
            chat_id,
            primary_runtime={
                "role": "primary",
                "chat_id": chat_id,
                "runtime_reachable": True,
                "activity_observed": False,
                "native_activity": "unknown",
                "has_draft": False,
            },
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_busy")
        self.assertEqual(result["worker"]["instance_id"], "MAIN")
        self.assertEqual(result["worker"]["binding_status"], "confirmed")

    async def test_chat_deletion_requires_confirmed_native_close(self):
        chat_id = "55555555-5555-4555-8555-555555555555"
        self._bind_deletion_worker(chat_id)
        runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=runtime,
            recheck_runtime=runtime,
            close_confirmed=False,
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_state_unavailable")
        self.assertEqual(result["detail_code"], "window_close_unconfirmed")
        self.assertEqual(manager.close_requests, 1)
        self.assertIn(chat_id, parallel_cdp._CHAT_TARGET_IDS)
        self.assertIn("delete-target", parallel_cdp._WORKER_STATES)

    async def test_chat_deletion_requires_target_to_disappear_after_close(self):
        chat_id = "56565656-5656-4565-8565-565656565656"
        self._bind_deletion_worker(chat_id)
        runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=runtime,
            recheck_runtime=runtime,
            close_confirmed=True,
            target_disappears=False,
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_state_unavailable")
        self.assertEqual(result["detail_code"], "window_close_unconfirmed")
        self.assertIn(chat_id, parallel_cdp._CHAT_TARGET_IDS)

    async def test_native_close_false_is_preserved(self):
        manager = ParallelCDPManager()
        client = AsyncMock()
        client.evaluate.return_value = False
        manager.get_client_for_target = AsyncMock(return_value=client)

        closed = await manager._request_target_window_close({
            "webSocketDebuggerUrl": "ws://example.test/target",
        })

        self.assertFalse(closed)
        expression = client.evaluate.await_args.args[0]
        self.assertIn("closed !== false", expression)

    async def test_close_target_window_cancellation_still_cleans_registry(self):
        chat_id = "57575757-5757-4575-8575-575757575757"
        self._bind_deletion_worker(chat_id)
        manager = ParallelCDPManager()
        manager._request_target_window_close = AsyncMock(
            side_effect=asyncio.CancelledError,
        )

        with self.assertRaises(asyncio.CancelledError):
            await manager.close_target_window({
                "id": "delete-target",
                "webSocketDebuggerUrl": "ws://example.test/target",
            })

        self.assertNotIn(chat_id, parallel_cdp._CHAT_TARGET_IDS)
        self.assertNotIn("delete-target", parallel_cdp._WORKER_STATES)

    async def test_target_lock_cleanup_waits_for_queued_user_then_removes_lock(self):
        target_id = "delete-target"
        target_lock = parallel_cdp._target_lock(target_id)
        await target_lock.acquire()
        queued_entered = asyncio.Event()
        release_queued = asyncio.Event()

        async def queued_user():
            async with target_lock:
                queued_entered.set()
                await release_queued.wait()

        queued_task = asyncio.create_task(queued_user())
        await asyncio.sleep(0)
        target_lock.release()
        cleanup_task = asyncio.create_task(
            ParallelCDPManager._forget_target_lock_when_unused(
                target_id,
                target_lock,
            )
        )

        await queued_entered.wait()
        self.assertIn(target_id, parallel_cdp._TARGET_LOCKS)
        release_queued.set()
        await asyncio.gather(queued_task, cleanup_task)

        self.assertNotIn(target_id, parallel_cdp._TARGET_LOCKS)

    async def test_chat_deletion_requires_verified_duplicate_role(self):
        chat_id = "58585858-5858-4585-8585-585858585858"
        self._bind_deletion_worker(chat_id)
        discovery_runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=discovery_runtime,
            recheck_runtime={
                **discovery_runtime,
                "role": None,
            },
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_state_unavailable")
        self.assertEqual(result["detail_code"], "worker_role_unverified")
        self.assertEqual(manager.close_requests, 0)

    async def test_chat_deletion_closes_exact_confirmed_idle_worker(self):
        chat_id = "66666666-6666-4666-8666-666666666666"
        self._bind_deletion_worker(chat_id)
        runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=runtime,
            recheck_runtime=runtime,
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertTrue(result["allowed"])
        self.assertTrue(result["window_closed"])
        self.assertEqual(manager.close_requests, 1)
        self.assertEqual(manager.lock_observations, [(True, True), (True, True)])
        self.assertNotIn(chat_id, parallel_cdp._CHAT_TARGET_IDS)
        self.assertNotIn("delete-target", parallel_cdp._WORKER_STATES)
        self.assertNotIn("delete-target", parallel_cdp._TARGET_LOCKS)
        self.assertEqual(manager.discovery_mutation_flags, [False, False])

    async def test_chat_deletion_holds_chat_lock_through_file_deletion(self):
        chat_id = "67676767-6767-4767-8767-676767676767"
        self._bind_deletion_worker(chat_id)
        runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=runtime,
            recheck_runtime=runtime,
        )
        deletion_started = threading.Event()
        allow_deletion = threading.Event()

        def delete_files(conversation_id):
            self.assertEqual(conversation_id, chat_id)
            self.assertTrue(parallel_cdp._chat_lock(chat_id).locked())
            deletion_started.set()
            self.assertTrue(allow_deletion.wait(timeout=2))
            return {"success": True, "found": True}

        deletion_task = asyncio.create_task(
            manager.prepare_chat_deletion(
                chat_id,
                delete_callback=delete_files,
            )
        )
        self.assertTrue(
            await asyncio.to_thread(deletion_started.wait, 2),
        )

        competitor_entered = asyncio.Event()

        async def competing_operation():
            async with parallel_cdp._chat_lock(chat_id):
                competitor_entered.set()

        competitor_task = asyncio.create_task(competing_operation())
        await asyncio.sleep(0)
        self.assertFalse(competitor_entered.is_set())

        allow_deletion.set()
        result = await deletion_task
        await competitor_task

        self.assertTrue(competitor_entered.is_set())
        self.assertEqual(
            result["deletion_result"],
            {"success": True, "found": True},
        )

    async def test_cancelled_delete_holds_chat_lock_until_thread_finishes(self):
        chat_id = "67777777-6777-4777-8777-677777777777"
        manager = DeletionGateManager(chat_id)
        deletion_started = threading.Event()
        allow_deletion = threading.Event()

        def delete_files(_conversation_id):
            deletion_started.set()
            self.assertTrue(allow_deletion.wait(timeout=2))
            return {"success": True, "found": True}

        deletion_task = asyncio.create_task(
            manager.prepare_chat_deletion(
                chat_id,
                delete_callback=delete_files,
            )
        )
        self.assertTrue(await asyncio.to_thread(deletion_started.wait, 2))
        deletion_task.cancel()
        await asyncio.sleep(0)

        competitor_entered = asyncio.Event()

        async def competing_operation():
            async with parallel_cdp._chat_lock(chat_id):
                competitor_entered.set()

        competitor_task = asyncio.create_task(competing_operation())
        await asyncio.sleep(0)
        self.assertFalse(competitor_entered.is_set())

        allow_deletion.set()
        with self.assertRaises(asyncio.CancelledError):
            await deletion_task
        await competitor_task
        self.assertTrue(competitor_entered.is_set())

    async def test_chat_deletion_rechecks_main_after_target_lock_wait(self):
        chat_id = "68686868-6868-4868-8868-686868686868"
        self._bind_deletion_worker(chat_id)
        runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=runtime,
            recheck_runtime=runtime,
            primary_runtime={
                "role": "primary",
                "chat_id": None,
                "runtime_reachable": True,
            },
            final_primary_runtime={
                "role": "primary",
                "chat_id": chat_id,
                "runtime_reachable": True,
            },
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_busy")
        self.assertEqual(result["worker"]["instance_id"], "MAIN")
        self.assertEqual(manager.close_requests, 0)

    async def test_chat_deletion_blocks_if_any_worker_runtime_is_unreachable(self):
        chat_id = "69696969-6969-4969-8969-696969696969"
        self._bind_deletion_worker(chat_id)
        runtime = {
            "role": "duplicate",
            "stamp": "AG-07",
            "chat_id": chat_id,
            "runtime_reachable": True,
            "activity_observed": True,
            "native_activity": "idle",
            "has_draft": False,
        }
        manager = DeletionGateManager(
            chat_id,
            discovery_runtime=runtime,
            recheck_runtime=runtime,
            extra_worker_runtime={"runtime_reachable": False},
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_state_unavailable")
        self.assertEqual(result["detail_code"], "worker_runtime_unreachable")
        self.assertEqual(manager.close_requests, 0)

    async def test_chat_deletion_reports_discovery_failure_without_details(self):
        chat_id = "77777777-7777-4777-8777-777777777777"
        manager = DeletionGateManager(
            chat_id,
            discovery_error=ConnectionError("secret CDP endpoint failed"),
        )

        result = await manager.prepare_chat_deletion(chat_id)

        self.assertFalse(result["allowed"])
        self.assertEqual(result["code"], "conversation_state_unavailable")
        self.assertEqual(result["detail_code"], "desktop_state_unavailable")
        self.assertNotIn("secret", str(result))

    async def test_sequential_chats_reuse_one_idle_worker(self):
        manager = DistinctWindowManager()

        first = await manager.ensure_chat_window("chat-a")
        second = await manager.ensure_chat_window("chat-b")

        self.assertEqual(manager.open_count, 1)
        self.assertEqual(first["target_id"], second["target_id"])
        self.assertNotIn("chat-a", parallel_cdp._CHAT_TARGET_IDS)
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS["chat-b"],
            second["target_id"],
        )

    async def test_native_project_section_is_forwarded_to_navigation(self):
        manager = FakeWindowManager()

        await manager.ensure_chat_window(
            "chat-project",
            section="project-native-uuid",
        )

        self.assertEqual(
            manager.navigations,
            [("chat-project", "project-native-uuid")],
        )

    async def test_two_concurrent_new_chats_are_allocated_atomically(self):
        manager = DistinctWindowManager()

        first, second = await __import__("asyncio").gather(
            manager.create_new_project_chat_window("C:/repo", "new-chat-a"),
            manager.create_new_project_chat_window("C:/repo", "new-chat-b"),
        )

        self.assertEqual(manager.open_count, 2)
        self.assertEqual(manager.max_active_creations, 2)
        self.assertNotEqual(first["target_id"], second["target_id"])
        self.assertEqual(parallel_cdp._CHAT_TARGET_IDS["new-chat-a"], first["target_id"])
        self.assertEqual(parallel_cdp._CHAT_TARGET_IDS["new-chat-b"], second["target_id"])

    async def test_normal_and_project_chat_receive_distinct_parallel_windows(self):
        manager = DistinctWindowManager()

        normal, project = await __import__("asyncio").gather(
            manager.create_new_normal_chat_window("normal-chat"),
            manager.create_new_project_chat_window("C:/repo", "project-chat"),
        )

        self.assertEqual(manager.open_count, 2)
        self.assertEqual(manager.max_active_creations, 2)
        self.assertNotEqual(normal["target_id"], project["target_id"])
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS["normal-chat"],
            normal["target_id"],
        )
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS["project-chat"],
            project["target_id"],
        )

    async def test_worker_monitor_retries_catalog_errors_before_release(self):
        target_id = "monitor-retry-target"
        chat_id = "monitor-retry-chat"
        state = parallel_cdp._worker_state(target_id)
        state.update({
            "state": "working",
            "chat_id": chat_id,
            "reserved": True,
        })
        generation = float(state["updated_at"])
        running = [{"convo_id": chat_id, "status": "running", "archived": False}]
        complete = [{"convo_id": chat_id, "status": "complete", "archived": False}]
        catalog = Mock(
            side_effect=[
                RuntimeError("temporary catalog lock"),
                running,
                complete,
                complete,
                complete,
            ]
        )

        async def controlled_sleep(delay):
            if delay == parallel_cdp.IDLE_WORKER_TTL_SECONDS:
                raise asyncio.CancelledError()

        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                catalog,
            ),
            patch("src.parallel_cdp.asyncio.sleep", new=controlled_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await ParallelCDPManager._monitor_worker_until_idle(
                    target_id,
                    chat_id,
                    generation,
                )

        self.assertEqual(catalog.call_count, 5)
        self.assertEqual(state["state"], "idle")
        self.assertFalse(state["reserved"])

    async def test_worker_monitor_holds_approval_gate_then_resumes_working(self):
        target_id = "monitor-gate-target"
        chat_id = "monitor-gate-chat"
        state = parallel_cdp._worker_state(target_id)
        state.update({
            "state": "working",
            "chat_id": chat_id,
            "reserved": True,
        })
        generation = float(state["updated_at"])
        catalog = Mock(return_value=[{
            "convo_id": chat_id,
            "status": "running",
            "archived": False,
        }])
        gated_history = {
            "history": [{
                "idx": 8,
                "type": "tool_call",
                "status": 9,
                "requires_user_input": True,
            }],
        }
        resumed_history = {
            "history": [{
                "idx": 8,
                "type": "tool_call",
                "status": 7,
                "requires_user_input": False,
            }],
        }
        histories = Mock(side_effect=[gated_history, resumed_history])
        observed_states = []

        async def stop_after_resume(_delay):
            observed_states.append(
                (state["state"], state["detail"], state["reserved"])
            )
            if len(observed_states) >= 2:
                raise asyncio.CancelledError()

        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                catalog,
            ),
            patch(
                "src.integrity_sync.get_integrity_chat_history",
                histories,
            ),
            patch("src.parallel_cdp.asyncio.sleep", new=stop_after_resume),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await ParallelCDPManager._monitor_worker_until_idle(
                    target_id,
                    chat_id,
                    generation,
                )

        self.assertEqual(
            observed_states,
            [
                ("waiting_human", "Freigabe erforderlich", True),
                ("working", "Agent arbeitet", True),
            ],
        )
        self.assertEqual(state["state"], "working")
        self.assertTrue(state["reserved"])

    async def test_worker_monitor_ignores_superseded_approval_gate(self):
        target_id = "monitor-historical-gate-target"
        chat_id = "monitor-historical-gate-chat"
        state = parallel_cdp._worker_state(target_id)
        state.update({
            "state": "working",
            "chat_id": chat_id,
            "reserved": True,
        })
        generation = float(state["updated_at"])
        catalog = Mock(return_value=[{
            "convo_id": chat_id,
            "status": "running",
            "archived": False,
        }])
        historical_gate = {
            "history": [
                {
                    "idx": 8,
                    "type": "tool_call",
                    "status": 9,
                    "requires_user_input": True,
                },
                {
                    "idx": 9,
                    "type": "tool_output",
                    "output": "Skipped",
                },
            ],
        }

        async def stop_after_observation(_delay):
            raise asyncio.CancelledError()

        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                catalog,
            ),
            patch(
                "src.integrity_sync.get_integrity_chat_history",
                return_value=historical_gate,
            ),
            patch(
                "src.parallel_cdp.asyncio.sleep",
                new=stop_after_observation,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await ParallelCDPManager._monitor_worker_until_idle(
                    target_id,
                    chat_id,
                    generation,
                )

        self.assertEqual(state["state"], "working")
        self.assertTrue(state["reserved"])

    async def test_catalog_failure_resets_idle_grace_window(self):
        target_id = "monitor-grace-target"
        chat_id = "monitor-grace-chat"
        state = parallel_cdp._worker_state(target_id)
        state.update({
            "state": "working",
            "chat_id": chat_id,
            "reserved": True,
        })
        generation = float(state["updated_at"])
        complete = [{
            "convo_id": chat_id,
            "status": "complete",
            "archived": False,
        }]
        catalog = Mock(
            side_effect=[
                complete,
                RuntimeError("catalog unavailable during grace window"),
                complete,
            ]
        )
        sleep_calls = 0

        async def stop_after_recovered_observation(_delay):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 3:
                raise asyncio.CancelledError()

        fake_time = Mock(
            monotonic=Mock(side_effect=[0.0, 60.0, 61.0, 62.0])
        )
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                catalog,
            ),
            patch(
                "src.parallel_cdp.asyncio.sleep",
                new=stop_after_recovered_observation,
            ),
            patch("src.parallel_cdp.time", fake_time),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await ParallelCDPManager._monitor_worker_until_idle(
                    target_id,
                    chat_id,
                    generation,
                )

        self.assertEqual(catalog.call_count, 3)
        self.assertEqual(state["state"], "working")
        self.assertTrue(state["reserved"])

    async def test_running_worker_survives_legacy_thirty_minute_boundary(self):
        monitor_source = inspect.getsource(
            ParallelCDPManager._monitor_worker_until_idle
        )
        self.assertNotIn("< 1800", monitor_source)

        target_id = "monitor-long-target"
        chat_id = "monitor-long-chat"
        state = parallel_cdp._worker_state(target_id)
        state.update({
            "state": "working",
            "chat_id": chat_id,
            "reserved": True,
        })
        generation = float(state["updated_at"])
        catalog = Mock(
            return_value=[{
                "convo_id": chat_id,
                "status": "running",
                "archived": False,
            }]
        )

        async def stop_after_observation(_delay):
            raise asyncio.CancelledError()

        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                catalog,
            ),
            patch(
                "src.parallel_cdp.asyncio.sleep",
                new=stop_after_observation,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await ParallelCDPManager._monitor_worker_until_idle(
                    target_id,
                    chat_id,
                    generation,
                )

        catalog.assert_called_once()
        self.assertEqual(state["state"], "working")
        self.assertTrue(state["reserved"])

    async def test_duplicate_windows_are_always_spawned_from_primary(self):
        manager = DuplicateSourceManager()

        first = await manager.open_duplicate_window(9222)
        second = await manager.open_duplicate_window(9222)

        self.assertEqual(first["id"], "duplicate-1")
        self.assertEqual(second["id"], "duplicate-2")
        self.assertEqual(manager.duplicate_sources, ["primary", "primary"])
        self.assertEqual(first["window_id"], "AG-01")
        self.assertEqual(second["window_id"], "AG-02")

    def test_linked_display_name_wins_over_same_workspace_full_path(self):
        workspace = "D:/projects/workspace/Antigravity Agent"
        details = [
            {
                "index": 0,
                "text": r"d:\projects\workspace\Antigravity Agent",
            },
            {"index": 1, "text": "Antigravity Agent"},
        ]

        linked_match = ParallelCDPManager._choose_project_entry(
            details,
            workspace,
            project_name="Antigravity Agent",
        )
        path_match = ParallelCDPManager._choose_project_entry(details, workspace)

        self.assertEqual(linked_match["index"], 1)
        self.assertEqual(path_match["index"], 0)

    def test_linked_project_falls_back_to_exact_workspace_path(self):
        workspace = (
            "D:/projects/workspace/"
            "cat-search-hub-e2e-20260727"
        )
        details = [
            {
                "index": 0,
                "text": (
                    "d:\\projects\\workspace\\"
                    "cat-search-hub-e2e-20260727"
                ),
            },
        ]

        linked_match = ParallelCDPManager._choose_project_entry(
            details,
            workspace,
            project_name="cat-search-hub-e2e-20260727",
        )

        self.assertEqual(linked_match["index"], 0)


class TestConfirmedModelSelection(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        for task in list(parallel_cdp._WORKER_MONITORS.values()):
            task.cancel()
        parallel_cdp._WORKER_MONITORS.clear()
        parallel_cdp._CHAT_TARGET_IDS.clear()
        parallel_cdp._DUPLICATE_TARGET_IDS.clear()
        parallel_cdp._WINDOW_STAMPS.clear()
        parallel_cdp._WORKER_STATES.clear()
        parallel_cdp._TARGET_LOCKS.clear()
        parallel_cdp._CHAT_LOCKS.clear()

    async def test_model_is_confirmed_in_exact_chat_worker(self):
        chat_id = "11111111-1111-4111-8111-111111111111"
        manager = ModelSelectionManager(chat_id)

        result = await manager.select_model_for_chat(
            chat_id,
            "Claude Sonnet 4.6 (Thinking)",
        )

        self.assertEqual(manager.asserted_chat_id, chat_id)
        self.assertEqual(manager.prepared_target, "duplicate-target-1")
        self.assertTrue(manager.client.bridge_injected)
        self.assertTrue(manager.client.minimized)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["window_id"], "AG-07")
        self.assertEqual(result["model"], "Claude Sonnet 4.6 (Thinking)")

    async def test_model_effort_is_confirmed_without_parentheses(self):
        chat_id = "22222222-2222-4222-8222-222222222222"
        manager = ModelSelectionManager(chat_id)

        result = await manager.select_model_for_chat(
            chat_id,
            "Gemini 3.6 Flash (Medium)",
        )

        self.assertTrue(result["confirmed"])
        self.assertTrue(result["minimized"])
        self.assertEqual(result["model"], "Gemini 3.6 Flash (Medium)")
        self.assertEqual(result["native_model"], "Gemini 3.6 Flash Medium")

    async def test_post_submit_minimize_failure_is_only_a_warning(self):
        manager = MessageDeliveryManager("chat-delivery")

        with patch.object(
            ParallelCDPManager,
            "_start_worker_monitor",
        ):
            result = await manager.send_message_to_chat(
                "chat-delivery",
                "persist this",
                minimize=True,
            )

        self.assertTrue(result["submitted"]["success"])
        self.assertFalse(result["minimized"])
        self.assertIn("could not be minimized", result["warning"])
        self.assertNotEqual(
            parallel_cdp._worker_state(manager.target["id"])["state"],
            "error",
        )

    async def test_post_persist_stamp_and_minimize_failures_are_warnings(self):
        manager = MessageDeliveryManager("chat-created")

        with (
            patch.object(
                manager,
                "apply_window_stamp",
                new=AsyncMock(side_effect=RuntimeError("stamp unavailable")),
            ),
            patch.object(
                ParallelCDPManager,
                "_start_worker_monitor",
            ),
        ):
            result = await manager._finalize_created_chat_window(
                manager.target,
                "chat-created",
                minimize=True,
            )

        self.assertTrue(result["ready"])
        self.assertFalse(result["minimized"])
        self.assertEqual(len(result["warnings"]), 2)
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS["chat-created"],
            manager.target["id"],
        )

    async def test_post_persist_client_disconnect_is_warning_only(self):
        manager = MessageDeliveryManager("chat-created-disconnected")

        with (
            patch.object(
                manager,
                "apply_window_stamp",
                new=AsyncMock(side_effect=RuntimeError("stamp disconnected")),
            ),
            patch.object(
                manager,
                "get_client_for_target",
                new=AsyncMock(side_effect=RuntimeError("CDP disconnected")),
            ),
            patch.object(
                ParallelCDPManager,
                "_start_worker_monitor",
            ),
        ):
            result = await manager._finalize_created_chat_window(
                manager.target,
                "chat-created-disconnected",
                minimize=False,
            )

        self.assertTrue(result["ready"])
        self.assertFalse(result["minimized"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(
            parallel_cdp._CHAT_TARGET_IDS["chat-created-disconnected"],
            manager.target["id"],
        )


class TestDashboardDeliveryContract(unittest.TestCase):
    def test_dashboard_requires_verified_delivery(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("result.verified !== true", source)
        self.assertIn("created.verified !== true", source)
        self.assertIn("Zustellung wird vorbereitet", source)
        self.assertIn("result.pending_verification === true", source)
        self.assertIn("An Anti-Gravity gesendet · Bestätigung läuft", source)
        self.assertIn("Zugestellt ✓", source)
        handler_source = (
            PROJECT_ROOT / "src" / "project_handlers.py"
        ).read_text(encoding="utf-8")
        manager_source = (
            PROJECT_ROOT / "src" / "parallel_cdp.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"pending_verification": True', handler_source)
        self.assertIn("status=202", handler_source)
        self.assertIn("send_message_to_chat", handler_source)
        self.assertNotIn("SendUserCascadeMessage", handler_source)
        self.assertIn("set_input_text_native(message)", manager_source)
        self.assertIn("window.__agBridge.prepareAndSend('')", manager_source)
        self.assertIn("MAX_WORKERS", manager_source)
        self.assertIn("_allocate_worker_target", manager_source)
        self.assertIn("route_reused", manager_source)

    def test_dashboard_clears_composer_before_waiting_for_worker(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        send_start = source.index("async function sendIntegrityChatMessageForConvo")
        send_end = source.index("function startChatPollingForConvo", send_start)
        send_source = source[send_start:send_end]

        self.assertLess(
            send_source.index("clearChatComposerDraft(convoId, input);"),
            send_source.index("await ensureDedicatedAntigravityWindow(convoId);"),
        )
        self.assertIn("Anti-Gravity-Fenster wird gestartet", source)
        self.assertIn("setChatDeliveryPhase(convoId, \"error\"", source)
        self.assertIn("restoreChatComposerDraft(convoId, input, draft);", send_source)

    def test_dashboard_limits_stream_cursor_to_current_assistant_bubble(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function clearStreamingAssistantBubbles", source)
        self.assertIn("clearStreamingAssistantBubbles(convoId, bubble);", source)
        self.assertIn("!running || !winState.hasAssistantOutput", source)

    def test_dashboard_exposes_recording_start_live_and_stop_states(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        style = (PROJECT_ROOT / "dashboard" / "css" / "style.css").read_text(encoding="utf-8")

        self.assertIn('setVoiceUIForConvo(convoId, "starting")', source)
        self.assertIn('setVoiceUIForConvo(convoId, "recording")', source)
        self.assertIn('setVoiceUIForConvo(convoId, "stopping")', source)
        self.assertIn("chat-voice-elapsed", source)
        self.assertIn(".chat-mic-btn.is-recording", style)
        self.assertIn("background: #dc2626 !important;", style)

    def test_chat_header_actions_cannot_overflow_the_browser_card(self):
        source = (
            PROJECT_ROOT / "dashboard" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        style = (
            PROJECT_ROOT / "dashboard" / "css" / "style.css"
        ).read_text(encoding="utf-8")

        self.assertIn(">+ Normalchat</button>", source)
        self.assertIn("flex-direction: column;", style)
        self.assertIn(
            "grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);",
            style,
        )
        self.assertIn(
            ".antigravity-chat-create-actions .btn:last-child",
            style,
        )

    def test_new_project_chat_is_created_with_its_first_message(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        handler_source = (PROJECT_ROOT / "src" / "project_handlers.py").read_text(encoding="utf-8")
        self.assertIn('await openChatInWorkspace("new")', source)
        self.assertIn("mountChatWindowEmbedded(convoId)", source)
        self.assertIn("message: message", source)
        self.assertIn("attachments: sendAttachments", source)
        self.assertNotIn("await sendIntegrityChatMessageForConvo(created.convo_id)", source)
        self.assertIn('project.get("integrity_workspace_path")', handler_source)

    def test_dashboard_can_create_normal_and_project_conversations(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        handler_source = (PROJECT_ROOT / "src" / "project_handlers.py").read_text(encoding="utf-8")
        manager_source = (PROJECT_ROOT / "src" / "parallel_cdp.py").read_text(encoding="utf-8")

        self.assertIn("createIntegrityChat('normal')", source)
        self.assertIn("createIntegrityChat('project')", source)
        self.assertIn("conversation_type: conversationType", source)
        self.assertIn('conversation_type not in {"normal", "project"}', handler_source)
        self.assertIn("create_new_normal_chat_window", manager_source)

    def test_opening_a_chat_prepares_its_dedicated_window(self):
        source = (PROJECT_ROOT / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        manager_source = (PROJECT_ROOT / "src" / "parallel_cdp.py").read_text(encoding="utf-8")
        self.assertIn("ensureDedicatedAntigravityWindow(convoId)", source)
        self.assertIn("desktopWindowReady", source)
        self.assertIn("/api/antigravity/chats/", source)
        self.assertIn('[role=\\"combobox\\"]', manager_source)
        self.assertIn("prepare_target_for_automation(target)", manager_source)
        self.assertIn("allow_basename: bool = False", manager_source)
        self.assertIn("_choose_project_entry", manager_source)
        handler_source = (
            PROJECT_ROOT / "src" / "project_handlers.py"
        ).read_text(encoding="utf-8")
        self.assertIn("project_name=linked_project_name", handler_source)
        self.assertIn("scan_antigravity_conversation_catalog", handler_source)
        self.assertIn("apply_window_stamp(target)", manager_source)
        self.assertIn("window.window_id", source)

    def test_dashboard_locks_composer_until_model_confirmation(self):
        source = (
            PROJECT_ROOT / "dashboard" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            PROJECT_ROOT / "dashboard" / "css" / "style.css"
        ).read_text(encoding="utf-8")

        self.assertIn("setChatModelSwitching", source)
        self.assertIn("model-switch-lock", source)
        self.assertIn("data.confirmed === true", source)
        self.assertIn("winState.isModelSwitching", source)
        self.assertIn("renderMarkdownContent(msg.content)", source)
        self.assertIn("getToolOutputHtml", source)
        self.assertIn("chat-markdown-table-wrap", stylesheet)
        self.assertIn("modelSwitchSpin", stylesheet)

    def test_dashboard_and_cdp_accept_typed_values_and_native_attachments(self):
        source = (
            PROJECT_ROOT / "dashboard" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        client_source = (
            PROJECT_ROOT / "src" / "cdp_client.py"
        ).read_text(encoding="utf-8")
        manager_source = (
            PROJECT_ROOT / "src" / "parallel_cdp.py"
        ).read_text(encoding="utf-8")
        handler_source = (
            PROJECT_ROOT / "src" / "project_handlers.py"
        ).read_text(encoding="utf-8")

        self.assertIn("function displayString", source)
        self.assertIn("const str = displayString(value)", source)
        self.assertIn("queueChatImageForConvo", source)
        self.assertIn("CHAT_IMAGE_MAX_BYTES", source)
        self.assertIn('"DOM.setFileInputFiles"', client_source)
        self.assertIn("attachment_paths", manager_source)
        self.assertIn("text or an attachment", manager_source)
        self.assertIn("_save_chat_attachments", handler_source)
        self.assertNotIn("def do_patch():", handler_source)

    def test_bridge_uses_semantic_project_conversation_buttons(self):
        source = (PROJECT_ROOT / "src" / "bridge.js").read_text(encoding="utf-8")
        manager_source = (
            PROJECT_ROOT / "src" / "parallel_cdp.py"
        ).read_text(encoding="utf-8")
        self.assertIn('button[aria-label="New Conversation in Project"]', source)
        self.assertIn('a[aria-label="New Conversation in Project"]', source)
        self.assertIn('button,a,[role="button"],[role="menuitem"]', source)
        self.assertIn(
            'button,a,[role=\\"button\\"],[role=\\"menuitem\\"]',
            manager_source,
        )
        self.assertIn("_version: 45", source)
        self.assertIn("getComposerState()", source)
        self.assertIn("'model-loading'", source)
        self.assertIn("const baseReady = editable && !busy && !modelLoading", source)
        self.assertIn('[data-testid^="convo-pill-"]', source)
        self.assertIn("async archiveChat(chatId)", source)
        self.assertIn("async restoreChat(chatId)", source)
        self.assertIn("=== 'new conversation'", source)
        self.assertIn(
            "labels.some(label => label.includes('in project'))",
            source,
        )
        self.assertIn("waitForComposerReady", source)
        self.assertNotIn("headless contenteditable fallback", source)
        self.assertNotIn("sendBtn.disabled = false", source)
        self.assertIn("refusing to report a false submission", source)
        self.assertIn("reload_required: true", source)
        self.assertIn("targetUrl.pathname = '/c/' + encodeURIComponent(chatId)", source)
        self.assertIn("targetUrl.searchParams.set('section', section)", source)
        client_source = (PROJECT_ROOT / "src" / "cdp_client.py").read_text(encoding="utf-8")
        self.assertIn("window.__agBridge._version === 45", client_source)
        self.assertIn("document.activeElement === input", client_source)
        self.assertIn("navigateToChat({chat_id_json}, {section_json})", client_source)
        self.assertIn('"Input.dispatchKeyEvent"', client_source)
        self.assertIn('"Input.insertText"', client_source)
        self.assertIn("textMatches && sendEnabled", client_source)
        self.assertIn('"Page.navigate"', client_source)

    def test_manager_reuses_one_semantic_action_selector_contract(self):
        manager_source = (
            PROJECT_ROOT / "src" / "parallel_cdp.py"
        ).read_text(encoding="utf-8")
        selector = 'button,a,[role=\\"button\\"],[role=\\"menuitem\\"]'

        self.assertEqual(manager_source.count(selector), 1)
        self.assertEqual(manager_source.count("_semantic_action_matches_js("), 4)


class TestIntegrityPromptParsing(unittest.TestCase):
    def test_direct_text_field_wins_over_nested_display_field(self):
        message = "Exact project delivery"
        nested_display = encode_field_bytes(1, message.encode("utf-8"))
        user_prompt = (
            encode_field_bytes(2, message.encode("utf-8"))
            + encode_field_bytes(3, nested_display)
        )
        payload = encode_field_bytes(19, user_prompt)

        content, attachments = get_user_prompt_from_payload(payload)

        self.assertEqual(content, message)
        self.assertEqual(attachments, [])

    def test_nested_display_field_is_supported_as_fallback(self):
        message = "Nested only"
        nested_display = encode_field_bytes(1, message.encode("utf-8"))
        payload = encode_field_bytes(19, encode_field_bytes(3, nested_display))

        content, _ = get_user_prompt_from_payload(payload)

        self.assertEqual(content, message)


if __name__ == "__main__":
    unittest.main()
