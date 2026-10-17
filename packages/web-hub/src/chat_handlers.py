"""
chat_handlers.py - HTTP & SSE handlers for reading/streaming Antigravity chats.

Endpoints:
  GET  /api/chats                  -> handle_get_chats
  GET  /api/chats/active           -> handle_get_active_chat
  GET  /api/chats/{id}             -> handle_get_chat_snapshot
  GET  /api/chats/{id}/stream      -> handle_stream_chat   (SSE)
  POST /api/chats/{id}/navigate    -> handle_navigate_chat

Architecture note:
  Each handler creates a short-lived AntigravityCDP connection.
  The connection is closed after the request completes (or kept open for SSE).
  This avoids conflicts with the Orchestrator's own CDP session.
"""

import asyncio
import json
import logging
from typing import Optional
from aiohttp import web

logger = logging.getLogger(__name__)


async def _get_connected_cdp():
    """Create and return a connected AntigravityCDP instance.

    Raises HTTPServiceUnavailable if the Desktop App is not running.
    """
    from src.cdp_client import AntigravityCDP
    cdp = AntigravityCDP()
    try:
        await cdp.connect()
        await cdp.inject_bridge()
        return cdp
    except Exception as e:
        raise web.HTTPServiceUnavailable(
            reason=f"Cannot connect to Anti-Gravity Desktop App: {e}"
        )


def _json_response(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        status=status,
    )


def _sse_event(event: str, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ============================================================
# GET /api/chats  - List all visible chats in the sidebar
# ============================================================

async def handle_get_chats(request: web.Request) -> web.Response:
    """Return all chats visible in the Antigravity sidebar."""
    cdp = None
    try:
        cdp = await _get_connected_cdp()
        result = await cdp.get_chat_list()
        return _json_response(result)
    except web.HTTPException:
        raise
    except Exception as e:
        logger.error(f"handle_get_chats error: {e}", exc_info=True)
        return _json_response({"error": str(e), "chats": [], "count": 0}, status=500)
    finally:
        if cdp:
            try:
                await cdp.disconnect()
            except Exception:
                pass


# ============================================================
# GET /api/chats/active  - Active chat metadata
# ============================================================

async def handle_get_active_chat(request: web.Request) -> web.Response:
    """Return metadata about the currently active chat."""
    cdp = None
    try:
        cdp = await _get_connected_cdp()
        meta = await cdp.get_active_chat_meta()
        return _json_response(meta)
    except web.HTTPException:
        raise
    except Exception as e:
        logger.error(f"handle_get_active_chat error: {e}", exc_info=True)
        return _json_response({"error": str(e)}, status=500)
    finally:
        if cdp:
            try:
                await cdp.disconnect()
            except Exception:
                pass


# ============================================================
# GET /api/chats/{chat_id}  - Full chat snapshot
# ============================================================

async def handle_get_chat_snapshot(request: web.Request) -> web.Response:
    """Return the full message history of a chat with type detection.

    URL parameter:
      chat_id - UUID of the conversation (or 'active' for the current one)

    Each message in the response has:
      index, role (user|assistant), type (text|thinking|tool_call|tool_result|system),
      content, thinking (if applicable), has_code, is_finished
    """
    chat_id = request.match_info.get("chat_id")
    if chat_id == "active":
        chat_id = None

    cdp = None
    try:
        cdp = await _get_connected_cdp()
        history = await cdp.get_chat_history(chat_id=chat_id)
        return _json_response(history)
    except web.HTTPException:
        raise
    except Exception as e:
        logger.error(f"handle_get_chat_snapshot error: {e}", exc_info=True)
        return _json_response({"error": str(e), "messages": []}, status=500)
    finally:
        if cdp:
            try:
                await cdp.disconnect()
            except Exception:
                pass


# ============================================================
# GET /api/chats/{chat_id}/stream  - Live SSE token stream
# ============================================================

async def handle_stream_chat(request: web.Request) -> web.StreamResponse:
    """Stream new tokens from a chat via Server-Sent Events.

    URL parameter:
      chat_id - UUID of the conversation (or 'active' for the current one)

    Query parameters:
      timeout  - Max duration in seconds (default: 300)

    SSE event types:
      connected  - Stream established
      token      - New token delta: {delta, type, message_index, current_len, is_running, finished, timestamp}
      done       - Stream finished: {reason, duration_s}
      error      - Error occurred: {error, code?}
    """
    chat_id = request.match_info.get("chat_id")
    if chat_id == "active":
        chat_id = None

    timeout = float(request.rel_url.query.get("timeout", "300"))

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        }
    )
    await response.prepare(request)

    cdp = None
    try:
        cdp = await _get_connected_cdp()

        await response.write(
            _sse_event("connected", {
                "chat_id": chat_id or "active",
                "timeout": timeout,
                "message": "Stream connected. Waiting for tokens..."
            }).encode("utf-8")
        )

        async for token_data in cdp.stream_chat_tokens(chat_id=chat_id, timeout=timeout):
            if token_data.get("type") == "system":
                await response.write(
                    _sse_event("done", token_data).encode("utf-8")
                )
                break
            else:
                await response.write(
                    _sse_event("token", token_data).encode("utf-8")
                )

    except web.HTTPServiceUnavailable as e:
        try:
            await response.write(
                _sse_event("error", {"error": str(e), "code": "CDP_UNAVAILABLE"}).encode("utf-8")
            )
        except Exception:
            pass
    except asyncio.CancelledError:
        # Client disconnected - clean exit
        pass
    except Exception as e:
        logger.error(f"handle_stream_chat error: {e}", exc_info=True)
        try:
            await response.write(
                _sse_event("error", {"error": str(e)}).encode("utf-8")
            )
        except Exception:
            pass
    finally:
        if cdp:
            try:
                await cdp.disconnect()
            except Exception:
                pass

    return response


# ============================================================
# POST /api/chats/{chat_id}/navigate  - Navigate to a chat
# ============================================================

async def handle_navigate_chat(request: web.Request) -> web.Response:
    """Navigate the Antigravity webview to a specific chat.

    URL parameter:
      chat_id - UUID of the conversation to navigate to

    Response:
      { success: bool, chat_id: str, url: str }
    """
    chat_id = request.match_info.get("chat_id")
    if not chat_id:
        return _json_response({"error": "chat_id is required"}, status=400)

    cdp = None
    try:
        cdp = await _get_connected_cdp()
        result = await cdp.navigate_to_chat(chat_id)
        status = 200 if result.get("success") else 422
        return _json_response(result, status=status)
    except web.HTTPException as he:
        return _json_response({"error": he.reason, "success": False}, status=he.status)
    except Exception as e:
        logger.error(f"handle_navigate_chat error: {e}", exc_info=True)
        return _json_response({"error": str(e), "success": False}, status=500)
    finally:
        if cdp:
            try:
                await cdp.disconnect()
            except Exception:
                pass
