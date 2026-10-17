"""Native completion should relay promptly without ending an active response."""

import unittest
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.cdp_client import AntigravityCDP
from src.api_model_catalog import model_rows
from src import api_handlers


class ApiResponseLatencyTests(unittest.IsolatedAsyncioTestCase):
    def client(self, polls):
        client = AntigravityCDP(profile='api')
        client.inject_bridge = AsyncMock()
        client.select_verified_model = AsyncMock()
        iterator = iter(polls)
        last = polls[-1]

        async def evaluate(expression, **kwargs):
            if 'prepareAndSend' in expression:
                return {'success': True, 'beforeCount': 0, 'beforeLastText': ''}
            if 'pollResponse' in expression:
                return next(iterator, last)
            return None

        client.evaluate = AsyncMock(side_effect=evaluate)
        return client

    async def test_completed_response_has_no_fixed_initial_wait(self):
        client = self.client([{'text': 'OK', 'finished': True, 'native_observed': True}])
        with patch('src.cdp_client.asyncio.sleep', new=AsyncMock()) as sleep:
            result = await client.send_chat('Return OK')
        self.assertEqual('OK', result['response'])
        sleep.assert_not_awaited()

    async def test_stable_text_while_native_running_is_not_a_final_response(self):
        polls = [{'text': 'First part', 'finished': False, 'native_observed': True, 'is_running': True}] * 14
        polls.append({'text': 'First part and the complete remainder', 'finished': True, 'native_observed': True, 'is_running': False})
        client = self.client(polls)
        with patch('src.cdp_client.asyncio.sleep', new=AsyncMock()):
            result = await client.send_chat('Return the complete answer')
        self.assertEqual('First part and the complete remainder', result['response'])

    async def test_user_input_gate_is_not_returned_as_a_successful_answer(self):
        client = self.client([{'text': 'Waiting for user input...', 'finished': False, 'native_observed': True, 'requires_user_input': True}])
        with patch('src.cdp_client.asyncio.sleep', new=AsyncMock()):
            result = await client.send_chat('Create a file')
        self.assertTrue(result.get('requires_user_input'))
        self.assertIn('error', result)
        self.assertNotIn('response', result)

    async def test_current_native_model_does_not_reopen_the_model_menu(self):
        client = AntigravityCDP(profile='api')
        client.evaluate = AsyncMock(return_value={'label': 'Gemini 3.8 Flash High', 'ready': True})
        client.get_model_catalog = AsyncMock(side_effect=AssertionError('Current model must not reopen the catalog'))
        selected = await client.select_verified_model('gemini-3.8-flash-high', 'high')
        self.assertEqual('gemini-3.8-flash-high', selected['id'])
        self.assertEqual('high', selected['reasoning_effort'])
        client.get_model_catalog.assert_not_awaited()

    async def test_changed_reasoning_still_uses_and_verifies_the_live_catalog(self):
        client = AntigravityCDP(profile='api')
        client._current_native_model = 'Gemini 3.8 Flash High'
        client.get_model_catalog = AsyncMock(return_value=model_rows([{'label': 'Gemini 3.8 Flash High'}, {'label': 'Gemini 3.8 Flash Low'}]))

        async def evaluate(expression, **kwargs):
            if 'ready:' in expression:
                return {'label': 'Gemini 3.8 Flash High', 'ready': True}
            if 'selectModel' in expression:
                return True
            return 'Gemini 3.8 Flash Low'

        client.evaluate = AsyncMock(side_effect=evaluate)
        selected = await client.select_verified_model('gemini-3.8-flash', 'low')
        self.assertEqual('low', selected['reasoning_effort'])
        client.get_model_catalog.assert_awaited_once()

    async def test_chat_http_returns_a_structured_approval_error(self):
        client = SimpleNamespace(send_chat=AsyncMock(return_value={'error': 'User approval required', 'requires_user_input': True}), get_active_conversation_id=AsyncMock(return_value='owned-api-chat'))

        @asynccontextmanager
        async def operation(app):
            yield client

        class Request(dict):
            app = {'api_request_monitor': None}

            async def json(self):
                return {'messages': [{'role': 'user', 'content': 'Create a file'}]}

        with patch.object(api_handlers, 'cdp_operation', operation):
            response = await api_handlers.chat_completions_handler(Request())
        self.assertEqual(409, response.status)
        payload = json.loads(response.text)
        self.assertEqual('user_input_required', payload['error']['type'])
        self.assertEqual('owned-api-chat', payload['conversation_id'])
        self.assertNotIn('choices', payload)


if __name__ == '__main__':
    unittest.main()
