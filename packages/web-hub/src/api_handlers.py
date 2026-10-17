import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from aiohttp import web

from src.config import config
from src.cdp_lifecycle import cdp_operation
from src.api_helpers import (
    log_interaction,
    track_usage,
    sanitize_message,
    sanitize_error_response
)

DEFAULT_TIMEOUT = 120
MAX_REQUEST_TIMEOUT = 600


def _reasoning_effort(body):
    effort = body.get('reasoning_effort')
    if effort is None and isinstance(body.get('reasoning'), dict):
        effort = body['reasoning'].get('effort')
    if effort is not None and effort not in ('low', 'medium', 'high'):
        raise ValueError('reasoning_effort must be low, medium or high and supported by the selected native model.')
    return effort


def _execution_metadata(request, cdp):
    selected = getattr(cdp, 'last_model_selection', None) or {}
    metadata = {'native_model': selected.get('native_name'), 'model_id': selected.get('id'), 'reasoning_effort': selected.get('reasoning_effort'), 'profile': 'api'}
    request['execution_metadata'] = metadata
    return metadata


def _mark_running(request):
    monitor = request.app.get('api_request_monitor')
    if monitor is not None:
        monitor.running(request)


def _parse_timeout(body: Dict[str, Any]) -> int:
    """Extract and validate timeout from request body."""
    raw = body.get("timeout", DEFAULT_TIMEOUT)
    try:
        timeout = int(raw)
    except (ValueError, TypeError):
        timeout = DEFAULT_TIMEOUT
    return max(10, min(timeout, MAX_REQUEST_TIMEOUT))


async def chat_completions_handler(request: web.Request) -> web.Response:
    """OpenAI-compatible chat completions endpoint."""
    start = time.monotonic()
    req_id = uuid.uuid4().hex[:8]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id}
        )

    messages = body.get("messages", [])
    if not messages:
        return web.json_response(
            {"error": {"message": "messages array required", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id}
        )

    # Combine system and user messages
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            parts.insert(0, f"[System: {content}]")
        elif role == "user":
            parts.append(content)

    full_message = "\n".join(parts) if len(parts) > 1 else parts[-1] if parts else ""

    if not full_message:
        return web.json_response(
            {"error": {"message": "No user message found", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id}
        )

    model = body.get("model", None)
    try:
        effort = _reasoning_effort(body)
    except ValueError as error:
        return web.json_response({'error': {'message': str(error), 'type': 'invalid_request_error'}}, status=400)
    request['reasoning_effort'] = effort
    # Allow explicit new_chat flag from request body, otherwise auto-detect
    new_chat = body.get("new_chat", len(messages) <= 1)
    project_name = body.get("project_name", None)
    timeout = _parse_timeout(body)
    stream = body.get("stream", False)
    run_id = body.get("run_id")

    print(f"[CHAT] [{req_id}] Eingehend | model={model} stream={stream} "
          f"timeout={timeout}s msg_len={len(full_message)} run_id={run_id}", flush=True)

    if stream:
        return await _handle_streaming(request, req_id, full_message, model, new_chat, project_name, timeout, messages, run_id=run_id)

    # Non-blocking, sequential processing via asyncio lock in AntigravityCDP
    conv_id = None
    try:
        async with cdp_operation(request.app) as cdp:
            _mark_running(request)
            result = await cdp.send_chat(
                full_message, timeout=timeout, model=model, new_chat=new_chat, project_name=project_name, req_id=req_id,
                **({'reasoning_effort': effort} if effort is not None else {})
            )
            execution_metadata = _execution_metadata(request, cdp)
            try:
                conv_id = await cdp.get_active_conversation_id()
                if conv_id and run_id:
                    from src.database import db
                    db.update_agent_run_conversation_id(run_id, conv_id)
            except Exception as e:
                print(f"[CHAT] [{req_id}] Fehler beim Holen der Konversations-ID: {e}", flush=True)
    except ConnectionError as e:
        return web.json_response(
            {"error": {"message": str(e), "type": "connection_error"}},
            status=503,
            headers={"X-Request-Id": req_id}
        )
    except ValueError as e:
        return web.json_response({'error': {'message': str(e), 'type': 'invalid_request_error'}}, status=400, headers={'X-Request-Id': req_id})
    except Exception as e:
        return web.json_response(
            {"error": {"message": f"CDP error: {str(e)}", "type": "internal_error"}},
            status=500,
            headers={"X-Request-Id": req_id}
        )

    duration = (time.monotonic() - start) * 1000

    if result and result.get('requires_user_input'):
        return web.json_response({'error': {'message': result['error'], 'type': 'user_input_required', 'requires_user_input': True}, 'conversation_id': conv_id}, status=409, headers={'X-Request-Id': req_id})
    if not result or result.get("error"):
        error_msg = result.get("error", "No response") if result else "No response from Antigravity"
        log_interaction({"messages": messages[-1:]}, {"error": error_msg}, duration, 500, req_id=req_id)
        return web.json_response(
            {"error": {"message": error_msg, "type": "backend_error",
                       "debug": result.get("debug") if result else None}},
            status=500,
            headers={"X-Request-Id": req_id}
        )

    response_text = result.get("response", "")

    # Auto-sanitize JSON for clients like Dokploy expecting raw JSON objects
    if any(keyword in full_message for keyword in ["JSON object", "json object", '"suggestions"', "dockerCompose"]):
        import re
        clean_text = response_text.strip()
        # Extract outer json block using regex ({ ... })
        match = re.search(r'(\{[\s\S]*\})', clean_text)
        if match:
            clean_text = match.group(1).strip()

        # Verify it's valid JSON, and re-serialize compactly
        try:
            parsed = json.loads(clean_text)
            response_text = json.dumps(parsed, ensure_ascii=False)
            print(f"[CHAT] [{req_id}] Auto-sanitized JSON for Dokploy ({len(response_text)} chars)", flush=True)
        except Exception as json_err:
            print(f"[CHAT] [{req_id}] JSON sanitization warning: {json_err} (raw len: {len(response_text)})", flush=True)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    prompt_tokens = max(1, len(full_message) // 4)
    completion_tokens = max(1, len(response_text) // 4)
    total_tokens = prompt_tokens + completion_tokens

    openai_response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": execution_metadata.get('model_id') or model or "antigravity",
        **execution_metadata,
        "conversation_id": conv_id,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": response_text
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "estimated": True,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens
        }
    }

    log_interaction(
        {"messages": messages[-2:]},
        {"response": response_text[:500], "tokens": total_tokens, "duration_ms": result.get("duration_ms")},
        duration, 200, req_id=req_id
    )

    print(f"[CHAT] [{req_id}] OpenAI | {round(duration)}ms | {len(response_text)} chars | ~{total_tokens} tokens", flush=True)
    track_usage(prompt_tokens, completion_tokens, model=model)
    resp = web.json_response(openai_response)
    resp.headers["X-Request-Id"] = req_id
    if conv_id:
        resp.headers["X-Conversation-Id"] = conv_id
    return resp


async def _handle_streaming(request: web.Request, req_id: str, full_message: str, model: Optional[str], new_chat: bool, project_name: Optional[str], timeout: int, messages: list, run_id: Optional[int] = None) -> web.StreamResponse:
    """Helper to stream chat completions via Server-Sent Events (SSE)."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    supervisor = request.app.get("cdp_startup_supervisor")
    if supervisor is not None:
        try:
            await supervisor.ensure_ready()
        except Exception as error:
            return web.json_response(
                {"error": {"message": str(error), "type": "connection_error"}},
                status=503,
                headers={"X-Request-Id": req_id},
            )
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-Id": req_id,
            "Access-Control-Allow-Origin": "*",
        }
    )
    await response.prepare(request)

    role_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": model or "gemini-3.5-flash-high",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant"},
            "finish_reason": None
        }]
    }
    await response.write(f"data: {json.dumps(role_chunk)}\n\n".encode("utf-8"))

    total_content = ""
    error_occurred = False
    conv_id = None

    try:
        async with cdp_operation(request.app) as cdp:
            _mark_running(request)
            async for delta in cdp.send_chat_streaming(
                full_message, timeout=timeout, model=model, new_chat=new_chat, project_name=project_name, req_id=req_id, run_id=run_id,
                **({'reasoning_effort': request['reasoning_effort']} if request.get('reasoning_effort') is not None else {})
            ):
                if not delta:
                    continue
                total_content += delta
                _execution_metadata(request, cdp)

                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "model": model or "gemini-3.5-flash-high",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": delta},
                        "finish_reason": None
                    }]
                }
                await response.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            try:
                conv_id = await cdp.get_active_conversation_id()
            except Exception:
                pass
            _execution_metadata(request, cdp)

    except ConnectionError as e:
        print(f"[STREAM] [{req_id}] Verbindungsfehler: {e}", flush=True)
        error_occurred = True
        request['operation_error'] = str(e)
    except Exception as e:
        print(f"[STREAM] [{req_id}] Fehler: {e}", flush=True)
        error_occurred = True
        request['operation_error'] = str(e)
        if getattr(e, 'requires_user_input', False):
            request['requires_user_input'] = True

    if not total_content and not error_occurred:
        error_occurred = True
        request['operation_error'] = 'Native API returned no response content.'
    request['stream_response_preview'] = total_content[:280]
    request['stream_conversation_id'] = conv_id

    finish_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": model or "gemini-3.5-flash-high",
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop" if not error_occurred else "error"
        }],
        "conversation_id": conv_id
    }
    finish_chunk.update(request.get('execution_metadata') or {})
    if error_occurred:
        finish_chunk['error'] = {'message': request.get('operation_error'), 'type': 'user_input_required' if request.get('requires_user_input') else 'backend_error'}
        if request.get('requires_user_input'):
            finish_chunk['error']['requires_user_input'] = True
    await response.write(f"data: {json.dumps(finish_chunk)}\n\n".encode("utf-8"))
    await response.write(b"data: [DONE]\n\n")

    duration = (time.monotonic() - request.app['start_time_mono']) * 1000
    print(f"[CHAT] [{req_id}] Stream | {round(duration)}ms | {len(total_content)} chars", flush=True)

    prompt_tokens = max(1, len(full_message) // 4)
    completion_tokens = max(1, len(total_content) // 4)
    track_usage(prompt_tokens, completion_tokens, model=model)

    log_interaction(
        {"messages": messages[-2:], "stream": True},
        {"response": total_content[:500], "stream_chars": len(total_content), "tokens": prompt_tokens + completion_tokens},
        duration, 200, req_id=req_id
    )

    return response


async def simple_chat_handler(request: web.Request) -> web.Response:
    """Simple chat endpoint: POST {"message": "..."} -> {"response": "..."}"""
    start = time.monotonic()
    req_id = uuid.uuid4().hex[:8]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON"},
            status=400,
            headers={"X-Request-Id": req_id}
        )

    raw_message = body.get("message", "")
    message, error_resp = sanitize_message(raw_message, source="simple_api")
    if error_resp:
        return error_resp

    model = body.get("model", None)
    new_chat = body.get("new_chat", False)
    try:
        effort = _reasoning_effort(body)
    except ValueError as error:
        return web.json_response({'error': {'message': str(error), 'type': 'invalid_request_error'}}, status=400)
    request['reasoning_effort'] = effort
    timeout = _parse_timeout(body)

    print(f"[CHAT] [{req_id}] Simple | model={model} timeout={timeout}s", flush=True)

    try:
        async with cdp_operation(request.app) as cdp:
            _mark_running(request)
            result = await cdp.send_chat(
                message, timeout=timeout, model=model, new_chat=new_chat, req_id=req_id,
                **({'reasoning_effort': effort} if effort is not None else {})
            )
            execution_metadata = _execution_metadata(request, cdp)
    except ConnectionError as e:
        return web.json_response(
            {"error": str(e)},
            status=503,
            headers={"X-Request-Id": req_id}
        )
    except ValueError as e:
        return web.json_response({'error': {'message': str(e), 'type': 'invalid_request_error'}}, status=400, headers={'X-Request-Id': req_id})
    except Exception as e:
        return web.json_response(
            {"error": f"CDP error: {str(e)}"},
            status=500,
            headers={"X-Request-Id": req_id}
        )

    duration = (time.monotonic() - start) * 1000

    if result and result.get('requires_user_input'):
        return web.json_response({'error': {'message': result['error'], 'type': 'user_input_required', 'requires_user_input': True}}, status=409, headers={'X-Request-Id': req_id})
    if not result or result.get("error"):
        error_msg = result.get("error", "No response") if result else "No response"
        log_interaction({"message": message}, {"error": error_msg}, duration, 500, req_id=req_id)
        return web.json_response({
            "error": error_msg,
            "partial": result.get("partial") if result else None,
            "debug": result.get("debug") if result else None
        }, status=500, headers={"X-Request-Id": req_id})

    response_text = result.get("response", "")

    prompt_tokens = max(1, len(message) // 4)
    completion_tokens = max(1, len(response_text) // 4)
    total_tokens = prompt_tokens + completion_tokens

    response_data = {
        "id": str(uuid.uuid4()),
        "response": response_text,
        "model": execution_metadata.get('model_id') or model or "antigravity",
        **execution_metadata,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration),
        "frontend_duration_ms": result.get("duration_ms"),
        "usage": {
            "estimated": True,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens
        }
    }

    log_interaction(
        {"message": message, "model": model},
        {"response": response_text[:500], "tokens": total_tokens},
        duration, 200, req_id=req_id
    )
    print(f"[CHAT] [{req_id}] Simple | {round(duration)}ms | {len(response_text)} chars | ~{total_tokens} tokens", flush=True)
    track_usage(prompt_tokens, completion_tokens, model=model)

    resp = web.json_response(response_data)
    resp.headers["X-Request-Id"] = req_id
    return resp


async def models_handler(request: web.Request) -> web.Response:
    """Lists available models."""
    try:
        async with cdp_operation(request.app) as cdp:
            models = await cdp.get_model_catalog()
        return web.json_response({"object": "list", "data": models, "profile": "api"})
    except ConnectionError as error:
        return web.json_response({"error": {"type": "connection_error", "message": str(error)}}, status=503)


async def send_parallel_handler(request: web.Request) -> web.Response:
    """Send each prompt through a distinct, verified API-profile renderer."""
    import asyncio

    start_total = time.monotonic()
    req_id = uuid.uuid4().hex[:8]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id}
        )

    if not isinstance(body, dict):
        return web.json_response(
            {"error": {"message": "Request body must be an object", "type": "invalid_request_error"}},
            status=400, headers={"X-Request-Id": req_id},
        )
    requests_list = body.get("requests", [])
    if not isinstance(requests_list, list) or not requests_list:
        return web.json_response(
            {"error": {"message": "requests array is required and cannot be empty", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id}
        )

    try:
        for item in requests_list:
            if not isinstance(item, dict) or not isinstance(item.get("prompt"), str) or not item["prompt"].strip():
                raise ValueError("Each request requires a non-empty prompt string")
            if item.get("conversation_id") is not None and not isinstance(item["conversation_id"], str):
                raise ValueError("conversation_id must be a string")
            if item.get("model") is not None and not isinstance(item["model"], str):
                raise ValueError("model must be a native model ID string")
            _reasoning_effort(item)
    except ValueError as exc:
        return web.json_response(
            sanitize_error_response(str(exc), "invalid_request_error"),
            status=400, headers={"X-Request-Id": req_id},
        )

    n_requests = len(requests_list)
    from src.parallel_cdp import ParallelCDPManager
    manager = ParallelCDPManager(profile='api')
    try:
        from src.window_tiling import ensure_and_tile_windows
        page_targets = await ensure_and_tile_windows(n_requests, manager=manager)
    except Exception as e:
        print(f"[Parallel] Alignment error: {e}", flush=True)
        await manager.close_all()
        return web.json_response(
            sanitize_error_response(f"Failed to align window targets: {e}", "internal_error"),
            status=500,
            headers={"X-Request-Id": req_id}
        )

    targets = []
    seen_urls = set()
    for target in page_targets:
        ws_url = target.get("webSocketDebuggerUrl")
        if ws_url and ws_url not in seen_urls:
            targets.append(target)
            seen_urls.add(ws_url)
    if len(targets) < n_requests:
        await manager.close_all()
        return web.json_response(
            {"error": {"message": "Not enough distinct API-profile windows; no prompts were sent", "type": "connection_error"}},
            status=503, headers={"X-Request-Id": req_id},
        )
    _mark_running(request)

    async def run_single(target, req_data):
        ws_url = target["webSocketDebuggerUrl"]
        prompt = req_data.get("prompt", "")
        convo_id = req_data.get("conversation_id") or ""
        model = req_data.get("model")
        new_chat = convo_id.lower() in ("", "new", "none", "null")

        start_single = time.monotonic()
        client = await manager.get_client_for_target(ws_url)

        await client.inject_bridge()
        if not new_chat:
            manager.profile_runtime.validate_conversation(convo_id)
            active_convo = await client.get_active_conversation_id()
            if active_convo != convo_id:
                navigation = await client.navigate_to_chat(convo_id)
                if not navigation or not navigation.get("success"):
                    raise RuntimeError("The API window could not open the requested conversation")
                await client.inject_bridge()
                if await client.get_active_conversation_id() != convo_id:
                    raise RuntimeError("The API window did not reach the requested conversation")

        # Reuse scoped delivery and completion polling; never read private transcripts.
        result = await client.send_chat(
            prompt, model=model, reasoning_effort=_reasoning_effort(req_data),
            new_chat=new_chat, timeout=300, req_id=req_id,
        )
        if not isinstance(result, dict) or result.get("error") or not result.get("response"):
            raise RuntimeError(result.get("error", "No response received") if isinstance(result, dict) else "No response received")
        convo_id = await client.get_active_conversation_id()
        if not convo_id or convo_id.lower() in ("new", "none", "null"):
            raise RuntimeError("The API window did not expose a conversation ID after delivery")
        selected = getattr(client, "last_model_selection", None) or {}
        time_taken = time.monotonic() - start_single
        return {
            "conversation_id": convo_id,
            "response": result["response"],
            "time_taken": round(time_taken, 2),
            "profile": "api",
            "model_id": selected.get("id"),
            "native_model": selected.get("native_name"),
            "reasoning_effort": selected.get("reasoning_effort"),
        }

    # Execute all concurrently
    tasks = []
    for i in range(n_requests):
        tasks.append(run_single(targets[i], requests_list[i]))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # Clean up WebSocket connections in manager
        await manager.close_all()

    # Post-process results
    responses = []
    errors = 0
    for i, res in enumerate(results):
        convo_id = requests_list[i].get("conversation_id", "")
        if isinstance(res, Exception):
            errors += 1
            print(f"[Parallel] Error running request for {convo_id}: {res}", flush=True)
            error = sanitize_error_response(str(res), "invalid_request_error" if isinstance(res, ValueError) else "internal_error")["error"]
            responses.append({
                "conversation_id": convo_id,
                "response": f"Error: {error['message']}",
                "error": error,
                "time_taken": round(time.monotonic() - start_total, 2),
            })
        else:
            responses.append(res)

    total_time = round(time.monotonic() - start_total, 2)
    if errors:
        request["operation_error"] = f"{errors} of {n_requests} parallel API requests failed"
    request["stream_response_preview"] = " | ".join(row["response"] for row in responses)[:280]

    return web.json_response({
        "status": "success" if not errors else ("error" if errors == n_requests else "partial_error"),
        "profile": "api",
        "responses": responses,
        "total_time": total_time
    }, headers={"X-Request-Id": req_id})
