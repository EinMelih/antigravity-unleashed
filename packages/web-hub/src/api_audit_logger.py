"""Persistent API Audit & Revert Logger for the Anti-Gravity API Bridge.

Stores complete request/response records, exact token/context window metrics,
shield actions, and conversation revert history in both SQLite (`dashboard.db`)
and append-only JSONL (`~/.antigravity-hub/api_audit_logs.jsonl`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import config
from src.database import db

AUDIT_LOG_DIR = Path.home() / ".antigravity-hub"
AUDIT_LOG_JSONL = AUDIT_LOG_DIR / "api_audit_logs.jsonl"

_OPENCLAW_SIGNATURE_TOOLS: Set[str] = {
    "sessions_spawn",
    "sessions_send",
    "sessions_list",
    "sessions_history",
    "session_status",
    "subagents",
    "memory_search",
    "memory_get",
    "agents_list",
    "gateway",
    "canvas",
    "nodes",
    "apply_patch",
    "web_fetch",
    "cron",
    "image_generate",
}

_HERMES_SIGNATURE_TOOLS: Set[str] = {
    "delegate_task",
    "skill_view",
    "skills_list",
    "skill_manage",
    "session_search",
    "clarify",
    "mixture_of_agents",
    "web_extract",
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_vision",
    "execute_code",
    "terminal",
    "read_file",
    "write_file",
    "search_files",
}


def _extract_tool_names(tools: Optional[List[Dict[str, Any]]]) -> Set[str]:
    names: Set[str] = set()
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if item.get("type") == "function" else item
        if isinstance(fn, dict) and fn.get("name"):
            names.add(str(fn["name"]).strip().lower())
        elif item.get("name"):
            names.add(str(item["name"]).strip().lower())
    return names


def _normalize_source_slug(raw: str) -> Optional[str]:
    low = (raw or "").strip().lower()
    if not low or low == "auto":
        return None
    if low in ("ich", "me", "user", "local", "lokal", "pc", "melih", "self"):
        return "user"
    if "openclaw" in low or "claw" in low or "moltbot" in low:
        return "openclaw"
    if "hermes" in low:
        return "hermes"
    if "openwebui" in low or "open-webui" in low:
        return "openwebui"
    if "dokploy" in low:
        return "dokploy"
    if "openai" in low:
        return "openai"
    return low


def _match_configured_ip_rule(client_ip: str) -> Optional[Tuple[str, str]]:
    ip_clean = (client_ip or "").strip()
    if not ip_clean:
        return None
    ip_map = config.api_engine.get("source_ip_map") or {}
    if not isinstance(ip_map, dict):
        return None
    # 1. Exact IP match
    if ip_clean in ip_map:
        slug = _normalize_source_slug(str(ip_map[ip_clean]))
        if slug:
            return slug, f"ip-rule:{ip_clean}"
    # 2. Prefix / wildcard match (e.g. "192.168.178.*" or "10.0.")
    for pattern, target in ip_map.items():
        pat = str(pattern or "").strip()
        if not pat:
            continue
        if pat.endswith("*"):
            prefix = pat[:-1]
            if prefix and ip_clean.startswith(prefix):
                slug = _normalize_source_slug(str(target))
                if slug:
                    return slug, f"ip-rule:{pat}"
    return None


def detect_source_framework_detailed(
    user_agent: str,
    headers: Optional[Dict[str, str]] = None,
    raw_messages: Optional[List[Dict[str, Any]]] = None,
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    client_ip: str = "",
    api_key_name: str = "",
    path: str = "",
) -> Tuple[str, str]:
    """Identify request origin (OpenClaw, Hermes, User/Local, OpenWebUI, Dokploy, OpenAI) BEFORE Shield 2 scrubs it.

    Returns ``(source_framework, detection_reason)``.
    """
    hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}

    # 1. Explicit URL route prefix (e.g. /openclaw/v1/chat/completions or /hermes/v1/...)
    low_path = (path or "").strip().lower()
    if low_path.startswith("/openclaw/"):
        return "openclaw", "url:/openclaw/v1"
    if low_path.startswith("/hermes/"):
        return "hermes", "url:/hermes/v1"
    if low_path.startswith("/openwebui/"):
        return "openwebui", "url:/openwebui/v1"
    if low_path.startswith("/dokploy/"):
        return "dokploy", "url:/dokploy/v1"
    if low_path.startswith(("/ich/", "/me/", "/user/", "/local/")):
        return "user", f"url:{low_path.split('/v1')[0]}"

    # 2. Explicit HTTP header
    explicit = (
        hdrs.get("x-source-framework")
        or hdrs.get("x-client-framework")
        or hdrs.get("x-source-client")
        or hdrs.get("x-title")
        or ""
    ).strip()
    explicit_slug = _normalize_source_slug(explicit)
    if explicit_slug:
        return explicit_slug, f"header:{explicit.lower()[:24]}"

    # 3. API-Key name mapping
    key_slug = _normalize_source_slug(api_key_name) if api_key_name and api_key_name != "default" else None
    if key_slug:
        return key_slug, f"api-key:{api_key_name}"

    # 4. User-Agent header check
    ua = (user_agent or "").lower()
    if "hermes" in ua:
        return "hermes", "auto:user-agent"
    if "openclaw" in ua or "clawd" in ua or "moltbot" in ua or "claw" in ua:
        return "openclaw", "auto:user-agent"
    if "open-webui" in ua or "openwebui" in ua:
        return "openwebui", "auto:user-agent"
    if "dokploy" in ua:
        return "dokploy", "auto:user-agent"

    # 5. Deep Tool-Schema Fingerprinting (detects OpenClaw & Hermes even with neutral prompts!)
    tool_names = _extract_tool_names(tools)
    if tool_names:
        oc_hits = tool_names & _OPENCLAW_SIGNATURE_TOOLS
        hm_hits = tool_names & _HERMES_SIGNATURE_TOOLS
        if oc_hits and len(oc_hits) >= len(hm_hits):
            sample = sorted(oc_hits)[0]
            return "openclaw", f"auto:tools({sample})"
        if hm_hits:
            sample = sorted(hm_hits)[0]
            return "hermes", f"auto:tools({sample})"
        if {"read", "write", "edit"}.issubset(tool_names) and bool(tool_names & {"exec", "bash", "process"}):
            return "openclaw", "auto:tools(exec+read+write+edit)"
        if {"terminal", "read_file", "write_file"}.issubset(tool_names):
            return "hermes", "auto:tools(terminal+read_file)"

    # 6. Raw Message & System-Prompt Fingerprinting (runs BEFORE Shield 2 strips keywords)
    combined_chunks: List[str] = []
    for msg in raw_messages or []:
        if not isinstance(msg, dict):
            continue
        raw_content = msg.get("content") or ""
        if isinstance(raw_content, list):
            content = " ".join(
                str(part.get("text") or "") if isinstance(part, dict) else str(part)
                for part in raw_content
            )
        else:
            content = str(raw_content)
        combined_chunks.append(content)

    low_all = "\n".join(combined_chunks).lower()
    if low_all:
        # 6a. Exclusive Hermes Agent upstream markers (NousResearch/hermes-agent prompt_builder.py)
        for hm_marker in (
            "you are hermes agent",
            "created by nous research",
            "nous research",
            "hermes-agent",
            "hermes agent",
            "delegate_task",
            "skill_view",
            "skills_list",
            "session_search",
            "mixture_of_agents",
        ):
            if hm_marker in low_all:
                return "hermes", f"auto:system-prompt({hm_marker})"

        # 6b. Exclusive OpenClaw upstream markers (openclaw/src/agents/system-prompt.ts)
        for oc_marker in (
            "openclaw",
            "clawdbot",
            "moltbot",
            "clawd",
            "tool availability (filtered by policy)",
            "do not pursue self-preservation",
            "heartbeat.md",
            "heartbeat_ok",
            "bootstrap.md",
            "identity.md",
            "tools.md",
            "sessions_spawn",
            "sessions_send",
            "pi-mono",
            "soul.md",
        ):
            if oc_marker in low_all:
                return "openclaw", f"auto:system-prompt({oc_marker})"

        if (
            "open-webui" in low_all
            or "openwebui" in low_all
            or ("### task:" in low_all and ("3-5 word title" in low_all or "follow-up questions" in low_all))
        ):
            return "openwebui", "auto:system-prompt"
        if "dockercompose" in low_all or '"suggestions"' in low_all or "dokploy" in low_all:
            return "dokploy", "auto:system-prompt"

    # 7. User-configured Custom IP Mapping (`source_ip_map`)
    ip_match = _match_configured_ip_rule(client_ip)
    if ip_match is not None:
        return ip_match

    # 8. Hub UI / Interactive /docs Tester detection via Referer / Origin
    referer = hdrs.get("referer", "").lower()
    origin = hdrs.get("origin", "").lower()
    if "/docs" in referer or "/dashboard" in referer or ":8000" in origin or ":8001" in referer:
        return "user", "hub-ui:/docs"

    # 9. Local PC (127.0.0.1 / ::1) -> "Ich / Lokal" ("user") when enabled
    if client_ip in ("127.0.0.1", "::1", "localhost") and bool(
        config.api_engine.get("local_ip_is_user", True)
    ):
        return "user", f"local-pc:{client_ip}"

    if "openai" in ua or "python-httpx" in ua:
        return "openai-sdk", "fallback:sdk"
    return "openai", "fallback:openai"


def detect_source_framework(
    user_agent: str,
    headers: Optional[Dict[str, str]] = None,
    raw_messages: Optional[List[Dict[str, Any]]] = None,
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    client_ip: str = "",
    api_key_name: str = "",
    path: str = "",
) -> str:
    """Identify whether a request originated from Hermes, OpenClaw, User/Local, Dokploy, or OpenAI SDK."""
    source, _ = detect_source_framework_detailed(
        user_agent,
        headers,
        raw_messages,
        tools=tools,
        client_ip=client_ip,
        api_key_name=api_key_name,
        path=path,
    )
    return source


def record_api_audit_log(
    *,
    req_id: str,
    client_ip: str = "",
    user_agent: str = "",
    api_key_name: str = "",
    source_framework: str = "openai",
    endpoint: str = "/v1/chat/completions",
    engine_mode: str = "rpc",
    workspace_slot: str = "",
    conversation_id: str = "",
    model_requested: str = "",
    model_actual: str = "",
    reasoning_effort: str = "",
    stream: bool = False,
    status_code: int = 200,
    duration_ms: float = 0.0,
    token_metrics: Optional[Dict[str, Any]] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    system_prompt: str = "",
    user_prompt_preview: str = "",
    response_text: str = "",
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    shield_metadata: Optional[Dict[str, Any]] = None,
    error_text: str = "",
) -> Dict[str, Any]:
    """Persist a complete API audit record to SQLite and JSONL."""
    now_iso = datetime.now(timezone.utc).isoformat()
    t_meta = token_metrics or {}
    entry = {
        "req_id": req_id,
        "created_at": now_iso,
        "client_ip": client_ip or "127.0.0.1",
        "user_agent": user_agent or "",
        "api_key_name": api_key_name or "default",
        "source_framework": source_framework or "openai",
        "endpoint": endpoint,
        "engine_mode": engine_mode,
        "workspace_slot": workspace_slot,
        "conversation_id": conversation_id or "",
        "model_requested": model_requested or "antigravity",
        "model_actual": model_actual or t_meta.get("model_actual") or model_requested or "antigravity",
        "reasoning_effort": reasoning_effort or "",
        "stream": bool(stream),
        "status_code": int(status_code),
        "duration_ms": round(float(duration_ms), 1),
        "prompt_tokens": int(t_meta.get("prompt_tokens") or 0),
        "completion_tokens": int(t_meta.get("completion_tokens") or 0),
        "cached_tokens": int(t_meta.get("cached_tokens") or 0),
        "thinking_tokens": int(t_meta.get("thinking_tokens") or 0),
        "total_tokens": int(t_meta.get("total_tokens") or 0),
        "context_used_tokens": int(t_meta.get("context_used_tokens") or 0),
        "context_max_tokens": int(t_meta.get("context_max_tokens") or 0),
        "token_source": str(t_meta.get("token_source") or "exact_rpc"),
        "messages": messages or [],
        "system_prompt": system_prompt or "",
        "user_prompt_preview": (user_prompt_preview or "")[:500],
        "response_text": response_text or "",
        "tool_calls": tool_calls or [],
        "shield_metadata": shield_metadata or {},
        "error_text": error_text or "",
        "reverted_at": None,
        "reverted_to_step": None,
    }

    try:
        db.insert_api_request_log(entry)
    except Exception as db_err:
        print(f"[AUDIT] [WARN] Failed to insert SQLite audit log: {db_err}", flush=True)

    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_JSONL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as file_err:
        print(f"[AUDIT] [WARN] Failed to append JSONL audit log: {file_err}", flush=True)

    return entry


def record_revert_event(
    *,
    conversation_id: str,
    target_step_index: int,
    previous_step_count: int = 0,
    reason: str = "manual_revert",
    triggered_by_ip: str = "127.0.0.1",
    engine_mode: str = "rpc",
) -> Dict[str, Any]:
    """Record a conversation revert ('Zurückdengeln') in SQLite and JSONL."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db.mark_conversation_logs_reverted(
            conversation_id=conversation_id,
            target_step_index=target_step_index,
            reverted_at=now_iso,
            previous_step_count=previous_step_count,
            reason=reason,
            triggered_by_ip=triggered_by_ip,
            engine_mode=engine_mode,
        )
    except Exception as err:
        print(f"[AUDIT] [WARN] Failed to record SQLite revert event: {err}", flush=True)

    event = {
        "event": "conversation_revert",
        "created_at": now_iso,
        "conversation_id": conversation_id,
        "target_step_index": target_step_index,
        "previous_step_count": previous_step_count,
        "reason": reason,
        "triggered_by_ip": triggered_by_ip,
        "engine_mode": engine_mode,
    }
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_JSONL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return event
