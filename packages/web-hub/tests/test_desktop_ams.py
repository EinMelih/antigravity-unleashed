import asyncio
import json
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.desktop_ams import extract_ams_template, invoke_native_method, native_rpc_handler, protect_quota_updates


class DesktopAMSTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_quota_fraction_never_produces_nan(self):
        original = '''
            const currentQuotaData = {gemini5h: 99, claude5h: 0};
            const geminiConfig = {quotaInfo:{}};
            const claudeConfig = {quotaInfo:{}};
            if (geminiConfig && geminiConfig.quotaInfo) {
                currentQuotaData.gemini5h = Math.round(geminiConfig.quotaInfo.remainingFraction * 100);
            }
            if (claudeConfig && claudeConfig.quotaInfo) {
                currentQuotaData.claude5h = Math.round(claudeConfig.quotaInfo.remainingFraction * 100);
            } else { currentQuotaData.claude5h = 0; }
            process.stdout.write(JSON.stringify(currentQuotaData));
        '''
        before = subprocess.run(['node', '-e', original], capture_output=True, text=True, check=True)
        self.assertIsNone(json.loads(before.stdout)['claude5h'])
        after = subprocess.run(['node', '-e', protect_quota_updates(original)], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(after.stdout), {'gemini5h': 99, 'claude5h': 0})

    async def test_exact_native_script_is_extracted_without_running_preload(self):
        literal = extract_ams_template('const amsScriptContent = `const text = \\`hello\\`; const n = \\${1};`; console.log("outside");')
        self.assertEqual(literal, '`const text = \\`hello\\`; const n = \\${1};`')

    async def test_interpolated_native_script_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_ams_template('const amsScriptContent = `${process.env.SECRET}`;')

    async def test_unknown_or_injected_method_never_connects_to_desktop(self):
        with patch('src.desktop_ams.AntigravityCDP') as client:
            with self.assertRaises(ValueError):
                await invoke_native_method('getNotes);window.fetch', [])
            client.assert_not_called()

    async def test_real_result_and_conversation_context_are_preserved(self):
        native = AsyncMock()
        native.evaluate.side_effect = [
            {'profile': 'default', 'profile_contract_version': 2},
            {'ok': True, 'data': {'status': 'success', 'plan': '- [ ] Actual task'}},
        ]
        with patch('src.desktop_ams.AntigravityCDP', return_value=native):
            result = await invoke_native_method('getTaskPlan', ['a812702f-9b1f-4089-a7a9-238b54fe3561'])
        self.assertEqual(result['plan'], '- [ ] Actual task')
        expression = native.evaluate.call_args.args[0]
        self.assertIn('a812702f-9b1f-4089-a7a9-238b54fe3561', expression)
        self.assertIn('getTaskPlan', expression)
        native.disconnect.assert_awaited_once()

    async def test_api_profile_is_never_used_as_private_desktop_fallback(self):
        native = AsyncMock()
        native.evaluate.return_value = {'profile': 'api', 'profile_contract_version': 2}
        with patch('src.desktop_ams.AntigravityCDP', return_value=native):
            with self.assertRaises(ConnectionError):
                await invoke_native_method('getSyncStatus', [])
        self.assertEqual(native.evaluate.await_count, 1)
        native.disconnect.assert_awaited_once()

    async def test_native_operational_error_is_not_an_empty_result(self):
        native = AsyncMock()
        native.evaluate.side_effect = [
            {'profile': 'default', 'profile_contract_version': 2},
            {'ok': False, 'error': {'message': 'Desktop function unavailable', 'code': 'AMS_METHOD_MISSING'}},
        ]
        with patch('src.desktop_ams.AntigravityCDP', return_value=native):
            with self.assertRaisesRegex(RuntimeError, 'Desktop function unavailable'):
                await invoke_native_method('getSyncStatus', [])

    async def test_cross_origin_mutation_is_rejected(self):
        app = web.Application()
        app.router.add_route('*', '/api/desktop/ams/{operation}', native_rpc_handler)
        async with TestClient(TestServer(app)) as client:
            with patch('src.desktop_ams.invoke_native_method', new=AsyncMock()) as invoke:
                response = await client.post('/api/desktop/ams/setTaskPlan', json={'args': ['task', None]}, headers={'Origin': 'https://unrelated.example'})
                self.assertEqual(response.status, 403)
                invoke.assert_not_awaited()

    async def test_mutating_function_cannot_be_called_using_get(self):
        app = web.Application()
        app.router.add_route('*', '/api/desktop/ams/{operation}', native_rpc_handler)
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/api/desktop/ams/setNotes', params={'args': json.dumps(['text', False, None])})
            self.assertEqual(response.status, 405)

    async def test_native_failure_is_not_reported_as_http_success(self):
        app = web.Application()
        app.router.add_route('*', '/api/desktop/ams/{operation}', native_rpc_handler)
        original = {'status': 'error', 'message': 'Repository is unavailable'}
        async with TestClient(TestServer(app)) as client:
            with patch('src.desktop_ams.invoke_native_method', new=AsyncMock(return_value=original)):
                response = await client.get('/api/desktop/ams/getGitStatus')
                self.assertEqual(response.status, 503)
                payload = await response.json()
                self.assertEqual(payload['native_result'], original)
                self.assertFalse(payload['ok'])


if __name__ == '__main__':
    unittest.main()
