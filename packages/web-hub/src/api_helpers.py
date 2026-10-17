import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from aiohttp import web
from src.config import config

# Paths
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
LOG_DIR = Path(os.environ.get('ANTIGRAVITY_API_REQUEST_LOG_DIR') or BASE_DIR / "logs")
LOG_FILE = LOG_DIR / "api_requests.jsonl"
API_LOG_MAX_BYTES = 5 * 1024 * 1024
API_LOG_BACKUP_COUNT = 3
API_LOG_MAX_RECORD_BYTES = 64 * 1024
API_LOG_MAX_STRING_CHARS = 2_000
API_LOG_MAX_COLLECTION_ITEMS = 50
API_LOG_MAX_DEPTH = 6
_API_LOG_LOCK = threading.Lock()
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_SENSITIVE_LOG_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|passwd|secret|token|api[_-]?key)",
    re.IGNORECASE,
)

# In-Memory Session Stats (for Live Widget)
session_stats = {
    "total_requests": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_tokens": 0,
    "requests_by_model": {},
    "start_time": None,
}


def _api_content_logging_enabled() -> bool:
    value = str(os.environ.get("ANTIGRAVITY_LOG_API_CONTENT") or "")
    return value.strip().lower() in _TRUTHY_ENV_VALUES


def _serialized_size(value: Any) -> int:
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError, OverflowError):
        serialized = str(value)
    return len(serialized.encode("utf-8", errors="replace"))


def _log_metadata(value: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "type": type(value).__name__,
        "size_bytes": _serialized_size(value),
    }
    if isinstance(value, dict):
        keys = [
            _truncate_log_string(str(key))
            for key in list(value)[:API_LOG_MAX_COLLECTION_ITEMS]
        ]
        metadata["field_count"] = len(value)
        metadata["fields"] = keys
        if len(value) > len(keys):
            metadata["fields_omitted"] = len(value) - len(keys)
    elif isinstance(value, (list, tuple, set)):
        metadata["item_count"] = len(value)
    elif isinstance(value, str):
        metadata["character_count"] = len(value)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        metadata["byte_count"] = len(value)
    return metadata


def _minimal_log_metadata(value: Any) -> Dict[str, Any]:
    return {
        "type": type(value).__name__,
        "size_bytes": _serialized_size(value),
    }


def _truncate_log_string(value: str) -> str:
    if len(value) <= API_LOG_MAX_STRING_CHARS:
        return value
    omitted = len(value) - API_LOG_MAX_STRING_CHARS
    return f"{value[:API_LOG_MAX_STRING_CHARS]}...[{omitted} chars omitted]"


def _sanitize_log_content(
    value: Any,
    *,
    depth: int = 0,
    seen: Optional[set] = None,
) -> Any:
    if depth >= API_LOG_MAX_DEPTH:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_log_string(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[{len(value)} BYTES]"

    seen = seen if seen is not None else set()
    object_id = id(value)
    if object_id in seen:
        return "[CIRCULAR]"
    seen.add(object_id)
    try:
        if isinstance(value, dict):
            sanitized: Dict[str, Any] = {}
            items = list(value.items())
            for key, child in items[:API_LOG_MAX_COLLECTION_ITEMS]:
                key_text = _truncate_log_string(str(key))
                sanitized[key_text] = (
                    "[REDACTED]"
                    if _SENSITIVE_LOG_KEY_RE.search(key_text)
                    else _sanitize_log_content(
                        child,
                        depth=depth + 1,
                        seen=seen,
                    )
                )
            if len(items) > API_LOG_MAX_COLLECTION_ITEMS:
                sanitized["__items_omitted__"] = (
                    len(items) - API_LOG_MAX_COLLECTION_ITEMS
                )
            return sanitized
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            sanitized_items = [
                _sanitize_log_content(item, depth=depth + 1, seen=seen)
                for item in items[:API_LOG_MAX_COLLECTION_ITEMS]
            ]
            if len(items) > API_LOG_MAX_COLLECTION_ITEMS:
                sanitized_items.append(
                    f"[{len(items) - API_LOG_MAX_COLLECTION_ITEMS} ITEMS OMITTED]"
                )
            return sanitized_items
        return _truncate_log_string(str(value))
    finally:
        seen.discard(object_id)


def _rotated_log_path(index: int) -> Path:
    return LOG_FILE.with_name(f"{LOG_FILE.name}.{index}")


def _rotate_api_log(incoming_bytes: int) -> None:
    try:
        current_bytes = LOG_FILE.stat().st_size
    except FileNotFoundError:
        return
    if current_bytes + incoming_bytes <= API_LOG_MAX_BYTES:
        return

    oldest = _rotated_log_path(API_LOG_BACKUP_COUNT)
    oldest.unlink(missing_ok=True)
    for index in range(API_LOG_BACKUP_COUNT - 1, 0, -1):
        source = _rotated_log_path(index)
        if source.exists():
            source.replace(_rotated_log_path(index + 1))
    LOG_FILE.replace(_rotated_log_path(1))


def log_interaction(
    request_data: Dict[str, Any],
    response_data: Dict[str, Any],
    duration_ms: float,
    status_code: int = 200,
    req_id: Optional[str] = None,
) -> None:
    """Log bounded API metadata, with sanitized content only by explicit opt-in."""
    include_content = _api_content_logging_enabled()
    entry = {
        "id": str(uuid.uuid4()),
        "req_id": req_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status_code,
        "duration_ms": round(duration_ms),
        "content_included": include_content,
        "request": (
            _sanitize_log_content(request_data)
            if include_content
            else _log_metadata(request_data)
        ),
        "response": (
            _sanitize_log_content(response_data)
            if include_content
            else _log_metadata(response_data)
        ),
    }
    try:
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        if len(line.encode("utf-8")) > API_LOG_MAX_RECORD_BYTES:
            entry["content_included"] = False
            entry["content_truncated"] = True
            entry["request"] = _log_metadata(request_data)
            entry["response"] = _log_metadata(response_data)
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        if len(line.encode("utf-8")) > API_LOG_MAX_RECORD_BYTES:
            entry["request"] = _minimal_log_metadata(request_data)
            entry["response"] = _minimal_log_metadata(response_data)
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"

        encoded_bytes = len(line.encode("utf-8"))
        with _API_LOG_LOCK:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _rotate_api_log(encoded_bytes)
            with LOG_FILE.open(
                "a",
                encoding="utf-8",
                newline="\n",
            ) as log_handle:
                log_handle.write(line)
    except Exception as e:
        print(f"[LOG] Error writing log: {e}", flush=True)


class RateLimiter:
    """In-Memory Rate Limiter per client IP address."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, list] = {}  # ip -> [timestamps]

    def is_allowed(self, ip: str) -> bool:
        now = time.monotonic()
        if ip not in self.requests:
            self.requests[ip] = []
        self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
        if len(self.requests[ip]) >= self.max_requests:
            return False
        self.requests[ip].append(now)
        return True

    def remaining(self, ip: str) -> int:
        now = time.monotonic()
        if ip not in self.requests:
            return self.max_requests
        active = [t for t in self.requests[ip] if now - t < self.window]
        return max(0, self.max_requests - len(active))

    def update_limit(self, max_requests: int) -> None:
        self.max_requests = max_requests


# Instantiate global rate limiter
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


def sanitize_message(message: Any, source: str = "api") -> Tuple[Optional[str], Optional[web.Response]]:
    """Validates and sanitizes a chat message."""
    if not isinstance(message, str):
        return None, web.json_response(
            {"error": {"message": "Message must be a string", "type": "invalid_request_error"}},
            status=400
        )
    message = message.replace('\x00', '')
    if not message.strip():
        return None, web.json_response(
            {"error": {"message": "Message is empty", "type": "invalid_request_error"}},
            status=400
        )
    if len(message) > 50000:
        print(f"[WARN] Very long message from {source}: {len(message)} characters", flush=True)
    if len(message) > config.max_message_length:
        return None, web.json_response(
            {"error": {"message": f"Message too long: {len(message)} (max: {config.max_message_length})",
                       "type": "invalid_request_error"}},
            status=400
        )
    return message, None


def sanitize_error_response(error_msg: str, error_type: str, debug_info: Optional[Any] = None) -> Dict[str, Any]:
    """Formats an error response based on configuration debug mode."""
    if config.debug_mode:
        resp = {"error": {"message": str(error_msg), "type": error_type}}
        if debug_info is not None:
            resp["error"]["debug"] = debug_info
        return resp
    else:
        generic = {
            "connection_error": "Service temporarily unavailable",
            "internal_error": "Internal server error",
            "backend_error": "Backend error",
            "invalid_request_error": str(error_msg),
            "authentication_error": "Authentication failed",
            "rate_limit_error": str(error_msg),
        }
        return {"error": {"message": generic.get(error_type, "Error"), "type": error_type}}


def track_usage(prompt_tokens: int, completion_tokens: int, model: Optional[str] = None) -> None:
    """Tracks token usage metrics in memory."""
    if session_stats["start_time"] is None:
        session_stats["start_time"] = datetime.now(timezone.utc).isoformat()
    session_stats["total_requests"] += 1
    session_stats["total_prompt_tokens"] += prompt_tokens
    session_stats["total_completion_tokens"] += completion_tokens
    session_stats["total_tokens"] += prompt_tokens + completion_tokens

    model_key = model or "gemini-3.5-flash-high"
    if model_key in ("antigravity", "default"):
        model_key = "gemini-3.5-flash-high"

    if model_key not in session_stats["requests_by_model"]:
        session_stats["requests_by_model"][model_key] = {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "tokens": 0
        }
    stats = session_stats["requests_by_model"][model_key]
    stats["requests"] += 1
    stats["prompt_tokens"] += prompt_tokens
    stats["completion_tokens"] += completion_tokens
    stats["tokens"] += prompt_tokens + completion_tokens
