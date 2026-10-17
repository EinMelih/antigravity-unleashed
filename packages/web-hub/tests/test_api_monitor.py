import json
import unittest
from aiohttp import web
from src.api_monitor import APIRequestMonitor


class Request(dict):
    method = 'POST'
    path = '/v1/chat/completions'


class ApiMonitorTests(unittest.TestCase):
    def test_queued_running_and_completed_details_are_truthful(self):
        monitor = APIRequestMonitor()
        request = Request()
        monitor.begin(request, {'model': 'native-high', 'reasoning_effort': 'high', 'messages': [{'role': 'user', 'content': 'API_ISOLATED_CHECK 42'}]})
        self.assertEqual('queued', monitor.snapshot()['requests'][0]['state'])
        monitor.running(request)
        self.assertEqual('running', monitor.snapshot()['requests'][0]['state'])
        request['execution_metadata'] = {'native_model': 'Gemini Native (High)', 'reasoning_effort': 'high', 'profile': 'api'}
        monitor.finish(request, web.json_response({'choices': [{'message': {'content': 'API_ISOLATED_CHECK 42'}}]}, headers={'X-Request-Id': 'test-id'}))
        snapshot = monitor.snapshot()
        self.assertEqual(0, snapshot['active_requests'])
        self.assertEqual(1, snapshot['successful_requests'])
        self.assertEqual('test-id', snapshot['requests'][0]['request_id'])
        self.assertEqual('Gemini Native (High)', snapshot['requests'][0]['native_model'])

    def test_stream_transport_200_does_not_hide_an_operation_error(self):
        monitor = APIRequestMonitor()
        request = Request()
        monitor.begin(request, {'message': 'test'})
        request['operation_error'] = 'Native stream failed'
        monitor.finish(request, web.StreamResponse(status=200))
        self.assertEqual('error', monitor.snapshot()['requests'][0]['state'])
        self.assertEqual(1, monitor.snapshot()['failed_requests'])

    def test_stream_preview_is_retained_without_a_json_response_body(self):
        monitor = APIRequestMonitor()
        request = Request()
        monitor.begin(request, {'message':'test'})
        request['stream_response_preview'] = 'stream answer'
        request['stream_conversation_id'] = 'api-conversation'
        monitor.finish(request, web.StreamResponse(status=200))
        row = monitor.snapshot()['requests'][0]
        self.assertEqual('stream answer', row['response_preview'])
        self.assertEqual('api-conversation', row['conversation_id'])

    def test_active_request_remains_visible_after_history_fills(self):
        monitor = APIRequestMonitor()
        for _ in range(55):
            request = Request()
            monitor.begin(request, {'message': 'past'})
            monitor.finish(request, web.json_response({'response': 'done'}))
        current = Request()
        monitor.begin(current, {'message': 'current'})
        self.assertEqual('current', monitor.snapshot()['requests'][0]['prompt_preview'])
        self.assertEqual('queued', monitor.snapshot()['requests'][0]['state'])


if __name__ == '__main__':
    unittest.main()
