import unittest
from unittest.mock import AsyncMock, patch
from src.cdp_client import AntigravityCDP


class ApiStreamDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_stream_submits_in_its_renderer_without_global_native_typing(self):
        client = AntigravityCDP(profile='api')
        async def evaluate(expression, **_kwargs):
            if 'prepareAndSend' in expression:
                if 'owned API text' not in expression:
                    raise AssertionError('Streaming must submit the actual prompt.')
                return {'success':True,'beforeCount':0,'beforeLastText':''}
            if 'pollResponse' in expression:
                return {'text':'owned stream response','started':True,'finished':True}
            raise AssertionError('Unexpected expression')
        with (
            patch.object(client,'inject_bridge',new=AsyncMock()),
            patch.object(client,'select_verified_model',new=AsyncMock()),
            patch.object(client,'set_input_text_native',new=AsyncMock(return_value=False)) as native,
            patch.object(client,'evaluate',side_effect=evaluate),
            patch('src.cdp_client.asyncio.sleep',new=AsyncMock()),
        ):
            chunks = [chunk async for chunk in client.send_chat_streaming('owned API text',model='model',reasoning_effort='high')]
            self.assertEqual('owned stream response',''.join(chunks))
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
