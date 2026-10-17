import ssl
import gzip
import aiohttp
from aiohttp import web
from pathlib import Path
from typing import Optional

from src.tauri_shim import inject_shim
from src.port_finder import find_active_ports
from src.config import config
from src.app_keys import BACKEND_PORT_KEY, CODE_SERVER_PORT_KEY

# Constants
BACKEND_HOST = "127.0.0.1"

# Global session pool for the proxy
_session: Optional[aiohttp.ClientSession] = None
_home_dir = str(Path.home())


async def get_session(force_new: bool = False) -> aiohttp.ClientSession:
    """Retrieves or creates a reusable client session for proxying requests."""
    global _session
    if force_new and _session and not _session.closed:
        await _session.close()
        _session = None

    if _session is None or _session.closed:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=100, force_close=True)
        timeout = aiohttp.ClientTimeout(total=None, connect=2, sock_read=None)
        _session = aiohttp.ClientSession(
            connector=connector, timeout=timeout, auto_decompress=False
        )
    return _session


async def close_proxy_session() -> None:
    """Closes the client session if active."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def refresh_backend_port(app: web.Application) -> Optional[int]:
    """Rediscover the current Antigravity backend after desktop-app restarts."""
    loop = __import__('asyncio').get_running_loop()
    _, backend_port = await loop.run_in_executor(None, find_active_ports)
    app[BACKEND_PORT_KEY] = backend_port
    return backend_port


async def docs_handler(request: web.Request) -> web.Response:
    """Serves the static API documentation from docs/api.html."""
    base_dir = Path(__file__).resolve().parent.parent
    docs_file = base_dir / 'docs' / 'api.html'
    if not docs_file.exists():
        return web.Response(
            status=404,
            content_type='text/html',
            text=f'<h1>404 - Dokumentation nicht gefunden</h1>'
                 f'<p>Die Datei <code>docs/api.html</code> wurde nicht gefunden.</p>'
                 f'<p>Bitte sicherstellen, dass die Datei unter <code>{docs_file}</code> vorhanden ist.</p>',
        )
    try:
        html = docs_file.read_bytes()
        return web.Response(
            status=200,
            content_type='text/html',
            body=html,
        )
    except Exception as e:
        print(f"[DOCS] Fehler beim Lesen von {docs_file}: {e}", flush=True)
        return web.Response(status=500, text=f"Fehler beim Laden der Dokumentation: {e}")


async def stats_proxy_handler(request: web.Request) -> web.Response:
    """Proxies /api/stats to the API Bridge on Port 8001."""
    headers = {}
    auth = request.headers.get('Authorization')
    api_key = request.headers.get('X-Api-Key')
    if auth:
        headers['Authorization'] = auth
    elif api_key:
        headers['X-Api-Key'] = api_key
    else:
        api_keys = config.api_keys
        bridge_token = next(iter(api_keys), config.auth_token)
        if bridge_token:
            headers['Authorization'] = f'Bearer {bridge_token}'

    method = request.method
    body_data = None
    if method == 'POST':
        body_data = await request.read()
        headers['Content-Type'] = request.headers.get('Content-Type', 'application/json')

    try:
        session = await get_session()
        async with session.request(
            method=method,
            url=f"http://127.0.0.1:{config.api_bridge_port}/api/stats",
            headers=headers,
            data=body_data,
            ssl=False
        ) as resp:
            body = await resp.read()
            resp_headers = {
                'Content-Type': resp.headers.get('Content-Type', 'application/json'),
                'Access-Control-Allow-Origin': '*',
            }
            return web.Response(status=resp.status, headers=resp_headers, body=body)
    except Exception as e:
        print(f"[STATS] API-Bridge nicht erreichbar bei {method}: {e}", flush=True)
        return web.json_response(
            {"error": "API-Bridge nicht erreichbar", "details": str(e)},
            status=502,
        )


async def proxy_handler(request: web.Request) -> web.Response:
    """Main proxy handler routing requests to the Antigravity backend."""
    backend_port = request.app.get(BACKEND_PORT_KEY)
    code_server_port = request.app.get(CODE_SERVER_PORT_KEY, 8080)
    body = await request.read()

    headers = {}
    for k, v in request.headers.items():
        if k.lower() not in ('host', 'connection', 'transfer-encoding'):
            headers[k] = v
    is_page_load = (
        request.method == 'GET'
        and (request.path == '/' or request.path.startswith('/c/'))
    )

    last_error = None
    for attempt in range(2):
        if not backend_port:
            backend_port = await refresh_backend_port(request.app)
        if not backend_port:
            return web.Response(status=503, text="Antigravity desktop backend is not running.")

        target_url = f"https://{BACKEND_HOST}:{backend_port}{request.path_qs}"
        headers['Host'] = f"{BACKEND_HOST}:{backend_port}"
        session = await get_session(force_new=(attempt > 0))
        try:
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body if body else None,
                allow_redirects=False,
            ) as resp:

                content_type = resp.headers.get('Content-Type', '')
                content_encoding = resp.headers.get('Content-Encoding', '').lower()
                transfer_encoding = resp.headers.get('Transfer-Encoding', '').lower()

                resp_headers = {}
                skip = {'transfer-encoding', 'connection'}
                for k, v in resp.headers.items():
                    if k.lower() not in skip:
                        resp_headers[k] = v

                # Inject Tauri shim on page load HTML responses
                if is_page_load and 'text/html' in content_type:
                    raw_body = await resp.read()

                    if content_encoding == 'gzip' and raw_body[:2] == b'\x1f\x8b':
                        raw_body = gzip.decompress(raw_body)
                        resp_headers.pop('Content-Encoding', None)
                        resp_headers.pop('content-encoding', None)

                    modified = inject_shim(raw_body, code_server_port, _home_dir)
                    resp_headers['Content-Length'] = str(len(modified))
                    resp_headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
                    resp_headers['Pragma'] = 'no-cache'

                    print(f"[SHIM] Injected ({len(raw_body)} -> {len(modified)} bytes)", flush=True)
                    return web.Response(status=resp.status, headers=resp_headers, body=modified)

                elif 'chunked' in transfer_encoding or 'grpc' in content_type:
                    resp_headers.pop('Content-Length', None)
                    resp_headers.pop('content-length', None)

                    response = web.StreamResponse(status=resp.status, headers=resp_headers)
                    response.enable_chunked_encoding()
                    await response.prepare(request)

                    try:
                        async for chunk in resp.content.iter_any():
                            await response.write(chunk)
                    except (ConnectionResetError, ConnectionAbortedError):
                        pass

                    try:
                        await response.write_eof()
                    except Exception:
                        pass
                    return response

                else:
                    body_data = await resp.read()
                    return web.Response(status=resp.status, headers=resp_headers, body=body_data)

        except (aiohttp.ClientError, ConnectionResetError, OSError) as e:
            last_error = e
            if attempt == 0:
                print(f"[RETRY] {request.method} {request.path} failed: {e}", flush=True)
                backend_port = await refresh_backend_port(request.app)
                continue
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            return web.Response(status=500, text=f"Internal error: {e}")

    return web.Response(status=502, text=f"Backend unreachable after retry: {last_error}")
