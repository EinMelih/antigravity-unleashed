"""Exact, read-only workspace authorization for the desktop project wizard."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from src.database import db
from src.local_admin_security import local_cors_response


ACTIVE_TASK_STATES = ("running",)
MAX_WORKSPACE_PATH_LENGTH = 32_768


def _canonical_directory(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_WORKSPACE_PATH_LENGTH:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_dir():
        return None
    return os.path.normcase(str(resolved))


def authorized_workspace_kind(candidate: Any, *, database=None) -> str:
    """Return the narrow authorization class without exposing stored paths."""
    database = database or db
    target = _canonical_directory(candidate)
    if not target:
        return ""

    for project in database.get_projects():
        if _canonical_directory(project.get("path")) == target:
            return "project"

    placeholders = ",".join("?" for _ in ACTIVE_TASK_STATES)
    with database._get_connection() as connection:
        rows = connection.execute(
            f"""SELECT worktree_path FROM control_agent_tasks
                WHERE status IN ({placeholders}) AND worktree_path <> ''""",
            ACTIVE_TASK_STATES,
        ).fetchall()
    for row in rows:
        worktree_path = row["worktree_path"] if hasattr(row, "keys") else row[0]
        if _canonical_directory(worktree_path) == target:
            return "active_task_worktree"
    return ""


async def _authorize_workspace(request: web.Request) -> web.Response:
    if request.content_length is not None and request.content_length > 64 * 1024:
        return web.json_response({"authorized": False, "kind": ""}, status=413)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"authorized": False, "kind": ""}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"authorized": False, "kind": ""}, status=400)
    kind = await asyncio.to_thread(authorized_workspace_kind, payload.get("path"))
    response = web.json_response({"authorized": bool(kind), "kind": kind})
    response.headers["Cache-Control"] = "no-store"
    return response


async def handle_workspace_authorization(request: web.Request) -> web.StreamResponse:
    return await local_cors_response(
        request,
        _authorize_workspace,
        methods="POST, OPTIONS",
    )
