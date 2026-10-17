"""HTTP adapters for safe project frontend/backend runtimes."""

from __future__ import annotations

from aiohttp import web

from src.database import db
from src.project_runtime import project_runtime_manager


def _project(request: web.Request):
    project_id = int(request.match_info["id"])
    project = db.get_project(project_id)
    if not project:
        raise KeyError(project_id)
    return project


def _error(error: Exception) -> web.Response:
    if isinstance(error, KeyError):
        return web.json_response({"error": "Project not found."}, status=404)
    if isinstance(error, ValueError):
        return web.json_response({"error": str(error)}, status=400)
    if isinstance(error, RuntimeError):
        return web.json_response({"error": str(error)}, status=409)
    return web.json_response({"error": str(error)}, status=500)


async def handle_project_runtime(request: web.Request) -> web.Response:
    try:
        return web.json_response(project_runtime_manager.snapshot(_project(request)))
    except Exception as error:
        return _error(error)


async def handle_save_project_runtime(request: web.Request) -> web.Response:
    try:
        project = _project(request)
        profile = project_runtime_manager.save_profile(project, await request.json())
        return web.json_response({
            "success": True,
            "profile": profile,
            **project_runtime_manager.snapshot(project),
        })
    except Exception as error:
        return _error(error)


async def handle_start_project_runtime(request: web.Request) -> web.Response:
    try:
        project = _project(request)
        service_name = request.match_info["service"]
        body = await request.json() if request.can_read_body else {}
        if isinstance(body, dict) and body.get("services"):
            project_runtime_manager.save_profile(project, body)
        return web.json_response(
            await project_runtime_manager.start(project, service_name),
            status=201,
        )
    except Exception as error:
        return _error(error)


async def handle_setup_project_runtime(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            await project_runtime_manager.setup_dependencies(
                _project(request),
                request.match_info["service"],
            )
        )
    except Exception as error:
        return _error(error)


async def handle_stop_project_runtime(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            await project_runtime_manager.stop(
                _project(request),
                request.match_info["service"],
            )
        )
    except Exception as error:
        return _error(error)


async def handle_capture_project_screenshot(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            await project_runtime_manager.capture_screenshot(_project(request)),
            status=201,
        )
    except Exception as error:
        return _error(error)


async def handle_project_screenshot_image(request: web.Request) -> web.StreamResponse:
    try:
        project = _project(request)
        path = project_runtime_manager.screenshot_path(int(project["id"]))
        if not path.is_file():
            return web.json_response({"error": "No project screenshot exists yet."}, status=404)
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})
    except Exception as error:
        return _error(error)
