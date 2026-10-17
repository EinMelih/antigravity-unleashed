"""HTTP adapter for the bounded project stack inspector."""

from __future__ import annotations

import asyncio

from aiohttp import web

from src.database import db
from src.project_stack import ProjectPathUnavailable, inspect_project_stack


def _error_response(message: str, code: str, status: int) -> web.Response:
    return web.json_response(
        {"error": message, "code": code},
        status=status,
        headers={"Cache-Control": "no-store"},
    )


async def handle_project_stack(request: web.Request) -> web.Response:
    """GET /api/projects/{id}/stack for one registered project."""
    raw_project_id = str(request.match_info.get("id") or "")
    if not raw_project_id.isascii() or not raw_project_id.isdecimal():
        return _error_response("Invalid project id.", "INVALID_PROJECT_ID", 400)
    project_id = int(raw_project_id)
    if project_id <= 0 or project_id > 9_223_372_036_854_775_807:
        return _error_response("Invalid project id.", "INVALID_PROJECT_ID", 400)

    try:
        project = await asyncio.to_thread(db.get_project, project_id)
    except Exception:
        return _error_response(
            "Project stack inspection failed.",
            "STACK_INSPECTION_FAILED",
            500,
        )
    if not project:
        return _error_response("Project not found.", "PROJECT_NOT_FOUND", 404)
    try:
        payload = await asyncio.to_thread(inspect_project_stack, project)
    except ProjectPathUnavailable:
        return _error_response(
            "Registered project directory is unavailable.",
            "PROJECT_PATH_UNAVAILABLE",
            409,
        )
    except Exception:
        return _error_response(
            "Project stack inspection failed.",
            "STACK_INSPECTION_FAILED",
            500,
        )
    return web.json_response(
        payload,
        headers={"Cache-Control": "no-store"},
    )
