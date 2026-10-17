"""Security boundaries for loopback-only administrative HTTP services."""

from ipaddress import ip_address
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from aiohttp import web


def validate_loopback_host(host: str, *, service: str) -> str:
    """Refuse direct network exposure; remote access belongs behind Nginx."""
    selected = str(host or "").strip()
    if selected.lower().rstrip(".") == "localhost":
        return selected
    try:
        address = ip_address(selected)
    except ValueError as error:
        raise RuntimeError(
            f"{service} must bind to a loopback address, not {selected!r}."
        ) from error
    if not address.is_loopback:
        raise RuntimeError(
            f"{service} must bind to loopback; use authenticated Nginx for "
            "remote access."
        )
    return selected


def is_local_browser_origin(origin: str) -> bool:
    """Accept only browser origins hosted on the local loopback interface."""
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


async def local_cors_response(
    request: Any,
    handler: Callable[[Any], Awaitable[web.StreamResponse]],
    *,
    methods: str,
) -> web.StreamResponse:
    """Reject cross-site browser access while preserving local dashboard use."""
    origin = str(request.headers.get("Origin") or "").strip()
    if not is_local_browser_origin(origin):
        return web.json_response(
            {"error": "External browser origins are not allowed."},
            status=403,
        )

    if request.method == "OPTIONS":
        response: web.StreamResponse = web.Response(status=204)
    else:
        response = await handler(request)

    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = methods
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, X-Api-Key"
        )
        response.headers["Vary"] = "Origin"
    return response
