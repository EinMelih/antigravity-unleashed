"""aiohttp middleware enforcing operation leases and idempotency."""

from __future__ import annotations

import asyncio
import hashlib
import json

from aiohttp import web

from src.operation_coordinator import (
    CONTROL_COORDINATOR_KEY,
    IdempotencyConflictError,
    OperationQueueTimeout,
    classify_control_operation,
)


class InvalidRequestCharsetError(Exception):
    """Raised only when a client names an unknown JSON charset."""


@web.middleware
async def control_plane_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Coordinate every mutating Hub API request before invoking its handler."""

    spec = classify_control_operation(request.method, request.path)
    if spec is None:
        return await handler(request)

    coordinator = request.app[CONTROL_COORDINATOR_KEY]
    idempotency_key = request.headers.get("Idempotency-Key")
    try:
        intent_fingerprint = (
            await _request_intent_fingerprint(request)
            if idempotency_key
            else None
        )
        result = await coordinator.run(
            spec,
            lambda: handler(request),
            idempotency_key=idempotency_key,
            intent_fingerprint=intent_fingerprint,
            metadata={
                "method": request.method,
                "remote": request.remote or "",
            },
        )
    except IdempotencyConflictError as error:
        return web.json_response(
            {
                "error": str(error),
                "code": "IDEMPOTENCY_KEY_CONFLICT",
            },
            status=409,
        )
    except InvalidRequestCharsetError:
        return web.json_response(
            {
                "error": "Unsupported request charset.",
                "code": "INVALID_REQUEST_CHARSET",
            },
            status=400,
        )
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except OperationQueueTimeout as error:
        return web.json_response(
            {
                "error": str(error),
                "code": "CONTROL_OPERATION_WAIT_TIMEOUT",
            },
            status=503,
        )
    except asyncio.CancelledError:
        raise

    operation = result.operation
    if result.deduplicated:
        original_state = operation.get("state")
        status = 200 if original_state == "succeeded" else 409
        return web.json_response(
            {
                "success": original_state == "succeeded",
                "deduplicated": True,
                "message": "This Idempotency-Key was already processed.",
                "result_ref": operation.get("result_ref", {}),
                "operation": operation,
            },
            status=status,
            headers={
                "X-Antigravity-Operation-Id": operation["operation_id"],
                "X-Antigravity-Deduplicated": "true",
            },
        )

    response = result.value
    if not response.prepared:
        response.headers["X-Antigravity-Operation-Id"] = operation["operation_id"]
        response.headers["X-Antigravity-Queue-Wait-Ms"] = str(
            operation.get("wait_ms") or 0
        )
    return response


async def _request_intent_fingerprint(request: web.Request) -> str:
    """Hash the HTTP intent without retaining request content or target details."""

    body = await request.read()
    content_type = (request.content_type or "").lower()
    canonical_body = body
    if content_type == "application/json" or content_type.endswith("+json"):
        try:
            try:
                decoded_body = body.decode(request.charset or "utf-8")
            except LookupError as error:
                raise InvalidRequestCharsetError from error
            payload = json.loads(decoded_body)
            canonical_body = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (UnicodeDecodeError, ValueError, TypeError):
            canonical_body = body

    route = request.path
    resource = getattr(request.match_info.route, "resource", None)
    if resource is not None:
        route = str(getattr(resource, "canonical", route))
    canonical_intent = json.dumps(
        {
            "method": request.method.upper(),
            "route": route,
            "target": {
                "path": request.path,
                "query": sorted(
                    (str(key), str(value))
                    for key, value in request.query.items()
                ),
            },
            "payload": {
                "content_type": content_type,
                "sha256": hashlib.sha256(canonical_body).hexdigest(),
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical_intent).hexdigest()
