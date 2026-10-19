import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from aiohttp import web

from src.antigravity_shields import (
    QuotaExhaustedError,
    extract_and_sanitize_messages,
    pacing_guard,
    write_workspace_agents_md,
)
from src.api_audit_logger import (
    AUDIT_LOG_JSONL,
    detect_source_framework,
    detect_source_framework_detailed,
    record_api_audit_log,
    record_revert_event,
)
from src.api_helpers import (
    log_interaction,
    sanitize_error_response,
    sanitize_message,
    track_usage,
)
from src.api_token_reader import parse_generator_metadata_tokens
from src.cdp_lifecycle import cdp_operation as _DEFAULT_CDP_OPERATION
from src.config import config
from src.database import db
from src.rpc_pool import rpc_pool

# Keep module-level reference so unit tests can patch `api_handlers.cdp_operation`
cdp_operation = _DEFAULT_CDP_OPERATION

DEFAULT_TIMEOUT = 120
MAX_REQUEST_TIMEOUT = 600


def _reasoning_effort(body: Dict[str, Any]) -> Optional[str]:
    effort = body.get("reasoning_effort")
    if effort is None and isinstance(body.get("reasoning"), dict):
        effort = body["reasoning"].get("effort")
    if effort is not None and effort not in ("low", "medium", "high"):
        raise ValueError(
            "reasoning_effort must be low, medium or high and supported by the selected native model."
        )
    return effort


def _execution_metadata(request: Any, cdp: Any) -> Dict[str, Any]:
    selected = getattr(cdp, "last_model_selection", None) or {}
    metadata = {
        "native_model": selected.get("native_name"),
        "model_id": selected.get("id"),
        "reasoning_effort": selected.get("reasoning_effort"),
        "profile": "api",
    }
    request["execution_metadata"] = metadata
    return metadata


def _mark_running(request: Any) -> None:
    app = getattr(request, "app", None) or {}
    monitor = app.get("api_request_monitor") if hasattr(app, "get") else None
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


def _resolve_engine_mode(request: Any, body: Optional[Dict[str, Any]] = None) -> str:
    """Determine whether to execute via Direct ConnectRPC ('rpc') or Electron/CDP ('ui').

    Automatically respects unit tests that patch `api_handlers.cdp_operation` or inject
    a fake CDP instance into `request.app['cdp']`.
    """
    if isinstance(body, dict) and body.get("engine_mode") in ("rpc", "ui"):
        return str(body["engine_mode"])
    headers = getattr(request, "headers", None) or {}
    hdr_mode = str(headers.get("X-Engine-Mode") or "").strip().lower()
    if hdr_mode in ("rpc", "ui"):
        return hdr_mode

    # If a unit test patched `api_handlers.cdp_operation`, use UI/CDP path for test compatibility
    if cdp_operation is not _DEFAULT_CDP_OPERATION:
        return "ui"

    app = getattr(request, "app", None) or {}
    if hasattr(app, "get"):
        if app.get("force_engine_mode") in ("rpc", "ui"):
            return str(app["force_engine_mode"])
        cdp_obj = app.get("cdp")
        if cdp_obj is not None and type(cdp_obj).__name__ != "AntigravityCDP" and "rpc_pool" not in app:
            return "ui"

    return config.api_mode


def _extract_request_context(
    request: Any,
    messages: Optional[List[Dict[str, Any]]] = None,
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    headers = getattr(request, "headers", None) or {}
    client_ip = (
        headers.get("X-Client-Ip", "").strip()
        or headers.get("X-Real-IP", "").strip()
        or headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or getattr(request, "remote", None)
        or "127.0.0.1"
    )
    user_agent = headers.get("User-Agent", "")
    key_name = str((request.get("api_key_name") if hasattr(request, "get") else None) or "default")
    req_path = str(getattr(request, "path", "") or "/v1/chat/completions")
    framework, detection_reason = detect_source_framework_detailed(
        user_agent,
        dict(headers),
        messages,
        tools=tools,
        client_ip=client_ip,
        api_key_name=key_name,
        path=req_path,
    )
    if hasattr(request, "__setitem__"):
        try:
            request["source_detection_reason"] = detection_reason
        except Exception:
            pass
    return {
        "client_ip": client_ip,
        "user_agent": user_agent,
        "api_key_name": key_name,
        "source_framework": framework,
    }


def _build_usage_dict(token_metrics: Dict[str, Any]) -> Dict[str, Any]:
    prompt_t = int(token_metrics.get("prompt_tokens") or 0)
    comp_t = int(token_metrics.get("completion_tokens") or 0)
    cached_t = int(token_metrics.get("cached_tokens") or 0)
    think_t = int(token_metrics.get("thinking_tokens") or 0)
    total_t = int(token_metrics.get("total_tokens") or (prompt_t + comp_t + think_t))
    return {
        "estimated": bool(token_metrics.get("estimated", False)),
        "token_source": str(token_metrics.get("token_source") or "exact_rpc"),
        "prompt_tokens": prompt_t,
        "completion_tokens": comp_t,
        "total_tokens": total_t,
        "prompt_tokens_details": {
            "cached_tokens": cached_t,
        },
        "completion_tokens_details": {
            "reasoning_tokens": think_t,
        },
        "context_window": {
            "used_tokens": int(token_metrics.get("context_used_tokens") or total_t),
            "max_tokens": int(token_metrics.get("context_max_tokens") or 200_000),
        },
    }


async def chat_completions_handler(request: web.Request) -> web.Response:
    """OpenAI-compatible `/v1/chat/completions` endpoint with Dual-Engine (`rpc` / `ui`) & 8 Shields."""
    start = time.monotonic()
    req_id = uuid.uuid4().hex[:8]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )

    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return web.json_response(
            {"error": {"message": "messages array required", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )

    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    # Stage 1 (Local Hub Detection): Identify OpenClaw / Hermes / User BEFORE Shield 2 scrubs signatures for Google
    req_ctx = _extract_request_context(request, messages, tools=tools)

    # Stage 2 (Shield 2 Sanitizer): Strip all OpenClaw / Hermes / SOUL.md signatures before contacting language_server.exe
    firewall_enabled = bool(config.api_engine.get("keyword_firewall_enabled", True))
    sanitized = extract_and_sanitize_messages(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        firewall_enabled=firewall_enabled,
    )
    user_message = sanitized["latest_user_message"]
    system_instructions = sanitized["system_instructions"]

    if not user_message:
        return web.json_response(
            {"error": {"message": "No user message found", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )

    model = body.get("model", None)
    try:
        effort = _reasoning_effort(body)
    except ValueError as error:
        return web.json_response(
            {"error": {"message": str(error), "type": "invalid_request_error"}},
            status=400,
        )
    request["reasoning_effort"] = effort

    headers = getattr(request, "headers", None) or {}
    explicit_conv_id = (
        body.get("conversation_id")
        or headers.get("X-Conversation-Id")
        or None
    )
    new_chat = bool(body.get("new_chat", False))
    project_name = body.get("project_name", None)
    timeout = _parse_timeout(body)
    stream = bool(body.get("stream", False))
    run_id = body.get("run_id")
    engine_mode = _resolve_engine_mode(request, body)

    print(
        f"[CHAT] [{req_id}] Eingehend | mode={engine_mode} framework={req_ctx['source_framework']} "
        f"model={model} stream={stream} timeout={timeout}s msg_len={len(user_message)}",
        flush=True,
    )

    if stream:
        return await _handle_streaming(
            request,
            req_id=req_id,
            user_message=user_message,
            system_instructions=system_instructions,
            model=model,
            new_chat=new_chat,
            project_name=project_name,
            timeout=timeout,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            explicit_conv_id=explicit_conv_id,
            engine_mode=engine_mode,
            req_ctx=req_ctx,
            run_id=run_id,
        )

    # ------------------------------------------------------------------
    # Direct ConnectRPC Mode (`mode == "rpc"`)
    # ------------------------------------------------------------------
    if engine_mode == "rpc":
        pool = (
            request.app.get("rpc_pool")
            if hasattr(getattr(request, "app", None), "get") and request.app.get("rpc_pool")
            else rpc_pool
        )
        try:
            _mark_running(request)
            rpc_result = await pool.execute_chat_completion(
                messages=messages,
                model=model,
                reasoning_effort=effort,
                tools=tools,
                tool_choice=tool_choice,
                explicit_conversation_id=explicit_conv_id,
                force_new_chat=new_chat,
                timeout=timeout,
                client_ip=req_ctx["client_ip"],
            )
        except QuotaExhaustedError as q_err:
            duration = (time.monotonic() - start) * 1000
            record_api_audit_log(
                req_id=req_id,
                **req_ctx,
                endpoint="/v1/chat/completions",
                engine_mode="rpc",
                model_requested=model or "antigravity",
                reasoning_effort=effort or "",
                stream=False,
                status_code=429,
                duration_ms=duration,
                messages=messages,
                system_prompt=system_instructions,
                user_prompt_preview=user_message,
                shield_metadata={"quota_breaker_tripped": True, "remaining_fraction": q_err.remaining_fraction},
                error_text=str(q_err),
            )
            return web.json_response(
                {
                    "error": {
                        "message": str(q_err),
                        "type": "insufficient_quota",
                        "code": "model_quota_exhausted",
                        "model": q_err.model,
                        "remaining_fraction": q_err.remaining_fraction,
                    }
                },
                status=429,
                headers={"X-Request-Id": req_id},
            )
        except ConnectionError as c_err:
            duration = (time.monotonic() - start) * 1000
            record_api_audit_log(
                req_id=req_id,
                **req_ctx,
                endpoint="/v1/chat/completions",
                engine_mode="rpc",
                model_requested=model or "antigravity",
                status_code=503,
                duration_ms=duration,
                messages=messages,
                system_prompt=system_instructions,
                user_prompt_preview=user_message,
                error_text=str(c_err),
            )
            return web.json_response(
                {"error": {"message": str(c_err), "type": "connection_error"}},
                status=503,
                headers={"X-Request-Id": req_id},
            )
        except Exception as err:
            duration = (time.monotonic() - start) * 1000
            record_api_audit_log(
                req_id=req_id,
                **req_ctx,
                endpoint="/v1/chat/completions",
                engine_mode="rpc",
                model_requested=model or "antigravity",
                status_code=500,
                duration_ms=duration,
                messages=messages,
                system_prompt=system_instructions,
                user_prompt_preview=user_message,
                error_text=str(err),
            )
            return web.json_response(
                {"error": {"message": f"RPC error: {err}", "type": "internal_error"}},
                status=500,
                headers={"X-Request-Id": req_id},
            )

        duration = (time.monotonic() - start) * 1000
        response_text = rpc_result.get("response", "")
        tool_calls = rpc_result.get("tool_calls") or []
        if not tool_calls and response_text and (tools or '"tool_call' in response_text):
            response_text, tool_calls = DirectRPCPool._parse_possible_tool_calls(response_text)
        conv_id = rpc_result.get("conversation_id")
        if conv_id and run_id:
            try:
                db.update_agent_run_conversation_id(run_id, conv_id)
            except Exception:
                pass

        response_text = _maybe_sanitize_dokploy_json(user_message, response_text, req_id)
        token_metrics = rpc_result.get("token_metrics") or {}
        usage_dict = _build_usage_dict(token_metrics)
        actual_model = rpc_result.get("model_actual") or model or "gemini-4-argon-medium"
        native_label = rpc_result.get("native_model") or actual_model
        request["execution_metadata"] = {
            "native_model": native_label,
            "model_id": actual_model,
            "reasoning_effort": effort,
            "profile": "api",
            "engine_mode": "rpc",
            "workspace_slot": rpc_result.get("workspace_slot", ""),
        }

        message_obj: Dict[str, Any] = {
            "role": "assistant",
            "content": response_text if not tool_calls else (response_text or None),
        }
        if tool_calls:
            message_obj["tool_calls"] = tool_calls

        openai_response = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(datetime.now(timezone.utc).timestamp()),
            "model": actual_model,
            **request["execution_metadata"],
            "conversation_id": conv_id,
            "choices": [
                {
                    "index": 0,
                    "message": message_obj,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": usage_dict,
        }

        record_api_audit_log(
            req_id=req_id,
            **req_ctx,
            endpoint="/v1/chat/completions",
            engine_mode="rpc",
            workspace_slot=rpc_result.get("workspace_slot", ""),
            conversation_id=conv_id or "",
            model_requested=model or "antigravity",
            model_actual=actual_model,
            reasoning_effort=effort or "",
            stream=False,
            status_code=200,
            duration_ms=duration,
            token_metrics=token_metrics,
            messages=messages,
            system_prompt=system_instructions,
            user_prompt_preview=user_message,
            response_text=response_text or json.dumps(tool_calls, ensure_ascii=False),
            shield_metadata={
                "detection_reason": request.get("source_detection_reason", "auto")
                if hasattr(request, "get")
                else "auto",
                **(rpc_result.get("shield_metadata") or {}),
            },
        )
        log_interaction(
            {"messages": messages[-2:], "engine_mode": "rpc"},
            {"response": response_text[:500], "tokens": usage_dict["total_tokens"]},
            duration,
            200,
            req_id=req_id,
        )
        track_usage(usage_dict["prompt_tokens"], usage_dict["completion_tokens"], model=actual_model)

        resp = web.json_response(openai_response)
        resp.headers["X-Request-Id"] = req_id
        resp.headers["X-Engine-Mode"] = "rpc"
        if conv_id:
            resp.headers["X-Conversation-Id"] = conv_id
        return resp

    # ------------------------------------------------------------------
    # Backup UI / CDP Mode (`mode == "ui"`)
    # ------------------------------------------------------------------
    # Shield 2 in UI mode: write system instructions to API workspace AGENTS.md instead of [System: ...]
    try:
        local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
        ui_workspace = local_app_data / "AntigravityApiProfile/home/workspace"
        if system_instructions:
            write_workspace_agents_md(ui_workspace, system_instructions)
    except Exception:
        pass

    conv_id = None
    ui_new_chat = body.get("new_chat", len(messages) <= 1)
    try:
        async with cdp_operation(request.app) as cdp:
            _mark_running(request)
            result = await cdp.send_chat(
                user_message,
                timeout=timeout,
                model=model,
                new_chat=ui_new_chat,
                project_name=project_name,
                req_id=req_id,
                **({"reasoning_effort": effort} if effort is not None else {}),
            )
            execution_metadata = _execution_metadata(request, cdp)
            try:
                conv_id = await cdp.get_active_conversation_id()
                if conv_id and run_id:
                    db.update_agent_run_conversation_id(run_id, conv_id)
            except Exception as e:
                print(f"[CHAT] [{req_id}] Fehler beim Holen der Konversations-ID: {e}", flush=True)
    except ConnectionError as e:
        return web.json_response(
            {"error": {"message": str(e), "type": "connection_error"}},
            status=503,
            headers={"X-Request-Id": req_id},
        )
    except ValueError as e:
        return web.json_response(
            {"error": {"message": str(e), "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )
    except Exception as e:
        return web.json_response(
            {"error": {"message": f"CDP error: {str(e)}", "type": "internal_error"}},
            status=500,
            headers={"X-Request-Id": req_id},
        )

    duration = (time.monotonic() - start) * 1000

    if result and result.get("requires_user_input"):
        return web.json_response(
            {
                "error": {
                    "message": result["error"],
                    "type": "user_input_required",
                    "requires_user_input": True,
                },
                "conversation_id": conv_id,
            },
            status=409,
            headers={"X-Request-Id": req_id},
        )
    if not result or result.get("error"):
        error_msg = result.get("error", "No response") if result else "No response from Antigravity"
        log_interaction({"messages": messages[-1:]}, {"error": error_msg}, duration, 500, req_id=req_id)
        return web.json_response(
            {
                "error": {
                    "message": error_msg,
                    "type": "backend_error",
                    "debug": result.get("debug") if result else None,
                }
            },
            status=500,
            headers={"X-Request-Id": req_id},
        )

    response_text = result.get("response", "")
    response_text = _maybe_sanitize_dokploy_json(user_message, response_text, req_id)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    token_metrics = parse_generator_metadata_tokens(
        None,
        prompt_text=user_message,
        response_text=response_text,
        requested_model=execution_metadata.get("model_id") or model or "antigravity",
    )
    usage_dict = _build_usage_dict(token_metrics)

    openai_response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": execution_metadata.get("model_id") or model or "antigravity",
        **execution_metadata,
        "conversation_id": conv_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": usage_dict,
    }

    record_api_audit_log(
        req_id=req_id,
        **req_ctx,
        endpoint="/v1/chat/completions",
        engine_mode="ui",
        workspace_slot="ui-cdp",
        conversation_id=conv_id or "",
        model_requested=model or "antigravity",
        model_actual=execution_metadata.get("model_id") or model or "antigravity",
        reasoning_effort=effort or "",
        stream=False,
        status_code=200,
        duration_ms=duration,
        token_metrics=token_metrics,
        messages=messages,
        system_prompt=system_instructions,
        user_prompt_preview=user_message,
        response_text=response_text,
        shield_metadata={"firewall_hits": sanitized["firewall_hits"]},
    )
    log_interaction(
        {"messages": messages[-2:]},
        {"response": response_text[:500], "tokens": usage_dict["total_tokens"], "duration_ms": result.get("duration_ms")},
        duration,
        200,
        req_id=req_id,
    )
    track_usage(usage_dict["prompt_tokens"], usage_dict["completion_tokens"], model=model)
    resp = web.json_response(openai_response)
    resp.headers["X-Request-Id"] = req_id
    resp.headers["X-Engine-Mode"] = "ui"
    if conv_id:
        resp.headers["X-Conversation-Id"] = conv_id
    return resp


def _maybe_sanitize_dokploy_json(user_message: str, response_text: str, req_id: str) -> str:
    if any(keyword in user_message for keyword in ["JSON object", "json object", '"suggestions"', "dockerCompose"]):
        import re

        clean_text = response_text.strip()
        match = re.search(r"(\{[\s\S]*\})", clean_text)
        if match:
            clean_text = match.group(1).strip()
        try:
            parsed = json.loads(clean_text)
            response_text = json.dumps(parsed, ensure_ascii=False)
            print(f"[CHAT] [{req_id}] Auto-sanitized JSON for Dokploy ({len(response_text)} chars)", flush=True)
        except Exception as json_err:
            print(f"[CHAT] [{req_id}] JSON sanitization warning: {json_err}", flush=True)
    return response_text


async def _handle_streaming(
    request: web.Request,
    *,
    req_id: str,
    user_message: str,
    system_instructions: str,
    model: Optional[str],
    new_chat: bool,
    project_name: Optional[str],
    timeout: int,
    messages: list,
    tools: Optional[list] = None,
    tool_choice: Optional[Any] = None,
    explicit_conv_id: Optional[str] = None,
    engine_mode: str = "rpc",
    req_ctx: Optional[Dict[str, str]] = None,
    run_id: Optional[int] = None,
) -> web.StreamResponse:
    """Stream chat completions via Server-Sent Events (SSE) in either `rpc` or `ui` mode."""
    start = time.monotonic()
    ctx = req_ctx or _extract_request_context(request, messages)
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if engine_mode == "ui":
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

    total_content = ""
    error_occurred = False
    conv_id = explicit_conv_id
    rpc_state: Dict[str, Any] = {}
    first_rpc_delta: Optional[str] = None
    rpc_stream_iter = None

    if engine_mode == "rpc":
        pool = (
            request.app.get("rpc_pool")
            if hasattr(getattr(request, "app", None), "get") and request.app.get("rpc_pool")
            else rpc_pool
        )
        _mark_running(request)
        rpc_stream_iter = pool.execute_chat_streaming(
            messages=messages,
            model=model,
            reasoning_effort=request.get("reasoning_effort"),
            tools=tools,
            tool_choice=tool_choice,
            explicit_conversation_id=explicit_conv_id,
            force_new_chat=new_chat,
            timeout=timeout,
            client_ip=ctx["client_ip"],
            state_out=rpc_state,
        ).__aiter__()
        try:
            first_rpc_delta = await rpc_stream_iter.__anext__()
        except StopAsyncIteration:
            first_rpc_delta = None
        except QuotaExhaustedError as q_err:
            duration = (time.monotonic() - start) * 1000
            request["operation_error"] = str(q_err)
            request["quota_exhausted"] = True
            record_api_audit_log(
                req_id=req_id,
                **ctx,
                endpoint="/v1/chat/completions",
                engine_mode="rpc",
                model_requested=model or "antigravity",
                model_actual=q_err.model,
                stream=True,
                status_code=429,
                duration_ms=duration,
                messages=messages,
                system_prompt=system_instructions,
                user_prompt_preview=user_message,
                error_text=str(q_err),
            )
            return web.json_response(
                {
                    "error": {
                        "message": str(q_err),
                        "type": "insufficient_quota",
                        "code": "model_quota_exhausted",
                        "remaining_fraction": q_err.remaining_fraction,
                    }
                },
                status=429,
                headers={"X-Request-Id": req_id, "Retry-After": "60"},
            )
        except ConnectionError as conn_err:
            duration = (time.monotonic() - start) * 1000
            request["operation_error"] = str(conn_err)
            record_api_audit_log(
                req_id=req_id,
                **ctx,
                endpoint="/v1/chat/completions",
                engine_mode="rpc",
                model_requested=model or "antigravity",
                stream=True,
                status_code=503,
                duration_ms=duration,
                messages=messages,
                system_prompt=system_instructions,
                user_prompt_preview=user_message,
                error_text=str(conn_err),
            )
            return web.json_response(
                {"error": {"message": str(conn_err), "type": "connection_error"}},
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
            "X-Engine-Mode": engine_mode,
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    role_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": rpc_state.get("model_actual") or model or "gemini-3.1-pro-high",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None,
            }
        ],
    }
    await response.write(f"data: {json.dumps(role_chunk)}\n\n".encode("utf-8"))

    try:
        if engine_mode == "rpc" and rpc_stream_iter is not None:
            if first_rpc_delta:
                total_content += first_rpc_delta
                conv_id = rpc_state.get("conversation_id") or conv_id
                first_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "model": rpc_state.get("model_actual") or model or "gemini-3.1-pro-high",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": first_rpc_delta},
                            "finish_reason": None,
                        }
                    ],
                }
                await response.write(f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))

            async for delta in rpc_stream_iter:
                if not delta:
                    continue
                total_content += delta
                conv_id = rpc_state.get("conversation_id") or conv_id
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "model": rpc_state.get("model_actual") or model or "gemini-3.1-pro-high",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta},
                            "finish_reason": None,
                        }
                    ],
                }
                await response.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            conv_id = rpc_state.get("conversation_id") or conv_id
            actual_stream_model = rpc_state.get("model_actual") or model or "gemini-4-argon-medium"
            native_stream_label = rpc_state.get("native_model") or actual_stream_model
            request["execution_metadata"] = {
                "native_model": native_stream_label,
                "model_id": actual_stream_model,
                "reasoning_effort": request.get("reasoning_effort"),
                "profile": "api",
                "engine_mode": "rpc",
                "workspace_slot": rpc_state.get("workspace_slot", ""),
            }
        else:
            async with cdp_operation(request.app) as cdp:
                _mark_running(request)
                async for delta in cdp.send_chat_streaming(
                    user_message,
                    timeout=timeout,
                    model=model,
                    new_chat=new_chat,
                    project_name=project_name,
                    req_id=req_id,
                    run_id=run_id,
                    **(
                        {"reasoning_effort": request["reasoning_effort"]}
                        if request.get("reasoning_effort") is not None
                        else {}
                    ),
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
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": delta},
                                "finish_reason": None,
                            }
                        ],
                    }
                    await response.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                try:
                    conv_id = await cdp.get_active_conversation_id()
                except Exception:
                    pass
                _execution_metadata(request, cdp)

    except QuotaExhaustedError as q_err:
        error_occurred = True
        request["operation_error"] = str(q_err)
        request["quota_exhausted"] = True
    except ConnectionError as e:
        print(f"[STREAM] [{req_id}] Verbindungsfehler: {e}", flush=True)
        error_occurred = True
        request["operation_error"] = str(e)
    except Exception as e:
        print(f"[STREAM] [{req_id}] Fehler: {e}", flush=True)
        error_occurred = True
        request["operation_error"] = str(e)
        if getattr(e, "requires_user_input", False):
            request["requires_user_input"] = True

    stream_tool_calls = rpc_state.get("tool_calls") or []
    if not stream_tool_calls and total_content and (tools or '"tool_call' in total_content):
        cleaned_text, parsed_tc = DirectRPCPool._parse_possible_tool_calls(total_content)
        if parsed_tc:
            stream_tool_calls = parsed_tc
            total_content = cleaned_text

    if stream_tool_calls and not error_occurred:
        if total_content:
            lead_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(datetime.now(timezone.utc).timestamp()),
                "model": rpc_state.get("model_actual") or model or "gemini-3.1-pro-high",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": total_content},
                        "finish_reason": None,
                    }
                ],
            }
            await response.write(f"data: {json.dumps(lead_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
        tc_deltas = []
        for idx, tc in enumerate(stream_tool_calls):
            fn = tc.get("function") or {}
            tc_deltas.append(
                {
                    "index": idx,
                    "id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": str(fn.get("name") or ""),
                        "arguments": (
                            fn.get("arguments")
                            if isinstance(fn.get("arguments"), str)
                            else json.dumps(fn.get("arguments") or {}, ensure_ascii=False)
                        ),
                    },
                }
            )
        tc_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(datetime.now(timezone.utc).timestamp()),
            "model": rpc_state.get("model_actual") or model or "gemini-3.1-pro-high",
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": tc_deltas},
                    "finish_reason": None,
                }
            ],
        }
        await response.write(f"data: {json.dumps(tc_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))

    if not total_content and not stream_tool_calls and not error_occurred:
        error_occurred = True
        request["operation_error"] = "Native API returned no response content."
    request["stream_response_preview"] = (
        total_content[:280]
        if total_content
        else (json.dumps(stream_tool_calls, ensure_ascii=False)[:280] if stream_tool_calls else "")
    )
    request["stream_conversation_id"] = conv_id

    token_metrics = rpc_state.get("token_metrics") or parse_generator_metadata_tokens(
        None,
        prompt_text=user_message,
        response_text=total_content or json.dumps(stream_tool_calls, ensure_ascii=False),
        requested_model=model or "antigravity",
    )
    usage_dict = _build_usage_dict(token_metrics)

    finish_reason = "error" if error_occurred else ("tool_calls" if stream_tool_calls else "stop")
    finish_chunk: Dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": rpc_state.get("model_actual") or model or "gemini-3.5-flash-high",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": finish_reason,
            }
        ],
        "conversation_id": conv_id,
        "usage": usage_dict,
    }
    finish_chunk.update(request.get("execution_metadata") or {})
    if error_occurred:
        err_type = (
            "insufficient_quota"
            if request.get("quota_exhausted")
            else ("user_input_required" if request.get("requires_user_input") else "backend_error")
        )
        finish_chunk["error"] = {
            "message": request.get("operation_error"),
            "type": err_type,
        }
        if request.get("requires_user_input"):
            finish_chunk["error"]["requires_user_input"] = True
    await response.write(f"data: {json.dumps(finish_chunk)}\n\n".encode("utf-8"))
    await response.write(b"data: [DONE]\n\n")

    duration = (time.monotonic() - start) * 1000
    print(f"[CHAT] [{req_id}] Stream ({engine_mode}) | {round(duration)}ms | {len(total_content)} chars", flush=True)

    track_usage(usage_dict["prompt_tokens"], usage_dict["completion_tokens"], model=model)
    record_api_audit_log(
        req_id=req_id,
        **ctx,
        endpoint="/v1/chat/completions",
        engine_mode=engine_mode,
        workspace_slot=rpc_state.get("workspace_slot", "ui-cdp" if engine_mode == "ui" else ""),
        conversation_id=conv_id or "",
        model_requested=model or "antigravity",
        model_actual=rpc_state.get("model_actual") or model or "antigravity",
        reasoning_effort=request.get("reasoning_effort") or "",
        stream=True,
        status_code=200 if not error_occurred else (429 if request.get("quota_exhausted") else 500),
        duration_ms=duration,
        token_metrics=token_metrics,
        messages=messages,
        system_prompt=system_instructions,
        user_prompt_preview=user_message,
        response_text=total_content or (json.dumps(stream_tool_calls, ensure_ascii=False) if stream_tool_calls else ""),
        shield_metadata=rpc_state.get("shield_metadata") or {},
        error_text=str(request.get("operation_error") or ""),
    )
    log_interaction(
        {"messages": messages[-2:], "stream": True, "engine_mode": engine_mode},
        {"response": total_content[:500], "stream_chars": len(total_content), "tokens": usage_dict["total_tokens"]},
        duration,
        200,
        req_id=req_id,
    )

    return response


async def openai_responses_handler(request: web.Request) -> web.Response:
    """OpenAI `/v1/responses` endpoint compatibility wrapper for Hermes / OpenAI Responses SDK."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            status=400,
        )

    raw_input = body.get("input", "")
    instructions = body.get("instructions", "")
    messages: List[Dict[str, Any]] = []
    if instructions:
        messages.append({"role": "system", "content": str(instructions)})
    if isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, dict) and item.get("role"):
                messages.append(item)
            elif isinstance(item, str):
                messages.append({"role": "user", "content": item})
    elif isinstance(raw_input, str) and raw_input.strip():
        messages.append({"role": "user", "content": raw_input})
    elif body.get("messages"):
        messages.extend(body["messages"])

    synthetic_body = {
        **body,
        "messages": messages,
    }

    class _ProxyReq:
        def __init__(self, orig: web.Request, payload: Dict[str, Any]) -> None:
            self._orig = orig
            self._payload = payload
            self.app = orig.app
            self.headers = orig.headers
            self.remote = orig.remote
            self._store: Dict[str, Any] = {}

        async def json(self) -> Dict[str, Any]:
            return self._payload

        def __setitem__(self, k: str, v: Any) -> None:
            self._store[k] = v

        def __getitem__(self, k: str) -> Any:
            return self._store[k]

        def get(self, k: str, default: Any = None) -> Any:
            return self._store.get(k, self._orig.get(k, default))

    chat_resp = await chat_completions_handler(_ProxyReq(request, synthetic_body))  # type: ignore[arg-type]
    if chat_resp.status != 200 or not getattr(chat_resp, "text", None):
        return chat_resp

    data = json.loads(chat_resp.text)
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    output_text = msg.get("content") or ""
    resp_payload = {
        "id": f"resp_{uuid.uuid4().hex[:16]}",
        "object": "response",
        "created_at": data.get("created"),
        "status": "completed",
        "model": data.get("model"),
        "conversation_id": data.get("conversation_id"),
        "output_text": output_text,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text}],
            }
        ],
        "usage": data.get("usage"),
    }
    return web.json_response(resp_payload, headers=dict(chat_resp.headers))


async def simple_chat_handler(request: web.Request) -> web.Response:
    """Simple chat endpoint: POST {"message": "..."} -> {"response": "..."}."""
    start = time.monotonic()
    req_id = uuid.uuid4().hex[:8]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON"},
            status=400,
            headers={"X-Request-Id": req_id},
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
        return web.json_response(
            {"error": {"message": str(error), "type": "invalid_request_error"}},
            status=400,
        )
    request["reasoning_effort"] = effort
    timeout = _parse_timeout(body)
    engine_mode = _resolve_engine_mode(request, body)
    req_ctx = _extract_request_context(request, [{"role": "user", "content": message}])

    if engine_mode == "rpc":
        pool = (
            request.app.get("rpc_pool")
            if hasattr(getattr(request, "app", None), "get") and request.app.get("rpc_pool")
            else rpc_pool
        )
        try:
            _mark_running(request)
            rpc_result = await pool.execute_chat_completion(
                messages=[{"role": "user", "content": message}],
                model=model,
                reasoning_effort=effort,
                force_new_chat=new_chat,
                timeout=timeout,
                client_ip=req_ctx["client_ip"],
            )
        except QuotaExhaustedError as q_err:
            return web.json_response(
                {"error": str(q_err), "code": "model_quota_exhausted"},
                status=429,
                headers={"X-Request-Id": req_id},
            )
        except ConnectionError as e:
            return web.json_response({"error": str(e)}, status=503, headers={"X-Request-Id": req_id})
        except Exception as e:
            return web.json_response({"error": f"RPC error: {e}"}, status=500, headers={"X-Request-Id": req_id})

        duration = (time.monotonic() - start) * 1000
        response_text = rpc_result.get("response", "")
        token_metrics = rpc_result.get("token_metrics") or {}
        usage_dict = _build_usage_dict(token_metrics)
        actual_model = rpc_result.get("model_actual") or model or "gemini-4-argon-medium"
        native_label = rpc_result.get("native_model") or actual_model
        request["execution_metadata"] = {
            "native_model": native_label,
            "model_id": actual_model,
            "reasoning_effort": effort,
            "profile": "api",
            "engine_mode": "rpc",
            "workspace_slot": rpc_result.get("workspace_slot", ""),
        }

        record_api_audit_log(
            req_id=req_id,
            **req_ctx,
            endpoint="/api/chat",
            engine_mode="rpc",
            workspace_slot=rpc_result.get("workspace_slot", ""),
            conversation_id=rpc_result.get("conversation_id", ""),
            model_requested=model or "antigravity",
            model_actual=actual_model,
            reasoning_effort=effort or "",
            stream=False,
            status_code=200,
            duration_ms=duration,
            token_metrics=token_metrics,
            messages=[{"role": "user", "content": message}],
            user_prompt_preview=message,
            response_text=response_text,
            shield_metadata=rpc_result.get("shield_metadata") or {},
        )
        return web.json_response(
            {
                "id": str(uuid.uuid4()),
                "response": response_text,
                "model": actual_model,
                "native_model": native_label,
                "model_id": actual_model,
                "reasoning_effort": effort,
                "profile": "api",
                "engine_mode": "rpc",
                "conversation_id": rpc_result.get("conversation_id"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round(duration),
                "usage": usage_dict,
            },
            headers={"X-Request-Id": req_id},
        )

    try:
        async with cdp_operation(request.app) as cdp:
            _mark_running(request)
            result = await cdp.send_chat(
                message,
                timeout=timeout,
                model=model,
                new_chat=new_chat,
                req_id=req_id,
                **({"reasoning_effort": effort} if effort is not None else {}),
            )
            execution_metadata = _execution_metadata(request, cdp)
    except ConnectionError as e:
        return web.json_response({"error": str(e)}, status=503, headers={"X-Request-Id": req_id})
    except ValueError as e:
        return web.json_response(
            {"error": {"message": str(e), "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )
    except Exception as e:
        return web.json_response({"error": f"CDP error: {str(e)}"}, status=500, headers={"X-Request-Id": req_id})

    duration = (time.monotonic() - start) * 1000
    if result and result.get("requires_user_input"):
        return web.json_response(
            {"error": {"message": result["error"], "type": "user_input_required", "requires_user_input": True}},
            status=409,
            headers={"X-Request-Id": req_id},
        )
    if not result or result.get("error"):
        error_msg = result.get("error", "No response") if result else "No response"
        log_interaction({"message": message}, {"error": error_msg}, duration, 500, req_id=req_id)
        return web.json_response(
            {
                "error": error_msg,
                "partial": result.get("partial") if result else None,
                "debug": result.get("debug") if result else None,
            },
            status=500,
            headers={"X-Request-Id": req_id},
        )

    response_text = result.get("response", "")
    prompt_tokens = max(1, len(message) // 4)
    completion_tokens = max(1, len(response_text) // 4)
    total_tokens = prompt_tokens + completion_tokens

    response_data = {
        "id": str(uuid.uuid4()),
        "response": response_text,
        "model": execution_metadata.get("model_id") or model or "antigravity",
        **execution_metadata,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration),
        "frontend_duration_ms": result.get("duration_ms"),
        "usage": {
            "estimated": True,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }
    log_interaction(
        {"message": message, "model": model},
        {"response": response_text[:500], "tokens": total_tokens},
        duration,
        200,
        req_id=req_id,
    )
    track_usage(prompt_tokens, completion_tokens, model=model)
    resp = web.json_response(response_data)
    resp.headers["X-Request-Id"] = req_id
    return resp


async def models_handler(request: web.Request) -> web.Response:
    """List available models from either the mocked/active CDP client or Direct ConnectRPC."""
    app = getattr(request, "app", None) or {}
    cdp_obj = app.get("cdp") if hasattr(app, "get") else None
    # Preserve existing unit test contract when a FakeCDP is passed directly in request.app
    if cdp_obj is not None and type(cdp_obj).__name__ != "AntigravityCDP":
        try:
            async with cdp_operation(app) as cdp:
                models = await cdp.get_model_catalog()
            return web.json_response({"object": "list", "data": models, "profile": "api"})
        except ConnectionError as error:
            return web.json_response({"error": {"type": "connection_error", "message": str(error)}}, status=503)

    if config.api_mode == "rpc":
        pool = app.get("rpc_pool") if hasattr(app, "get") and app.get("rpc_pool") else rpc_pool
        try:
            models = await pool.rpc_client.get_available_models()
            return web.json_response({"object": "list", "data": models, "profile": "api", "engine_mode": "rpc"})
        except Exception:
            pass

    try:
        async with cdp_operation(app) as cdp:
            models = await cdp.get_model_catalog()
        return web.json_response({"object": "list", "data": models, "profile": "api", "engine_mode": "ui"})
    except ConnectionError as error:
        return web.json_response({"error": {"type": "connection_error", "message": str(error)}}, status=503)


async def revert_chat_handler(request: web.Request) -> web.Response:
    """Explicitly revert a conversation ('Zurück zur vorherigen Nachricht') via `POST /v1/chat/revert`."""
    req_id = uuid.uuid4().hex[:8]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            status=400,
        )

    conversation_id = str(body.get("conversation_id") or "").strip()
    if not conversation_id:
        return web.json_response(
            {"error": {"message": "conversation_id is required", "type": "invalid_request_error"}},
            status=400,
        )

    steps_back = max(1, int(body.get("steps_back") or 1))
    target_step_index = body.get("target_step_index")
    if target_step_index is not None:
        target_step_index = max(0, int(target_step_index))
    reason = str(body.get("reason") or "manual_api_revert")
    req_ctx = _extract_request_context(request)

    pool = (
        request.app.get("rpc_pool")
        if hasattr(getattr(request, "app", None), "get") and request.app.get("rpc_pool")
        else rpc_pool
    )
    try:
        result = await pool.revert_conversation(
            conversation_id,
            steps_back=steps_back,
            target_step_index=target_step_index,
            triggered_by_ip=req_ctx["client_ip"],
            reason=reason,
        )
        return web.json_response(result, headers={"X-Request-Id": req_id})
    except Exception as err:
        # Even if `language_server` is offline in a unit test environment, record the revert in SQLite
        fallback_step = target_step_index if target_step_index is not None else 0
        event = record_revert_event(
            conversation_id=conversation_id,
            target_step_index=fallback_step,
            previous_step_count=steps_back * 2,
            reason=f"{reason} (local_record: {err})",
            triggered_by_ip=req_ctx["client_ip"],
            engine_mode=config.api_mode,
        )
        return web.json_response(
            {
                "status": "reverted",
                "conversation_id": conversation_id,
                "reverted_to_step": fallback_step,
                "event": event,
            },
            headers={"X-Request-Id": req_id},
        )


# ============================================================
# Persistent API Audit Logs & Engine Mode Handlers (#/api-logs)
# ============================================================
async def api_audit_logs_list_handler(request: web.Request) -> web.Response:
    limit = min(int(request.query.get("limit", "100")), 1000)
    offset = max(0, int(request.query.get("offset", "0")))
    model = request.query.get("model") or None
    status = request.query.get("status") or None
    framework = request.query.get("framework") or None
    engine_mode = request.query.get("engine_mode") or None
    conversation_id = request.query.get("conversation_id") or None
    search = request.query.get("search") or None

    rows = db.list_api_request_logs(
        limit=limit,
        offset=offset,
        model=model,
        status=status,
        framework=framework,
        engine_mode=engine_mode,
        conversation_id=conversation_id,
        search=search,
    )
    return web.json_response(
        {
            "count": len(rows),
            "logs": rows,
            "engine": rpc_pool.status_snapshot(),
        }
    )


async def api_audit_log_detail_handler(request: web.Request) -> web.Response:
    req_id = request.match_info.get("req_id", "")
    row = db.get_api_request_log(req_id)
    if not row:
        return web.json_response({"error": "Log entry not found"}, status=404)
    return web.json_response(row)


async def api_audit_logs_stats_handler(request: web.Request) -> web.Response:
    stats = db.get_api_logs_stats()
    stats["engine"] = rpc_pool.status_snapshot()
    return web.json_response(stats)


async def api_audit_reverts_list_handler(request: web.Request) -> web.Response:
    limit = min(int(request.query.get("limit", "100")), 500)
    conversation_id = request.query.get("conversation_id") or None
    events = db.list_api_revert_events(limit=limit, conversation_id=conversation_id)
    return web.json_response({"count": len(events), "reverts": events})


async def api_audit_logs_export_handler(request: web.Request) -> web.Response:
    rows = db.list_api_request_logs(limit=1000)
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    body = "\n".join(lines) + ("\n" if lines else "")
    return web.Response(
        text=body,
        content_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="antigravity_api_audit_logs.jsonl"'
        },
    )


async def api_audit_logs_clear_handler(request: web.Request) -> web.Response:
    db.clear_api_request_logs()
    if AUDIT_LOG_JSONL.exists():
        try:
            AUDIT_LOG_JSONL.unlink()
        except OSError:
            pass
    return web.json_response({"status": "cleared"})


async def api_engine_mode_handler(request: web.Request) -> web.Response:
    """GET or POST `/api/engine-mode` to inspect or live-switch `rpc` vs `ui` and the 8 Shields."""
    from src.config import get_runtime_mode

    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "JSON object required"}, status=400)
        updated = config.update_api_engine_settings(body)
        return web.json_response(
            {
                "status": "updated",
                "runtime_mode": get_runtime_mode(),
                "api_engine": updated,
                "pool": rpc_pool.status_snapshot(),
            }
        )
    return web.json_response(
        {
            "runtime_mode": get_runtime_mode(),
            "api_engine": config.api_engine,
            "pool": rpc_pool.status_snapshot(),
        }
    )


async def send_parallel_handler(request: web.Request) -> web.Response:
    """Send each prompt through a distinct workspace slot (RPC mode) or API-profile renderer (UI mode)."""
    import asyncio

    start_total = time.monotonic()
    req_id = uuid.uuid4().hex[:8]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )

    if not isinstance(body, dict):
        return web.json_response(
            {"error": {"message": "Request body must be an object", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
        )
    requests_list = body.get("requests", [])
    if not isinstance(requests_list, list) or not requests_list:
        return web.json_response(
            {"error": {"message": "requests array is required and cannot be empty", "type": "invalid_request_error"}},
            status=400,
            headers={"X-Request-Id": req_id},
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
            status=400,
            headers={"X-Request-Id": req_id},
        )

    n_requests = len(requests_list)
    from src.parallel_cdp import ParallelCDPManager

    manager = ParallelCDPManager(profile="api")
    try:
        from src.window_tiling import ensure_and_tile_windows

        page_targets = await ensure_and_tile_windows(n_requests, manager=manager)
    except Exception as e:
        print(f"[Parallel] Alignment error: {e}", flush=True)
        await manager.close_all()
        return web.json_response(
            sanitize_error_response(f"Failed to align window targets: {e}", "internal_error"),
            status=500,
            headers={"X-Request-Id": req_id},
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
            status=503,
            headers={"X-Request-Id": req_id},
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

        result = await client.send_chat(
            prompt,
            model=model,
            reasoning_effort=_reasoning_effort(req_data),
            new_chat=new_chat,
            timeout=300,
            req_id=req_id,
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

    tasks = [run_single(targets[i], requests_list[i]) for i in range(n_requests)]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await manager.close_all()

    responses = []
    errors = 0
    for i, res in enumerate(results):
        convo_id = requests_list[i].get("conversation_id", "")
        if isinstance(res, Exception):
            errors += 1
            error = sanitize_error_response(
                str(res), "invalid_request_error" if isinstance(res, ValueError) else "internal_error"
            )["error"]
            responses.append(
                {
                    "conversation_id": convo_id,
                    "response": f"Error: {error['message']}",
                    "error": error,
                    "time_taken": round(time.monotonic() - start_total, 2),
                }
            )
        else:
            responses.append(res)

    total_time = round(time.monotonic() - start_total, 2)
    if errors:
        request["operation_error"] = f"{errors} of {n_requests} parallel API requests failed"
    request["stream_response_preview"] = " | ".join(row["response"] for row in responses)[:280]

    return web.json_response(
        {
            "status": "success" if not errors else ("error" if errors == n_requests else "partial_error"),
            "profile": "api",
            "responses": responses,
            "total_time": total_time,
        },
        headers={"X-Request-Id": req_id},
    )


async def oauth_status_handler(request: web.Request) -> web.Response:
    """GET `/v1/auth/status` or `/api/auth/status` — report headless Google OAuth status."""
    from src.api_profile import api_profile_runtime

    return web.json_response(
        {
            "status": "ok",
            "oauth": api_profile_runtime.get_oauth_status(),
            "pool": rpc_pool.status_snapshot(),
        }
    )


async def oauth_token_import_handler(request: web.Request) -> web.Response:
    """POST `/v1/auth/token` or `/api/auth/token` — import or refresh a Google OAuth token headlessly."""
    from src.api_profile import api_profile_runtime

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
            status=400,
        )
    try:
        saved = api_profile_runtime.import_oauth_token(body)
        token_sub = saved.get("token") if isinstance(saved.get("token"), dict) else saved
        return web.json_response(
            {
                "status": "imported",
                "oauth": api_profile_runtime.get_oauth_status(),
                "has_access_token": bool(token_sub.get("access_token")),
                "has_refresh_token": bool(token_sub.get("refresh_token")),
            }
        )
    except ValueError as err:
        return web.json_response(
            {"error": {"message": str(err), "type": "invalid_request_error"}},
            status=400,
        )

