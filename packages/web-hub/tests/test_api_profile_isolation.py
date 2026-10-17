import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import api_handlers, api_server
from src.api_profile import APIProfileRuntime, PROFILE_CONTRACT_VERSION
from src.api_model_catalog import model_rows, resolve_model
from src.cdp_client import AntigravityCDP


class FakeCDP:
    def __init__(self):
        self.ws = None
        self._connected = False
        self._bridge_injected = False

    async def connect(self):
        self.ws = SimpleNamespace(closed=False)
        self._connected = True

    async def inject_bridge(self):
        self._bridge_injected = True

    async def disconnect(self):
        self._connected = False
        self.ws = None

    async def get_model_catalog(self):
        return [{"id": "gemini-99.7-pro-high", "native_name": "Gemini 99.7 Pro (High)", "reasoning_effort": "high", "owned_by": "google", "source": "native"}]


class ApiProfileIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_target_is_rejected_before_bridge_injection(self):
        client = AntigravityCDP(profile='api')
        socket = SimpleNamespace(closed=False, close=AsyncMock())
        session = SimpleNamespace(closed=False, ws_connect=AsyncMock(return_value=socket), close=AsyncMock())
        with (
            patch('src.cdp_client.aiohttp.ClientSession', return_value=session),
            patch.object(client, '_read_loop', new=AsyncMock()),
            patch.object(client, 'call_cdp', new=AsyncMock(return_value={})),
            patch.object(client, 'evaluate', new=AsyncMock(return_value={'profile_contract_version': 1, 'profile': 'default'})),
            patch.object(client, 'inject_bridge', new=AsyncMock()) as inject,
        ):
            with self.assertRaisesRegex(ConnectionError, 'dedicated'):
                await client.connect(f'ws://127.0.0.1:{client.profile_runtime.devtools_port}/devtools/page/private')
            inject.assert_not_called()
            self.assertFalse(client._connected)
            self.assertIsNone(client.profile_info)

    async def test_correct_profile_name_with_private_paths_is_rejected(self):
        runtime = APIProfileRuntime()
        info = {'profile_contract_version': PROFILE_CONTRACT_VERSION, 'profile': 'api', 'user_data_dir': str(runtime.auth_source_user_data_dir.with_name('Antigravity')), 'app_data_dir': str(runtime.app_data_dir), 'settings_path': str(runtime.config_dir / 'config.json')}
        with self.assertRaisesRegex(ConnectionError, 'user_data_dir'):
            runtime.verify_identity(info)

    async def test_separate_chat_paths_with_private_home_are_rejected(self):
        runtime = APIProfileRuntime()
        info = {'profile_contract_version': PROFILE_CONTRACT_VERSION, 'profile': 'api', 'user_data_dir': str(runtime.user_data_dir), 'app_data_dir': str(runtime.app_data_dir), 'settings_path': str(runtime.config_dir / 'config.json'), 'home_dir': str(runtime.private_home), 'config_dir': str(runtime.config_dir), 'process_cwd': str(runtime.workspace_dir)}
        with self.assertRaisesRegex(ConnectionError, 'home_dir'):
            runtime.verify_identity(info)

    async def test_separate_home_with_private_config_is_rejected(self):
        runtime = APIProfileRuntime()
        info = {'profile_contract_version': PROFILE_CONTRACT_VERSION, 'profile': 'api', 'user_data_dir': str(runtime.user_data_dir), 'app_data_dir': str(runtime.app_data_dir), 'settings_path': str(runtime.config_dir / 'config.json'), 'home_dir': str(runtime.profile_home), 'config_dir': str(runtime.private_home / '.gemini/config'), 'process_cwd': str(runtime.workspace_dir)}
        with self.assertRaisesRegex(ConnectionError, 'config_dir'):
            runtime.verify_identity(info)

    async def test_reconnect_never_uses_global_private_discovery(self):
        client = AntigravityCDP(profile='api')
        client._pinned_ws_url = 'ws://127.0.0.1:11111/devtools/page/stale'
        with (
            patch.object(client, 'disconnect', new=AsyncMock()),
            patch.object(client, 'connect', new=AsyncMock()) as connect,
            patch('src.cdp_client.find_devtools', side_effect=AssertionError('private discovery forbidden')),
        ):
            await client.reconnect()
            connect.assert_awaited_once_with()
            self.assertIsNone(client._pinned_ws_url)

    async def test_reasoning_selection_must_be_a_native_option(self):
        rows = model_rows([{'label': 'Gemini 99.7 Pro (High)', 'reasoning_effort': 'high'}, {'label': 'Gemini 99.7 Pro (Low)', 'reasoning_effort': 'low'}])
        high = resolve_model(rows, 'gemini-99.7-pro', 'high', 'Gemini 99.7 Pro (Low)')
        self.assertEqual('Gemini 99.7 Pro (High)', high['native_name'])
        with self.assertRaises(ValueError):
            resolve_model(rows, 'gemini-99.7-pro', 'medium', 'Gemini 99.7 Pro (Low)')
        with self.assertRaises(ValueError):
            resolve_model(rows, 'invented-model', 'high', 'Gemini 99.7 Pro (Low)')

    async def test_current_native_effort_label_without_parentheses_is_recognized(self):
        rows = model_rows([{'label': 'Gemini 3.8 Flash High'}, {'label': 'Gemini 3.8 Flash (High)', 'reasoning_effort': 'high'}])
        self.assertEqual(1, len(rows))
        self.assertEqual('gemini-3.8-flash', rows[0]['base_model_id'])
        self.assertEqual('high', rows[0]['reasoning_effort'])

    async def test_public_api_startup_requires_the_api_profile(self):
        app = {}
        with (
            patch.object(api_server, "AntigravityCDP", return_value=FakeCDP()) as factory,
            patch.object(api_server, "send_telegram", new=AsyncMock()),
        ):
            await api_server.on_startup(app)
            try:
                factory.assert_called_once_with(profile="api")
            finally:
                await api_server.on_shutdown(app)

    async def test_models_are_read_from_the_native_api_profile(self):
        response = await api_handlers.models_handler(SimpleNamespace(app={"cdp": FakeCDP()}))
        data = json.loads(response.text)
        self.assertEqual(["gemini-99.7-pro-high"], [row["id"] for row in data["data"]])
        self.assertEqual("native", data["data"][0]["source"])
        self.assertEqual("high", data["data"][0]["reasoning_effort"])


if __name__ == "__main__":
    unittest.main()
