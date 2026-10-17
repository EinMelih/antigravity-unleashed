"""HTTP handlers for native Anti-Gravity scheduled tasks."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiohttp import web

from src.scheduled_task_service import ScheduledTaskService


_scheduled_task_service = ScheduledTaskService()


async def _respond(operation: Callable[[], Awaitable[Any]], status: int = 200) -> web.Response:
    try:
        payload = await operation()
        return web.json_response(payload, status=status)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except KeyError as error:
        task_id = str(error.args[0] if error.args else "")
        return web.json_response(
            {"error": f"Scheduled task not found: {task_id}"},
            status=404,
        )
    except FileExistsError as error:
        task_id = str(error.args[0] if error.args else "")
        return web.json_response(
            {"error": f"Scheduled task already exists: {task_id}"},
            status=409,
        )
    except (ConnectionError, TimeoutError) as error:
        return web.json_response({"error": str(error)}, status=503)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=502)


async def handle_list_scheduled_tasks(request: web.Request) -> web.Response:
    """GET /api/antigravity/scheduled-tasks."""
    return await _respond(_scheduled_task_service.list_tasks)


async def handle_create_scheduled_task(request: web.Request) -> web.Response:
    """POST /api/antigravity/scheduled-tasks."""
    body = await request.json()
    return await _respond(
        lambda: _scheduled_task_service.create_task(body),
        status=201,
    )


async def handle_update_scheduled_task(request: web.Request) -> web.Response:
    """PATCH /api/antigravity/scheduled-tasks/{task_id}."""
    body = await request.json()
    task_id = request.match_info["task_id"]
    return await _respond(
        lambda: _scheduled_task_service.update_task(task_id, body)
    )


async def handle_enable_scheduled_task(request: web.Request) -> web.Response:
    """POST /api/antigravity/scheduled-tasks/{task_id}/enable."""
    task_id = request.match_info["task_id"]
    return await _respond(
        lambda: _scheduled_task_service.set_enabled(task_id, True)
    )


async def handle_disable_scheduled_task(request: web.Request) -> web.Response:
    """POST /api/antigravity/scheduled-tasks/{task_id}/disable."""
    task_id = request.match_info["task_id"]
    return await _respond(
        lambda: _scheduled_task_service.set_enabled(task_id, False)
    )


async def handle_run_scheduled_task(request: web.Request) -> web.Response:
    """Compatibility alias for restarting the native scheduler."""
    task_id = request.match_info["task_id"]
    return await _respond(lambda: _scheduled_task_service.run_task(task_id))


async def handle_restart_scheduled_task(request: web.Request) -> web.Response:
    """POST /api/antigravity/scheduled-tasks/{task_id}/restart."""
    task_id = request.match_info["task_id"]
    return await _respond(lambda: _scheduled_task_service.restart_task(task_id))


async def handle_delete_scheduled_task(request: web.Request) -> web.Response:
    """DELETE /api/antigravity/scheduled-tasks/{task_id}."""
    task_id = request.match_info["task_id"]
    return await _respond(lambda: _scheduled_task_service.delete_task(task_id))


async def handle_get_scheduled_task_events(request: web.Request) -> web.Response:
    """GET /api/antigravity/scheduled-tasks/{task_id}/events."""
    task_id = request.match_info["task_id"]
    return await _respond(lambda: _scheduled_task_service.get_events(task_id))
