"""Bounded, in-memory request details for the read-only desktop API monitor."""

import json
import re
import time
import uuid
from datetime import datetime, timezone


def _preview(value, limit=280):
    text = str(value or '')
    text = re.sub(r'(?i)(Bearer\s+)\S+', r'\1<REDACTED>', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}\b', '<REDACTED>', text)
    return text[:limit]


class APIRequestMonitor:
    def __init__(self):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.rows = []
        self.total = 0
        self.successful = 0
        self.failed = 0

    def begin(self, request, body):
        messages = body.get('messages') or []
        text = body.get('message') or next((row.get('content', '') for row in reversed(messages) if isinstance(row, dict) and row.get('role') == 'user'), '')
        reasoning = body.get('reasoning')
        effort = body.get('reasoning_effort') or (reasoning.get('effort') if isinstance(reasoning, dict) else None)
        effort = effort[:16] if isinstance(effort, str) else None
        row = {'request_id': uuid.uuid4().hex[:8], 'method': request.method, 'path': request.path, 'profile': 'api', 'state': 'queued', 'started_at': datetime.now(timezone.utc).isoformat(), 'requested_model': _preview(body.get('model'), 160), 'reasoning_effort': effort, 'prompt_preview': _preview(text), 'prompt_chars': len(text) if isinstance(text, str) else 0, '_started_mono': time.monotonic()}
        self.rows.append(row)
        retained = {id(value) for value in [value for value in self.rows if value['state'] not in ('queued', 'running')][-50:]}
        self.rows = [value for value in self.rows if value['state'] in ('queued', 'running') or id(value) in retained]
        self.total += 1
        request['monitor_row'] = row

    def running(self, request):
        row = request.get('monitor_row')
        if row is not None:
            row['state'] = 'running'

    def finish(self, request, response):
        row = request.get('monitor_row')
        if row is None:
            return
        row['request_id'] = response.headers.get('X-Request-Id') or row['request_id']
        row['duration_ms'] = round((time.monotonic() - row.pop('_started_mono')) * 1000)
        row['http_status'] = response.status
        row.update(request.get('execution_metadata') or {})
        row['error'] = _preview(request.get('operation_error')) or None
        if request.get('stream_response_preview'):
            row['response_preview'] = _preview(request['stream_response_preview'])
            row['conversation_id'] = request.get('stream_conversation_id')
        payload = {}
        if getattr(response, 'body', None):
            try:
                payload = json.loads(response.body)
            except (ValueError, TypeError):
                pass
        if isinstance(payload, dict):
            error = payload.get('error')
            if error:
                row['error'] = _preview(error.get('message') if isinstance(error, dict) else error)
            choices = payload.get('choices') or []
            content = payload.get('response') or (choices[0].get('message', {}).get('content') if choices else '')
            if content:
                row['response_preview'] = _preview(content)
            if payload.get('conversation_id'):
                row['conversation_id'] = payload['conversation_id']
        row['state'] = 'error' if response.status >= 400 or row['error'] else 'success'
        if row['state'] == 'success': self.successful += 1
        else: self.failed += 1

    def snapshot(self):
        active = sum(row['state'] in ('queued', 'running') for row in self.rows)
        return {'started_at': self.started_at, 'period': 'since_api_start', 'total_requests': self.total, 'successful_requests': self.successful, 'failed_requests': self.failed, 'active_requests': active, 'requests': [{key: value for key, value in row.items() if not key.startswith('_')} for row in reversed(self.rows[-30:])]}
