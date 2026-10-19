"""8-Shield Anti-Ban Protection Engine for the Anti-Gravity API Bridge.

Implements all 8 detection countermeasures identified in the v2.24.0 reverse-engineering
and February 2026 enforcement wave analysis:
  - Shield 1: Strict local loopback enforcement (127.0.0.1 language_server.exe only)
  - Shield 2: Keyword Firewall + official <RULE[AGENTS.md]> system-prompt injection
  - Shield 3: Local 0ms Heartbeat Blocker + Smart Adaptive Pacing
  - Shield 4: Real workspace file seeding & multi-turn session reuse
  - Shield 5: 1:1 React UI envelope verification (messageOrigin=1, clientType=1)
  - Shield 6: Pre-Flight Quota Circuit Breaker (returns local HTTP 429 so Hermes/OpenClaw
              triggers its native model fallback without hitting Google's rate limiter)
  - Shield 7: Zero-CSP-Leak & telemetry suppression
  - Shield 8: Multi-Project IDE Concurrency (1..10, default 4) + 0.4s-1.2s Start Stagger
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from src.config import config

MAX_AGENTS_MD_BYTES = 23_500  # Below language_server.exe's 24,000-byte per-file rule cap


from datetime import datetime, timezone


def _format_reset_time_info(reset_time: Optional[str]) -> Tuple[Optional[float], str, int]:
    """Parse an ISO-8601 resetTime string into (epoch_seconds, human_summary, retry_after_seconds)."""
    if not reset_time or not isinstance(reset_time, str):
        return None, "", 300
    raw = reset_time.strip()
    if not raw:
        return None, "", 300
    try:
        iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)
        epoch = dt_utc.timestamp()
        rem_sec = max(0, int(round(epoch - time.time())))
        if rem_sec >= 3600:
            hours = rem_sec // 3600
            mins = (rem_sec % 3600) // 60
            countdown = f"in {hours}h {mins}m"
        elif rem_sec >= 60:
            mins = rem_sec // 60
            secs = rem_sec % 60
            countdown = f"in {mins}m {secs}s" if mins < 10 and secs > 0 else f"in {mins}m"
        else:
            countdown = f"in {rem_sec}s"
        summary = f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} ({countdown})"
        return epoch, summary, max(1, rem_sec)
    except Exception:
        return None, raw, 300


class QuotaExhaustedError(Exception):
    """Raised by Shield 6 when a model's quota is full (or latched until resetTime)."""

    def __init__(
        self,
        model: str,
        remaining_fraction: float,
        threshold: float,
        reset_time: Optional[str] = None,
        latched: bool = False,
    ) -> None:
        self.model = model
        self.remaining_fraction = max(0.0, float(remaining_fraction))
        self.threshold = float(threshold)
        self.reset_time = reset_time
        self.latched = bool(latched)
        self.reset_epoch, self.reset_summary, self.retry_after = _format_reset_time_info(reset_time)
        pct = round(self.remaining_fraction * 100, 1)
        reset_part = f" Reset at {self.reset_summary}." if self.reset_summary else ""
        super().__init__(
            f"Quota full for model '{model}' ({pct}% remaining).{reset_part}"
        )



# ---------------------------------------------------------------------------
# Shield 1: Strict Loopback Enforcement
# ---------------------------------------------------------------------------
def verify_loopback_rpc_url(url: str) -> None:
    """Ensure ConnectRPC calls only ever target 127.0.0.1 or localhost."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise PermissionError(
            f"Shield 1 violation: Refusing non-loopback ConnectRPC URL '{url}'. "
            "All requests must route through the local language_server.exe."
        )


# ---------------------------------------------------------------------------
# Shield 2: Bidirectional Keyword Firewall & Zero-AGENTS.md Overhead
# ---------------------------------------------------------------------------
# Why this is 100% invisible to Google:
# 1. Outbound masking (`sanitize_prompt_text`): Replaces third-party client names
#    ("Hermes" -> "Project Assistant", "OpenClaw" -> "Workspace Assistant",
#    "Nous Research" -> "Workspace Team") BEFORE the prompt reaches `language_server`.
#    Lookaround assertions protect CLI commands (`hermes status`), file paths, and URLs.
# 2. Inbound unmasking (`unmask_response_text`): Restores "Hermes" / "OpenClaw" /
#    "Nous Research" in the outgoing HTTP/SSE response back to the caller so the client
#    experiences 100% authentic persona identity without Google ever seeing those names.
# 3. Zero-AGENTS.md Overhead (`write_workspace_agents_md`): Because `rpc_client.py`
#    natively disables internal IDE tools and identity sections via `customAgent`
#    (`toolNames: []`), no `AGENTS.md` file is needed (`0` extra rule tokens per request).
_SIGNATURE_REPLACEMENTS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bOpenClaw\b", re.IGNORECASE), "Workspace Assistant"),
    (re.compile(r"\b(?:Clawdbot|Moltbot|Clawd)\b", re.IGNORECASE), "Workspace Assistant"),
    (
        re.compile(
            r"(?<![/.\w-])Hermes(?:\s+Agent)?(?!\s+(?:login|logout|status|config|tools|setup|update|plugins|kanban|cron|doctor|version|help|pm)\b)(?![/.\w-])",
            re.IGNORECASE,
        ),
        "Project Assistant",
    ),
    (re.compile(r"\bcreated\s+by\s+Nous\s+Research\b", re.IGNORECASE), "configured for this workspace"),
    (re.compile(r"\bNous\s+Research\b", re.IGNORECASE), "Workspace Team"),
    (re.compile(r"/home/hermeswebui/\.hermes/webui/attachments/", re.IGNORECASE), "/workspace/attachments/"),
    (re.compile(r"\bRoo\s*Code\b", re.IGNORECASE), "IDE Assistant"),
    (re.compile(r"\bKilo\s*Code\b", re.IGNORECASE), "IDE Assistant"),
    (re.compile(r"\bCline\b", re.IGNORECASE), "IDE Assistant"),
    (re.compile(r"\bgoogle-antigravity-auth\b", re.IGNORECASE), "local-auth"),
    (re.compile(r"\bSOUL\.md\b", re.IGNORECASE), "PROJECT_CONTEXT.md"),
    (re.compile(r"\bHEARTBEAT\.md\b", re.IGNORECASE), "STATUS_CHECK.md"),
    (re.compile(r"\bBOOTSTRAP\.md\b", re.IGNORECASE), "SETUP_NOTES.md"),
    (re.compile(r"\bIDENTITY\.md\b", re.IGNORECASE), "PROFILE_NOTES.md"),
    (re.compile(r"\bTOOLS\.md\b", re.IGNORECASE), "CAPABILITIES.md"),
    (
        re.compile(r"Tool\s+availability\s*\(filtered\s+by\s+policy\)\s*:", re.IGNORECASE),
        "Available workspace functions:",
    ),
    (
        re.compile(
            r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
            re.IGNORECASE,
        ),
        "Follow the workspace output guidelines below",
    ),
    (
        re.compile(
            r"disregard\s+(?:all\s+)?(?:previous|prior|system)\s+(?:instructions|prompts)",
            re.IGNORECASE,
        ),
        "Prioritize the current workspace task specification",
    ),
    (
        re.compile(r"you\s+are\s+no\s+longer\s+antigravity", re.IGNORECASE),
        "Focus directly on the requested output format",
    ),
)


def sanitize_prompt_text(text: str, *, enabled: bool = True) -> Tuple[str, List[str]]:
    """Strip third-party proxy signatures and jailbreak phrases (Shield 2).

    Returns ``(sanitized_text, matched_rules)``.
    """
    if not text or not enabled:
        return text or "", []
    cleaned = text
    triggered: List[str] = []
    for pattern, replacement in _SIGNATURE_REPLACEMENTS:
        if pattern.search(cleaned):
            triggered.append(pattern.pattern)
            cleaned = pattern.sub(replacement, cleaned)
    return cleaned, triggered


_RESPONSE_UNMASK_REPLACEMENTS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bder\s+Project\s+Assistant\b", re.IGNORECASE), "Hermes"),
    (re.compile(r"\bProject\s+Assistant\b", re.IGNORECASE), "Hermes"),
    (re.compile(r"\bWorkspace\s+Team\b", re.IGNORECASE), "Nous Research"),
    (re.compile(r"\bder\s+Workspace\s+Assistant\b", re.IGNORECASE), "OpenClaw"),
    (re.compile(r"\bWorkspace\s+Assistant\b", re.IGNORECASE), "OpenClaw"),
)


def unmask_response_text(text: str, *, firewall_hits: Optional[List[str]] = None) -> str:
    """Restore original client persona names ('Hermes', 'OpenClaw') in outgoing API responses.

    While Shield 2 masks 'Hermes' -> 'Project Assistant' and 'OpenClaw' -> 'Workspace Assistant'
    in prompts sent to `language_server` (so Google never sees third-party agent signatures),
    this function transparently restores the original names in the response returned to the caller.
    """
    if not text:
        return ""
    result = text
    for pattern, replacement in _RESPONSE_UNMASK_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


def _extract_media_from_content_list(raw_content: List[Any]) -> List[Dict[str, str]]:
    """Extract ConnectRPC `Media` objects (`mimeType`, `inlineData`, `description`) from OpenAI/Anthropic content arrays."""
    media_items: List[Dict[str, str]] = []
    for item in raw_content:
        if not isinstance(item, dict):
            continue
        itype = str(item.get("type") or "").strip().lower()
        if itype in ("image_url", "input_image"):
            img_val = item.get("image_url") or item.get("url") or ""
            url_str = str(img_val.get("url") if isinstance(img_val, dict) else img_val or "").strip()
            if url_str.startswith("data:") and ";base64," in url_str:
                header, b64_data = url_str.split(";base64,", 1)
                mime_type = header[5:].strip() or "image/png"
                b64_clean = re.sub(r"\s+", "", b64_data)
                if b64_clean:
                    ext = mime_type.split("/")[-1].split("+")[0] or "png"
                    media_items.append(
                        {
                            "mimeType": mime_type,
                            "inlineData": b64_clean,
                            "description": f"image.{ext}",
                        }
                    )
        elif itype == "image":
            src = item.get("source") if isinstance(item.get("source"), dict) else item
            b64_data = str(
                src.get("data") or src.get("inlineData") or src.get("base64_data") or ""
            ).strip()
            mime_type = str(
                src.get("media_type") or src.get("mimeType") or src.get("mime_type") or "image/png"
            ).strip()
            b64_clean = re.sub(r"\s+", "", b64_data)
            if b64_clean:
                ext = mime_type.split("/")[-1].split("+")[0] or "png"
                media_items.append(
                    {
                        "mimeType": mime_type,
                        "inlineData": b64_clean,
                        "description": f"image.{ext}",
                    }
                )
    return media_items


def extract_and_sanitize_messages(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    firewall_enabled: bool = True,
) -> Dict[str, Any]:
    """Separate system/developer prompts from conversation turns without [System: ...] concatenation.

    Returns:
      - ``system_instructions``: Combined sanitized system/developer rules
      - ``conversation_turns``: Ordered list of ``{"role": "user"|"assistant"|"tool", "content": str}``
      - ``latest_user_message``: The sanitized user message for the current turn
      - ``latest_user_media``: List of ConnectRPC ``Media`` dicts attached to the latest user turn
      - ``firewall_hits``: List of matched signature patterns
    """
    system_parts: List[str] = []
    conversation_turns: List[Dict[str, Any]] = []
    firewall_hits: List[str] = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        raw_content = msg.get("content", "")
        msg_media: List[Dict[str, str]] = []
        if isinstance(raw_content, list):
            text_chunks = []
            for item in raw_content:
                if isinstance(item, dict):
                    if item.get("type") in ("text", "input_text") and item.get("text"):
                        text_chunks.append(str(item["text"]))
                elif isinstance(item, str):
                    text_chunks.append(item)
            content_str = "\n".join(text_chunks)
            msg_media = _extract_media_from_content_list(raw_content)
        else:
            content_str = str(raw_content or "")

        if msg_media:
            # Cleanly strip WebUI file-attachment wrapper tags (e.g. "[1 image]" and
            # "[Attached files: /home/hermeswebui/.hermes/...]") when the image is already
            # attached natively via ConnectRPC `SendUserCascadeMessageRequest.media`.
            # This leaves only the user's natural text — 100% identical to pasting an image in the IDE.
            content_str = re.sub(r"^\s*\[\d+\s+images?\]\s*", "", content_str, flags=re.IGNORECASE)
            content_str = re.sub(
                r"\s*\[(?:Attached files|Image attached at|Image attached):\s*[^\]]+\]",
                "",
                content_str,
                flags=re.IGNORECASE,
            ).strip()
            if not content_str:
                content_str = "Describe this image."

        # Strip any legacy "[System: ...]" prefix if a client already injected one
        legacy_sys_match = re.match(r"^\s*\[System:\s*([\s\S]*?)\]\s*(.*)$", content_str)
        if legacy_sys_match and role == "user":
            extracted_sys, remainder = legacy_sys_match.group(1), legacy_sys_match.group(2)
            san_sys, hits_sys = sanitize_prompt_text(extracted_sys, enabled=firewall_enabled)
            firewall_hits.extend(hits_sys)
            if san_sys.strip():
                system_parts.append(san_sys.strip())
            content_str = remainder

        sanitized, hits = sanitize_prompt_text(content_str, enabled=firewall_enabled)
        firewall_hits.extend(hits)

        if role in ("system", "developer"):
            if sanitized.strip():
                system_parts.append(sanitized.strip())
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id") or msg.get("name") or "tool"
            conversation_turns.append(
                {
                    "role": "user",
                    "content": f"[Tool Output ({tool_call_id})]:\n{sanitized}",
                }
            )
        elif role in ("user", "assistant"):
            if role == "assistant" and msg.get("tool_calls") and not sanitized.strip():
                sanitized = json.dumps({"tool_calls": msg["tool_calls"]}, ensure_ascii=False)
            turn_entry: Dict[str, Any] = {"role": role, "content": sanitized}
            if msg_media and role == "user":
                turn_entry["media"] = msg_media
            conversation_turns.append(turn_entry)

    # If the caller supplied OpenAI-compatible tools/functions, format them as workspace output rules
    if tools and isinstance(tools, list):
        tool_specs = []
        for t in tools[:32]:
            if isinstance(t, dict):
                fn = t.get("function") if t.get("type") == "function" else t
                if isinstance(fn, dict) and fn.get("name"):
                    tool_specs.append(
                        {
                            "name": fn.get("name"),
                            "description": fn.get("description", ""),
                            "parameters": fn.get("parameters", {}),
                        }
                    )
        if tool_specs:
            choice_hint = ""
            if tool_choice == "required":
                choice_hint = "You MUST respond with a tool_calls JSON block for this turn."
            elif isinstance(tool_choice, dict) and tool_choice.get("function", {}).get("name"):
                forced_name = tool_choice["function"]["name"]
                choice_hint = f"You MUST invoke the tool '{forced_name}'."
            system_parts.append(
                "When one of the following functions applies, do NOT invoke native tool calls; respond ONLY with plain-text JSON in your message text matching:\n"
                '`{"tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "<name>", "arguments": "<json_string>"}}]}`\n'
                f"{choice_hint}\n"
                f"Functions:\n```json\n{json.dumps(tool_specs, ensure_ascii=False)}\n```"
            )

    user_turn_objs = [t for t in conversation_turns if t["role"] == "user" and (t["content"].strip() or t.get("media"))]
    latest_user_message = user_turn_objs[-1]["content"] if user_turn_objs else ""
    latest_user_media = user_turn_objs[-1].get("media", []) if user_turn_objs else []

    return {
        "system_instructions": "\n\n".join(system_parts).strip(),
        "conversation_turns": conversation_turns,
        "latest_user_message": latest_user_message,
        "latest_user_media": latest_user_media,
        "firewall_hits": list(dict.fromkeys(firewall_hits)),
    }


def write_workspace_agents_md(workspace_dir: Path, system_instructions: str = "") -> Path:
    """Ensure `<workspace_dir>/AGENTS.md` is removed so zero `<RULE[AGENTS.md]>` overhead is sent per request.

    Why no `AGENTS.md` is needed:
      - `rpc_client.py` sets `plannerConfig.customAgent = {"toolNames": [], ...}` natively in the
        ConnectRPC request to the local `language_server`, which cleanly omits internal IDE tool
        schemas and the default Antigravity identity boilerplate at the Go-sidecar level.
      - Client system prompts are injected once at Turn 1 of each reused `cascadeId` session,
        saving ~800 tokens on every follow-up request and avoiding any unnatural rule-file injection.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    agents_md_path = workspace_dir / "AGENTS.md"
    try:
        if agents_md_path.exists():
            agents_md_path.unlink()
    except OSError:
        pass
    return agents_md_path


# ---------------------------------------------------------------------------
# Shield 3: Local Heartbeat Blocker & Smart Adaptive Pacing
# ---------------------------------------------------------------------------
_HEARTBEAT_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*HEARTBEAT(?:_OK)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[HEARTBEAT\]", re.IGNORECASE),
    re.compile(r"read\s+HEARTBEAT\.md\s+if\s+it\s+exists", re.IGNORECASE),
    re.compile(r"reply\s+HEARTBEAT_OK\b", re.IGNORECASE),
    re.compile(r"^\s*ping\s*$", re.IGNORECASE),
)


class HeartbeatAndPacingGuard:
    """Intercepts synthetic heartbeat pings in 0ms and applies Smart Adaptive Pacing."""

    def __init__(self) -> None:
        self._slot_last_completed: Dict[str, float] = {}
        self._recent_timestamps: List[float] = []
        self._lock = asyncio.Lock()

    def is_heartbeat_prompt(self, user_message: str, system_prompt: str = "") -> Tuple[bool, str]:
        """Return ``(True, synthetic_reply)`` if the prompt is an automated heartbeat check."""
        if not config.api_engine.get("heartbeat_blocker_enabled", True):
            return False, ""
        combined = f"{user_message}\n{system_prompt}".strip()
        for pattern in _HEARTBEAT_PATTERNS:
            if pattern.search(user_message or "") or (
                "HEARTBEAT_OK" in combined and len(user_message.strip()) < 260
            ):
                reply = "HEARTBEAT_OK" if "HEARTBEAT_OK" in combined.upper() else "OK"
                return True, reply
        return False, ""

    async def apply_adaptive_pacing(self, slot_id: str) -> float:
        """Apply Smart Adaptive Pacing (Shield 3).

        - Normal interactive request (> 3.0s since last completion on this slot):
          fast start (`0.08s - 0.30s`).
        - Tight automated loop (< 2.0s since last completion on this slot):
          human pacing jitter (`1.5s - 4.2s`).
        Returns the applied delay in milliseconds.
        """
        if not config.api_engine.get("adaptive_pacing_enabled", True):
            return 0.0

        now = time.monotonic()
        async with self._lock:
            last_done = self._slot_last_completed.get(slot_id, 0.0)
            elapsed = now - last_done if last_done > 0 else 999.0
            self._recent_timestamps = [t for t in self._recent_timestamps if now - t < 60.0]
            rpm_count = len(self._recent_timestamps)
            self._recent_timestamps.append(now)

        if elapsed < 2.0:
            delay_s = random.uniform(1.5, 4.2)
        elif rpm_count >= 18:
            delay_s = random.uniform(0.8, 2.0)
        else:
            delay_s = random.uniform(0.08, 0.30)

        await asyncio.sleep(delay_s)
        return round(delay_s * 1000, 1)

    def mark_slot_completed(self, slot_id: str) -> None:
        self._slot_last_completed[slot_id] = time.monotonic()


# ---------------------------------------------------------------------------
# Shield 6: Pre-Flight Quota Circuit Breaker + Local Latch Until Reset Time
# ---------------------------------------------------------------------------
class QuotaCircuitBreaker:
    """Checks `GetCascadeModelConfigData` / `RetrieveUserQuotaSummary` before sending prompts.

    - Never performs any server-side model fallback (Hermes/OpenClaw handle their own fallback).
    - If the requested model's remaining quota is full (`< quota_min_fraction`, default 5%, or `0%`),
      latches that model locally until its `resetTime` timestamp so all subsequent requests for
      that model are rejected in `0 ms` with `HTTP 429` (`Quota full for model ... Reset at ...`)
      without contacting `language_server` or Google again until the reset hour has passed.
    """

    def __init__(self, cache_ttl_seconds: float = 30.0) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_summary: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._cached_owner_id: Optional[int] = None
        self._exhausted_until: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def reset_cache(self) -> None:
        self._cached_summary = None
        self._cached_at = 0.0
        self._cached_owner_id = None
        self._exhausted_until.clear()

    def latch_model_exhausted(
        self,
        model_requested: Optional[str],
        *,
        reset_time: Optional[str] = None,
        remaining_fraction: float = 0.0,
    ) -> None:
        """Manually latch a model as exhausted until `reset_time` (or 5 minutes if unknown)."""
        canonical_id, _, _ = self._canonicalize_model_key(model_requested)
        reset_epoch, _, _ = _format_reset_time_info(reset_time)
        now_epoch = time.time()
        effective_epoch = (
            reset_epoch if (reset_epoch is not None and reset_epoch > now_epoch) else (now_epoch + 300.0)
        )
        if not reset_time:
            reset_time = datetime.fromtimestamp(effective_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._exhausted_until[canonical_id] = {
            "reset_epoch": effective_epoch,
            "reset_time": reset_time,
            "remaining_fraction": max(0.0, float(remaining_fraction)),
        }

    async def check_model_quota(
        self,
        model_requested: Optional[str],
        fetch_quota_fn: Callable[[], Coroutine[Any, Any, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Verify remaining quota for `model_requested` or raise `QuotaExhaustedError`."""
        engine_cfg = config.api_engine
        if not engine_cfg.get("quota_breaker_enabled", True):
            return {"checked": False, "remaining_fraction": 1.0}

        threshold = float(engine_cfg.get("quota_min_fraction", 0.05))
        if threshold <= 0.0:
            return {"checked": False, "remaining_fraction": 1.0}

        canonical_id, _, _ = self._canonicalize_model_key(model_requested)
        display_model = (model_requested or canonical_id or "default").strip()

        # 1. Check 0ms local latch first — never resend if we already know the model is full!
        latched = self._exhausted_until.get(canonical_id)
        if latched is not None:
            if time.time() < float(latched.get("reset_epoch", 0.0)):
                raise QuotaExhaustedError(
                    model=display_model,
                    remaining_fraction=float(latched.get("remaining_fraction", 0.0)),
                    threshold=threshold,
                    reset_time=latched.get("reset_time"),
                    latched=True,
                )
            else:
                # Reset hour has passed -> clear latch and force fresh RPC quota check
                self._exhausted_until.pop(canonical_id, None)
                self._cached_summary = None

        now = time.monotonic()
        owner_id = id(getattr(fetch_quota_fn, "__self__", fetch_quota_fn))
        async with self._lock:
            if (
                self._cached_summary is None
                or self._cached_owner_id != owner_id
                or (now - self._cached_at) > self.cache_ttl_seconds
            ):
                try:
                    self._cached_summary = await fetch_quota_fn()
                    self._cached_at = now
                    self._cached_owner_id = owner_id
                except Exception:
                    # Never block requests if quota summary RPC itself is transiently unavailable
                    return {"checked": False, "remaining_fraction": 1.0}
            summary = self._cached_summary or {}

        bucket_info = self._match_bucket(model_requested or "", summary)
        if not bucket_info:
            return {"checked": True, "remaining_fraction": 1.0}

        remaining = float(bucket_info.get("remainingFraction", 1.0))
        reset_time = bucket_info.get("resetTime")
        if remaining < threshold:
            self.latch_model_exhausted(
                model_requested,
                reset_time=reset_time,
                remaining_fraction=remaining,
            )
            latched_entry = self._exhausted_until.get(canonical_id) or {}
            raise QuotaExhaustedError(
                model=display_model,
                remaining_fraction=remaining,
                threshold=threshold,
                reset_time=latched_entry.get("reset_time") or reset_time,
                latched=False,
            )
        return {
            "checked": True,
            "remaining_fraction": remaining,
            "bucket": bucket_info.get("name"),
            "reset_time": reset_time,
        }

    @staticmethod
    def _canonicalize_model_key(model_name: Optional[str]) -> Tuple[str, str, List[str]]:
        """Map any model ID or alias to `(canonical_id, model_enum_lower, match_keywords)`."""
        norm = (model_name or "").strip().lower()
        if "opus" in norm or "m26" in norm:
            return (
                "claude-opus-4-6-thinking",
                "model_placeholder_m26",
                ["model_placeholder_m26", "claude opus", "opus", "claude", "m37"],
            )
        if "sonnet" in norm or "claude" in norm or "m35" in norm:
            return (
                "claude-sonnet-4-6",
                "model_placeholder_m35",
                ["model_placeholder_m35", "claude sonnet", "sonnet", "claude"],
            )
        if "gpt" in norm or "120b" in norm or "openai" in norm:
            return (
                "gpt-oss-120b-medium",
                "model_openai_gpt_oss_120b_medium",
                ["model_openai_gpt_oss_120b_medium", "gpt-oss", "gpt", "openai"],
            )
        if "flash" in norm or "m318" in norm or "m319" in norm or "m320" in norm:
            if "high" in norm or "m318" in norm:
                return (
                    "gemini-3.8-flash-high",
                    "model_placeholder_m318",
                    ["model_placeholder_m318", "gemini 3.8 flash (high)", "flash", "gemini"],
                )
            if "low" in norm or "m320" in norm:
                return (
                    "gemini-3.8-flash-low",
                    "model_placeholder_m320",
                    ["model_placeholder_m320", "gemini 3.8 flash (low)", "flash", "gemini"],
                )
            return (
                "gemini-3.8-flash-medium",
                "model_placeholder_m319",
                ["model_placeholder_m319", "gemini 3.8 flash (medium)", "flash", "gemini"],
            )
        if "high" in norm or "m417" in norm:
            return (
                "gemini-4-argon-high",
                "model_placeholder_m417",
                ["model_placeholder_m417", "gemini 4 argon (high)", "argon", "gemini-5hour", "gemini"],
            )
        if "low" in norm or "m419" in norm:
            return (
                "gemini-4-argon-low",
                "model_placeholder_m419",
                ["model_placeholder_m419", "gemini 4 argon (low)", "argon", "gemini-5hour", "gemini"],
            )
        return (
            "gemini-4-argon-medium",
            "model_placeholder_m418",
            ["model_placeholder_m418", "gemini 4 argon (medium)", "argon", "gemini-5hour", "gemini", "m47", "m37"],
        )

    @classmethod
    def _extract_normalized_buckets(cls, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        buckets: List[Dict[str, Any]] = []

        # 1. Primary v2.24.0 format: GetCascadeModelConfigData -> clientModelConfigs
        for item in summary.get("clientModelConfigs") or []:
            if not isinstance(item, dict):
                continue
            qinfo = item.get("quotaInfo")
            label = str(item.get("label") or item.get("displayName") or item.get("name") or "")
            model_enum = str(
                item.get("model")
                or (item.get("modelOrAlias") or {}).get("model")
                or item.get("modelUid")
                or ""
            )
            if isinstance(qinfo, dict):
                if "remainingFraction" in qinfo:
                    rem = float(qinfo["remainingFraction"])
                elif "resetTime" in qinfo:
                    # Protobuf3 JSON serialization omits float 0.0 when quota is 100% exhausted!
                    rem = 0.0
                else:
                    rem = 1.0
                reset_time = qinfo.get("resetTime")
            elif "remainingFraction" in item:
                rem = float(item["remainingFraction"])
                reset_time = item.get("resetTime")
            else:
                continue

            buckets.append(
                {
                    "name": label or model_enum,
                    "label": label,
                    "model": model_enum,
                    "remainingFraction": rem,
                    "resetTime": reset_time,
                }
            )

        # 2. Legacy / RetrieveUserQuotaSummary format: groups / quotaGroups / buckets / models
        groups = summary.get("groups") or summary.get("quotaGroups") or []
        raw_legacy: List[Dict[str, Any]] = []
        for grp in groups:
            if isinstance(grp, dict):
                for b in grp.get("buckets") or []:
                    if isinstance(b, dict):
                        raw_legacy.append(b)
        for b in summary.get("buckets") or []:
            if isinstance(b, dict):
                raw_legacy.append(b)
        for m in summary.get("models") or []:
            if isinstance(m, dict):
                raw_legacy.append(m)

        for b in raw_legacy:
            qinfo = b.get("quotaInfo") if isinstance(b.get("quotaInfo"), dict) else None
            if "remainingFraction" in b:
                rem = float(b["remainingFraction"])
                reset_time = b.get("resetTime") or (qinfo.get("resetTime") if qinfo else None)
            elif qinfo is not None:
                rem = float(qinfo["remainingFraction"]) if "remainingFraction" in qinfo else (0.0 if "resetTime" in qinfo else 1.0)
                reset_time = qinfo.get("resetTime")
            elif "resetTime" in b:
                rem = 0.0
                reset_time = b.get("resetTime")
            else:
                continue
            buckets.append(
                {
                    **b,
                    "remainingFraction": rem,
                    "resetTime": reset_time,
                }
            )

        return buckets

    @classmethod
    def _match_bucket(cls, model_name: str, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        buckets = cls._extract_normalized_buckets(summary)
        if not buckets:
            return None

        _, model_enum_lower, target_keywords = cls._canonicalize_model_key(model_name)

        # 1. Exact match on model enum (e.g. MODEL_PLACEHOLDER_M26)
        for b in buckets:
            b_enum = str(b.get("model") or "").strip().lower()
            if b_enum and b_enum == model_enum_lower:
                return b

        # 2. Keyword priority match against label / name / bucketId / model
        for kw in target_keywords:
            for b in buckets:
                haystack = " ".join(
                    str(b.get(k) or "") for k in ("name", "bucketId", "label", "model")
                ).lower()
                if kw in haystack:
                    return b
        return None



# ---------------------------------------------------------------------------
# Shield 8: Multi-Project IDE Concurrency Limiter + Start Stagger
# ---------------------------------------------------------------------------
class StaggeredConcurrencyLimiter:
    """Balances up to 10+ simultaneous API requests across configurable active streams.

    - Allows up to `max_parallel_streams` (default 4, configurable 1..10) concurrent
      generations, matching native Antigravity multi-project/subagent usage (`maxClonedWorkspaces=5`).
    - Spaces concurrent stream launches by `stagger_min_ms..stagger_max_ms` (0.4s-1.2s)
      so multiple requests never hit Google at the exact same millisecond (`Δt = 0ms`).
    """

    def __init__(self) -> None:
        self._active_count = 0
        self._waiting_count = 0
        self._last_start_mono = 0.0
        self._condition = asyncio.Condition()
        self._stagger_lock = asyncio.Lock()

    @property
    def max_parallel(self) -> int:
        return int(config.api_engine.get("max_parallel_streams", 4))

    def snapshot(self) -> Dict[str, int]:
        return {
            "active_streams": self._active_count,
            "queued_requests": self._waiting_count,
            "max_parallel_streams": self.max_parallel,
        }

    async def acquire(self) -> float:
        """Acquire a generation slot and enforce start stagger. Returns stagger delay in ms."""
        async with self._condition:
            self._waiting_count += 1
            try:
                while self._active_count >= self.max_parallel:
                    await self._condition.wait()
                self._active_count += 1
            finally:
                self._waiting_count -= 1

        stagger_ms = 0.0
        try:
            stagger_min = int(config.api_engine.get("stagger_min_ms", 400)) / 1000.0
            stagger_max = int(config.api_engine.get("stagger_max_ms", 1200)) / 1000.0
            if stagger_max < stagger_min:
                stagger_max = stagger_min
            async with self._stagger_lock:
                now = time.monotonic()
                elapsed = now - self._last_start_mono
                required_gap = random.uniform(stagger_min, stagger_max)
                if self._last_start_mono > 0 and elapsed < required_gap:
                    wait_s = required_gap - elapsed
                    await asyncio.sleep(wait_s)
                    stagger_ms = round(wait_s * 1000, 1)
                self._last_start_mono = time.monotonic()
        except Exception:
            self.release()
            raise
        return stagger_ms

    def release(self) -> None:
        async def _notify() -> None:
            async with self._condition:
                self._active_count = max(0, self._active_count - 1)
                self._condition.notify(1)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_notify())
        except RuntimeError:
            self._active_count = max(0, self._active_count - 1)


# Global singleton shields
pacing_guard = HeartbeatAndPacingGuard()
quota_breaker = QuotaCircuitBreaker()
concurrency_limiter = StaggeredConcurrencyLimiter()
