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


class QuotaExhaustedError(Exception):
    """Raised by Shield 6 before Google is contacted when a model's quota is < threshold."""

    def __init__(
        self,
        model: str,
        remaining_fraction: float,
        threshold: float,
        reset_time: Optional[str] = None,
    ) -> None:
        self.model = model
        self.remaining_fraction = remaining_fraction
        self.threshold = threshold
        self.reset_time = reset_time
        pct = round(remaining_fraction * 100, 1)
        min_pct = round(threshold * 100, 1)
        super().__init__(
            f"Pre-flight quota protection (Shield 6): Model '{model}' has {pct}% remaining quota "
            f"(safety threshold: {min_pct}%). Returning local 429 so client fallback can switch models."
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
# Shield 2: Keyword Firewall & Official AGENTS.md System-Prompt Rule Engine
# ---------------------------------------------------------------------------
_SIGNATURE_REPLACEMENTS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bOpenClaw\b", re.IGNORECASE), "Workspace Assistant"),
    (re.compile(r"\b(?:Clawdbot|Moltbot|Clawd)\b", re.IGNORECASE), "Workspace Assistant"),
    (re.compile(r"\bHermes(?:\s+Agent)?\b", re.IGNORECASE), "Project Assistant"),
    (re.compile(r"\bcreated\s+by\s+Nous\s+Research\b", re.IGNORECASE), "configured for this workspace"),
    (re.compile(r"\bNous\s+Research\b", re.IGNORECASE), "Workspace Team"),
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


def extract_and_sanitize_messages(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    firewall_enabled: bool = True,
) -> Dict[str, Any]:
    """Separate system/developer prompts from conversation turns without [System: ...] concatenation.

    Returns:
      - ``system_instructions``: Combined sanitized system/developer rules for ``AGENTS.md``
      - ``conversation_turns``: Ordered list of ``{"role": "user"|"assistant"|"tool", "content": str}``
      - ``latest_user_message``: The sanitized user message for the current turn
      - ``firewall_hits``: List of matched signature patterns
    """
    system_parts: List[str] = []
    conversation_turns: List[Dict[str, str]] = []
    firewall_hits: List[str] = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        raw_content = msg.get("content", "")
        if isinstance(raw_content, list):
            text_chunks = []
            for item in raw_content:
                if isinstance(item, dict):
                    if item.get("type") in ("text", "input_text") and item.get("text"):
                        text_chunks.append(str(item["text"]))
                elif isinstance(item, str):
                    text_chunks.append(item)
            content_str = "\n".join(text_chunks)
        else:
            content_str = str(raw_content or "")

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
            conversation_turns.append({"role": role, "content": sanitized})

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
                "## Client Function / Tool Definitions\n"
                "When the user request requires calling one of the client tools below, "
                "respond ONLY with a valid JSON object matching:\n"
                '`{"tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "<tool_name>", "arguments": "<json_string>"}}]}`\n'
                f"{choice_hint}\n"
                f"Available client tools:\n```json\n{json.dumps(tool_specs, ensure_ascii=False)}\n```"
            )

    user_turns = [t["content"] for t in conversation_turns if t["role"] == "user" and t["content"].strip()]
    latest_user_message = user_turns[-1] if user_turns else ""

    return {
        "system_instructions": "\n\n".join(system_parts).strip(),
        "conversation_turns": conversation_turns,
        "latest_user_message": latest_user_message,
        "firewall_hits": list(dict.fromkeys(firewall_hits)),
    }


def write_workspace_agents_md(workspace_dir: Path, system_instructions: str) -> Path:
    """Write sanitized system instructions to `<workspace_dir>/AGENTS.md` (Shield 2).

    `language_server.exe` automatically walks `workspace_uris` and injects `AGENTS.md`
    via its native `<RULE[AGENTS.md]>` template (`0x3267C05`), capped at 24 KB.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    agents_md_path = workspace_dir / "AGENTS.md"

    header = (
        "# Workspace Output & Response Guidelines\n\n"
        "- Respond directly and concisely in your very first response without calling internal workspace tools (`run_command`, `view_file`, `grep_search`, `find_by_name`, `list_dir`) unless the user explicitly asks to inspect files in the current workspace.\n"
        "- When Client Function / Tool Definitions are provided below, never execute local commands yourself; instead output the requested `{\"tool_calls\": [...]}` JSON directly in your text response.\n"
        "- Do not request interactive confirmation dialogs; operate autonomously within this workspace.\n"
    )
    if system_instructions.strip():
        body = f"{header}\n## Task & Formatting Specification\n\n{system_instructions.strip()}\n"
    else:
        body = header

    encoded = body.encode("utf-8")
    if len(encoded) > MAX_AGENTS_MD_BYTES:
        encoded = encoded[:MAX_AGENTS_MD_BYTES]
        body = encoded.decode("utf-8", errors="ignore") + "\n"

    # Only write if changed to avoid unnecessary filesystem mtime churn
    try:
        if agents_md_path.exists() and agents_md_path.read_text(encoding="utf-8") == body:
            return agents_md_path
    except OSError:
        pass

    agents_md_path.write_text(body, encoding="utf-8")
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
# Shield 6: Pre-Flight Quota Circuit Breaker (For Native Hermes Fallback)
# ---------------------------------------------------------------------------
class QuotaCircuitBreaker:
    """Checks `RetrieveUserQuotaSummary` before sending prompts to Google.

    If the target model's remaining quota is below `quota_min_fraction` (default 5%),
    raises `QuotaExhaustedError` locally so the API Bridge returns an OpenAI HTTP 429
    (`model_quota_exhausted`), triggering Hermes/OpenClaw's built-in model fallback.
    """

    def __init__(self, cache_ttl_seconds: float = 30.0) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_summary: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._cached_owner_id: Optional[int] = None
        self._lock = asyncio.Lock()

    def reset_cache(self) -> None:
        self._cached_summary = None
        self._cached_at = 0.0
        self._cached_owner_id = None

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
            raise QuotaExhaustedError(
                model=model_requested or "default",
                remaining_fraction=remaining,
                threshold=threshold,
                reset_time=reset_time,
            )
        return {
            "checked": True,
            "remaining_fraction": remaining,
            "bucket": bucket_info.get("name"),
            "reset_time": reset_time,
        }

    @staticmethod
    def _match_bucket(model_name: str, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        norm = model_name.strip().lower()
        groups = summary.get("groups") or summary.get("quotaGroups") or []
        buckets: List[Dict[str, Any]] = []
        for grp in groups:
            if isinstance(grp, dict):
                for b in grp.get("buckets") or []:
                    if isinstance(b, dict):
                        buckets.append(b)
        for b in summary.get("buckets") or []:
            if isinstance(b, dict):
                buckets.append(b)
        for m in summary.get("models") or []:
            if isinstance(m, dict):
                buckets.append(m)

        if not buckets:
            return None

        target_keywords = []
        if "opus" in norm:
            target_keywords = ["opus", "claude", "m37"]
        elif "sonnet" in norm or "claude" in norm:
            target_keywords = ["sonnet", "claude", "m35"]
        elif "gpt" in norm:
            target_keywords = ["gpt", "openai"]
        elif "gemini" in norm or "flash" in norm or "pro" in norm:
            target_keywords = ["gemini-5hour", "gemini", "m47", "m37"]

        for kw in target_keywords:
            for b in buckets:
                b_name = str(
                    b.get("name") or b.get("bucketId") or b.get("label") or b.get("model") or ""
                ).lower()
                if kw in b_name and "remainingFraction" in b:
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
