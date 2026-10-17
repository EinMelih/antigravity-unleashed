"""Typed transport boundary for Anti-Gravity's Hub HTTP control plane.

This module deliberately contains no product or orchestration logic.  It gives
agent-facing adapters one small, testable HTTP seam while the Hub remains the
single owner of authorization, idempotency, leases, and business rules.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from ipaddress import ip_address
from types import TracebackType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from yarl import URL

from src.redaction import redact_sensitive_text


DEFAULT_HUB_URL = "http://127.0.0.1:8000"
_JSON_CONTENT_TYPES = ("application/json",)
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_OPERATION_ID = re.compile(r"^[0-9A-Fa-f]{32}$")
_PATH_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|secret|token|api[_-]?key)",
    re.IGNORECASE,
)
_MAX_ERROR_DEPTH = 6
_MAX_ERROR_ITEMS = 100
_MAX_ERROR_TEXT = 2_048
_DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class HubResult:
    """Successful JSON object plus transport metadata from the Hub."""

    payload: dict[str, Any]
    status: int
    operation_id: str | None = None
    deduplicated: bool = False


class HubControlError(RuntimeError):
    """Structured and redacted failure raised by :class:`HubControlGateway`."""

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str,
        retryable: bool,
        operation_id: str | None = None,
        deduplicated: bool = False,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        safe_payload = _sanitize_error_payload(dict(payload or {}))
        safe_message = _sanitize_text(message)
        super().__init__(safe_message)
        self.status = status
        self.code = str(code or "hub_control_error")
        self.retryable = bool(retryable)
        self.operation_id = _sanitize_operation_id(operation_id)
        self.deduplicated = bool(deduplicated)
        self.payload = safe_payload

    def public(self) -> dict[str, Any]:
        """Return the stable, JSON-safe error shape exposed by agent adapters."""
        return {
            "error": str(self),
            "status": self.status,
            "code": self.code,
            "retryable": self.retryable,
            "operation_id": self.operation_id,
            "deduplicated": self.deduplicated,
            "payload": dict(self.payload),
        }


@runtime_checkable
class HubControlClient(Protocol):
    """Minimal seam implemented by the real gateway and in-memory test fakes."""

    async def get(
        self,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> HubResult: ...

    async def mutate(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str,
    ) -> HubResult: ...


class HubControlGateway:
    """Async JSON client for the existing Hub HTTP control plane."""

    def __init__(
        self,
        base_url: str = DEFAULT_HUB_URL,
        bearer_token: str = "",
        *,
        allow_remote: bool = False,
        timeout_seconds: float = 30,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._bearer_token = _validate_header_value(
            bearer_token,
            field="bearer_token",
        )
        self._base_url = _validate_base_url(
            base_url,
            allow_remote=allow_remote,
            authenticated=bool(self._bearer_token),
        )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero.")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer.")
        self._timeout = aiohttp.ClientTimeout(
            total=float(timeout_seconds),
            connect=min(float(timeout_seconds), 5.0),
            sock_connect=min(float(timeout_seconds), 5.0),
            sock_read=float(timeout_seconds),
        )
        self._max_response_bytes = max_response_bytes
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> HubControlGateway:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close only the session owned by this gateway."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    def encode_path(*segments: object) -> str:
        """Encode caller-supplied path segments without losing slash boundaries."""
        if not segments:
            return "/"
        encoded: list[str] = []
        for segment in segments:
            value = str(segment)
            if not value or value in {".", ".."} or "\x00" in value:
                raise ValueError("Path segments must be non-empty and non-traversing.")
            encoded.append(quote(value, safe="-._~"))
        return "/" + "/".join(encoded)

    async def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> HubResult:
        """Perform one bounded JSON request against the configured Hub."""
        normalized_method = str(method or "").strip().upper()
        if normalized_method == "GET":
            if idempotency_key is not None:
                raise ValueError("GET requests must not carry an Idempotency-Key.")
            if json_body is not None:
                raise ValueError("GET requests must not carry a JSON body.")
        elif normalized_method in _MUTATION_METHODS:
            idempotency_key = _validate_idempotency_key(idempotency_key)
        else:
            raise ValueError(
                "method must be GET, POST, PUT, PATCH, or DELETE."
            )

        url = self._build_url(path, path_params=path_params, query=query)
        headers = {"Accept": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        session = self._get_session()
        try:
            async with session.request(
                normalized_method,
                url,
                headers=headers,
                json=dict(json_body) if json_body is not None else None,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                return await self._decode_response(response)
        except HubControlError:
            raise
        except asyncio.TimeoutError as error:
            raise HubControlError(
                "The Anti-Gravity Hub request timed out.",
                status=504,
                code="hub_timeout",
                retryable=True,
            ) from error
        except aiohttp.ClientError as error:
            raise HubControlError(
                "The Anti-Gravity Hub could not be reached.",
                status=503,
                code="hub_unreachable",
                retryable=True,
            ) from error

    async def get(
        self,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> HubResult:
        return await self.request(
            "GET",
            path,
            path_params=path_params,
            query=query,
        )

    async def mutate(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str,
    ) -> HubResult:
        normalized_method = str(method or "").strip().upper()
        if normalized_method not in _MUTATION_METHODS:
            raise ValueError("mutate() requires POST, PUT, PATCH, or DELETE.")
        return await self.request(
            normalized_method,
            path,
            path_params=path_params,
            query=query,
            json_body=json_body,
            idempotency_key=idempotency_key,
        )

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            if not self._owns_session:
                raise RuntimeError("The supplied HTTP session is closed.")
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def _build_url(
        self,
        path: str,
        *,
        path_params: Mapping[str, Any] | None,
        query: Mapping[str, Any] | None,
    ) -> URL:
        route = _validate_route_path(_expand_path(path, path_params))
        base_path = self._base_url.raw_path.rstrip("/")
        target = self._base_url.with_path(
            f"{base_path}{route}",
            encoded=True,
        )
        if query:
            target = target.with_query(_query_pairs(query))
        return target

    async def _decode_response(
        self,
        response: aiohttp.ClientResponse,
    ) -> HubResult:
        operation_id = _sanitize_operation_id(
            response.headers.get("X-Antigravity-Operation-Id")
        )
        deduplicated = (
            response.headers.get("X-Antigravity-Deduplicated", "").lower()
            == "true"
        )
        content_type = response.headers.get("Content-Type", "")
        mime_type = content_type.split(";", 1)[0].strip().lower()
        is_json = mime_type in _JSON_CONTENT_TYPES or mime_type.endswith("+json")
        body = await self._read_response_body(
            response,
            operation_id=operation_id,
            deduplicated=deduplicated,
        )

        if not is_json:
            payload = {"body": body.decode("utf-8", errors="replace")}
            raise HubControlError(
                "The Anti-Gravity Hub returned a non-JSON response.",
                status=response.status,
                code="non_json_response",
                retryable=_is_retryable_status(response.status),
                operation_id=operation_id,
                deduplicated=deduplicated,
                payload=payload,
            )

        try:
            decoded = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise HubControlError(
                "The Anti-Gravity Hub returned invalid JSON.",
                status=response.status,
                code="invalid_json_response",
                retryable=_is_retryable_status(response.status),
                operation_id=operation_id,
                deduplicated=deduplicated,
            ) from error

        if not isinstance(decoded, dict):
            raise HubControlError(
                "The Anti-Gravity Hub response must be a JSON object.",
                status=response.status,
                code="invalid_json_shape",
                retryable=_is_retryable_status(response.status),
                operation_id=operation_id,
                deduplicated=deduplicated,
                payload={"response": decoded},
            )

        if operation_id is None:
            operation_id = _operation_id_from_payload(decoded)
        deduplicated = deduplicated or bool(decoded.get("deduplicated"))

        if response.status < 200 or response.status >= 300:
            safe_payload = _sanitize_error_payload(decoded)
            raise HubControlError(
                _error_message(safe_payload, response.status),
                status=response.status,
                code=_error_code(safe_payload, response.status),
                retryable=_is_retryable_status(response.status),
                operation_id=operation_id,
                deduplicated=deduplicated,
                payload=safe_payload,
            )

        return HubResult(
            payload=decoded,
            status=response.status,
            operation_id=operation_id,
            deduplicated=deduplicated,
        )

    async def _read_response_body(
        self,
        response: aiohttp.ClientResponse,
        *,
        operation_id: str | None,
        deduplicated: bool,
    ) -> bytes:
        if (
            response.content_length is not None
            and response.content_length > self._max_response_bytes
        ):
            raise HubControlError(
                "The Anti-Gravity Hub response exceeded the configured size limit.",
                status=502,
                code="hub_response_too_large",
                retryable=False,
                operation_id=operation_id,
                deduplicated=deduplicated,
            )
        try:
            body = await response.content.readexactly(self._max_response_bytes + 1)
        except asyncio.IncompleteReadError as error:
            body = error.partial
        if len(body) > self._max_response_bytes:
            raise HubControlError(
                "The Anti-Gravity Hub response exceeded the configured size limit.",
                status=502,
                code="hub_response_too_large",
                retryable=False,
                operation_id=operation_id,
                deduplicated=deduplicated,
            )
        return body


def _validate_base_url(
    value: str,
    *,
    allow_remote: bool,
    authenticated: bool,
) -> URL:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        parsed.port  # Validate malformed and out-of-range ports eagerly.
    except ValueError as error:
        raise ValueError("base_url is invalid.") from error

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not hostname or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain a query or fragment.")
    if any(_is_traversal_segment(segment) for segment in parsed.path.split("/")):
        raise ValueError("base_url must not contain path traversal.")

    is_loopback = hostname == "localhost"
    if not is_loopback:
        try:
            is_loopback = ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False

    if not is_loopback and (not allow_remote or scheme != "https"):
        raise ValueError(
            "Remote Hub URLs require HTTPS and allow_remote=True."
        )
    if not is_loopback and not authenticated:
        raise ValueError("Remote Hub URLs require a non-empty bearer_token.")
    return URL(raw)


def _validate_route_path(path: str) -> str:
    raw = str(path or "").strip()
    parsed = urlsplit(raw)
    if (
        not raw
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or "\\" in raw
        or "\x00" in raw
        or _INVALID_PERCENT_ESCAPE.search(raw)
    ):
        raise ValueError("path must be a relative route without query data.")

    route = "/" + raw.lstrip("/")
    if any(_is_traversal_segment(segment) for segment in route.split("/")):
        raise ValueError("path traversal is not allowed.")
    return quote(route, safe="/%:@-._~")


def _expand_path(
    template: str,
    path_params: Mapping[str, Any] | None,
) -> str:
    raw = str(template or "")
    names = _PATH_PARAMETER.findall(raw)
    if not path_params:
        if names or "{" in raw or "}" in raw:
            raise ValueError("path contains unresolved parameters.")
        return raw

    supplied = {str(key): value for key, value in path_params.items()}
    required = set(names)
    if "{" in _PATH_PARAMETER.sub("", raw) or "}" in _PATH_PARAMETER.sub("", raw):
        raise ValueError("path contains an invalid parameter placeholder.")
    if set(supplied) != required:
        raise ValueError("path_params must match the path placeholders exactly.")

    def replace(match: re.Match[str]) -> str:
        value = str(supplied[match.group(1)])
        if not value or value in {".", ".."} or "\x00" in value:
            raise ValueError("Path parameters must be non-empty and non-traversing.")
        return quote(value, safe="-._~")

    return _PATH_PARAMETER.sub(replace, raw)


def _query_pairs(query: Mapping[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        key_text = str(key)
        values: Sequence[Any]
        if isinstance(value, (list, tuple)):
            values = value
        else:
            values = (value,)
        for item in values:
            if isinstance(item, bool):
                item_text = "true" if item else "false"
            elif item is None:
                item_text = ""
            else:
                item_text = str(item)
            pairs.append((key_text, item_text))
    return pairs


def _is_traversal_segment(segment: str) -> bool:
    decoded = str(segment)
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded in {".", ".."}


def _validate_header_value(value: str, *, field: str) -> str:
    selected = str(value or "").strip()
    if "\r" in selected or "\n" in selected:
        raise ValueError(f"{field} must not contain line breaks.")
    return selected


def _validate_idempotency_key(value: str | None) -> str:
    selected = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(selected):
        raise ValueError(
            "idempotency_key must contain 1-128 letters, digits, '.', '_', ':' or '-'."
        )
    return selected


def _sanitize_operation_id(value: object) -> str | None:
    """Accept only the UUID-hex format emitted by OperationCoordinator."""
    if not isinstance(value, str):
        return None
    selected = value.strip()
    if not _OPERATION_ID.fullmatch(selected):
        return None
    return selected.lower()


def _operation_id_from_payload(payload: Mapping[str, Any]) -> str | None:
    direct = payload.get("operation_id")
    selected = _sanitize_operation_id(direct)
    if selected:
        return selected
    operation = payload.get("operation")
    if isinstance(operation, Mapping):
        return _sanitize_operation_id(operation.get("operation_id"))
    return None


def _error_code(payload: Mapping[str, Any], status: int) -> str:
    code = payload.get("code")
    if isinstance(code, str) and code:
        return _sanitize_text(code)[:128]
    error = payload.get("error")
    if isinstance(error, Mapping):
        nested = error.get("code")
        if isinstance(nested, str) and nested:
            return _sanitize_text(nested)[:128]
    return f"hub_http_{status}"


def _error_message(payload: Mapping[str, Any], status: int) -> str:
    for key in ("error", "message", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Mapping):
            nested = value.get("message")
            if isinstance(nested, str) and nested:
                return nested
    return f"The Anti-Gravity Hub request failed with HTTP {status}."


def _is_retryable_status(status: int) -> bool:
    return status in {408, 425, 429, 500, 502, 503, 504}


def _sanitize_text(value: object) -> str:
    return redact_sensitive_text(value, maximum=_MAX_ERROR_TEXT)


def _sanitize_error_payload(
    value: Any,
    *,
    depth: int = 0,
) -> dict[str, Any]:
    sanitized = _sanitize_error_value(value, depth=depth)
    if isinstance(sanitized, dict):
        return sanitized
    return {"details": sanitized}


def _sanitize_error_value(value: Any, *, depth: int) -> Any:
    if depth >= _MAX_ERROR_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_ERROR_ITEMS:
                result["__items_omitted__"] = len(value) - _MAX_ERROR_ITEMS
                break
            key_text = _sanitize_text(key)
            result[key_text] = (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(key_text)
                else _sanitize_error_value(item, depth=depth + 1)
            )
        return result
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_error_value(item, depth=depth + 1)
            for item in value[:_MAX_ERROR_ITEMS]
        ]
        if len(value) > _MAX_ERROR_ITEMS:
            items.append(f"[{len(value) - _MAX_ERROR_ITEMS} ITEMS OMITTED]")
        return items
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(value)


__all__ = [
    "DEFAULT_HUB_URL",
    "HubControlClient",
    "HubControlError",
    "HubControlGateway",
    "HubResult",
]
