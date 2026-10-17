"""Loopback-only HTTP endpoints for the local Codex app-server manager."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict
from urllib.parse import urlsplit

from aiohttp import web

from src.codex_app_server import (
    CodexAppServerError,
    CodexBinaryNotFound,
    CodexRequestTimeout,
    CodexUnavailable,
    CodexValidationError,
    get_codex_manager,
)
from src.local_admin_security import local_cors_response
from src.workspace_authorization import authorized_workspace_kind


class CodexWorkspaceUnauthorized(CodexAppServerError):
    code = "codex_workspace_unauthorized"


def _error_response(error: CodexAppServerError) -> web.Response:
    if isinstance(error, CodexWorkspaceUnauthorized):
        status = 403
    elif isinstance(error, CodexValidationError):
        status = 400
    elif isinstance(error, CodexRequestTimeout):
        status = 504
    elif isinstance(error, (CodexBinaryNotFound, CodexUnavailable)):
        status = 503
    else:
        status = 502
    return web.json_response(
        {"error": error.public_message, "code": error.code}, status=status
    )


async def _json_body(request: web.Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception as error:
        raise CodexValidationError("A valid JSON body is required.") from error
    if not isinstance(body, dict):
        raise CodexValidationError("A JSON object is required.")
    return body


async def _guard(
    request: web.Request,
    implementation: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    methods: str,
) -> web.StreamResponse:
    async def safe_implementation(
        guarded_request: web.Request,
    ) -> web.StreamResponse:
        try:
            return await implementation(guarded_request)
        except CodexAppServerError as error:
            return _error_response(error)
        except Exception:
            return web.json_response(
                {
                    "error": "The Codex integration failed unexpectedly.",
                    "code": "codex_internal_error",
                },
                status=500,
            )

    return await local_cors_response(
        request, safe_implementation, methods=methods
    )


async def handle_codex_status(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        try:
            result = await asyncio.to_thread(get_codex_manager().status)
            return web.json_response(result)
        except CodexAppServerError as error:
            return _error_response(error)

    return await _guard(request, implementation, methods="GET, OPTIONS")


async def handle_codex_login_start(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        try:
            result = await asyncio.to_thread(get_codex_manager().login_start)
            parsed = urlsplit(result["auth_url"])
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise CodexValidationError("Codex returned an unsafe sign-in URL.")
            return web.json_response(result, status=201)
        except CodexAppServerError as error:
            return _error_response(error)

    return await _guard(request, implementation, methods="POST, OPTIONS")


async def handle_codex_login_cancel(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        try:
            body = await _json_body(request)
            result = await asyncio.to_thread(
                get_codex_manager().login_cancel,
                str(body.get("login_id") or ""),
            )
            return web.json_response(result)
        except CodexAppServerError as error:
            return _error_response(error)

    return await _guard(request, implementation, methods="POST, OPTIONS")


async def handle_codex_logout(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        try:
            await asyncio.to_thread(get_codex_manager().logout)
            return web.json_response({"success": True})
        except CodexAppServerError as error:
            return _error_response(error)

    return await _guard(request, implementation, methods="POST, OPTIONS")


async def handle_codex_models(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        try:
            models = await asyncio.to_thread(get_codex_manager().list_models)
            return web.json_response({"models": models})
        except CodexAppServerError as error:
            return _error_response(error)

    return await _guard(request, implementation, methods="GET, OPTIONS")


async def handle_codex_chat(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        try:
            body = await _json_body(request)
            model = str(body.get("model") or "")
            prompt = str(body.get("prompt") or "")
            thread_id = body.get("thread_id")
            reasoning_effort = body.get("reasoning_effort")
            images = body.get("images") or []
            if not isinstance(images, list):
                raise CodexValidationError("images must be a list.")
            result = await asyncio.to_thread(
                get_codex_manager().chat,
                model,
                prompt,
                thread_id=(str(thread_id) if thread_id else None),
                reasoning_effort=(
                    str(reasoning_effort) if reasoning_effort else None
                ),
                image_urls=[str(image) for image in images],
            )
            return web.json_response(result, status=201 if not thread_id else 200)
        except CodexAppServerError as error:
            return _error_response(error)

    return await _guard(request, implementation, methods="POST, OPTIONS")


async def handle_codex_agent_turn(request: web.Request) -> web.StreamResponse:
    async def implementation(_: web.Request) -> web.StreamResponse:
        body = await _json_body(request)
        workspace_path = str(body.get("workspace_path") or "")
        workspace_kind = await asyncio.to_thread(
            authorized_workspace_kind, workspace_path
        )
        if not workspace_kind:
            raise CodexWorkspaceUnauthorized(
                "The selected workspace is not authorized for Anti-Gravity."
            )

        thread_id = body.get("thread_id")
        reasoning_effort = body.get("reasoning_effort")
        result = await asyncio.to_thread(
            get_codex_manager().agent_turn,
            str(body.get("model") or ""),
            str(body.get("prompt") or ""),
            workspace_path=workspace_path,
            conversation_id=str(body.get("conversation_id") or ""),
            thread_id=(str(thread_id) if thread_id else None),
            reasoning_effort=(
                str(reasoning_effort) if reasoning_effort else None
            ),
        )
        response = web.json_response(result, status=201 if not thread_id else 200)
        response.headers["Cache-Control"] = "no-store"
        return response

    return await _guard(request, implementation, methods="POST, OPTIONS")


def register_codex_routes(app: web.Application) -> None:
    """Register method-specific endpoints and their local CORS preflights."""
    routes = (
        ("GET", "/api/antigravity/codex/status", handle_codex_status),
        ("POST", "/api/antigravity/codex/login/start", handle_codex_login_start),
        ("POST", "/api/antigravity/codex/login/cancel", handle_codex_login_cancel),
        ("POST", "/api/antigravity/codex/logout", handle_codex_logout),
        ("GET", "/api/antigravity/codex/models", handle_codex_models),
        ("POST", "/api/antigravity/codex/chat", handle_codex_chat),
        (
            "POST",
            "/api/antigravity/codex/agent-turn",
            handle_codex_agent_turn,
        ),
    )
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
        app.router.add_route("OPTIONS", path, handler)
