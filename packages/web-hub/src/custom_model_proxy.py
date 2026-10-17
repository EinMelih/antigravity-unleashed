"""Secure OpenAI-compatible proxy support for Hub-managed custom models."""

from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from typing import Any, Dict, Iterable, List, Optional


class CustomModelError(RuntimeError):
    """A safe, user-facing custom-provider error."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _run_dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise CustomModelError("API-key protection currently requires Windows DPAPI.")

    source_buffer = ctypes.create_string_buffer(data)
    source_blob = _DataBlob(
        len(data),
        ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    result_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    description = "Anti-Gravity Hub custom model" if protect else None
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN

    if protect:
        success = function(
            ctypes.byref(source_blob),
            description,
            None,
            None,
            None,
            flags,
            ctypes.byref(result_blob),
        )
    else:
        success = function(
            ctypes.byref(source_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(result_blob),
        )
    if not success:
        raise CustomModelError(f"Windows DPAPI failed with error {ctypes.get_last_error()}.")

    try:
        return ctypes.string_at(result_blob.pbData, result_blob.cbData)
    finally:
        kernel32.LocalFree(result_blob.pbData)


def protect_secret(secret: str) -> bytes:
    return _run_dpapi(secret.encode("utf-8"), protect=True) if secret else b""


def unprotect_secret(protected: Optional[bytes]) -> str:
    if not protected:
        return ""
    return _run_dpapi(bytes(protected), protect=False).decode("utf-8")


def _is_loopback_hostname(hostname: str) -> bool:
    normalized = str(hostname or "").rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def normalize_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if len(raw) > 2048:
        raise CustomModelError("Base URL may contain at most 2048 characters.")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CustomModelError("Base URL must be an absolute http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise CustomModelError("Credentials must not be embedded in the Base URL.")
    if parsed.scheme == "http" and not _is_loopback_hostname(parsed.hostname or ""):
        raise CustomModelError("External custom-model providers must use HTTPS; HTTP is allowed only for loopback development servers.")
    return raw


def validate_extra_headers(value: Any) -> Dict[str, str]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise CustomModelError(f"Extra headers are not valid JSON: {error.msg}.") from error
    if not isinstance(value, dict):
        raise CustomModelError("Extra headers must be a JSON object.")
    if len(value) > 32:
        raise CustomModelError("At most 32 extra headers are allowed.")

    blocked = {"host", "content-length", "connection", "transfer-encoding"}
    headers: Dict[str, str] = {}
    for key, header_value in value.items():
        name = str(key).strip()
        if not name or len(name) > 128 or name.lower() in blocked or "\r" in name or "\n" in name:
            raise CustomModelError(f"Header {name!r} is not allowed.")
        text = str(header_value)
        if header_value is None:
            raise CustomModelError(f"Header {name!r} requires a value.")
        if len(text) > 8192:
            raise CustomModelError(f"Header {name!r} exceeds 8192 characters.")
        if "\r" in text or "\n" in text:
            raise CustomModelError(f"Header {name!r} contains invalid line breaks.")
        headers[name] = text
    return headers


_PROTECTED_HEADER_PREFIX = "dpapi:v1:"


def protect_extra_headers(value: Any) -> Dict[str, str]:
    """Encrypt every extra-header value before it is persisted."""
    protected: Dict[str, str] = {}
    for name, text in validate_extra_headers(value).items():
        encrypted = protect_secret(text)
        protected[name] = _PROTECTED_HEADER_PREFIX + base64.b64encode(encrypted).decode("ascii")
    return protected


def unprotect_extra_headers(value: Any) -> Dict[str, str]:
    """Decrypt persisted headers while accepting legacy plaintext rows."""
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise CustomModelError("Stored extra headers are invalid.") from error
    if not isinstance(value, dict):
        raise CustomModelError("Stored extra headers are invalid.")

    plain: Dict[str, str] = {}
    for name, stored_value in value.items():
        text = str(stored_value)
        if text.startswith(_PROTECTED_HEADER_PREFIX):
            encoded = text[len(_PROTECTED_HEADER_PREFIX):]
            try:
                protected = base64.b64decode(encoded, validate=True)
                text = unprotect_secret(protected)
            except (ValueError, UnicodeError) as error:
                raise CustomModelError(f"Protected header {name!r} could not be decoded.") from error
        plain[str(name)] = text
    return validate_extra_headers(plain)


def redact_extra_headers(value: Any) -> Dict[str, None]:
    """Expose header names for editing without disclosing their values."""
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    return {str(name): None for name in value}


def validate_provider_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    model_id = str(payload.get("model_id") or "").strip()
    if not name or len(name) > 80:
        raise CustomModelError("Display name is required and may contain at most 80 characters.")
    if not model_id or len(model_id) > 200:
        raise CustomModelError("Model ID is required and may contain at most 200 characters.")

    api_key_header = str(payload.get("api_key_header") or "Authorization").strip()
    api_key_prefix = str(payload.get("api_key_prefix") if payload.get("api_key_prefix") is not None else "Bearer").strip()
    if not api_key_header or any(char in api_key_header for char in "\r\n:"):
        raise CustomModelError("API-key header is invalid.")

    try:
        temperature = float(payload.get("temperature", 0.7))
    except (TypeError, ValueError) as error:
        raise CustomModelError("Temperature must be numeric.") from error
    if not 0 <= temperature <= 2:
        raise CustomModelError("Temperature must be between 0 and 2.")

    try:
        timeout_seconds = int(payload.get("timeout_seconds", 60))
    except (TypeError, ValueError) as error:
        raise CustomModelError("Timeout must be a whole number.") from error
    if not 5 <= timeout_seconds <= 300:
        raise CustomModelError("Timeout must be between 5 and 300 seconds.")

    base_url = normalize_base_url(payload.get("base_url"))
    verify_tls = payload.get("verify_tls", True)
    if not isinstance(verify_tls, bool):
        raise CustomModelError("TLS verification must be a boolean.")
    parsed_base_url = urllib.parse.urlparse(base_url)
    if not verify_tls and not _is_loopback_hostname(parsed_base_url.hostname or ""):
        raise CustomModelError("TLS verification may be disabled only for loopback development servers.")

    return {
        "name": name,
        "base_url": base_url,
        "model_id": model_id,
        "api_key_header": api_key_header,
        "api_key_prefix": api_key_prefix,
        "extra_headers": validate_extra_headers(payload.get("extra_headers")),
        "system_prompt": str(payload.get("system_prompt") or "").strip(),
        "temperature": temperature,
        "verify_tls": verify_tls,
        "timeout_seconds": timeout_seconds,
    }


def public_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize SQLite values and guarantee that secret material cannot escape."""
    return {
        "id": int(provider["id"]),
        "name": provider["name"],
        "base_url": provider["base_url"],
        "model_id": provider["model_id"],
        "api_key_header": provider.get("api_key_header") or "Authorization",
        "api_key_prefix": provider.get("api_key_prefix") or "Bearer",
        "extra_headers": redact_extra_headers(provider.get("extra_headers")),
        "system_prompt": provider.get("system_prompt") or "",
        "temperature": float(provider.get("temperature", 0.7)),
        "verify_tls": bool(provider.get("verify_tls", 1)),
        "timeout_seconds": int(provider.get("timeout_seconds", 60)),
        "has_api_key": bool(provider.get("has_api_key") or provider.get("api_key_protected")),
    }


def _endpoint(base_url: str, suffix: str) -> str:
    base = normalize_base_url(base_url)
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/{suffix.lstrip('/')}"


def _request_headers(provider: Dict[str, Any]) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Antigravity-Hub/1.0",
    }
    headers.update(unprotect_extra_headers(provider.get("extra_headers")))
    api_key = unprotect_secret(provider.get("api_key_protected"))
    if api_key:
        prefix = str(provider.get("api_key_prefix") or "").strip()
        value = f"{prefix} {api_key}".strip()
        headers[str(provider.get("api_key_header") or "Authorization")] = value
    return headers


def _ssl_context(provider: Dict[str, Any]) -> Optional[ssl.SSLContext]:
    if not str(provider["base_url"]).startswith("https://"):
        return None
    if bool(provider.get("verify_tls", 1)):
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _open_json(
    provider: Dict[str, Any],
    request: urllib.request.Request,
) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(
            request,
            timeout=int(provider.get("timeout_seconds", 60)),
            context=_ssl_context(provider),
        ) as response:
            raw = response.read(5 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", errors="replace")
        raise CustomModelError(f"Provider returned HTTP {error.code}: {detail[:500]}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise CustomModelError(f"Provider connection failed: {error}") from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CustomModelError("Provider did not return valid JSON.") from error


def test_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    request = urllib.request.Request(
        _endpoint(provider["base_url"], "models"),
        headers=_request_headers(provider),
        method="GET",
    )
    data = _open_json(provider, request)
    models = data.get("data") if isinstance(data, dict) else None
    return {"success": True, "model_count": len(models) if isinstance(models, list) else None}


def _response_content(data: Dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise CustomModelError("Provider response has no choices[0].message.content.") from error
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "".join(parts)
    raise CustomModelError("Provider returned an unsupported message content format.")


def send_chat_completion(
    provider: Dict[str, Any],
    messages: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    request_messages: List[Dict[str, Any]] = []
    system_prompt = str(provider.get("system_prompt") or "").strip()
    if system_prompt:
        request_messages.append({"role": "system", "content": system_prompt})
    request_messages.extend(list(messages)[-40:])
    body = json.dumps(
        {
            "model": provider["model_id"],
            "messages": request_messages,
            "temperature": float(provider.get("temperature", 0.7)),
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        _endpoint(provider["base_url"], "chat/completions"),
        data=body,
        headers=_request_headers(provider),
        method="POST",
    )
    data = _open_json(provider, request)
    return {
        "content": _response_content(data),
        "usage": data.get("usage") if isinstance(data, dict) else None,
        "provider_response_id": data.get("id") if isinstance(data, dict) else None,
    }
