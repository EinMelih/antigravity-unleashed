import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import time
import json
from ipaddress import ip_address
from datetime import datetime, timezone
from pathlib import Path
from aiohttp import web

from src.config import config
from src.telegram import send_telegram
from src.cdp_client import AntigravityCDP
from src.cdp_lifecycle import (
    CDPUnavailableError,
    CDPStartupSupervisor,
    bridge_is_ready,
    cdp_is_connected,
)
from src.api_helpers import (
    LOG_DIR,
    LOG_FILE,
    rate_limiter,
    session_stats,
    sanitize_error_response
)
from src.api_handlers import (
    api_audit_log_detail_handler,
    api_audit_logs_clear_handler,
    api_audit_logs_export_handler,
    api_audit_logs_list_handler,
    api_audit_logs_stats_handler,
    api_audit_reverts_list_handler,
    api_engine_mode_handler,
    chat_completions_handler,
    models_handler,
    oauth_status_handler,
    oauth_token_import_handler,
    openai_responses_handler,
    revert_chat_handler,
    send_parallel_handler,
    simple_chat_handler,
)
from src.api_monitor import APIRequestMonitor


CDP_STARTUP_RETRY_SECONDS = 2.0


import os


def validate_bind_security(host: str) -> None:
    """Refuse unauthenticated non-loopback API exposure unless running inside Docker/headless container."""
    if (
        os.environ.get("ANTIGRAVITY_DOCKER", "").strip().lower() in ("1", "true", "yes")
        or os.environ.get("ANTIGRAVITY_HEADLESS_UI", "").strip().lower() in ("1", "true", "yes")
    ):
        return
    normalized = str(host or "").strip().lower()
    try:
        loopback = normalized == "localhost" or ip_address(normalized).is_loopback
    except ValueError:
        loopback = False
    if not loopback and not (config.api_keys or config.auth_token):
        raise RuntimeError(
            "Non-loopback API binding requires a configured auth_token or api_keys."
        )


# ============================================================
# Middlewares
# ============================================================
@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.Response:
    if request.path in ('/health', '/') or request.method == 'OPTIONS':
        return await handler(request)

    auth = request.headers.get('Authorization', '')
    api_key_header = request.headers.get('X-Api-Key', '')
    provided = auth[7:] if auth.startswith('Bearer ') else (api_key_header or auth)

    key_name = None
    key_rpm = None

    api_keys = config.api_keys
    auth_token = config.auth_token
    rate_limit = config.rate_limit

    if api_keys and provided in api_keys:
        key_info = api_keys[provided]
        key_name = key_info.get("name", "unknown") if isinstance(key_info, dict) else str(key_info)
        key_rpm = key_info.get("rpm") if isinstance(key_info, dict) else None
    elif auth_token and provided == auth_token:
        key_name = "default"
    elif api_keys or auth_token:
        return web.json_response(
            sanitize_error_response("Ungültiger API-Key", "authentication_error"),
            status=401
        )

    request['api_key_name'] = key_name

    # Rate Limiting
    if rate_limit.get("enabled", False) and request.path != '/api/monitor':
        client_ip = request.remote or "unknown"
        whitelist = rate_limit.get("whitelist_ips", [])
        if client_ip not in whitelist:
            effective_rpm = key_rpm or rate_limit.get("max_requests_per_minute", 10)
            rate_limiter.update_limit(effective_rpm)
            if not rate_limiter.is_allowed(client_ip):
                print(f"[RATE] Limit erreicht für {client_ip} (key={key_name})", flush=True)
                return web.json_response(
                    sanitize_error_response(f"Rate Limit: max {effective_rpm}/min", "rate_limit_error"),
                    status=429,
                    headers={'Retry-After': '60',
                             'X-RateLimit-Limit': str(effective_rpm),
                             'X-RateLimit-Remaining': '0'}
                )
            request['rate_limit_remaining'] = rate_limiter.remaining(client_ip)
            request['rate_limit_limit'] = effective_rpm

    monitor = request.app.get('api_request_monitor')
    tracked = monitor is not None and request.method == 'POST' and request.path in {'/v1/chat/completions', '/api/chat', '/api/send_parallel'}
    if tracked:
        try:
            body = await request.json()
            body = body if isinstance(body, dict) else {}
        except Exception:
            body = {}
        monitor.begin(request, body)
    resp = await handler(request)
    if tracked:
        monitor.finish(request, resp)

    if rate_limit.get("enabled", False) and request.path != '/api/monitor' and request.remote not in rate_limit.get("whitelist_ips", []):
        resp.headers['X-RateLimit-Limit'] = str(request.get('rate_limit_limit', 10))
        resp.headers['X-RateLimit-Remaining'] = str(request.get('rate_limit_remaining', 0))

    return resp


@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    security_headers = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'no-referrer',
    }
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-Api-Key, X-Source-Framework, X-Client-Framework, X-Client-Ip, X-Conversation-Id',
        }
        headers.update(security_headers)
        return web.Response(status=200, headers=headers)

    resp = await handler(request)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    for k, v in security_headers.items():
        resp.headers[k] = v
    if request.path.startswith('/v1/') or request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp


# ============================================================
# Admin Handlers (Health, Logs, Stats, Root)
# ============================================================
async def root_handler(request: web.Request) -> web.Response:
    return web.json_response({
        "service": "Anti-Gravity API Bridge v2.1 (Frontend-Mode)",
        "info": "Alles laeuft ueber das Antigravity-Frontend. Keine externen API-Keys noetig.",
        "quickstart": {
            "1_check_cdp": "GET /health/cdp",
            "2_simple_chat": 'POST /api/chat  {"message": "Hallo!"}',
            "3_openai_chat": 'POST /v1/chat/completions  {"model":"antigravity","messages":[{"role":"user","content":"Hi"}]}',
            "4_streaming": 'POST /v1/chat/completions  {"model":"antigravity","stream":true,"messages":[{"role":"user","content":"Hi"}]}',
        },
        "auth": "Authorization: Bearer <configured-token>"
    })


async def health_handler(request: web.Request) -> web.Response:
    from src.config import get_runtime_mode

    runtime_mode = get_runtime_mode()
    cdp = request.app['cdp']
    connected = cdp_is_connected(cdp)
    ready = bridge_is_ready(cdp)
    profile = getattr(cdp, 'profile', None)
    profile_info = getattr(cdp, 'profile_info', None) or {}
    profile_verified = bool(profile_info)
    from src.api_profile import PROFILE_CONTRACT_VERSION
    home_isolated = profile == 'api' and profile_verified and profile_info.get('profile_contract_version') == PROFILE_CONTRACT_VERSION and bool(profile_info.get('home_dir'))
    if profile == 'api':
        ready = ready and home_isolated

    return web.json_response({
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "runtime_mode": runtime_mode,
        "service": "Anti-Gravity API Bridge (Frontend-Mode)",
        "version": "2.1.0",
        "cdp": {
            "status": "connected" if connected else "disconnected",
            "bridge": "injected" if ready else "missing",
            "profile": profile,
            "profile_verified": profile_verified,
            "home_isolated": home_isolated,
            "profile_contract_version": profile_info.get('profile_contract_version'),
        },
        "authentication": {
            "required": bool(config.api_keys or config.auth_token),
            "schemes": ["Bearer", "X-Api-Key"],
        },
        "diagnostics": "Authenticate and call GET /health/cdp.",
    })


async def api_monitor_handler(request: web.Request) -> web.Response:
    health = await health_handler(request)
    payload = json.loads(health.text)
    supervisor = request.app.get('cdp_startup_supervisor')
    info = getattr(request.app['cdp'], 'profile_info', None) or {}
    paths = {key: info.get(key) for key in ('home_dir', 'config_dir', 'app_data_dir', 'user_data_dir', 'process_cwd')}
    return web.json_response({'health': payload, 'profile': 'api', 'isolated': payload['cdp']['home_isolated'], 'profile_paths': paths, 'last_error': getattr(supervisor, 'last_error', None), **request.app['api_request_monitor'].snapshot()})


async def cdp_diagnose_handler(request: web.Request) -> web.Response:
    cdp = request.app['cdp']
    supervisor = request.app.get('cdp_startup_supervisor')
    if supervisor is None:
        if not cdp_is_connected(cdp):
            try:
                await cdp.connect()
            except Exception as e:
                return web.json_response({
                    "status": "error",
                    "error": str(e),
                    "hint": "Ist die Anti-Gravity Desktop App gestartet?"
                }, status=503)
        try:
            diag = await cdp.diagnose()
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)
        return web.json_response({"status": "ok", "diagnostics": diag})

    try:
        diag = await supervisor.diagnose()
    except CDPUnavailableError as e:
        return web.json_response({
            "status": "error",
            "error": str(e),
            "hint": "Ist die Anti-Gravity Desktop App gestartet?"
        }, status=503)
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)
    return web.json_response({"status": "ok", "diagnostics": diag})


async def chat_logs_handler(request: web.Request) -> web.Response:
    import json
    limit = min(int(request.query.get("limit", "50")), 500)
    logs = []
    if LOG_FILE.exists():
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    logs = logs[-limit:]
    logs.reverse()
    return web.json_response({"count": len(logs), "log_file": str(LOG_FILE), "logs": logs})


async def clear_logs_handler(request: web.Request) -> web.Response:
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    return web.json_response({"status": "cleared"})


async def stats_handler(request: web.Request) -> web.Response:
    """Returns accumulated token usage or updates it manually."""
    if request.method == 'POST':
        try:
            body = await request.json()
            prompt_tokens = int(body.get("prompt_tokens", 0))
            completion_tokens = int(body.get("completion_tokens", 0))
            model = body.get("model", "gemini-3.5-flash-high")
            if not model or model == "antigravity":
                model = "gemini-3.5-flash-high"
            from src.api_helpers import track_usage
            track_usage(prompt_tokens, completion_tokens, model=model)
            print(f"[STATS] Manuell erfasst: +{prompt_tokens + completion_tokens} tokens (model={model})", flush=True)
        except Exception as e:
            print(f"[STATS] Fehler bei POST: {e}", flush=True)
            return web.json_response({"error": str(e)}, status=400)

    uptime_seconds = round(time.monotonic() - request.app['start_time_mono'])
    return web.json_response({
        "session": session_stats,
        "uptime_seconds": uptime_seconds,
    })


# ============================================================
# Startup & Shutdown hooks
# ============================================================
async def on_startup(app: web.Application) -> None:
    from src.config import get_runtime_mode

    app['start_time_mono'] = time.monotonic()
    app['api_request_monitor'] = APIRequestMonitor()
    cdp = AntigravityCDP(profile="api")
    app['cdp'] = cdp

    async def notify_ready() -> None:
        if getattr(cdp, 'profile', None) == 'api':
            # API readiness is displayed locally in the desktop monitor.
            return
        await send_telegram("Server gestartet und erfolgreich mit Antigravity verbunden.")

    supervisor = CDPStartupSupervisor(
        cdp,
        retry_seconds=CDP_STARTUP_RETRY_SECONDS,
        on_ready=notify_ready,
    )
    app['cdp_startup_supervisor'] = supervisor
    if get_runtime_mode() != "headless_linux":
        supervisor.start()


async def on_shutdown(app: web.Application) -> None:
    supervisor = app.get('cdp_startup_supervisor')
    if supervisor is not None:
        await supervisor.stop()
    elif 'cdp' in app:
        await app['cdp'].disconnect()


# ============================================================
# Main Entry Point Function
# ============================================================
def main() -> None:
    config.load()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    app = web.Application(
        middlewares=[cors_middleware, auth_middleware],
        client_max_size=50 * 1024 * 1024
    )

    # Routes
    app.router.add_get('/', root_handler)
    app.router.add_post('/v1/chat/completions', chat_completions_handler)
    app.router.add_post('/v1/responses', openai_responses_handler)
    app.router.add_post('/v1/chat/revert', revert_chat_handler)
    app.router.add_get('/v1/models', models_handler)
    for src_prefix in ('openclaw', 'hermes', 'openwebui', 'dokploy', 'ich', 'user', 'me', 'local'):
        app.router.add_post(f'/{src_prefix}/v1/chat/completions', chat_completions_handler)
        app.router.add_post(f'/{src_prefix}/v1/responses', openai_responses_handler)
        app.router.add_post(f'/{src_prefix}/v1/chat/revert', revert_chat_handler)
        app.router.add_get(f'/{src_prefix}/v1/models', models_handler)
    app.router.add_post('/api/chat', simple_chat_handler)
    app.router.add_post('/api/send_parallel', send_parallel_handler)
    app.router.add_get('/api/chat/logs', chat_logs_handler)
    app.router.add_delete('/api/chat/logs', clear_logs_handler)
    app.router.add_get('/api/logs/stats', api_audit_logs_stats_handler)
    app.router.add_get('/api/logs/reverts', api_audit_reverts_list_handler)
    app.router.add_get('/api/logs/export', api_audit_logs_export_handler)
    app.router.add_get('/api/logs', api_audit_logs_list_handler)
    app.router.add_delete('/api/logs', api_audit_logs_clear_handler)
    app.router.add_get('/api/logs/{req_id}', api_audit_log_detail_handler)
    app.router.add_get('/api/engine-mode', api_engine_mode_handler)
    app.router.add_post('/api/engine-mode', api_engine_mode_handler)
    app.router.add_get('/v1/auth/status', oauth_status_handler)
    app.router.add_post('/v1/auth/token', oauth_token_import_handler)
    app.router.add_get('/api/auth/status', oauth_status_handler)
    app.router.add_post('/api/auth/token', oauth_token_import_handler)
    app.router.add_get('/api/stats', stats_handler)
    app.router.add_post('/api/stats', stats_handler)
    app.router.add_get('/health', health_handler)
    app.router.add_get('/health/cdp', cdp_diagnose_handler)
    app.router.add_get('/api/monitor', api_monitor_handler)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    host = config.api_bridge_host
    port = config.api_bridge_port
    validate_bind_security(host)
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host

    print(f"\n{'='*60}", flush=True)
    print("  Anti-Gravity API Bridge v2.1 (Frontend-Mode)", flush=True)
    print(f"  {'='*56}", flush=True)
    print("", flush=True)
    print("  Lokale Zustellung ueber die Anti-Gravity-Desktop-Integration.", flush=True)
    print("  Anbieter-, Konto- und Automatisierungsbedingungen beachten.", flush=True)
    print("", flush=True)
    print(f"  Server:     http://{display_host}:{port}", flush=True)
    print("  Auth:       Bearer <configured-token>", flush=True)
    print(f"  Logs:       {LOG_DIR}", flush=True)
    print("  Streaming:  Ja (stream: true)", flush=True)
    print("  Timeout:    120s Standard, 600s Max", flush=True)
    print("", flush=True)
    print("  Endpoints:", flush=True)
    print("    POST /v1/chat/completions  (OpenAI-kompatibel, +Streaming)", flush=True)
    print("    POST /api/chat             (Einfaches JSON)", flush=True)
    print("    GET  /v1/models            (Modelle)", flush=True)
    print("    GET  /api/chat/logs        (Logs)", flush=True)
    print("    GET  /health               (Status)", flush=True)
    print("    GET  /health/cdp           (CDP-Diagnose)", flush=True)
    print(f"{'='*60}\n", flush=True)

    web.run_app(app, host=host, port=port, print=None)
