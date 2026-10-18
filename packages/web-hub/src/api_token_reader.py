"""Exact Token & Context Window Reader for Anti-Gravity Conversations.

Extracts verified token counts from `GetCascadeTrajectoryGeneratorMetadata`
(`cortex.proto:1559` -> `chatModelMetadata.usage` & `contextWindowMetadata`),
with a read-only SQLite (`?mode=ro`) fallback on `<cascade_id>.db`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_MAX_CONTEXT_BY_MODEL: Dict[str, int] = {
    "gemini-4-argon-high": 1_000_000,
    "gemini-4-argon-medium": 1_000_000,
    "gemini-4-argon-low": 1_000_000,
    "gemini-3.8-flash-high": 1_000_000,
    "gemini-3.8-flash-medium": 1_000_000,
    "gemini-3.8-flash-low": 1_000_000,
    "claude-opus-4-6-thinking": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "gpt-oss-120b-medium": 128_000,
}


def infer_max_context_tokens(model_name: str) -> int:
    norm = (model_name or "").strip().lower()
    for key, limit in DEFAULT_MAX_CONTEXT_BY_MODEL.items():
        if key in norm:
            return limit
    if "claude" in norm or "opus" in norm or "sonnet" in norm:
        return 200_000
    if "gpt" in norm:
        return 128_000
    return 1_000_000


def parse_generator_metadata_tokens(
    gen_meta_response: Optional[Dict[str, Any]],
    *,
    prompt_text: str = "",
    response_text: str = "",
    requested_model: str = "",
) -> Dict[str, Any]:
    """Extract exact token usage & context window stats from `GetCascadeTrajectoryGeneratorMetadata`."""
    entries = []
    if isinstance(gen_meta_response, dict):
        entries = (
            gen_meta_response.get("generatorMetadata")
            or gen_meta_response.get("metadata")
            or []
        )

    if entries and isinstance(entries, list):
        # Take the most recent turn's generator metadata (last entry with chatModelMetadata)
        latest_chat_meta: Optional[Dict[str, Any]] = None
        latest_context_meta: Optional[Dict[str, Any]] = None
        for item in reversed(entries):
            if not isinstance(item, dict):
                continue
            chat_meta = item.get("chatModelMetadata") or item.get("chatModel") or item
            if isinstance(chat_meta, dict) and (
                chat_meta.get("usage") or chat_meta.get("responseModel")
            ):
                if latest_chat_meta is None:
                    latest_chat_meta = chat_meta
            start_meta = (
                chat_meta.get("chatStartMetadata")
                if isinstance(chat_meta, dict)
                else None
            ) or item.get("chatStartMetadata")
            if isinstance(start_meta, dict) and start_meta.get("contextWindowMetadata"):
                if latest_context_meta is None:
                    latest_context_meta = start_meta["contextWindowMetadata"]

        if latest_chat_meta:
            usage = latest_chat_meta.get("usage") or {}
            input_tokens = int(
                usage.get("inputTokens")
                or usage.get("promptTokens")
                or max(1, len(prompt_text) // 4)
            )
            output_tokens = int(
                usage.get("outputTokens")
                or usage.get("completionTokens")
                or max(1, len(response_text) // 4)
            )
            cached_tokens = int(
                usage.get("cacheReadInputTokens")
                or usage.get("cachedTokens")
                or 0
            )
            thinking_tokens = int(
                usage.get("thinkingOutputTokens")
                or usage.get("reasoningTokens")
                or 0
            )
            total_tokens = input_tokens + output_tokens + thinking_tokens
            actual_model = str(
                latest_chat_meta.get("responseModel")
                or usage.get("model")
                or requested_model
                or "antigravity"
            )
            ctx_used = int(
                (latest_context_meta or {}).get("estimatedTokensUsed")
                or (input_tokens + cached_tokens + output_tokens)
            )
            ctx_max = int(
                (latest_context_meta or {}).get("maxContextTokens")
                or infer_max_context_tokens(actual_model)
            )
            return {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "thinking_tokens": thinking_tokens,
                "total_tokens": total_tokens,
                "context_used_tokens": ctx_used,
                "context_max_tokens": ctx_max,
                "model_actual": actual_model,
                "token_source": "exact_rpc",
                "estimated": False,
            }

    # Fallback estimation when metadata RPC is not available (e.g. UI mode or synthetic reply)
    est_prompt = max(1, len(prompt_text) // 4) if prompt_text else 0
    est_completion = max(1, len(response_text) // 4) if response_text else 0
    est_total = est_prompt + est_completion
    max_ctx = infer_max_context_tokens(requested_model)
    return {
        "prompt_tokens": est_prompt,
        "completion_tokens": est_completion,
        "cached_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": est_total,
        "context_used_tokens": est_total,
        "context_max_tokens": max_ctx,
        "model_actual": requested_model or "antigravity",
        "token_source": "estimated",
        "estimated": True,
    }


def read_tokens_from_conversation_sqlite(
    app_data_dir: Path,
    cascade_id: str,
    *,
    prompt_text: str = "",
    response_text: str = "",
    requested_model: str = "",
) -> Dict[str, Any]:
    """Read-only (`?mode=ro`) SQLite fallback for `<app_data_dir>/conversations/<cascade_id>.db`."""
    db_file = (app_data_dir / "conversations" / f"{cascade_id}.db").resolve()
    if db_file.is_file():
        try:
            uri = db_file.as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1.5) as conn:
                conn.execute("PRAGMA query_only = ON;")
                row = conn.execute(
                    "SELECT payload FROM gen_metadata ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    raw = row[0]
                    if isinstance(raw, (bytes, bytearray)):
                        raw_str = raw.decode("utf-8", errors="ignore")
                    else:
                        raw_str = str(raw)
                    if "{" in raw_str:
                        parsed = json.loads(raw_str[raw_str.find("{") :])
                        res = parse_generator_metadata_tokens(
                            {"generatorMetadata": [parsed]},
                            prompt_text=prompt_text,
                            response_text=response_text,
                            requested_model=requested_model,
                        )
                        res["token_source"] = "sqlite_ro"
                        return res
        except Exception:
            pass

    return parse_generator_metadata_tokens(
        None,
        prompt_text=prompt_text,
        response_text=response_text,
        requested_model=requested_model,
    )
