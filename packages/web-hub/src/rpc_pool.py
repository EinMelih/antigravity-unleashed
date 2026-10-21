"""10-Slot Isolated Workspace & Multi-Turn Cascade Pool for Direct ConnectRPC.

Manages `ws-00` .. `ws-09` under `AntigravityApiProfile/home/workspaces/`,
provides automatic multi-turn session affinity, auto-revert when Hermes/OpenClaw
truncates or regenerates prior messages, and coordinates all 8 Anti-Ban Shields.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from src.antigravity_shields import (
    concurrency_limiter,
    extract_and_sanitize_messages,
    pacing_guard,
    quota_breaker,
    sanitize_prompt_text,
    unmask_response_text,
    write_workspace_agents_md,
)
from src.api_audit_logger import record_revert_event
from src.api_token_reader import (
    parse_generator_metadata_tokens,
    read_tokens_from_conversation_sqlite,
)
from src.config import config
from src.rpc_client import DirectConnectRPCClient


@dataclass
class TrackedConversation:
    cascade_id: str
    slot_id: str
    workspace_dir: Path
    model: str = "gemini-3.1-pro-high"
    system_hash: str = ""
    app_fingerprint: str = ""
    first_user_len: int = 0
    turn_hashes: List[str] = field(default_factory=list)
    step_offsets: List[int] = field(default_factory=list)
    last_step_count: int = 0
    native_turns: int = 0
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)


class WorkspaceSlot:
    """Represents one isolated workspace directory (`ws-00` .. `ws-09`)."""

    def __init__(self, slot_index: int, base_dir: Path) -> None:
        self.slot_index = slot_index
        self.slot_id = f"ws-{slot_index:02d}"
        self.workspace_dir = (base_dir / self.slot_id).resolve()
        self.lock = asyncio.Lock()
        self.active_cascade_id: Optional[str] = None
        self.last_used_at: float = 0.0
        self.alloc_seq: int = 0
        self._seed_workspace_files()

    def _seed_workspace_files(self) -> None:
        """Seed realistic project files for Shield 4 (`workspaceUris` & `editorState`)."""
        src_dir = self.workspace_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        readme = self.workspace_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# Workspace {self.slot_id}\n\nIsolated development workspace for automated tasks.\n",
                encoding="utf-8",
            )
        main_py = src_dir / "src" / "main.py" if False else src_dir / "main.py"
        if not main_py.exists():
            main_py.write_text(
                '"""Entry module for workspace tasks."""\n\n'
                "def main() -> None:\n"
                '    print("Workspace ready")\n\n\n'
                'if __name__ == "__main__":\n'
                "    main()\n",
                encoding="utf-8",
            )
        write_workspace_agents_md(self.workspace_dir)


def _hash_turn(role: str, content: str) -> str:
    canonical_text, _ = sanitize_prompt_text(content or "", enabled=True)
    norm = f"{role.strip().lower()}:{canonical_text.strip()}"
    return hashlib.sha256(norm.encode("utf-8", errors="ignore")).hexdigest()[:16]


def compute_app_fingerprint(
    *,
    client_ip: str = "127.0.0.1",
    source_framework: str = "",
    user_agent: str = "",
    api_key_name: str = "",
    client_session_key: str = "",
) -> str:
    """Compute a deterministic isolation fingerprint for the calling app/client/session.

    Guarantees that requests from different apps (Hermes, OpenClaw, OpenWebUI, custom apps,
    scripts, different IPs, different API keys, or different client session/user IDs)
    NEVER share a `cascade_id` or mix conversation context.
    """
    raw = "|".join(
        [
            (source_framework or "unknown").strip().lower(),
            (client_ip or "127.0.0.1").strip().lower(),
            (api_key_name or "default").strip().lower(),
            (user_agent or "").strip()[:80],
            (client_session_key or "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


class DirectRPCPool:
    """Balances up to 10 simultaneous Hermes/OpenClaw conversations across `ws-00`..`ws-09`."""

    def __init__(
        self,
        *,
        rpc_client: Optional[DirectConnectRPCClient] = None,
        base_workspaces_dir: Optional[Path] = None,
        slot_count: int = 10,
    ) -> None:
        from src.api_profile import resolve_api_profile_home

        self.rpc_client = rpc_client or DirectConnectRPCClient()
        self.profile_home = resolve_api_profile_home()
        self.app_data_dir = self.profile_home / ".gemini/antigravity-api"
        self.base_workspaces_dir = base_workspaces_dir or (
            self.profile_home / "workspaces"
        )
        self.slot_count = max(1, min(32, slot_count))
        self.slots: List[WorkspaceSlot] = [
            WorkspaceSlot(i, self.base_workspaces_dir) for i in range(self.slot_count)
        ]
        self._conversations: Dict[str, TrackedConversation] = {}
        self._pool_lock = asyncio.Lock()

    def status_snapshot(self) -> Dict[str, Any]:
        busy_slots = sum(1 for s in self.slots if s.lock.locked())
        return {
            "engine_mode": config.api_mode,
            "slot_count": len(self.slots),
            "busy_slots": busy_slots,
            "tracked_conversations": len(self._conversations),
            "concurrency": concurrency_limiter.snapshot(),
            "shields": config.api_engine,
        }

    async def _resolve_slot_and_session(
        self,
        conversation_turns: List[Dict[str, str]],
        *,
        system_instructions: str = "",
        explicit_conversation_id: Optional[str] = None,
        force_new_chat: bool = False,
        requested_model: Optional[str] = None,
        client_ip: str = "127.0.0.1",
        app_fingerprint: str = "",
    ) -> Tuple[WorkspaceSlot, TrackedConversation, Optional[Dict[str, Any]]]:
        """Find or allocate a workspace slot + `TrackedConversation`, performing auto-revert if needed.

        5-Layer Multi-App & Multi-Chat Context Isolation:
          1. App/Client Isolation (`app_fingerprint`): Different apps (Hermes, OpenClaw, OpenWebUI,
             custom scripts), different IPs, API keys, User-Agents, or `user`/`session_id` fields
             never share a `cascade_id`.
          2. System & Tool Schema Isolation (`system_hash`): Different system prompts or tool
             definitions never share a `cascade_id`.
          3. Single-Turn Guard (`len(turns) == 1`): Every 1-turn request always creates a brand-new
             `cascade_id` and never attaches to an existing chat.
          4. Two-Pass Newest-First Matching + Greeting Anti-Collision Guard:
             - Pass 1 checks ONLY exact prefix matches (`conv.turn_hashes == incoming_prefix`),
               ordered newest-first (`updated_at DESC`), so a new chat with a short greeting (`"hi"`)
               never triggers an accidental auto-revert on an older longer chat.
             - Pass 2 (Extended prefix for mid-chat Codex switch / Truncated prefix for Edit/Revert)
               only runs if Pass 1 found no exact match, and enforces a Greeting Guard: if only
               1 exchange (`overlap == 2`) overlaps, the first user prompt must be substantive
               (`first_user_len >= 16`) and recent (`<= 600s`), preventing two `"hi"` chats from colliding.
          5. Idle Session Expiry (`1800s`): Conversations idle for > 30 minutes are never prefix-matched.
        """
        req_system_hash = _hash_turn("system", system_instructions)
        effective_app_fp = app_fingerprint or compute_app_fingerprint(client_ip=client_ip)
        user_assistant_hashes = [
            _hash_turn(t["role"], t["content"]) for t in conversation_turns
        ]
        first_user_content = next(
            (str(t.get("content") or "").strip() for t in conversation_turns if t.get("role") == "user"),
            "",
        )
        req_first_user_len = len(first_user_content)
        is_trivial_greeting = first_user_content.lower().rstrip("!.? ") in {
            "hi",
            "hey",
            "hallo",
            "hello",
            "moin",
            "yo",
            "servus",
            "guten tag",
        }
        max_turns = int(config.api_engine.get("max_turns_per_session", 20))
        revert_info: Optional[Dict[str, Any]] = None
        now_mono = time.monotonic()
        idle_ttl_sec = 1800.0

        async with self._pool_lock:
            matched: Optional[TrackedConversation] = None

            # 1. Explicit conversation_id match
            if explicit_conversation_id and explicit_conversation_id in self._conversations:
                matched = self._conversations[explicit_conversation_id]

            # 2. 5-Layer Prefix Hash Affinity Match
            if matched is None and not force_new_chat and len(user_assistant_hashes) > 1:
                incoming_prefix = user_assistant_hashes[:-1]
                # Sort candidate conversations newest-first so active chats always take precedence
                candidates: List[TrackedConversation] = []
                for conv in sorted(
                    self._conversations.values(),
                    key=lambda c: c.updated_at,
                    reverse=True,
                ):
                    # Layer 1: App/Client Fingerprint Isolation
                    if conv.app_fingerprint and conv.app_fingerprint != effective_app_fp:
                        continue
                    # Layer 2: System Prompt & Tool Schema Isolation
                    if conv.system_hash != req_system_hash:
                        continue
                    # Layer 5: Idle Expiry (30 min)
                    if (now_mono - conv.updated_at) > idle_ttl_sec:
                        continue
                    slot_obj = self._get_slot_by_id(conv.slot_id)
                    if slot_obj.lock.locked():
                        continue
                    if conv.native_turns >= max_turns:
                        continue
                    candidates.append(conv)

                # Pass 1: Exact prefix match (normal next turn of the exact same chat)
                for conv in candidates:
                    if conv.turn_hashes == incoming_prefix:
                        matched = conv
                        break

                # Pass 2: Extended prefix (mid-chat model switch) or Truncated prefix (Edit/Revert)
                if matched is None:
                    best_match: Optional[TrackedConversation] = None
                    best_overlap = 0
                    for conv in candidates:
                        # Extended prefix match (e.g. user switched to Codex for 1-2 turns and switched back)
                        if (
                            len(conv.turn_hashes) >= 2
                            and len(incoming_prefix) > len(conv.turn_hashes)
                            and incoming_prefix[: len(conv.turn_hashes)] == conv.turn_hashes
                        ):
                            overlap = len(conv.turn_hashes)
                            # Greeting Anti-Collision Guard for 1-turn ("hi") chats
                            if overlap < 4 and (
                                is_trivial_greeting
                                or (now_mono - conv.updated_at) > 600.0
                            ):
                                continue
                            if overlap > best_overlap:
                                best_overlap = overlap
                                best_match = conv
                            continue

                        # Truncated prefix match (User clicked Edit / Retry / Revert — requires >= 2 turns)
                        common = 0
                        for h_old, h_new in zip(conv.turn_hashes, incoming_prefix):
                            if h_old == h_new:
                                common += 1
                            else:
                                break
                        if common >= 2 and common == len(incoming_prefix) and common < len(conv.turn_hashes):
                            # Greeting Anti-Collision Guard: never auto-revert an older chat on a 1-turn "hi"
                            if common < 4 and (
                                is_trivial_greeting
                                or (now_mono - conv.updated_at) > 600.0
                            ):
                                continue
                            if common > best_overlap:
                                best_overlap = common
                                best_match = conv
                    matched = best_match

            if matched is not None:
                slot = self._get_slot_by_id(matched.slot_id)
                # Check if incoming history is shorter than recorded history -> Auto-Revert!
                incoming_prior = user_assistant_hashes[:-1]
                if (
                    incoming_prior
                    and len(incoming_prior) < len(matched.turn_hashes)
                    and matched.turn_hashes[: len(incoming_prior)] == incoming_prior
                ):
                    turn_idx = len(incoming_prior)
                    target_step = (
                        matched.step_offsets[turn_idx]
                        if turn_idx < len(matched.step_offsets)
                        else max(0, matched.last_step_count - 2)
                    )
                    prev_steps = matched.last_step_count
                    try:
                        await self.rpc_client.revert_to_cascade_step(
                            matched.cascade_id,
                            target_step,
                            model=requested_model or matched.model,
                            conversation_only=True,
                        )
                    except Exception as rev_err:
                        print(f"[RPC Pool] Auto-revert warning: {rev_err}", flush=True)
                    matched.turn_hashes = matched.turn_hashes[:turn_idx]
                    matched.step_offsets = matched.step_offsets[:turn_idx]
                    matched.last_step_count = target_step
                    revert_info = record_revert_event(
                        conversation_id=matched.cascade_id,
                        target_step_index=target_step,
                        previous_step_count=prev_steps,
                        reason="auto_prefix_truncation_revert",
                        triggered_by_ip=client_ip,
                        engine_mode="rpc",
                    )
                return slot, matched, revert_info

            # 3. Allocate least-recently-used unlocked workspace slot
            self._alloc_counter = getattr(self, "_alloc_counter", 0) + 1
            free_slots = [s for s in self.slots if not s.lock.locked()]
            if free_slots:
                slot = min(free_slots, key=lambda s: (s.alloc_seq, s.last_used_at, s.slot_index))
            else:
                slot = min(self.slots, key=lambda s: (s.alloc_seq, s.last_used_at, s.slot_index))

            slot.alloc_seq = self._alloc_counter
            slot.last_used_at = time.monotonic()

        # Start a new cascade session on this slot
        cascade_id = await self.rpc_client.start_cascade(
            slot.workspace_dir, model=requested_model
        )
        tracked = TrackedConversation(
            cascade_id=cascade_id,
            slot_id=slot.slot_id,
            workspace_dir=slot.workspace_dir,
            model=requested_model or "gemini-3.1-pro-high",
            system_hash=req_system_hash,
            app_fingerprint=effective_app_fp,
            first_user_len=req_first_user_len,
        )
        evicted_ids: List[str] = []
        max_tracked = max(self.slot_count * 2, 20)
        async with self._pool_lock:
            self._conversations[cascade_id] = tracked
            slot.active_cascade_id = cascade_id
            if len(self._conversations) > max_tracked:
                active_slot_ids = {s.active_cascade_id for s in self.slots if s.active_cascade_id}
                candidates = sorted(
                    (c for cid, c in self._conversations.items() if cid not in active_slot_ids and cid != cascade_id),
                    key=lambda c: c.updated_at,
                )
                while len(self._conversations) > max_tracked and candidates:
                    oldest = candidates.pop(0)
                    self._conversations.pop(oldest.cascade_id, None)
                    evicted_ids.append(oldest.cascade_id)

        for old_id in evicted_ids:
            asyncio.create_task(self._cleanup_evicted_cascade(old_id))

        return slot, tracked, None

    async def _cleanup_evicted_cascade(self, cascade_id: str) -> None:
        """Delete an evicted cascade via ConnectRPC and remove its local .pb trajectory file."""
        try:
            await self.rpc_client.delete_cascade_trajectory(cascade_id)
        except Exception:
            pass
        for sub in (".gemini/antigravity/conversations", ".gemini/antigravity-api/conversations"):
            pb_file = self.profile_home / sub / f"{cascade_id}.pb"
            try:
                if pb_file.exists():
                    pb_file.unlink()
            except OSError:
                pass


    def _get_slot_by_id(self, slot_id: str) -> WorkspaceSlot:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return self.slots[0]

    @staticmethod
    def _parse_possible_tool_calls(response_text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Detect if the model returned a structured `tool_calls` JSON block for Hermes/OpenClaw.

        Handles raw JSON, Markdown code fences (```json ... ``` or ``` ... ```),
        surrounding explanatory prose, and both standard `{"tool_calls": [...]}`
        and single-call `{"tool_call": {...}}` payloads.
        """
        raw = response_text or ""
        stripped = raw.strip()
        if not stripped or ('"tool_calls"' not in stripped and '"tool_call"' not in stripped):
            return response_text, []

        candidates: List[Tuple[str, str]] = []
        # 1. Check Markdown fenced blocks (```json ... ``` or ``` ... ```)
        for match in re.finditer(r"```(?:json|JSON)?\s*([\s\S]*?)```", stripped):
            inner = match.group(1).strip()
            if inner.startswith("{"):
                prefix = stripped[: match.start()].strip()
                candidates.append((inner, prefix))

        # 2. Full string if it is a JSON object
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates.append((stripped, ""))

        # 3. Embedded JSON object extracted via raw_decode starting at any '{' before "tool_call"
        decoder = json.JSONDecoder()
        for brace_match in re.finditer(r"\{", stripped):
            start_idx = brace_match.start()
            if '"tool_call' not in stripped[start_idx:]:
                break
            try:
                obj, _ = decoder.raw_decode(stripped[start_idx:])
                if isinstance(obj, dict) and ("tool_calls" in obj or "tool_call" in obj):
                    prefix = stripped[:start_idx].strip()
                    candidates.append((json.dumps(obj, ensure_ascii=False), prefix))
                    break
            except Exception:
                continue

        for candidate_json, prefix_text in candidates:
            try:
                parsed = json.loads(candidate_json)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            raw_list = parsed.get("tool_calls")
            if isinstance(parsed.get("tool_call"), dict) and not isinstance(raw_list, list):
                raw_list = [parsed["tool_call"]]
            if not isinstance(raw_list, list):
                continue

            normalized_calls: List[Dict[str, Any]] = []
            for idx, tc in enumerate(raw_list):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                fn_name = str(fn.get("name") or tc.get("name") or "").strip()
                if not fn_name:
                    continue
                args = fn.get("arguments", tc.get("arguments", "{}"))
                if args is None:
                    args = "{}"
                elif not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                normalized_calls.append(
                    {
                        "id": str(tc.get("id") or f"call_{idx + 1}"),
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": args,
                        },
                    }
                )
            if normalized_calls:
                return prefix_text, normalized_calls

        return response_text, []


    async def execute_chat_completion(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        explicit_conversation_id: Optional[str] = None,
        force_new_chat: bool = False,
        timeout: float = 120.0,
        client_ip: str = "127.0.0.1",
        app_fingerprint: str = "",
    ) -> Dict[str, Any]:
        """Execute a complete non-streaming chat turn via Direct ConnectRPC with all 8 Shields."""
        firewall_enabled = bool(config.api_engine.get("keyword_firewall_enabled", True))
        sanitized = extract_and_sanitize_messages(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            firewall_enabled=firewall_enabled,
        )
        user_message = sanitized["latest_user_message"]
        system_instructions = sanitized["system_instructions"]
        turns = sanitized["conversation_turns"]

        # Shield 3: Local 0ms Heartbeat Interceptor
        is_hb, hb_reply = pacing_guard.is_heartbeat_prompt(user_message, system_instructions)
        if is_hb:
            return {
                "response": hb_reply,
                "tool_calls": [],
                "conversation_id": explicit_conversation_id or "heartbeat-local",
                "workspace_slot": "local-shield-3",
                "model_actual": model or "antigravity",
                "token_metrics": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cached_tokens": 0,
                    "thinking_tokens": 0,
                    "total_tokens": 0,
                    "context_used_tokens": 0,
                    "context_max_tokens": 200_000,
                    "token_source": "heartbeat_shortcircuit",
                    "estimated": False,
                },
                "shield_metadata": {
                    "heartbeat_intercepted": True,
                    "firewall_hits": sanitized["firewall_hits"],
                },
            }

        # Shield 6: Pre-Flight Quota Check (raises QuotaExhaustedError -> HTTP 429 for Hermes fallback)
        quota_info = await quota_breaker.check_model_quota(
            model, self.rpc_client.retrieve_user_quota_summary
        )

        # Shield 8: Acquire Multi-Project Concurrency Slot + Staggered Launch
        stagger_ms = await concurrency_limiter.acquire()
        try:
            slot, tracked, revert_info = await self._resolve_slot_and_session(
                turns,
                system_instructions=system_instructions,
                explicit_conversation_id=explicit_conversation_id,
                force_new_chat=force_new_chat,
                requested_model=model,
                client_ip=client_ip,
                app_fingerprint=app_fingerprint,
            )
            async with slot.lock:
                # Shield 3: Smart Adaptive Pacing
                pacing_ms = await pacing_guard.apply_adaptive_pacing(slot.slot_id)

                # Ensure no AGENTS.md file exists in the workspace slot (zero per-request rule bloat)
                write_workspace_agents_md(slot.workspace_dir)

                if tracked.last_step_count == 0 and not tracked.turn_hashes:
                    baseline_count = 0
                elif revert_info is None and tracked.last_step_count > 0:
                    baseline_count = tracked.last_step_count
                else:
                    baseline_steps = await self.rpc_client.get_trajectory_steps(
                        tracked.cascade_id, step_offset=0
                    )
                    baseline_count = len(baseline_steps)

                unrecorded_prior = (
                    turns[len(tracked.turn_hashes) : -1]
                    if len(turns) - 1 > len(tracked.turn_hashes)
                    else []
                )
                effective_user_message = user_message
                if unrecorded_prior:
                    prior_lines = [
                        f"{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '').strip()}"
                        for t in unrecorded_prior
                        if str(t.get("content") or "").strip()
                    ]
                    if prior_lines:
                        effective_user_message = (
                            "[Prior Conversation Context]:\n"
                            + "\n".join(prior_lines)
                            + "\n\n[Current User Message]:\n"
                            + user_message
                        )
                if system_instructions.strip() and not tracked.turn_hashes:
                    effective_user_message = f"{system_instructions.strip()}\n\n{effective_user_message}"

                user_media = list(sanitized.get("latest_user_media") or [])
                if not user_media and unrecorded_prior:
                    for pt in unrecorded_prior:
                        if pt.get("media"):
                            user_media.extend(pt["media"])
                await self.rpc_client.send_user_cascade_message(
                    tracked.cascade_id,
                    effective_user_message,
                    slot.workspace_dir,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    blocking=False,
                    **({"media": user_media} if user_media else {}),
                )

                thinking_chunks: List[str] = []
                chunks: List[str] = []
                if hasattr(self.rpc_client, "stream_response_events"):
                    async for kind, delta in self.rpc_client.stream_response_events(
                        tracked.cascade_id, baseline_count, timeout=timeout
                    ):
                        if kind == "thinking":
                            thinking_chunks.append(delta)
                        else:
                            chunks.append(delta)
                else:
                    async for delta in self.rpc_client.stream_response_deltas(
                        tracked.cascade_id, baseline_count, timeout=timeout
                    ):
                        chunks.append(delta)

                thinking_text = "".join(thinking_chunks).strip()
                response_text = "".join(chunks).strip()
                cached_step_count = getattr(self.rpc_client, "_last_step_counts", {}).pop(
                    tracked.cascade_id, None
                )
                cached_final_steps = getattr(self.rpc_client, "_last_final_steps", {}).pop(
                    tracked.cascade_id, None
                )
                if cached_step_count is not None and response_text:
                    final_step_count = cached_step_count
                else:
                    after_steps = await self.rpc_client.get_trajectory_steps(
                        tracked.cascade_id, step_offset=0
                    )
                    final_step_count = len(after_steps)
                    tail_steps = after_steps[baseline_count:] if after_steps else (cached_final_steps or [])
                    if tail_steps and (not response_text or not thinking_text):
                        if hasattr(self.rpc_client, "extract_planner_response_state"):
                            ext_thinking, ext_text, _ = self.rpc_client.extract_planner_response_state(
                                tail_steps
                            )
                            if not thinking_text and ext_thinking:
                                thinking_text = ext_thinking
                            if not response_text and ext_text:
                                response_text = ext_text
                        elif not response_text:
                            response_text, _ = self.rpc_client.extract_planner_response_text(
                                tail_steps
                            )

                thinking_text = unmask_response_text(
                    thinking_text, firewall_hits=sanitized["firewall_hits"]
                )
                response_text = unmask_response_text(
                    response_text, firewall_hits=sanitized["firewall_hits"]
                )

                clean_content, tool_calls = self._parse_possible_tool_calls(response_text)
                clean_content = unmask_response_text(
                    clean_content, firewall_hits=sanitized["firewall_hits"]
                )
                canonical_assistant_text = (
                    json.dumps({"tool_calls": tool_calls}, ensure_ascii=False)
                    if (tool_calls and not clean_content.strip())
                    else (clean_content or response_text)
                )

                # Record turn hashes and step offsets for future multi-turn / auto-revert
                for prior_turn in unrecorded_prior:
                    tracked.step_offsets.append(baseline_count)
                    tracked.turn_hashes.append(
                        _hash_turn(prior_turn.get("role", "user"), prior_turn.get("content", ""))
                    )
                tracked.step_offsets.append(baseline_count)
                tracked.turn_hashes.append(_hash_turn("user", user_message))
                tracked.step_offsets.append(final_step_count)
                tracked.turn_hashes.append(_hash_turn("assistant", canonical_assistant_text))
                tracked.last_step_count = final_step_count
                tracked.native_turns += 1
                tracked.updated_at = time.monotonic()
                slot.last_used_at = time.monotonic()
                pacing_guard.mark_slot_completed(slot.slot_id)

                # Read exact token & context window metadata
                canonical_model_id, native_label = (
                    self.rpc_client.resolve_canonical_model_id(
                        model, reasoning_effort=reasoning_effort
                    )
                    if hasattr(self.rpc_client, "resolve_canonical_model_id")
                    else (model or tracked.model, model or tracked.model)
                )
                gen_meta = await self.rpc_client.get_generator_metadata(tracked.cascade_id)
                if gen_meta:
                    token_metrics = parse_generator_metadata_tokens(
                        gen_meta,
                        prompt_text=user_message,
                        response_text=response_text,
                        requested_model=canonical_model_id,
                    )
                else:
                    token_metrics = read_tokens_from_conversation_sqlite(
                        self.app_data_dir,
                        tracked.cascade_id,
                        prompt_text=user_message,
                        response_text=response_text,
                        requested_model=canonical_model_id,
                    )

                return {
                    "response": clean_content,
                    "raw_response": response_text,
                    "thinking": thinking_text,
                    "tool_calls": tool_calls,
                    "conversation_id": tracked.cascade_id,
                    "workspace_slot": slot.slot_id,
                    "model_actual": canonical_model_id,
                    "native_model": native_label,
                    "token_metrics": token_metrics,
                    "system_prompt": system_instructions,
                    "user_prompt": user_message,
                    "shield_metadata": {
                        "firewall_hits": sanitized["firewall_hits"],
                        "stagger_ms": stagger_ms,
                        "pacing_ms": pacing_ms,
                        "quota": quota_info,
                        "auto_revert": revert_info,
                    },
                }
        finally:
            concurrency_limiter.release()

    async def execute_chat_streaming(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        explicit_conversation_id: Optional[str] = None,
        force_new_chat: bool = False,
        timeout: float = 120.0,
        client_ip: str = "127.0.0.1",
        app_fingerprint: str = "",
        state_out: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Any, None]:
        """Stream live deltas via Direct ConnectRPC with all 8 Shields."""
        out = state_out if state_out is not None else {}
        firewall_enabled = bool(config.api_engine.get("keyword_firewall_enabled", True))
        sanitized = extract_and_sanitize_messages(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            firewall_enabled=firewall_enabled,
        )
        user_message = sanitized["latest_user_message"]
        system_instructions = sanitized["system_instructions"]
        turns = sanitized["conversation_turns"]
        out["system_prompt"] = system_instructions
        out["user_prompt"] = user_message

        # Shield 3: Local 0ms Heartbeat Interceptor
        is_hb, hb_reply = pacing_guard.is_heartbeat_prompt(user_message, system_instructions)
        if is_hb:
            out["conversation_id"] = explicit_conversation_id or "heartbeat-local"
            out["workspace_slot"] = "local-shield-3"
            out["token_metrics"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cached_tokens": 0,
                "thinking_tokens": 0,
                "total_tokens": 0,
                "context_used_tokens": 0,
                "context_max_tokens": 200_000,
                "token_source": "heartbeat_shortcircuit",
                "estimated": False,
            }
            out["shield_metadata"] = {"heartbeat_intercepted": True}
            yield hb_reply
            return

        # Shield 6: Pre-Flight Quota Check
        quota_info = await quota_breaker.check_model_quota(
            model, self.rpc_client.retrieve_user_quota_summary
        )

        # Shield 8: Concurrency + Stagger
        stagger_ms = await concurrency_limiter.acquire()
        try:
            slot, tracked, revert_info = await self._resolve_slot_and_session(
                turns,
                system_instructions=system_instructions,
                explicit_conversation_id=explicit_conversation_id,
                force_new_chat=force_new_chat,
                requested_model=model,
                client_ip=client_ip,
                app_fingerprint=app_fingerprint,
            )
            out["conversation_id"] = tracked.cascade_id
            out["workspace_slot"] = slot.slot_id
            async with slot.lock:
                pacing_ms = await pacing_guard.apply_adaptive_pacing(slot.slot_id)
                write_workspace_agents_md(slot.workspace_dir)

                if tracked.last_step_count == 0 and not tracked.turn_hashes:
                    baseline_count = 0
                elif revert_info is None and tracked.last_step_count > 0:
                    baseline_count = tracked.last_step_count
                else:
                    baseline_steps = await self.rpc_client.get_trajectory_steps(
                        tracked.cascade_id, step_offset=0
                    )
                    baseline_count = len(baseline_steps)

                unrecorded_prior = (
                    turns[len(tracked.turn_hashes) : -1]
                    if len(turns) - 1 > len(tracked.turn_hashes)
                    else []
                )
                effective_user_message = user_message
                if unrecorded_prior:
                    prior_lines = [
                        f"{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '').strip()}"
                        for t in unrecorded_prior
                        if str(t.get("content") or "").strip()
                    ]
                    if prior_lines:
                        effective_user_message = (
                            "[Prior Conversation Context]:\n"
                            + "\n".join(prior_lines)
                            + "\n\n[Current User Message]:\n"
                            + user_message
                        )
                if system_instructions.strip() and not tracked.turn_hashes:
                    effective_user_message = f"{system_instructions.strip()}\n\n{effective_user_message}"

                user_media = list(sanitized.get("latest_user_media") or [])
                if not user_media and unrecorded_prior:
                    for pt in unrecorded_prior:
                        if pt.get("media"):
                            user_media.extend(pt["media"])
                await self.rpc_client.send_user_cascade_message(
                    tracked.cascade_id,
                    effective_user_message,
                    slot.workspace_dir,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    blocking=False,
                    **({"media": user_media} if user_media else {}),
                )

                collected_thinking: List[str] = []
                collected: List[str] = []
                emitted_unmasked_len = 0
                buffered_for_tools = False
                try:
                    if hasattr(self.rpc_client, "stream_response_events"):
                        async for kind, delta in self.rpc_client.stream_response_events(
                            tracked.cascade_id, baseline_count, timeout=timeout
                        ):
                            if kind == "thinking":
                                unmasked_t = unmask_response_text(
                                    delta, firewall_hits=sanitized["firewall_hits"]
                                )
                                if unmasked_t:
                                    collected_thinking.append(unmasked_t)
                                    out["thinking"] = "".join(collected_thinking)
                                    yield {"type": "thinking", "delta": unmasked_t}
                            else:
                                collected.append(delta)
                                if not buffered_for_tools:
                                    joined_raw = "".join(collected)
                                    stripped_raw = joined_raw.lstrip()
                                    if stripped_raw.startswith(("{", "```")) and (
                                        len(stripped_raw) < 48 or '"tool_call' in stripped_raw
                                    ):
                                        if '"tool_call' in stripped_raw:
                                            buffered_for_tools = True
                                    else:
                                        unmasked_so_far = unmask_response_text(
                                            joined_raw, firewall_hits=sanitized["firewall_hits"]
                                        )
                                        # Hold back trailing partial prefix so 'Project Assistant' unmasks cleanly
                                        safe_end = len(unmasked_so_far)
                                        for suffix in ("der Project", "der Project ", "Project", "Project ", "der Workspace", "der Workspace ", "Workspace", "Workspace "):
                                            if unmasked_so_far.endswith(suffix):
                                                safe_end = len(unmasked_so_far) - len(suffix)
                                                break
                                        if safe_end > emitted_unmasked_len:
                                            out_delta = unmasked_so_far[emitted_unmasked_len:safe_end]
                                            emitted_unmasked_len = safe_end
                                            yield out_delta
                    else:
                        async for delta in self.rpc_client.stream_response_deltas(
                            tracked.cascade_id, baseline_count, timeout=timeout
                        ):
                            collected.append(delta)
                            if not buffered_for_tools:
                                joined_so_far = "".join(collected).lstrip()
                                if joined_so_far.startswith(("{", "```")) and '"tool_call' in joined_so_far:
                                    buffered_for_tools = True
                                else:
                                    yield unmask_response_text(
                                        delta, firewall_hits=sanitized["firewall_hits"]
                                    )
                except asyncio.CancelledError:
                    await self.rpc_client.cancel_cascade_invocation(tracked.cascade_id)
                    raise

                full_text = unmask_response_text(
                    "".join(collected).strip(), firewall_hits=sanitized["firewall_hits"]
                )
                cleaned_text, parsed_tool_calls = self._parse_possible_tool_calls(full_text)
                cleaned_text = unmask_response_text(
                    cleaned_text, firewall_hits=sanitized["firewall_hits"]
                )
                if parsed_tool_calls:
                    out["tool_calls"] = parsed_tool_calls
                    if buffered_for_tools and cleaned_text:
                        yield cleaned_text
                elif buffered_for_tools and full_text:
                    yield full_text
                elif not buffered_for_tools:
                    full_unmasked_stream = unmask_response_text(
                        "".join(collected), firewall_hits=sanitized["firewall_hits"]
                    )
                    if len(full_unmasked_stream) > emitted_unmasked_len:
                        yield full_unmasked_stream[emitted_unmasked_len:]

                canonical_assistant_text = (
                    json.dumps({"tool_calls": parsed_tool_calls}, ensure_ascii=False)
                    if (parsed_tool_calls and not cleaned_text.strip())
                    else (cleaned_text or full_text)
                )

                cached_step_count = getattr(self.rpc_client, "_last_step_counts", {}).pop(
                    tracked.cascade_id, None
                )
                getattr(self.rpc_client, "_last_final_steps", {}).pop(
                    tracked.cascade_id, None
                )
                if cached_step_count is not None:
                    final_step_count = cached_step_count
                else:
                    after_steps = await self.rpc_client.get_trajectory_steps(
                        tracked.cascade_id, step_offset=0
                    )
                    final_step_count = len(after_steps)
                for prior_turn in unrecorded_prior:
                    tracked.step_offsets.append(baseline_count)
                    tracked.turn_hashes.append(
                        _hash_turn(prior_turn.get("role", "user"), prior_turn.get("content", ""))
                    )
                tracked.step_offsets.append(baseline_count)
                tracked.turn_hashes.append(_hash_turn("user", user_message))
                tracked.step_offsets.append(final_step_count)
                tracked.turn_hashes.append(_hash_turn("assistant", canonical_assistant_text))
                tracked.last_step_count = final_step_count
                tracked.native_turns += 1
                tracked.updated_at = time.monotonic()
                slot.last_used_at = time.monotonic()
                pacing_guard.mark_slot_completed(slot.slot_id)

                canonical_model_id, native_label = (
                    self.rpc_client.resolve_canonical_model_id(
                        model, reasoning_effort=reasoning_effort
                    )
                    if hasattr(self.rpc_client, "resolve_canonical_model_id")
                    else (model or tracked.model, model or tracked.model)
                )
                gen_meta = await self.rpc_client.get_generator_metadata(tracked.cascade_id)
                token_metrics = parse_generator_metadata_tokens(
                    gen_meta,
                    prompt_text=user_message,
                    response_text=full_text,
                    requested_model=canonical_model_id,
                )
                out["token_metrics"] = token_metrics
                out["model_actual"] = canonical_model_id
                out["native_model"] = native_label
                out["shield_metadata"] = {
                    "firewall_hits": sanitized["firewall_hits"],
                    "stagger_ms": stagger_ms,
                    "pacing_ms": pacing_ms,
                    "quota": quota_info,
                    "auto_revert": revert_info,
                }
        finally:
            concurrency_limiter.release()


    async def revert_conversation(
        self,
        conversation_id: str,
        *,
        steps_back: int = 1,
        target_step_index: Optional[int] = None,
        triggered_by_ip: str = "127.0.0.1",
        reason: str = "manual_api_revert",
    ) -> Dict[str, Any]:
        """Explicitly revert a conversation ('Zurück zur vorherigen Nachricht') via `RevertToCascadeStep`."""
        steps = await self.rpc_client.get_trajectory_steps(conversation_id, step_offset=0)
        current_count = len(steps)

        tracked = self._conversations.get(conversation_id)
        if target_step_index is None:
            if tracked and tracked.step_offsets:
                idx = max(0, len(tracked.step_offsets) - (steps_back * 2))
                target_step_index = (
                    tracked.step_offsets[idx] if idx < len(tracked.step_offsets) else 0
                )
            else:
                target_step_index = max(0, current_count - (steps_back * 2))

        await self.rpc_client.revert_to_cascade_step(
            conversation_id,
            target_step_index,
            model=tracked.model if tracked else None,
            conversation_only=True,
        )

        if tracked:
            while tracked.step_offsets and tracked.step_offsets[-1] > target_step_index:
                tracked.step_offsets.pop()
                if tracked.turn_hashes:
                    tracked.turn_hashes.pop()
            tracked.last_step_count = target_step_index

        event = record_revert_event(
            conversation_id=conversation_id,
            target_step_index=target_step_index,
            previous_step_count=current_count,
            reason=reason,
            triggered_by_ip=triggered_by_ip,
            engine_mode="rpc",
        )
        return {
            "status": "reverted",
            "conversation_id": conversation_id,
            "previous_step_count": current_count,
            "reverted_to_step": target_step_index,
            "event": event,
        }


# Global singleton pool
rpc_pool = DirectRPCPool()
