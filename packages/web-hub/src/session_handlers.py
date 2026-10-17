import time
import platform
import asyncio
import aiohttp
from aiohttp import web
from typing import Optional, Dict, Any

from src.config import config
from src.session_pool import SessionPool, APIBridgeSession, SessionStatus


def _get_client_id(request: web.Request) -> Optional[str]:
    """Extracts Client-ID header for session affinity mapping."""
    return request.headers.get('X-Client-Id')


def _build_auth_headers() -> Dict[str, str]:
    """Generates standard Authorization header for forwarding requests."""
    token = config.auth_token
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


async def _proxy_request(
    pool: SessionPool,
    session: APIBridgeSession,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, Any]] = None,
) -> tuple[int, Dict[str, Any]]:
    """Proxies an HTTP request to a downstream API bridge instance."""
    url = f"{session.url}{path}"
    proxy_headers = _build_auth_headers()
    if headers:
        proxy_headers.update(headers)

    if not pool._http:
        return 500, {"error": {"message": "HTTP client session not initialized in pool", "type": "internal_error"}}

    start = time.monotonic()
    try:
        async with pool._http.request(
            method, url,
            json=body,
            headers=proxy_headers,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            duration_ms = (time.monotonic() - start) * 1000

            try:
                result = await resp.json()
            except Exception:
                text = await resp.text()
                result = {"raw_response": text[:2000]}

            session.record_response(duration_ms)

            if resp.status >= 500:
                print(f"[PROXY] Fehler von {session.name}: HTTP {resp.status} ({round(duration_ms)}ms)", flush=True)
            else:
                print(f"[PROXY] {session.name} → {path} | HTTP {resp.status} | {round(duration_ms)}ms", flush=True)

            return resp.status, result

    except asyncio.TimeoutError:
        duration_ms = (time.monotonic() - start) * 1000
        print(f"[PROXY] Timeout bei {session.name} nach {round(duration_ms)}ms", flush=True)
        return 504, {"error": {"message": f"Timeout bei Session {session.name}", "type": "timeout_error"}}
    except aiohttp.ClientError as e:
        duration_ms = (time.monotonic() - start) * 1000
        print(f"[PROXY] Verbindungsfehler bei {session.name}: {e}", flush=True)
        return 502, {"error": {"message": f"Verbindungsfehler: {str(e)}", "type": "connection_error"}}
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        print(f"[PROXY] Unerwarteter Fehler bei {session.name}: {e}", flush=True)
        return 500, {"error": {"message": f"Interner Fehler: {str(e)}", "type": "internal_error"}}


async def chat_completions_proxy(request: web.Request) -> web.Response:
    """Proxy OpenAI-compatible chat requests to the best available downstream session."""
    client_id = _get_client_id(request)
    pool: SessionPool = request.app['pool']

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Ungültiges JSON", "type": "invalid_request_error"}},
            status=400
        )

    session = await pool.select_for_proxy(client_id)
    if not session:
        return web.json_response(
            {"error": {
                "message": "Keine verfügbare Session. Alle Sessions sind belegt oder fehlerhaft.",
                "type": "capacity_error",
                "pool_stats": pool.get_stats()["pool"],
            }},
            status=503
        )

    request_preview = ""
    messages = body.get("messages", [])
    if messages:
        last = messages[-1]
        content = last.get("content", "")
        request_preview = content[:60] if isinstance(content, str) else str(content)[:60]
    session.mark_busy(f"chat: {request_preview}...", client_id)

    try:
        status, result = await _proxy_request(pool, session, "POST", "/v1/chat/completions", body=body)
        return web.json_response(result, status=status)
    finally:
        session.mark_idle()


async def simple_chat_proxy(request: web.Request) -> web.Response:
    """Proxy simple chat requests to the best available downstream session."""
    client_id = _get_client_id(request)
    pool: SessionPool = request.app['pool']

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Ungültiges JSON"}, status=400)

    session = await pool.select_for_proxy(client_id)
    if not session:
        return web.json_response(
            {"error": "Keine verfügbare Session. Alle belegt oder fehlerhaft."},
            status=503
        )

    message = body.get("message", "")
    session.mark_busy(f"simple: {message[:60]}...", client_id)

    try:
        status, result = await _proxy_request(pool, session, "POST", "/api/chat", body=body)
        return web.json_response(result, status=status)
    finally:
        session.mark_idle()


async def models_proxy(request: web.Request) -> web.Response:
    """Aggregates and deduplicates models lists across active healthy sessions."""
    pool: SessionPool = request.app['pool']
    all_models = {}
    healthy_sessions = [
        s for s in pool.sessions.values()
        if s.status != SessionStatus.ERROR
    ]

    if not healthy_sessions:
        return web.json_response(
            {"error": {"message": "Keine gesunde Session verfügbar", "type": "capacity_error"}},
            status=503
        )

    tasks = []
    for s in healthy_sessions:
        tasks.append(_proxy_request(pool, s, "GET", "/v1/models"))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for s, result in zip(healthy_sessions, results):
        if isinstance(result, Exception):
            print(f"[MODELS] Fehler von {s.name}: {result}", flush=True)
            continue
        status, data = result
        if status == 200 and "data" in data:
            for model in data["data"]:
                mid = model.get("id", "")
                if mid and mid not in all_models:
                    model["_source_session"] = s.name
                    all_models[mid] = model

    return web.json_response({
        "object": "list",
        "data": list(all_models.values()),
        "_sessions_queried": len(healthy_sessions),
    })


async def list_sessions(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    try:
        sessions = [s.to_dict() for s in pool.sessions.values()]
        return web.json_response({
            "count": len(sessions),
            "sessions": sessions,
        })
    except Exception as e:
        print(f"[ERROR] list_sessions: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def register_session(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Ungültiges JSON"}, status=400)

    url = body.get("url", "").strip()
    name = body.get("name", "").strip()

    if not url:
        return web.json_response(
            {"error": "Feld 'url' ist erforderlich (z.B. http://127.0.0.1:8001)"},
            status=400
        )
    if not name:
        name = f"session-{len(pool.sessions) + 1}"

    # Verify URL is not already registered
    for s in pool.sessions.values():
        if s.url == url.rstrip('/'):
            return web.json_response(
                {"error": f"URL bereits registriert als '{s.name}' (id={s.id})"},
                status=409
            )

    session = pool.add_session(name, url)
    await pool.check_health(session)

    return web.json_response(session.to_dict(), status=201)


async def delete_session(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    try:
        session_id = request.match_info['id']
        if not pool.remove_session(session_id):
            return web.json_response(
                {"error": f"Session '{session_id}' nicht gefunden"},
                status=404
            )
        return web.json_response({"status": "removed", "id": session_id})
    except Exception as e:
        print(f"[ERROR] delete_session: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def session_status(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    try:
        session_id = request.match_info['id']
        session = pool.get_session(session_id)

        if not session:
            return web.json_response(
                {"error": f"Session '{session_id}' nicht gefunden"},
                status=404
            )

        result = session.to_dict()

        # Try to run live health check
        try:
            url = f"{session.url}/health"
            if pool._http:
                async with pool._http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        health_data = await resp.json()
                        result["live_health"] = health_data
                    else:
                        result["live_health"] = {"status": "error", "http_status": resp.status}
        except Exception as e:
            result["live_health"] = {"status": "unreachable", "error": str(e)}

        return web.json_response(result)
    except Exception as e:
        print(f"[ERROR] session_status: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def acquire_session(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    client_id = _get_client_id(request)

    if not client_id:
        try:
            body = await request.json()
            client_id = body.get("client_id")
        except Exception:
            pass

    session = await pool.acquire_session(client_id)
    if not session:
        return web.json_response(
            {"error": "Keine freie Session verfügbar",
             "pool_stats": pool.get_stats()["pool"]},
            status=503
        )

    return web.json_response({
        "session_id": session.id,
        "session_url": session.url,
        "session_name": session.name,
        "hint": f"Nutze POST /sessions/{session.id}/release zum Freigeben",
    })


async def release_session(request: web.Request) -> web.Response:
    pool: SessionPool = request.app['pool']
    session_id = request.match_info['id']
    session = pool.get_session(session_id)

    if not session:
        return web.json_response(
            {"error": f"Session '{session_id}' nicht gefunden"},
            status=404
        )

    if session.status != SessionStatus.BUSY:
        return web.json_response(
            {"warning": f"Session war nicht als 'busy' markiert (status={session.status})"},
            status=200
        )

    pool.release_session(session_id)
    return web.json_response({
        "status": "released",
        "session_id": session_id,
        "session_name": session.name,
    })

