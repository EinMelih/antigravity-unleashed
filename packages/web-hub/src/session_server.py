import sys
import asyncio
import aiohttp
from aiohttp import web

from src.config import config
from src.session_pool import SessionPool
from src.session_handlers import (
    chat_completions_proxy,
    models_proxy,
    simple_chat_proxy,
    list_sessions,
    register_session,
    delete_session,
    session_status,
    acquire_session,
    release_session,
)
from src.session_admin_handlers import (
    root_handler,
    stats_handler,
    health_handler,
)


# ============================================================
# Middlewares
# ============================================================
@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.Response:
    """Bearer token authentication middleware."""
    if request.path in ('/health', '/') or request.method == 'OPTIONS':
        return await handler(request)

    auth_token = config.auth_token
    if not auth_token:
        return await handler(request)

    auth = request.headers.get('Authorization', '')
    api_key = request.headers.get('X-Api-Key', '')
    provided = auth[7:] if auth.startswith('Bearer ') else (api_key or auth)

    if provided != auth_token:
        return web.json_response(
            {"error": {"message": "Ungültiger Token.",
                       "type": "authentication_error"}},
            status=401
        )
    return await handler(request)


@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    """CORS middleware supporting standard browser queries."""
    if request.method == 'OPTIONS':
        return web.Response(status=200, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-Api-Key, X-Client-Id',
        })
    resp = await handler(request)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# ============================================================
# Startup / Shutdown Hooks
# ============================================================
async def on_startup(app: web.Application) -> None:
    """Initializes TCP Connector, HTTP Client Session and launches health check loop."""
    connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
    http_session = aiohttp.ClientSession(connector=connector)
    app['http_session'] = http_session

    # Initialize pool
    pool = SessionPool()
    app['pool'] = pool
    await pool.start(http_session)

    # Load sessions from config
    sessions_cfg = config.session_manager.get("sessions", [])
    if sessions_cfg:
        for s in sessions_cfg:
            pool.add_session(s["name"], s["url"])

    # Fallback to default API bridge if no sessions configured
    if not pool.sessions:
        pool.add_session("main", "http://127.0.0.1:8001")

    print("[STARTUP] Initialer Health-Check...", flush=True)
    await pool.check_all_health()
    for s in pool.sessions.values():
        status_icon = "[OK]" if s.last_health_ok else "[ERR]"
        print(f"  {status_icon} {s.name}: {s.url} -> {s.status}", flush=True)

    # Launch Health Check background task
    pool._health_task = asyncio.create_task(pool.health_check_loop())


async def on_shutdown(app: web.Application) -> None:
    """Gracefully terminates health loops and closes ClientSession."""
    print("[SHUTDOWN] Session Manager wird beendet...", flush=True)
    pool = app.get('pool')
    if pool:
        try:
            await asyncio.wait_for(pool.stop(), timeout=5.0)
        except asyncio.TimeoutError:
            print("[SHUTDOWN] Pool-Stopp Timeout — erzwinge Beendigung", flush=True)
        except Exception as e:
            print(f"[SHUTDOWN] Fehler beim Stoppen des Pools: {e}", flush=True)

    http_session = app.get('http_session')
    if http_session and not http_session.closed:
        await http_session.close()
    print("[SHUTDOWN] Session Manager sauber beendet.", flush=True)


# ============================================================
# Main Entry Point Function
# ============================================================
def main() -> None:
    config.load()
    app = web.Application(middlewares=[cors_middleware, auth_middleware])

    # Routing
    app.router.add_get('/', root_handler)
    app.router.add_post('/v1/chat/completions', chat_completions_proxy)
    app.router.add_get('/v1/models', models_proxy)
    app.router.add_post('/api/chat', simple_chat_proxy)
    app.router.add_get('/sessions', list_sessions)
    app.router.add_post('/sessions', register_session)
    app.router.add_delete('/sessions/{id}', delete_session)
    app.router.add_get('/sessions/{id}/status', session_status)
    app.router.add_post('/sessions/acquire', acquire_session)
    app.router.add_post('/sessions/{id}/release', release_session)
    app.router.add_get('/stats', stats_handler)
    app.router.add_get('/health', health_handler)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    port = config.session_manager.get("port", 8002)

    print(f"\n{'='*65}", flush=True)
    print("  Antigravity Multi-Session Manager v1.0 - Refactored", flush=True)
    print(f"  {'='*61}", flush=True)
    print("", flush=True)
    print("  Verwaltet mehrere API-Bridge-Instanzen fuer parallele Anfragen.", flush=True)
    print("", flush=True)
    print(f"  Server:     http://127.0.0.1:{port}", flush=True)
    auth_label = "Bearer <configured-token>" if config.auth_token else "disabled (loopback only)"
    print(f"  Auth:       {auth_label}", flush=True)
    print("", flush=True)
    print("  Endpoints:", flush=True)
    print("    POST /v1/chat/completions  (Load-balanced Proxy)", flush=True)
    print("    POST /api/chat             (Simple Chat Proxy)", flush=True)
    print("    GET  /sessions             (List Sessions)", flush=True)
    print("    POST /sessions             (Register Session)", flush=True)
    print("    POST /sessions/acquire     (Acquire Session)", flush=True)
    print("    GET  /health               (Status)", flush=True)
    print(f"{'='*65}\n", flush=True)

    web.run_app(app, host='127.0.0.1', port=port, print=None)
