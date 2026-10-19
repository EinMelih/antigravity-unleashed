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
    turn_hashes: List[str] = field(default_factory=list)
    step_offsets: List[int] = field(default_factory=list)
    last_step_count: int = 0
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
        main_py = src_dir / "main.py"
        if not main_py.exists():
            main_py.write_text(
                '"""Entry module for workspace tasks."""\n\n'
                "def main() -> None:\n"
                '    print("Workspace ready")\n\n\n'
                'if __name__ == "__main__":\n'
                "    main()\n",
                encoding="utf-8",
            )
        agents_md = self.workspace_dir / "AGENTS.md"
        if not agents_md.exists():
            write_workspace_agents_md(self.workspace_dir, "")


def _hash_turn(role: str, content: str) -> str:
    canonical_text, _ = sanitize_prompt_text(content or "", enabled=True)
    norm = f"{role.strip().lower()}:{canonical_text.strip()}"
    return hashlib.sha256(norm.encode("utf-8", errors="ignore")).hexdigest()[:16]


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
        explicit_conversation_id: Optional[str] = None,
        force_new_chat: bool = False,
        requested_model: Optional[str] = None,
        client_ip: str = "127.0.0.1",
    ) -> Tuple[WorkspaceSlot, TrackedConversation, Optional[Dict[str, Any]]]:
        """Find or allocate a workspace slot + `TrackedConversation`, performing auto-revert if needed."""
        user_assistant_hashes = [
            _hash_turn(t["role"], t["content"]) for t in conversation_turns
        ]
        max_turns = int(config.api_engine.get("max_turns_per_session", 20))
        revert_info: Optional[Dict[str, Any]] = None

        async with self._pool_lock:
            matched: Optional[TrackedConversation] = None

            # 1. Explicit conversation_id match
            if explicit_conversation_id and explicit_conversation_id in self._conversations:
                matched = self._conversations[explicit_conversation_id]

            # 2. Prefix hash affinity match (for Hermes / OpenClaw multi-turn arrays)
            if matched is None and not force_new_chat and len(user_assistant_hashes) > 1:
                incoming_prefix = user_assistant_hashes[:-1]
                best_match: Optional[TrackedConversation] = None
                best_overlap = 0
                for conv in self._conversations.values():
                    slot_obj = self._get_slot_by_id(conv.slot_id)
                    if slot_obj.lock.locked():
                        continue
                    if len(conv.turn_hashes) >= max_turns * 2:
                        continue
                    # Exact prefix match (normal next turn)
                    if conv.turn_hashes == incoming_prefix:
                        best_match = conv
                        break
                    # Truncated prefix match (User clicked Edit / Retry / Revert in Hermes!)
                    common = 0
                    for h_old, h_new in zip(conv.turn_hashes, incoming_prefix):
                        if h_old == h_new:
                            common += 1
                        else:
                            break
                    if common > 0 and common == len(incoming_prefix) and common < len(conv.turn_hashes):
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
            free_slots = [s for s in self.slots if not s.lock.locked()]
            if free_slots:
                slot = min(free_slots, key=lambda s: s.last_used_at)
            else:
                slot = min(self.slots, key=lambda s: s.last_used_at)

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
        )
        async with self._pool_lock:
            self._conversations[cascade_id] = tracked
            slot.active_cascade_id = cascade_id
        return slot, tracked, None

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
                explicit_conversation_id=explicit_conversation_id,
                force_new_chat=force_new_chat,
                requested_model=model,
                client_ip=client_ip,
            )
            async with slot.lock:
                # Shield 3: Smart Adaptive Pacing
                pacing_ms = await pacing_guard.apply_adaptive_pacing(slot.slot_id)

                # Shield 2: Write sanitized system instructions to `<slot>/AGENTS.md`
                write_workspace_agents_md(slot.workspace_dir, system_instructions)

                baseline_steps = await self.rpc_client.get_trajectory_steps(
                    tracked.cascade_id, step_offset=0
                )
                baseline_count = len(baseline_steps)

                await self.rpc_client.send_user_cascade_message(
                    tracked.cascade_id,
                    user_message,
                    slot.workspace_dir,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    blocking=False,
                )

                chunks: List[str] = []
                async for delta in self.rpc_client.stream_response_deltas(
                    tracked.cascade_id, baseline_count, timeout=timeout
                ):
                    chunks.append(delta)

                response_text = "".join(chunks).strip()
                after_steps = await self.rpc_client.get_trajectory_steps(
                    tracked.cascade_id, step_offset=0
                )
                if not response_text and after_steps:
                    response_text, _ = self.rpc_client.extract_planner_response_text(
                        after_steps[baseline_count:]
                    )

                # Record turn hashes and step offsets for future multi-turn / auto-revert
                tracked.step_offsets.append(baseline_count)
                tracked.turn_hashes.append(_hash_turn("user", user_message))
                tracked.step_offsets.append(len(after_steps))
                tracked.turn_hashes.append(_hash_turn("assistant", response_text))
                tracked.last_step_count = len(after_steps)
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

                clean_content, tool_calls = self._parse_possible_tool_calls(response_text)
                return {
                    "response": clean_content,
                    "raw_response": response_text,
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
        state_out: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
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
                explicit_conversation_id=explicit_conversation_id,
                force_new_chat=force_new_chat,
                requested_model=model,
                client_ip=client_ip,
            )
            out["conversation_id"] = tracked.cascade_id
            out["workspace_slot"] = slot.slot_id
            async with slot.lock:
                pacing_ms = await pacing_guard.apply_adaptive_pacing(slot.slot_id)
                write_workspace_agents_md(slot.workspace_dir, system_instructions)

                baseline_steps = await self.rpc_client.get_trajectory_steps(
                    tracked.cascade_id, step_offset=0
                )
                baseline_count = len(baseline_steps)

                await self.rpc_client.send_user_cascade_message(
                    tracked.cascade_id,
                    user_message,
                    slot.workspace_dir,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    blocking=False,
                )

                collected: List[str] = []
                buffered_for_tools = bool(tools)
                try:
                    async for delta in self.rpc_client.stream_response_deltas(
                        tracked.cascade_id, baseline_count, timeout=timeout
                    ):
                        collected.append(delta)
                        if not buffered_for_tools:
                            joined_so_far = "".join(collected).lstrip()
                            if joined_so_far.startswith(("{", "```")) and '"tool_call' in joined_so_far:
                                buffered_for_tools = True
                            else:
                                yield delta
                except asyncio.CancelledError:
                    await self.rpc_client.cancel_cascade_invocation(tracked.cascade_id)
                    raise

                full_text = "".join(collected).strip()
                cleaned_text, parsed_tool_calls = self._parse_possible_tool_calls(full_text)
                if parsed_tool_calls:
                    out["tool_calls"] = parsed_tool_calls
                    if buffered_for_tools and cleaned_text:
                        yield cleaned_text
                elif buffered_for_tools and full_text:
                    yield full_text

                after_steps = await self.rpc_client.get_trajectory_steps(
                    tracked.cascade_id, step_offset=0
                )
                tracked.step_offsets.append(baseline_count)
                tracked.turn_hashes.append(_hash_turn("user", user_message))
                tracked.step_offsets.append(len(after_steps))
                tracked.turn_hashes.append(_hash_turn("assistant", full_text))
                tracked.last_step_count = len(after_steps)
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
